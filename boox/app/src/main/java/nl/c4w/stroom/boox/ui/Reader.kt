package nl.c4w.stroom.boox.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import nl.c4w.stroom.boox.AppState
import nl.c4w.stroom.boox.Screen
import nl.c4w.stroom.boox.data.ApiException
import nl.c4w.stroom.boox.data.Block
import nl.c4w.stroom.boox.data.ContentText
import nl.c4w.stroom.boox.data.Digest
import nl.c4w.stroom.boox.data.FeedItem
import nl.c4w.stroom.boox.data.ItemQuestion
import nl.c4w.stroom.boox.data.Lesson
import nl.c4w.stroom.boox.data.StroomDate
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Lange tekst als pagina's. Tikken links = terug, rechts = verder; vegen en
 * bladerknoppen werken ook. De positie wordt per item en tabblad onthouden.
 */
@Composable
fun DocumentReader(state: AppState, blocks: List<Block>, positionKey: String, modifier: Modifier = Modifier) {
    val type = LocalType.current
    val document = remember(blocks, type) { DocumentBuilder.build(blocks, type) }
    val pager = remember(positionKey) { DocumentPager(state.positions.get(positionKey)) }
    RegisterPageKeys(pager)
    LaunchedEffect(pager.page, pager.count) {
        if (pager.count > 0) state.positions.set(positionKey, pager.anchor)
    }
    val margin = Space.margin(state.reader.margin)
    Column(modifier.fillMaxSize()) {
        Box(
            Modifier.weight(1f).fillMaxWidth()
                .readerTapZones(pager, state.reader.tapZones)
                .padding(start = margin, end = margin, top = 18.dp, bottom = 10.dp),
        ) {
            PagedDocument(document, pager)
        }
        PageFooter(pager)
    }
}

/** Kop bovenaan elk tabblad van de lezer: soort, bron, datum, titel en onderwerpen. */
fun itemHeader(item: FeedItem): List<Block> {
    val meta = listOfNotNull(
        item.formatLabel?.uppercase(),
        item.sourceName.takeIf { it.isNotBlank() },
        StroomDate.long(item.publishedAt) ?: StroomDate.short(item.publishedAt),
        item.qualityScore?.let { "score ${it.toInt()}" },
    ).joinToString("  ·  ")
    val topics = item.topics.orEmpty().takeIf { it.isNotEmpty() }?.joinToString(" · ")
    return listOfNotNull(Block.Meta(meta), Block.Title(item.title), topics?.let { Block.Meta(it) })
}

private val SECTIONS = listOf("Samenvatting", "Bron", "Lessen", "Transcript", "Vragen")

