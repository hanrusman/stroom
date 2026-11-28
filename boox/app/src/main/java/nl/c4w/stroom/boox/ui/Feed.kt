package nl.c4w.stroom.boox.ui

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import nl.c4w.stroom.boox.ALL_TOPICS
import nl.c4w.stroom.boox.AppState
import nl.c4w.stroom.boox.Screen
import nl.c4w.stroom.boox.data.ApiException
import nl.c4w.stroom.boox.data.ContentText
import nl.c4w.stroom.boox.data.FeedItem
import nl.c4w.stroom.boox.data.SearchHit
import nl.c4w.stroom.boox.data.StroomDate
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

sealed interface FeedRow {
    data class Header(val title: String, val format: String?) : FeedRow
    data class Entry(val item: FeedItem, val snippet: String? = null) : FeedRow
}

val FORMATS = listOf("all" to "Alles", "article" to "Lezen", "podcast" to "Luisteren", "video" to "Kijken")

/** Kaartje in een lijst: gekleurde balk per soort, zwarte tekst, statusmarkeringen rechtsboven. */
@Composable
fun ItemCard(state: AppState, item: FeedItem, snippet: String? = null) {
    val type = LocalType.current
    val palette = LocalPalette.current
    val queued = state.isQueued(item)
    val offline = item.id in state.offlineIds
    val meta = listOfNotNull(item.sourceName.takeIf { it.isNotBlank() }, StroomDate.short(item.publishedAt))
        .joinToString(" · ")
    val markers = listOfNotNull(
        state.pending[item.id]?.let { "$it…" },
        if (queued) "WACHTRIJ" else null,
        if (item.isSaved) "BEWAARD" else null,
        if (item.status == "later") "LATER" else null,
    )
    val excerpt = snippet ?: ContentText.excerpt(item.description)
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().height(IntrinsicSize.Min)
                .pressable(
                    onClick = { state.open(Screen.Reader(item.id)) },
                    onLongClick = { state.actionItem = item },
                    label = "Acties",
                ),
        ) {
            Box(Modifier.width(5.dp).fillMaxHeight().background(palette.format(item.format)))
            Column(Modifier.weight(1f).padding(start = 14.dp, end = Space.gutter, top = 12.dp, bottom = 14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    item.formatLabel?.let {
                        Txt(
                            it.uppercase(),
                            type.meta.copy(color = palette.format(item.format), fontWeight = FontWeight.Bold),
                            maxLines = 1,
                        )
                        Txt("  ", type.meta)
                    }
                    Txt(meta, type.meta, Modifier.weight(1f), maxLines = 1)
                    if (markers.isNotEmpty()) {
                        Txt(
                            markers.joinToString(" · "),
                            type.meta.copy(color = palette.accent, fontWeight = FontWeight.Bold),
                            maxLines = 1,
                        )
                    }
                }
                Gap(4.dp)
                Txt(item.title, type.cardTitle, maxLines = 3)
                if (excerpt.isNotBlank()) {
                    Gap(4.dp)
                    Txt(excerpt, type.cardBody, maxLines = 2)
                }
                val extra = listOfNotNull(
                    item.qualityScore?.let { "score ${it.toInt()}" },
                    if (item.hasSummaryText) "samenvatting" else null,
                    if (item.isProcessing) "wordt verwerkt" else null,
                    if (offline) "offline leesbaar" else null,
                )
                if (extra.isNotEmpty()) {
                    Gap(4.dp)
                    Meta(extra.joinToString(" · "))
                }
            }
        }
        Rule()
    }
}

@Composable
private fun RowHeader(title: String, format: String?) {
    val palette = LocalPalette.current
    Column(Modifier.fillMaxWidth().padding(top = 14.dp)) {
        Row(Modifier.padding(horizontal = Space.gutter, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(14.dp).height(14.dp).background(if (format == null) Ink.Black else palette.format(format)))
            Txt("  " + title.uppercase(), LocalType.current.label.copy(fontWeight = FontWeight.Bold))
        }
        Rule(heavy = true, color = if (format == null) Ink.Black else palette.format(format))
    }
}

