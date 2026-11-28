package nl.c4w.stroom.boox.ui

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import nl.c4w.stroom.boox.AppState
import nl.c4w.stroom.boox.BuildConfig
import nl.c4w.stroom.boox.Screen
import nl.c4w.stroom.boox.data.ApiException
import nl.c4w.stroom.boox.data.InboxPreview
import nl.c4w.stroom.boox.data.InboxResult
import nl.c4w.stroom.boox.data.ReaderSettings
import nl.c4w.stroom.boox.data.TopicChoice

@Composable
fun LoginScreen(state: AppState) {
    val type = LocalType.current
    var server by rememberSaveable { mutableStateOf(state.server) }
    var email by rememberSaveable { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    val submit = { if (!state.busy) state.login(server, email, password) }
    Box(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier.widthIn(max = 520.dp).fillMaxWidth().padding(Space.gutter),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Gap(24.dp)
            Txt("Stroom", type.screenTitle.copy(fontSize = type.ui(2.2f)))
            Txt("Lezen op je Boox. Log in met je Stroom-account; het wachtwoord wordt niet bewaard.", type.cardBody)
            Rule(heavy = true, color = LocalPalette.current.accent)
            Field("Server", server, { server = it }, keyboard = KeyboardType.Uri)
            Field("E-mail", email, { email = it }, keyboard = KeyboardType.Email)
            Field("Wachtwoord", password, { password = it }, password = true, keyboard = KeyboardType.Password, ime = ImeAction.Go, onDone = submit)
            EButton(
                if (state.busy) "Inloggen…" else "Inloggen",
                submit,
                Modifier.fillMaxWidth(),
                filled = true,
                enabled = !state.busy && email.isNotBlank() && password.isNotBlank(),
            )
            state.loginError?.let { Txt(it, type.label.copy(fontWeight = FontWeight.Bold)) }
            Meta("Gebruik het HTTPS-adres van je website, zonder /api erachter.", maxLines = 3)
        }
    }
}

@Composable
fun MoreScreen(state: AppState) {
    val context = LocalContext.current
    Column(Modifier.fillMaxSize()) {
        TopBar("Meer")
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            SheetItem("Zoeken", { state.open(Screen.Search) }, detail = "In titels, samenvattingen en transcripten")
            SheetItem("Link insturen", { state.open(Screen.Submit()) }, detail = "Of deel een link vanuit de browser naar Stroom")
            SheetItem("Leesinstellingen", { state.open(Screen.Options) }, detail = "Letter, kleur, marges, bladerknoppen, verversen")
            SheetItem("Scherm verversen", { state.flash() }, detail = "Wist nabeelden met één volledige verversing")
            SheetItem("Inhoud verversen", { state.refresh() }, enabled = !state.syncing, detail = syncText(state))
            SheetItem("Open de Stroom-website", {
                try {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(state.server)))
                } catch (e: ActivityNotFoundException) {
                    state.notify("Geen browser gevonden.")
                }
            }, detail = "Voor beheer, podcasts maken en dossiers")
            SheetItem("Uitloggen", { state.logout() }, enabled = !state.busy, detail = "Wist ook offline kopieën en leesposities op dit apparaat")
            Column(Modifier.padding(Space.gutter), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Meta("Ingelogd als ${state.user?.email ?: "-"}", maxLines = 2)
                Meta("Server: ${state.server}", maxLines = 2)
                Meta("${state.offlineIds.size} teksten offline leesbaar", maxLines = 2)
                Meta("Stroom voor Boox ${BuildConfig.VERSION_NAME}", maxLines = 2)
            }
        }
    }
}

private sealed interface OptionRow {
    data object Preview : OptionRow
    data class Choice<T>(val title: String, val options: List<Pair<T, String>>, val value: T, val set: (T) -> ReaderSettings) : OptionRow
}

@Composable
fun OptionsScreen(state: AppState) {
    val s = state.reader
    val onOff = listOf(true to "Aan", false to "Uit")
    val rows: List<OptionRow> = listOf(
        OptionRow.Preview,
        OptionRow.Choice("Lettergrootte", ReaderSettings.TEXT_SIZES.map { it to "$it" }, s.textSize) { s.copy(textSize = it) },
        OptionRow.Choice("Tekstdikte", ReaderSettings.WEIGHTS, s.weight) { s.copy(weight = it) },
        OptionRow.Choice("Regelafstand", ReaderSettings.SPACINGS, s.lineSpacing) { s.copy(lineSpacing = it) },
        OptionRow.Choice("Marges", ReaderSettings.MARGINS, s.margin) { s.copy(margin = it) },
        OptionRow.Choice("Lettertype", listOf(true to "Newsreader", false to "Schreefloos"), s.serif) { s.copy(serif = it) },
        OptionRow.Choice("Kleuraccenten (Kaleido)", onOff, s.color) { s.copy(color = it) },
        OptionRow.Choice("Bladeren met knoppen", onOff, s.volumeKeys) { s.copy(volumeKeys = it) },
        OptionRow.Choice("Knoppen omdraaien", onOff, s.swapKeys) { s.copy(swapKeys = it) },
        OptionRow.Choice("Tikzones (links terug, rechts verder)", onOff, s.tapZones) { s.copy(tapZones = it) },
        OptionRow.Choice("Volledig verversen", ReaderSettings.REFRESH, s.refreshEvery) { s.copy(refreshEvery = it) },
    )
    val pager = state.listPager("options")
    RegisterPageKeys(pager)
    val type = LocalType.current
    Column(Modifier.fillMaxSize()) {
        TopBar("Leesinstellingen", onBack = { state.back() })
        Box(Modifier.weight(1f).pageGestures(pager)) {
            PagedColumn(rows, pager, key = { if (it is OptionRow.Choice<*>) it.title else "preview" }) { row ->
                when (row) {
                    OptionRow.Preview -> Column(Modifier.fillMaxWidth().padding(horizontal = Space.margin(s.margin), vertical = 16.dp)) {
                        Meta("VOORBEELD")
                        Gap(6.dp)
                        Txt(
                            "Het water van de stroom neemt alles mee wat los ligt. Wat blijft liggen, is wat je bewust " +
                                "uit de stroom haalt en rustig leest.",
                            type.body,
                        )
                        Gap(12.dp)
                        Rule()
                    }
                    is OptionRow.Choice<*> -> ChoiceRow(state, row)
                }
            }
        }
        PageFooter(pager)
    }
}

