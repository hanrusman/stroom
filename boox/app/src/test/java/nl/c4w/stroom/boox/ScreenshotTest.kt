package nl.c4w.stroom.boox

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import com.github.takahirom.roborazzi.captureRoboImage
import nl.c4w.stroom.boox.ui.StroomApp
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Schermen op de resolutie van de Boox Go Color 7 (1264 × 1680 px, 632 × 840 dp).
 * De afbeeldingen komen in app/build/outputs/roborazzi.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "w632dp-h840dp-xhdpi")
class ScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private val context get() = RuntimeEnvironment.getApplication()

    private fun shot(name: String) {
        compose.waitForIdle()
        compose.onRoot().captureRoboImage("build/outputs/roborazzi/$name.png")
    }

    private fun waitForPages() {
        compose.waitUntil(15_000) { compose.onAllNodesWithText("Pagina’s opmaken…").fetchSemanticsNodes().isEmpty() }
    }

    @Test
    fun login() {
        val state = Fixtures.state(context).apply { user = null }
        compose.setContent { StroomApp(state) }
        shot("01-inloggen")
    }

    @Test
    fun homeWithRails() {
        val state = Fixtures.state(context)
        compose.setContent { StroomApp(state) }
        compose.onNodeWithText("Technologie ▾").assertExists()
        shot("02-stroom-technologie")
        compose.onNodeWithText("Volgende ›").performClick()
        shot("03-stroom-pagina-2")
    }

    @Test
    fun homeInBlackAndWhite() {
        val state = Fixtures.state(context)
        state.updateReader(state.reader.copy(color = false))
        compose.setContent { StroomApp(state) }
        shot("04-stroom-zwart-wit")
    }

    @Test
    fun readerPagesInsteadOfScrolling() {
        val state = Fixtures.state(context)
        state.open(Screen.Reader("a1"))
        compose.setContent { StroomApp(state) }
        waitForPages()
        shot("05-lezer-samenvatting")
        compose.onNodeWithText("Volgende ›").performClick()
        shot("06-lezer-pagina-2")
        compose.onNodeWithText("2 / ", substring = true).assertExists()
    }

    @Test
    fun readerLargeText() {
        val state = Fixtures.state(context)
        state.updateReader(state.reader.copy(textSize = 28, weight = 550))
        state.open(Screen.Reader("a1"))
        compose.setContent { StroomApp(state) }
        waitForPages()
        shot("07-lezer-grote-letter")
    }

    @Test
    fun readerLessons() {
        val state = Fixtures.state(context)
        state.open(Screen.Reader("a1"))
        compose.setContent { StroomApp(state) }
        compose.onNodeWithText("Lessen").performClick()
        shot("08-lezer-lessen")
    }

    @Test
    fun actionSheet() {
        val state = Fixtures.state(context)
        state.open(Screen.Reader("a1"))
        state.actionItem = Fixtures.article
        compose.setContent { StroomApp(state) }
        waitForPages()
        shot("09-acties")
    }

    @Test
    fun queueOffline() {
        val state = Fixtures.state(context, offline = true)
        state.tab(Screen.Queue)
        compose.setContent { StroomApp(state) }
        compose.onNodeWithText("Offline", substring = true).assertExists()
        shot("10-wachtrij-offline")
    }

    @Test
    fun readingOptions() {
        val state = Fixtures.state(context)
        state.open(Screen.Options)
        compose.setContent { StroomApp(state) }
        shot("11-leesinstellingen")
        compose.onNodeWithText("Volgende ›").performClick()
        shot("12-leesinstellingen-2")
    }

    @Test
    fun moreScreen() {
        val state = Fixtures.state(context)
        state.tab(Screen.More)
        compose.setContent { StroomApp(state) }
        shot("13-meer")
        assertTrue(state.stack.size == 1)
    }
}
