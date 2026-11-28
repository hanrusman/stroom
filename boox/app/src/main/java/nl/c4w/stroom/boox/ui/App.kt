package nl.c4w.stroom.boox.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import kotlinx.coroutines.delay
import nl.c4w.stroom.boox.AppState
import nl.c4w.stroom.boox.Screen

@Composable
fun StroomApp(state: AppState) {
    val type = rememberTypography(state.reader)
    CompositionLocalProvider(
        LocalType provides type,
        LocalPalette provides Palette.of(state.reader.color),
        LocalIndication provides EinkIndication,
    ) {
        Box(Modifier.fillMaxSize().background(Ink.Paper).safeDrawingPadding()) {
            when {
                state.starting -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Txt("Stroom", type.screenTitle.copy(fontSize = type.ui(2.2f)))
                }
                state.user == null -> LoginScreen(state)
                else -> Main(state)
            }
            Flash(state.flashTick)
        }
    }
}

@Composable
private fun Main(state: AppState) {
    val sheet = state.actionItem
    BackHandler(enabled = sheet != null || state.stack.size > 1) {
        if (sheet != null) state.actionItem = null else state.back()
    }
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (val screen = state.screen) {
                    Screen.Home -> HomeScreen(state)
                    Screen.Queue -> QueueScreen(state)
                    Screen.Saved -> SavedScreen(state)
                    Screen.More -> MoreScreen(state)
                    Screen.Topics -> TopicsScreen(state)
                    Screen.Search -> SearchScreen(state)
                    Screen.Options -> OptionsScreen(state)
                    is Screen.Reader -> ReaderScreen(state, screen.id)
                    is Screen.Digest -> DigestScreen(state, screen)
                    is Screen.Doc -> DocScreen(state, screen)
                    is Screen.Submit -> SubmitScreen(state, screen.url)
                }
            }
            state.banner?.let { banner ->
                Banner(banner.text, banner.action, {
                    state.banner = null
                    banner.onAction?.invoke()
                }) { state.banner = null }
            }
            // In de lezer en andere subschermen geen tabbalk: elke centimeter is leesruimte.
            if (state.stack.size == 1) {
                val root = state.root
                TabBar(
                    listOf(
                        Tab("Stroom", root == Screen.Home) { state.tab(Screen.Home) },
                        Tab("Wachtrij", root == Screen.Queue) { state.tab(Screen.Queue) },
                        Tab("Bewaard", root == Screen.Saved) { state.tab(Screen.Saved) },
                        Tab("Meer", root == Screen.More) { state.tab(Screen.More) },
                    ),
                )
            }
        }
        if (sheet != null) ItemActions(state, sheet, inReader = state.screen is Screen.Reader)
    }
}

/**
 * Volledige verversing: één zwart beeld, daarna weer de inhoud. Elke pixel wisselt dan
 * helemaal, waardoor nabeelden van eerdere pagina's verdwijnen.
 */
@Composable
private fun Flash(tick: Int) {
    var black by remember { mutableStateOf(false) }
    LaunchedEffect(tick) {
        if (tick == 0) return@LaunchedEffect
        black = true
        delay(160)
        black = false
    }
    if (black) Box(Modifier.fillMaxSize().background(Ink.Black))
}