/** Een bladerbare lijst met voettekst; registreert zich voor de bladerknoppen. */
@Composable
fun FeedList(
    state: AppState,
    rows: List<FeedRow>,
    pager: ListPager,
    modifier: Modifier = Modifier,
    empty: @Composable () -> Unit,
) {
    RegisterPageKeys(pager)
    Column(modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).fillMaxWidth().pageGestures(pager)) {
            if (rows.isEmpty()) {
                empty()
            } else {
                PagedColumn(
                    items = rows,
                    pager = pager,
                    key = {
                        when (it) {
                            is FeedRow.Header -> "h:${it.title}"
                            is FeedRow.Entry -> it.item.id
                        }
                    },
                    keepWithNext = { it is FeedRow.Header },
                ) { row ->
                    when (row) {
                        is FeedRow.Header -> RowHeader(row.title, row.format)
                        is FeedRow.Entry -> ItemCard(state, state.current(row.item), row.snippet)
                    }
                }
            }
        }
        PageFooter(pager)
    }
}

@Composable
fun StatusLine(text: String) {
    Column(Modifier.fillMaxWidth()) {
        Txt(text, LocalType.current.meta, Modifier.padding(horizontal = Space.gutter, vertical = 6.dp), maxLines = 2)
        Rule()
    }
}

fun syncText(state: AppState): String? {
    val last = state.lastSync?.let { SimpleDateFormat("HH:mm", Locale.forLanguageTag("nl-NL")).format(Date(it)) }
    return when {
        state.syncing -> "Verversen…"
        state.offline && last != null -> "Offline · laatst bijgewerkt om $last"
        state.offline -> "Offline"
        else -> state.offlineSync
    }
}

@Composable
fun HomeScreen(state: AppState) {
    val topic = state.selectedTopic
    val format = state.homeFormat
    val rows: List<FeedRow> = if (topic == ALL_TOPICS) {
        state.visible(state.allItems).filter { format == "all" || it.format == format }.map { FeedRow.Entry(it) }
    } else {
        state.topicFeeds[topic]?.orderedRails.orEmpty()
            .filter { format == "all" || it.format == format }
            .flatMap { rail ->
                val items = state.visible(rail.items)
                if (items.isEmpty()) {
                    emptyList()
                } else {
                    val title = when (rail.format) {
                        "article" -> "Artikelen"
                        "podcast" -> "Podcasts"
                        else -> "Video’s"
                    }
                    listOf(FeedRow.Header(title, rail.format)) + items.map { FeedRow.Entry(it) }
                }
            }
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("Stroom") {
            EButton(if (state.syncing) "Bezig…" else "Ververs", { state.refresh() }, enabled = !state.syncing)
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            EButton("${state.topicName} ▾", { state.open(Screen.Topics) }, Modifier.weight(1f), description = "Kies onderwerp")
            if (topic != ALL_TOPICS) {
                EButton("Dag- en weekoverzicht", { state.open(Screen.Digest(topic, state.topicName)) })
            }
        }
        Segmented(FORMATS, format, { state.homeFormat = it }, Modifier.padding(horizontal = 12.dp))
        Gap(8.dp)
        syncText(state)?.let { StatusLine(it) } ?: Rule()
        FeedList(state, rows, state.listPager("home|$topic|$format")) {
            when {
                state.topicLoading || state.syncing -> Notice("Laden…")
                state.topicError != null -> Notice("Onderwerp niet geladen", state.topicError, "Opnieuw", { state.reloadTopic() })
                state.offline -> Notice(
                    "Offline",
                    "Dit onderwerp is niet eerder geladen. Je wachtrij is wel offline leesbaar.",
                    "Naar je wachtrij", { state.tab(Screen.Queue) },
                    secondary = "Ververs" to { state.refresh() },
                )
                else -> Notice(
                    "Niets te lezen",
                    "Er is hier niets nieuws in de laatste 30 dagen. Kies een ander onderwerp of filter.",
                    "Ververs", { state.refresh() },
                )
            }
        }
    }
}