@Composable
fun ReaderScreen(state: AppState, id: String) {
    val known = remember(id) {
        (state.allItems + state.queue + state.saved + state.topicFeeds.values.flatMap { t -> t.rails.flatMap { it.items } })
            .firstOrNull { it.id == id }
    }
    var item by remember(id) { mutableStateOf(known?.let(state::current)) }
    var cachedAt by remember(id) { mutableStateOf<Long?>(null) }
    var error by remember(id) { mutableStateOf<String?>(null) }
    var loaded by remember(id) { mutableStateOf(false) }
    var section by rememberSaveable(id) { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    suspend fun load() {
        try {
            val (fresh, from) = state.loadItem(id)
            item = fresh
            cachedAt = from
            error = null
        } catch (e: ApiException) {
            error = e.message
        }
        loaded = true
    }
    LaunchedEffect(id) { load() }
    // Volgt verwerking (samenvatten/transcriberen) zolang de lezer open is.
    LaunchedEffect(id, item?.isProcessing) {
        while (item?.isProcessing == true) {
            delay(20_000)
            load()
        }
    }

    val current = item?.let(state::current)
    val available = SECTIONS.filter { it != "Transcript" || current?.format == "podcast" || current?.format == "video" }
    if (section.isEmpty() && loaded && current != null) section = if (current.hasSummaryText) "Samenvatting" else "Bron"
    val active = section.ifEmpty { "Samenvatting" }

    Column(Modifier.fillMaxSize()) {
        TopBar(current?.sourceName?.ifBlank { null } ?: "In Stroom", onBack = { state.back() }) {
            if (current != null) EButton("Acties", { state.actionItem = current }, filled = true)
        }
        if (current == null) {
            if (error != null) {
                Notice("Niet geladen", error, "Opnieuw", { scope.launch { load() } })
            } else {
                Notice("Laden…")
            }
            return@Column
        }
        Segmented(
            available.map { it to it },
            active,
            { section = it },
            Modifier.padding(horizontal = 8.dp, vertical = 8.dp),
        )
        val notes = listOfNotNull(
            cachedAt?.let {
                "Offline kopie van " + SimpleDateFormat("d MMM HH:mm", Locale.forLanguageTag("nl-NL")).format(Date(it))
            },
            if (current.isProcessing) "Wordt verwerkt op de server; deze pagina ververst vanzelf." else null,
            state.pending[current.id]?.let { "$it…" },
        )
        if (notes.isNotEmpty()) StatusLine(notes.joinToString(" · ")) else Rule()

        // Tekst één keer verwerken per inhoud; lange transcripten kosten anders bij elke hertekening tijd.
        val summary = remember(current.summary) { ContentText.document(current.summary) }
        val source = remember(current.sourceBody) { ContentText.document(current.sourceBody) }
        val transcript = remember(current.transcript, current.transcriptSegments) { ContentText.transcriptDocument(current) }
        when (active) {
            "Samenvatting" -> {
                val body = summary
                if (body.isEmpty()) {
                    Notice(
                        if (current.isProcessing) "Samenvatting wordt gemaakt" else "Nog geen samenvatting",
                        if (current.isProcessing) "Dit duurt meestal een paar minuten." else "Laat Stroom dit item samenvatten, of lees de bron.",
                        if (current.isProcessing) "Opnieuw laden" else "Samenvatten",
                        {
                            if (current.isProcessing) scope.launch { load() } else state.process(current, "summarize") { item = it }
                        },
                        secondary = "Lees de bron" to { section = "Bron" },
                    )
                } else {
                    val model = current.summaryModel?.let { listOf(Block.Rule, Block.Meta("Samengevat met $it")) }.orEmpty()
                    DocumentReader(state, itemHeader(current) + body + model, "$id|samenvatting")
                }
            }
            "Bron" -> {
                val body = source
                if (body.isEmpty()) {
                    Notice(
                        "Geen brontekst",
                        "De bron heeft geen tekst meegeleverd. Open het origineel via Acties.",
                        "Acties", { state.actionItem = current },
                    )
                } else {
                    DocumentReader(state, itemHeader(current) + body, "$id|bron")
                }
            }
            "Transcript" -> {
                val body = transcript
                if (body.isEmpty()) {
                    Notice(
                        "Nog geen transcript",
                        if (current.isProcessing) "Wordt verwerkt; kom straks terug." else "Laat Stroom deze aflevering uitschrijven.",
                        if (current.isProcessing) null else "Transcriberen",
                        { state.process(current, "transcribe") { item = it } },
                    )
                } else {
                    DocumentReader(state, itemHeader(current) + body, "$id|transcript")
                }
            }
            "Lessen" -> LessonsPane(state, current)
            else -> QuestionsPane(state, current)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LessonsPane(state: AppState, item: FeedItem) {
    val id = item.id
    val lessons = state.lessons[id]
    var error by remember(id) { mutableStateOf<String?>(null) }
    val busy = remember(id) { mutableStateMapOf<String, String>() }
    val distillKey = "distill-$id"
    val distilling = state.pending.containsKey(distillKey)
    LaunchedEffect(id) {
        if (lessons == null) {
            try {
                state.loadLessons(id)
            } catch (e: ApiException) {
                error = e.message
            }
        }
    }
    fun distill() {
        if (distilling) return
        state.pending[distillKey] = "Lessen destilleren"
        error = null
        state.scope.launch {
            try {
                state.distill(id)
            } catch (e: ApiException) {
                error = "Destilleren niet afgerond: ${e.message}"
            } finally {
                state.pending.remove(distillKey)
            }
        }
    }
    fun run(lesson: Lesson, label: String, block: suspend () -> Unit) {
        if (busy.containsKey(lesson.id)) return
        busy[lesson.id] = label
        state.scope.launch {
            try {
                block()
            } catch (e: ApiException) {
                state.notify(e.message ?: "Dat lukte niet.")
            } finally {
                busy.remove(lesson.id)
            }
        }
    }
    when {
        distilling -> Notice("Lessen destilleren…", "Dit kan enkele minuten duren. Je kunt intussen verder lezen; de lessen verschijnen hier.")
        error != null -> Notice("Lessen niet beschikbaar", error, "Opnieuw destilleren", ::distill)
        lessons == null -> Notice("Laden…")
        lessons.isEmpty() -> Notice(
            "Nog geen lessen",
            "Laat Stroom de belangrijkste lessen uit dit item halen. Je kunt ze daarna beoordelen, verdiepen of naar Vikunja sturen.",
            "Destilleer lessen", ::distill,
        )
        else -> {
            val pager = state.listPager("lessons|$id")
            RegisterPageKeys(pager)
            val type = LocalType.current
            Column(Modifier.fillMaxSize()) {
                Box(Modifier.weight(1f).pageGestures(pager)) {
                    PagedColumn(lessons, pager, key = { it.id }) { lesson ->
                        Column(Modifier.fillMaxWidth().padding(horizontal = Space.gutter, vertical = 14.dp)) {
                            Txt(lesson.title, type.cardTitle)
                            Gap(6.dp)
                            Txt(ContentText.excerpt(lesson.body), type.cardBody)
                            Gap(10.dp)
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                EButton("Nuttig", { run(lesson, "Opslaan") { state.rate(id, lesson, 1) } }, filled = lesson.rating == 1)
                                EButton("Niet nuttig", { run(lesson, "Opslaan") { state.rate(id, lesson, -1) } }, filled = lesson.rating == -1)
                                if (lesson.expansion.isNullOrBlank()) {
                                    EButton("Verdiep", {
                                        run(lesson, "Verdiepen… dit kan enkele minuten duren") {
                                            val updated = state.expand(id, lesson)
                                            updated.expansion?.let { state.open(Screen.Doc(lesson.title, it, "Verdieping")) }
                                        }
                                    })
                                } else {
                                    EButton("Lees verdieping", { state.open(Screen.Doc(lesson.title, lesson.expansion, "Verdieping")) })
                                }
                                EButton(
                                    if (lesson.vikunjaTaskId != null) "In Vikunja ✓" else "Naar Vikunja",
                                    { run(lesson, "Naar Vikunja sturen") { state.sendToVikunja(id, lesson) } },
                                    enabled = lesson.vikunjaTaskId == null,
                                )
                            }
                            busy[lesson.id]?.let {
                                Gap(6.dp)
                                Meta(it)
                            }
                        }
                        Rule()
                    }
                }
                PageFooter(pager) {
                    EButton("Opnieuw", ::distill, borderless = true, description = "Opnieuw destilleren")
                }
            }
        }
    }
}

@Composable
private fun QuestionsPane(state: AppState, item: FeedItem) {
    val id = item.id
    val history = state.questions[id]
    var question by rememberSaveable(id) { mutableStateOf("") }
    var error by remember(id) { mutableStateOf<String?>(null) }
    val askKey = "ask-$id"
    val asking = state.pending.containsKey(askKey)
    LaunchedEffect(id) {
        if (history == null) {
            try {
                state.loadQuestions(id)
            } catch (e: ApiException) {
                error = e.message
            }
        }
    }
    fun ask() {
        val text = question.trim()
        if (text.length < 3 || asking) return
        state.pending[askKey] = "Vraag stellen"
        error = null
        state.scope.launch {
            try {
                val answer = state.ask(id, text)
                question = ""
                state.open(Screen.Doc(answer.question, answer.answer, answerMeta(answer)))
            } catch (e: ApiException) {
                error = e.message
            } finally {
                state.pending.remove(askKey)
            }
        }
    }
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Field("Vraag iets over dit item", question, { question = it }, Modifier.weight(1f), ime = ImeAction.Send, onDone = ::ask, singleLine = false)
            EButton(if (asking) "Denkt na…" else "Vraag", ::ask, filled = true, enabled = !asking && question.trim().length >= 3)
        }
        Rule()
        val rows = history.orEmpty()
        when {
            asking -> Notice("Stroom denkt na…", "Een antwoord kan een paar minuten duren. Het opent vanzelf.")
            error != null -> Notice("Vragen niet beschikbaar", error)
            history == null -> Notice("Laden…")
            rows.isEmpty() -> Notice("Nog geen vragen", "Het antwoord gebruikt de samenvatting, lessen en volledige tekst van dit item.")
            else -> {
                val pager = state.listPager("questions|$id")
                FeedLikeList(pager, rows, key = { it.id ?: it.question }) { answer ->
                    val type = LocalType.current
                    Column(
                        Modifier.fillMaxWidth()
                            .pressable({ state.open(Screen.Doc(answer.question, answer.answer, answerMeta(answer))) })
                            .padding(horizontal = Space.gutter, vertical = 14.dp),
                    ) {
                        Txt(answer.question, type.cardTitle, maxLines = 3)
                        Gap(4.dp)
                        Txt(ContentText.excerpt(answer.answer), type.cardBody, maxLines = 4)
                        Gap(4.dp)
                        Meta(answerMeta(answer))
                    }
                    Rule()
                }
            }
        }
    }
}

private fun answerMeta(answer: ItemQuestion): String {
    val sources = answer.sourcesUsed.orEmpty().map {
        mapOf("transcript" to "volledige tekst", "description" to "bronbeschrijving", "summary" to "samenvatting", "lessons" to "lessen")[it] ?: it
    }
    return listOfNotNull(
        "AI-antwoord · ${answer.model ?: "Stroom"}",
        StroomDate.long(answer.createdAt),
        sources.takeIf { it.isNotEmpty() }?.let { "gebruikt: " + it.joinToString(", ") },
    ).joinToString(" · ")
}

@Composable
fun <T> FeedLikeList(pager: ListPager, rows: List<T>, key: (T) -> Any, content: @Composable (T) -> Unit) {
    RegisterPageKeys(pager)
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f).pageGestures(pager)) {
            PagedColumn(rows, pager, key = key) { content(it) }
        }
        PageFooter(pager)
    }
}

