package nl.c4w.stroom.boox.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.serialization.Serializable
import java.io.File

/** Leesinstellingen. Standaarden zijn gekozen voor de Boox Go Color 7 (7", Kaleido 3). */
data class ReaderSettings(
    val textSize: Int = 20,
    val weight: Int = 450,
    val lineSpacing: Float = 1.5f,
    val margin: Int = 1,
    val serif: Boolean = true,
    val volumeKeys: Boolean = true,
    val tapZones: Boolean = true,
    val refreshEvery: Int = 8,
    /** Kleuraccenten voor Kaleido-schermen (Go Color 7); uit voor zwart-wit Boox-modellen. */
    val color: Boolean = true,
    /** Bladerknoppen omdraaien, bijvoorbeeld als je het apparaat in je andere hand houdt. */
    val swapKeys: Boolean = false,
) {
    companion object {
        val TEXT_SIZES = (16..32 step 2).toList()
        val WEIGHTS = listOf(400 to "Normaal", 450 to "Iets donkerder", 550 to "Donker", 650 to "Extra donker")
        val SPACINGS = listOf(1.3f to "Compact", 1.5f to "Normaal", 1.7f to "Ruim")
        val MARGINS = listOf(0 to "Smal", 1 to "Normaal", 2 to "Breed")
        val REFRESH = listOf(0 to "Nooit", 4 to "Elke 4 pagina’s", 8 to "Elke 8 pagina’s", 16 to "Elke 16 pagina’s")
    }
}

class Settings(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var server: String
        get() = prefs.getString("server", null) ?: "https://stroom.c4w.nl"
        set(value) = prefs.edit().putString("server", value).apply()

    /** "server|gebruikers-id": gegevens van een ander account worden nooit getoond. */
    var account: String?
        get() = prefs.getString("account", null)
        set(value) = prefs.edit().putString("account", value).apply()

    var selectedTopic: String
        get() = prefs.getString("topic", null) ?: ""
        set(value) = prefs.edit().putString("topic", value).apply()

    var reader: ReaderSettings
        get() = ReaderSettings(
            textSize = prefs.getInt("textSize", 20),
            weight = prefs.getInt("weight", 450),
            lineSpacing = prefs.getFloat("lineSpacing", 1.5f),
            margin = prefs.getInt("margin", 1),
            serif = prefs.getBoolean("serif", true),
            volumeKeys = prefs.getBoolean("volumeKeys", true),
            tapZones = prefs.getBoolean("tapZones", true),
            refreshEvery = prefs.getInt("refreshEvery", 8),
            color = prefs.getBoolean("color", true),
            swapKeys = prefs.getBoolean("swapKeys", false),
        )
        set(v) = prefs.edit()
            .putInt("textSize", v.textSize).putInt("weight", v.weight).putFloat("lineSpacing", v.lineSpacing)
            .putInt("margin", v.margin).putBoolean("serif", v.serif).putBoolean("volumeKeys", v.volumeKeys)
            .putBoolean("tapZones", v.tapZones).putInt("refreshEvery", v.refreshEvery)
            .putBoolean("color", v.color).putBoolean("swapKeys", v.swapKeys)
            .apply()
}

/** Onthoudt per item en tabblad waar je was, als tekenpositie (overleeft een andere lettergrootte). */
class ReadingPositions(context: Context) {
    private val prefs = context.getSharedPreferences("positions", Context.MODE_PRIVATE)

    fun get(key: String): Int = prefs.getString(key, null)?.substringBefore(':')?.toIntOrNull() ?: 0

    fun set(key: String, offset: Int) {
        val editor = prefs.edit().putString(key, "$offset:${System.currentTimeMillis()}")
        val all = prefs.all
        if (all.size > MAX) {
            all.entries.sortedBy { (it.value as? String)?.substringAfter(':')?.toLongOrNull() ?: 0L }
                .take(all.size - MAX).forEach { editor.remove(it.key) }
        }
        editor.apply()
    }

    fun clear() = prefs.edit().clear().apply()

    private companion object {
        const val MAX = 400
    }
}

@Serializable
data class FeedCache(
    val account: String,
    val user: StroomUser,
    val topics: List<Topic> = emptyList(),
    val topicFeeds: Map<String, HuygensTopic> = emptyMap(),
    val all: List<FeedItem> = emptyList(),
    val queue: List<FeedItem> = emptyList(),
    val saved: List<FeedItem> = emptyList(),
    val savedAt: Long = 0,
)

@Serializable
data class CachedDetail(val item: FeedItem, val fetchedAt: Long)

/** Laatst geladen lijsten en volledige teksten van de wachtrij, voor lezen zonder wifi. */
class OfflineCache(private val root: File) {
    private val feedFile get() = File(root, "feed.json")
    private val detailDir get() = File(root, "details").apply { mkdirs() }

    fun load(account: String): FeedCache? = runCatching {
        StroomJson.decodeFromString(FeedCache.serializer(), feedFile.readText())
    }.getOrNull()?.takeIf { it.account == account }

    fun save(cache: FeedCache) = writeAtomic(feedFile, StroomJson.encodeToString(FeedCache.serializer(), cache))

    fun detail(id: String): CachedDetail? = runCatching {
        StroomJson.decodeFromString(CachedDetail.serializer(), File(detailDir, safe(id)).readText())
    }.getOrNull()

    fun saveDetail(item: FeedItem, now: Long = System.currentTimeMillis()) =
        writeAtomic(File(detailDir, safe(item.id)), StroomJson.encodeToString(CachedDetail.serializer(), CachedDetail(item, now)))

    fun cachedIds(): Set<String> = detailDir.list()?.map { it.removeSuffix(".json") }?.toSet().orEmpty()

    /** Houdt alleen teksten van items die nog in de wachtrij of bij Bewaard staan. */
    fun prune(keep: Set<String>) {
        detailDir.listFiles()?.forEach { if (it.name.removeSuffix(".json") !in keep) it.delete() }
    }

    fun clear() {
        root.deleteRecursively()
    }

    private fun safe(id: String) = id.filter { it.isLetterOrDigit() || it == '-' } + ".json"

    private fun writeAtomic(file: File, text: String) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(text)
        if (!tmp.renameTo(file)) {
            file.delete()
            tmp.renameTo(file)
        }
    }
}