@Composable
fun TopicsScreen(state: AppState) {
    val rows = listOf(Triple(ALL_TOPICS, "Alles", "Alle onderwerpen, laatste 30 dagen")) +
        state.topics.map { Triple(it.slug, it.name, if (it.itemCount == 1) "1 item" else "${it.itemCount} items") }
    val pager = state.listPager("topics")
    RegisterPageKeys(pager)
    Column(Modifier.fillMaxSize()) {
        TopBar("Onderwerp", onBack = { state.back() })
        Box(Modifier.weight(1f).pageGestures(pager)) {
            PagedColumn(rows, pager, key = { it.first }) { (slug, name, detail) ->
                val selected = slug == state.selectedTopic
                Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                    Box(Modifier.width(6.dp).fillMaxHeight().background(if (selected) LocalPalette.current.accent else Ink.Paper))
                    Column(Modifier.weight(1f)) {
                        SheetItem(if (selected) "$name  ✓" else name, {
                            state.selectTopic(slug)
                            state.back()
                        }, detail = detail)
                    }
                }
            }
        }
        PageFooter(pager)
    }
}

@Composable
fun QueueScreen(state: AppState) {
    val format = state.queueFormat
    val items = state.visible(state.queue).filter { format == "all" || it.format == format }
    val offline = state.queue.count { it.id in state.offlineIds }
    Column(Modifier.fillMaxSize()) {
        TopBar("Wachtrij") {
            EButton(if (state.syncing) "Bezig…" else "Ververs", { state.refresh() }, enabled = !state.syncing)
        }
        Gap(8.dp)
        Segmented(FORMATS, format, { state.queueFormat = it }, Modifier.padding(horizontal = 12.dp))
        Gap(8.dp)
        StatusLine(
            syncText(state) ?: "${state.queue.size} in je wachtrij · $offline offline leesbaar · zelfde volgorde als op de website",
        )
        FeedList(state, items.map { FeedRow.Entry(it) }, state.listPager("queue|$format")) {
            if (state.queueError != null) {
                Notice("Wachtrij niet beschikbaar", state.queueError, "Opnieuw", { state.refresh() })
            } else if (format != "all" && state.visible(state.queue).isNotEmpty()) {
                Notice("Niets van deze soort", "Je wachtrij bevat wel andere items.", "Toon alles", { state.queueFormat = "all" })
            } else {
                Notice(
                    "Je wachtrij is leeg",
                    "Houd een item ingedrukt en kies „In wachtrij”. Alles in je wachtrij wordt ook offline bewaard, " +
                        "zodat je zonder wifi kunt lezen.",
                )
            }
        }
    }
}

@Composable
fun SavedScreen(state: AppState) {
    val items = state.visible(state.saved).filter { it.isSaved }
    Column(Modifier.fillMaxSize()) {
        TopBar("Bewaard") {
            EButton("Zoek", { state.open(Screen.Search) })
        }
        syncText(state)?.let { StatusLine(it) }
        FeedList(state, items.map { FeedRow.Entry(it) }, state.listPager("saved")) {
            Notice("Nog niets bewaard", "Bewaar een item via het actiemenu (lang indrukken of „Acties” in de lezer).")
        }
    }
}