@Composable
private fun <T> ChoiceRow(state: AppState, row: OptionRow.Choice<T>) {
    Column(Modifier.fillMaxWidth().padding(horizontal = Space.gutter, vertical = 10.dp)) {
        Label(row.title, bold = true)
        Gap(6.dp)
        Segmented(row.options, row.value, { state.updateReader(row.set(it)) })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SubmitScreen(state: AppState, initialUrl: String) {
    var url by rememberSaveable { mutableStateOf(initialUrl) }
    var title by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    var format by rememberSaveable { mutableStateOf("article") }
    var topic by rememberSaveable { mutableStateOf("") }
    var topics by remember { mutableStateOf<List<TopicChoice>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var result by remember { mutableStateOf<InboxResult?>(null) }
    val scope = rememberCoroutineScope()
    val valid = url.trim().let { it.startsWith("https://") || it.startsWith("http://") }

    LaunchedEffect(Unit) {
        val api = state.api ?: return@LaunchedEffect
        try {
            topics = api.get("inbox/topics")
            if (topic.isEmpty()) topic = topics.firstOrNull { it.slug == state.selectedTopic }?.slug ?: topics.firstOrNull()?.slug.orEmpty()
        } catch (e: ApiException) {
            error = e.message
        }
    }
    fun preview() {
        val api = state.api ?: return
        busy = true
        error = null
        scope.launch {
            try {
                val value: InboxPreview = api.send("inbox/fetch", body = buildJsonObject { put("url", url.trim()) })
                title = value.title ?: title
                description = value.description ?: description
                format = value.format
            } catch (e: ApiException) {
                error = "Ophalen mislukt. Je kunt titel en soort ook zelf invullen. ${e.message}"
            } finally {
                busy = false
            }
        }
    }
    fun submit() {
        val api = state.api ?: return
        busy = true
        error = null
        scope.launch {
            try {
                result = api.send(
                    "inbox/submit",
                    body = buildJsonObject {
                        put("url", url.trim())
                        put("title", title.trim())
                        put("format", format)
                        put("topic_slug", topic)
                        put("description", description)
                    },
                )
            } catch (e: ApiException) {
                error = e.message
            } finally {
                busy = false
            }
        }
    }
    LaunchedEffect(initialUrl) { if (initialUrl.isNotBlank() && title.isEmpty()) preview() }

    Column(Modifier.fillMaxSize()) {
        TopBar("Link insturen", onBack = { state.back() })
        val done = result
        if (done != null) {
            Notice("Ingestuurd", done.message, "Klaar", { state.back() })
            return@Column
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(Space.gutter),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Field("Link", url, { url = it }, keyboard = KeyboardType.Uri, ime = ImeAction.Go, onDone = { if (valid) preview() })
            EButton(if (busy) "Bezig…" else "Titel en beschrijving ophalen", ::preview, enabled = valid && !busy)
            Field("Titel", title, { title = it })
            Field("Beschrijving (optioneel)", description, { description = it }, singleLine = false, minLines = 3)
            Label("Soort", bold = true)
            Segmented(listOf("article" to "Artikel", "podcast" to "Podcast", "video" to "Video"), format, { format = it })
            Label("Onderwerp", bold = true)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                topics.forEach { choice -> EButton(choice.name, { topic = choice.slug }, filled = choice.slug == topic) }
            }
            error?.let { Txt(it, LocalType.current.label.copy(fontWeight = FontWeight.Bold)) }
            EButton(
                if (busy) "Bezig…" else "Stuur naar Stroom",
                ::submit,
                Modifier.fillMaxWidth(),
                filled = true,
                enabled = valid && title.isNotBlank() && topic.isNotEmpty() && !busy,
            )
            Txt(
                "Een gedeelde link wordt nooit automatisch verstuurd.",
                LocalType.current.meta,
                align = TextAlign.Start,
            )
        }
    }
}
