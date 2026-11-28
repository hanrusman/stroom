package nl.c4w.stroom.boox.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

// Veldnamen volgen de API in camelCase; de JSON-instelling zet snake_case om.

@Serializable
data class StroomUser(val id: String, val email: String)

@Serializable
data class UserResponse(val user: StroomUser)

@Serializable
data class Topic(val slug: String, val name: String, val itemCount: Int = 0)

@Serializable
data class FeedItem(
    val id: String,
    val title: String,
    val description: String? = null,
    val sourceName: String = "",
    val sourceId: String? = null,
    val mediaUrl: String? = null,
    val thumbnailUrl: String? = null,
    val publishedAt: String? = null,
    val format: String? = null,
    val status: String? = null,
    val processingStatus: String? = null,
    val qualityScore: Double? = null,
    val hasSummary: Boolean? = null,
    val hasTranscript: Boolean? = null,
    val summary: String? = null,
    val summaryModel: String? = null,
    val transcript: String? = null,
    // Losse segmenten worden apart en tolerant gelezen; één kapot segment mag
    // het hele item niet onleesbaar maken.
    val transcriptSegments: List<JsonElement>? = null,
    val topics: List<String>? = null,
    val sourceUrl: String? = null,
    val scheduledFor: String? = null,
    val author: String? = null,
    val queuePosition: Int? = null,
) {
    val isSaved get() = status == "pinned"
    val isArchived get() = status == "archived"
    val isPodcast get() = format == "podcast"
    val isProcessing
        get() = processingStatus in setOf(
            "queued", "transcribe_queued", "summarize_queued", "transcribing", "summarizing",
        )

    /** Artikelen bewaren de volledige tekst in `transcript`; anders is de beschrijving de bron. */
    val sourceBody: String?
        get() = if (format == "article" && !transcript.isNullOrBlank()) transcript else description

    val hasSummaryText get() = !summary.isNullOrBlank() || hasSummary == true

    val formatLabel
        get() = when (format) {
            "article" -> "Artikel"
            "podcast" -> "Podcast"
            "video" -> "Video"
            else -> null
        }

    val segments: List<TranscriptSegment>
        get() = transcriptSegments.orEmpty().mapNotNull { TranscriptSegment.from(it) }

    fun merged(update: FeedItem): FeedItem = update.copy(
        // Lijst-endpoints leveren geen samenvatting of transcript; bewaar wat we al hadden.
        summary = update.summary ?: summary,
        summaryModel = update.summaryModel ?: summaryModel,
        transcript = update.transcript ?: transcript,
        transcriptSegments = update.transcriptSegments ?: transcriptSegments,
        topics = update.topics ?: topics,
        sourceUrl = update.sourceUrl ?: sourceUrl,
    )
}

data class TranscriptSegment(val start: Double, val end: Double, val text: String, val speaker: String?) {
    companion object {
        /** Tolerant: ook een segment met een object of lijst waar een getal of tekst hoort telt als kapot. */
        fun from(element: JsonElement): TranscriptSegment? = runCatching { parse(element) }.getOrNull()

        private fun parse(element: JsonElement): TranscriptSegment? {
            val obj = element as? JsonObject ?: return null
            val start = obj["start"]?.jsonPrimitive?.doubleOrNull ?: return null
            val end = obj["end"]?.jsonPrimitive?.doubleOrNull ?: return null
            val text = obj["text"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
            if (!start.isFinite() || !end.isFinite() || start < 0 || end <= start || text.isEmpty()) return null
            val speaker = runCatching { obj["speaker"]?.jsonPrimitive?.contentOrNull }.getOrNull()
            return TranscriptSegment(start, end, text, speaker?.takeIf { it.isNotBlank() })
        }
    }
}

@Serializable
data class HuygensRail(val format: String, val items: List<FeedItem> = emptyList())

@Serializable
data class HuygensTopic(val slug: String, val name: String, val rails: List<HuygensRail> = emptyList()) {
    val orderedRails: List<HuygensRail>
        get() = listOf("article", "podcast", "video").mapNotNull { f -> rails.firstOrNull { it.format == f } }
}

@Serializable
data class Digest(
    val markdown: String? = null,
    val generatedAt: String? = null,
    val isGenerating: Boolean = false,
    val itemCount: Int? = null,
    val model: String? = null,
    val error: String? = null,
)

@Serializable
data class Lesson(
    val id: String,
    val title: String,
    val body: String,
    val rating: Int? = null,
    val expansion: String? = null,
    val vikunjaTaskId: Int? = null,
    val sourceName: String? = null,
    val itemTitle: String? = null,
    val itemId: String? = null,
)

@Serializable
data class ItemQuestion(
    val id: String? = null,
    val question: String,
    val answer: String,
    val model: String? = null,
    val createdAt: String? = null,
    val sourcesUsed: List<String>? = null,
)

@Serializable
data class SearchHit(
    val id: String,
    val title: String,
    val format: String = "article",
    val sourceName: String = "",
    val publishedAt: String? = null,
    val snippet: String? = null,
)

@Serializable
data class ModelSettings(val modelDefaults: Map<String, String> = emptyMap())

@Serializable
data class ActionOK(val ok: Boolean = true)

@Serializable
data class VikunjaResult(val success: Boolean = false, val taskId: Int? = null)

@Serializable
data class TopicChoice(val slug: String, val name: String)

@Serializable
data class InboxPreview(
    val url: String,
    val title: String? = null,
    val description: String? = null,
    val format: String = "article",
)

@Serializable
data class InboxResult(val id: String, val title: String, val message: String)

object StroomDate {
    private val dutch = Locale.forLanguageTag("nl-NL")
    private val dayMonth = DateTimeFormatter.ofPattern("d MMM", dutch)
    private val dayMonthYear = DateTimeFormatter.ofPattern("d MMM yyyy", dutch)
    private val full = DateTimeFormatter.ofPattern("d MMMM yyyy, HH:mm", dutch)

    fun parse(value: String?): OffsetDateTime? {
        if (value.isNullOrBlank()) return null
        val normalized = value.trim().replace(' ', 'T')
        return runCatching { OffsetDateTime.parse(normalized) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(normalized + "Z") }.getOrNull()
            ?: runCatching { LocalDate.parse(normalized.take(10)).atStartOfDay(ZoneId.of("UTC")).toOffsetDateTime() }
                .getOrNull()
    }

    /** Korte datum voor lijsten: „12 nov” dit jaar, anders „12 nov 2025”. */
    fun short(value: String?, today: LocalDate = LocalDate.now()): String? {
        val date = parse(value)?.atZoneSameInstant(ZoneId.systemDefault())?.toLocalDate() ?: return null
        return (if (date.year == today.year) dayMonth else dayMonthYear).format(date).replace(".", "")
    }

    fun long(value: String?): String? =
        parse(value)?.atZoneSameInstant(ZoneId.systemDefault())?.let { full.format(it) }
}