@Composable
fun SearchScreen(state: AppState) {
    // Zoekopdracht en resultaten staan in AppState: dit scherm verdwijnt uit beeld zodra je een
    // resultaat opent, en moet er bij Terug nog net zo staan.
    val query = state.searchQuery
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val pager = state.listPager("search")
    fun search() {
        val api = state.api ?: return
        if (busy || query.trim().length < 2) return
        busy = true
        error = null
        scope.launch {
            try {
                val hits: List<SearchHit> = api.get("search", mapOf("q" to query.trim(), "limit" to "60"))
                state.searchSnippets = hits.associate { it.id to ContentText.excerpt(it.snippet) }
                state.searchResults = hits.map { FeedItem(id = it.id, title = it.title, sourceName = it.sourceName, format = it.format, publishedAt = it.publishedAt) }
                pager.reset()
            } catch (e: ApiException) {
                error = e.message
            } finally {
                busy = false
            }
        }
    }
    Column(Modifier.fillMaxSize()) {
        TopBar("Zoeken", onBack = { state.back() })
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Field("Zoek in titels, samenvattingen en transcripten", query, { state.searchQuery = it }, Modifier.weight(1f), ime = ImeAction.Search, onDone = ::search)
            EButton(if (busy) "Zoekt…" else "Zoek", ::search, filled = true, enabled = !busy && query.trim().length >= 2)
        }
        Rule()
        val found = state.searchResults
        val snippets = state.searchSnippets
        when {
            error != null -> Notice("Zoeken mislukt", error, "Opnieuw", ::search)
            found == null -> Notice("Zoek in je hele archief", "Gebruik \"aanhalingstekens\" voor een exacte zin of OR voor alternatieven.")
            else -> FeedList(state, found.map { FeedRow.Entry(it, snippets[it.id]) }, pager) {
                Notice("Niets gevonden", "Probeer een ander of korter zoekwoord.")
            }
        }
    }
}

/** Het actiemenu voor één item: bovenop elk scherm, zonder animatie. */
@Composable
fun ItemActions(state: AppState, base: FeedItem, inReader: Boolean) {
    val item = state.current(base)
    val context = LocalContext.current
    val close = { state.actionItem = null }
    fun open(url: String, mime: String? = null) {
        val uri = Uri.parse(url)
        if (uri.scheme !in setOf("http", "https")) return
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW).apply { if (mime != null) setDataAndType(uri, mime) else data = uri })
        } catch (e: ActivityNotFoundException) {
            state.notify("Geen app gevonden om dit te openen.")
        }
    }
    Sheet(item.title, onDismiss = close) {
        val queued = state.isQueued(item)
        SheetItem(if (queued) "Uit wachtrij halen" else "In wachtrij (ook offline)", {
            state.toggleQueue(item)
            close()
        })
        SheetItem(if (item.isSaved) "Niet meer bewaren" else "Bewaren", {
            state.toggleSaved(item)
            close()
        })
        SheetItem("Later lezen", {
            state.later(item)
            close()
        }, enabled = item.status != "later")
        SheetItem("Archiveren", {
            state.archive(item, leaveReader = inReader)
            close()
        }, detail = "Verdwijnt uit je lijsten en wachtrij; je kunt het direct herstellen.")
        val original = item.sourceUrl?.takeIf { !item.isPodcast } ?: item.mediaUrl?.takeIf { !item.isPodcast }
        if (original != null) {
            SheetItem("Open origineel in de browser", {
                close()
                open(original)
            })
        }
        if (item.isPodcast && item.mediaUrl != null) {
            SheetItem("Beluister in een andere app", {
                close()
                open(item.mediaUrl, "audio/*")
            }, detail = "Bijvoorbeeld via bluetooth-oortjes.")
        }
        if (inReader) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Label("Letter ${state.reader.textSize}", Modifier.weight(1f))
                EButton("A−", { state.updateReader(state.reader.copy(textSize = (state.reader.textSize - 2).coerceAtLeast(16))) }, description = "Kleinere letter")
                EButton("A+", { state.updateReader(state.reader.copy(textSize = (state.reader.textSize + 2).coerceAtMost(32))) }, description = "Grotere letter")
                EButton("Ververs scherm", {
                    close()
                    state.flash()
                })
            }
        }
    }
}
