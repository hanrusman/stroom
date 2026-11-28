package nl.c4w.stroom.boox

import android.app.Application
import android.content.Intent
import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import nl.c4w.stroom.boox.data.ContentText
import nl.c4w.stroom.boox.data.KeystoreSessionStore
import nl.c4w.stroom.boox.data.OfflineCache
import nl.c4w.stroom.boox.data.ReadingPositions
import nl.c4w.stroom.boox.data.Settings
import nl.c4w.stroom.boox.ui.PageKeys
import nl.c4w.stroom.boox.ui.StroomApp
import nl.c4w.stroom.boox.ui.turnNext
import nl.c4w.stroom.boox.ui.turnPrevious
import java.io.File

class AppViewModel(app: Application) : AndroidViewModel(app) {
    val state = AppState(
        settings = Settings(app),
        sessions = KeystoreSessionStore(app),
        cache = OfflineCache(File(app.filesDir, "offline")),
        positions = ReadingPositions(app),
        scope = viewModelScope,
    )

    init {
        runCatching {
            val text = app.assets.open("html_entities.json").bufferedReader().use { it.readText() }
            ContentText.installEntities(Json.decodeFromString(MapSerializer(String.serializer(), String.serializer()), text))
        }
        state.start()
    }
}

class MainActivity : ComponentActivity() {
    private val model: AppViewModel by viewModels()
    private val state get() = model.state

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { StroomApp(state) }
        if (savedInstanceState == null) handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND) state.share(intent.getStringExtra(Intent.EXTRA_TEXT))
    }

    /**
     * Bladerknoppen. De Go Color 7 stuurt afhankelijk van de Boox-instelling volume- of
     * paginatoetsen; page turners en toetsenborden sturen paginatoetsen of pijltjes.
     * Alleen toetsen die niet al door een tekstveld zijn gebruikt komen hier aan.
     */
    private fun direction(keyCode: Int): Int {
        val settings = state.reader
        val raw = when (keyCode) {
            KeyEvent.KEYCODE_PAGE_DOWN, KeyEvent.KEYCODE_DPAD_RIGHT, KeyEvent.KEYCODE_DPAD_DOWN,
            KeyEvent.KEYCODE_SPACE, KeyEvent.KEYCODE_MEDIA_NEXT -> 1
            KeyEvent.KEYCODE_PAGE_UP, KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_UP,
            KeyEvent.KEYCODE_MEDIA_PREVIOUS -> -1
            KeyEvent.KEYCODE_VOLUME_DOWN -> if (settings.volumeKeys) 1 else 0
            KeyEvent.KEYCODE_VOLUME_UP -> if (settings.volumeKeys) -1 else 0
            else -> 0
        }
        return if (keyCode in PAGE_KEYS && settings.swapKeys) -raw else raw
    }

    /**
     * Pagina- en volumetoetsen gaan vóór Compose: anders kan de focusnavigatie ze opeten.
     * Pijltjes komen via onKeyDown, zodat ze in tekstvelden de cursor blijven verplaatsen.
     */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val paging = PageKeys.current
        val direction = if (event.keyCode in PAGE_KEYS) direction(event.keyCode) else 0
        if (paging == null || direction == 0 || state.user == null) return super.dispatchKeyEvent(event)
        if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
            if (direction > 0) paging.turnNext() else paging.turnPrevious()
        }
        // Ook het loslaten afvangen, anders verschijnt alsnog de volumebalk.
        return true
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        val paging = PageKeys.current
        val direction = direction(keyCode)
        if (paging == null || direction == 0 || state.user == null) return super.onKeyDown(keyCode, event)
        if (direction > 0) paging.turnNext() else paging.turnPrevious()
        return true
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent): Boolean {
        if (PageKeys.current != null && direction(keyCode) != 0 && state.user != null) return true
        return super.onKeyUp(keyCode, event)
    }

    private companion object {
        val PAGE_KEYS = setOf(
            KeyEvent.KEYCODE_PAGE_DOWN, KeyEvent.KEYCODE_PAGE_UP,
            KeyEvent.KEYCODE_VOLUME_DOWN, KeyEvent.KEYCODE_VOLUME_UP,
        )
    }
}