@Composable
fun DocScreen(state: AppState, doc: Screen.Doc) {
    Column(Modifier.fillMaxSize()) {
        TopBar(doc.meta ?: doc.title, onBack = { state.back() })
        val blocks = remember(doc) {
            listOfNotNull(doc.meta?.let { Block.Meta(it) }, Block.Title(doc.title)) + ContentText.document(doc.markdown)
        }
        DocumentReader(state, blocks, "doc|${doc.title.hashCode()}|${doc.markdown.length}")
    }
}

@Composable
fun DigestScreen(state: AppState, screen: Screen.Digest) {
    var window by rememberSaveable { mutableStateOf("daily") }
    var digest by remember { mutableStateOf<Digest?>(null) }
    var loaded by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var generating by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    suspend fun load() {
        val api = state.api ?: return
        loaded = false
        error = null
        try {
            digest = api.digest(screen.topic, window)
        } catch (e: ApiException) {
            error = e.message
        }
        loaded = true
    }
    LaunchedEffect(window) { load() }
    LaunchedEffect(window, digest?.isGenerating) {
        while (digest?.isGenerating == true) {
            delay(15_000)
            load()
        }
    }
    fun generate() {
        val api = state.api ?: return
        generating = true
        error = null
        scope.launch {
            try {
                val model = api.model(if (window == "weekly") "digest_weekly" else "digest")
                digest = api.send("huygens/${screen.topic}/digest", query = model + ("window" to window))
            } catch (e: ApiException) {
                error = e.message
            } finally {
                generating = false
            }
        }
    }
    val label = if (window == "weekly") "Weekoverzicht" else "Dagoverzicht"
    Column(Modifier.fillMaxSize()) {
        TopBar("$label · ${screen.name}", onBack = { state.back() })
        Segmented(listOf("daily" to "Dag", "weekly" to "Week"), window, { window = it }, Modifier.padding(8.dp))
        Rule()
        val value = digest
        val markdown = value?.markdown
        when {
            !loaded -> Notice("Laden…")
            error != null -> Notice("Overzicht niet geladen", error, "Opnieuw", { scope.launch { load() } })
            generating || value?.isGenerating == true -> Notice(
                "$label wordt gemaakt",
                "Dit duurt meestal een paar minuten. Deze pagina kijkt vanzelf opnieuw.",
                "Opnieuw laden", { scope.launch { load() } },
            )
            markdown.isNullOrBlank() -> Notice(
                "Nog geen ${label.lowercase()}",
                value?.error ?: "Er is voor deze periode nog geen overzicht gemaakt.",
                "Maak overzicht", ::generate,
            )
            else -> {
                val meta = listOfNotNull(
                    label.uppercase(),
                    StroomDate.long(value.generatedAt)?.let { "gemaakt $it" },
                    value.itemCount?.let { "$it items" },
                    value.model,
                ).joinToString("  ·  ")
                DocumentReader(
                    state,
                    listOf(Block.Meta(meta), Block.Title(screen.name)) + ContentText.document(markdown),
                    "digest|${screen.topic}|$window|${value.generatedAt}",
                )
            }
        }
    }
}
