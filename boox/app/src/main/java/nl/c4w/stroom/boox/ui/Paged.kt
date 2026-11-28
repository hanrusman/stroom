package nl.c4w.stroom.boox.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.layout.SubcomposeLayout
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFontFamilyResolver
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.abs

/**
 * Bladeren met hardwaretoetsen (volumeknoppen, page turner, pijltjes). Het bovenste
 * geregistreerde scherm krijgt de toetsen; MainActivity stuurt ze hierheen.
 */
object PageKeys {
    private val handlers = mutableStateListOf<Paging>()
    val current: Paging? get() = handlers.lastOrNull()
    fun push(paging: Paging) = handlers.add(paging)
    fun remove(paging: Paging) = handlers.remove(paging)
}

/** Telt paginawissels voor de periodieke volledige verversing tegen nabeelden. */
object PageTurns {
    var onTurn: () -> Unit = {}
}

fun Paging.turnNext(): Boolean = next().also { if (it) PageTurns.onTurn() }
fun Paging.turnPrevious(): Boolean = previous().also { if (it) PageTurns.onTurn() }

@Composable
fun RegisterPageKeys(paging: Paging) {
    DisposableEffect(paging) {
        PageKeys.push(paging)
        onDispose { PageKeys.remove(paging) }
    }
}

/**
 * Vegen naar links of omhoog = volgende pagina, naar rechts of omlaag = vorige.
 * Met [onTap] worden korte tikken (zonder veeg) doorgegeven, bijvoorbeeld voor tikzones.
 * Klikbare kinderen blijven werken; een veeg annuleert hun klik.
 */
fun Modifier.pageGestures(paging: Paging, onTap: ((Offset, IntSize) -> Unit)? = null): Modifier =
    pointerInput(paging, onTap) {
        val threshold = 40.dp.toPx()
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false)
            var total = Offset.Zero
            var dragging = false
            while (true) {
                val event = awaitPointerEvent()
                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                if (!change.pressed) {
                    if (dragging) {
                        val horizontal = abs(total.x) >= abs(total.y)
                        val delta = if (horizontal) total.x else total.y
                        if (abs(delta) > threshold) {
                            if (delta < 0) paging.turnNext() else paging.turnPrevious()
                        }
                        change.consume()
                    } else if (onTap != null && !change.isConsumed) {
                        onTap(change.position, size)
                        change.consume()
                    }
                    break
                }
                total += change.positionChange()
                if (!dragging && total.getDistance() > viewConfiguration.touchSlop * 1.5f) dragging = true
                if (dragging) change.consume()
            }
        }
    }

/** Tikzones voor tekst: linkerdeel terug, de rest verder (zoals op een e-reader). */
fun Modifier.readerTapZones(paging: Paging, enabled: Boolean) =
    pageGestures(paging, onTap = if (!enabled) null else { pos, size ->
        if (pos.x < size.width * 0.3f) paging.turnPrevious() else paging.turnNext()
    })

class BuiltDocument(
    val text: AnnotatedString,
    val spacerOffsets: Set<Int>,
    val keepOffsets: Set<Int>,
    val style: TextStyle,
)

/**
 * Toont één pagina van een lange tekst. De tekst wordt één keer opgemaakt (op de achtergrond)
 * en daarna op regelgrenzen in pagina's gesneden; een pagina tekenen is dan alleen nog een
 * uitsnede, zonder herberekening. Er wordt nooit gescrold.
 */
@Composable
fun PagedDocument(
    document: BuiltDocument,
    pager: DocumentPager,
    modifier: Modifier = Modifier,
    onLaidOut: () -> Unit = {},
) {
    val resolver = LocalFontFamilyResolver.current
    val density = LocalDensity.current
    val direction = LocalLayoutDirection.current
    val laidOut by rememberUpdatedState(onLaidOut)
    BoxWithConstraints(modifier.fillMaxSize()) {
        val width = constraints.maxWidth
        val height = constraints.maxHeight
        var layout by remember { mutableStateOf<TextLayoutResult?>(null) }
        LaunchedEffect(document, pager, width, height) {
            val measurer = TextMeasurer(resolver, density, direction, 0)
            val result = withContext(Dispatchers.Default) {
                measurer.measure(document.text, style = document.style, constraints = Constraints(maxWidth = width.coerceAtLeast(1)))
            }
            val lines = (0 until result.lineCount).map { i ->
                val start = result.getLineStart(i)
                LineBox(
                    top = result.getLineTop(i),
                    bottom = result.getLineBottom(i),
                    startOffset = start,
                    spacer = start in document.spacerOffsets,
                    keepWithNext = start in document.keepOffsets,
                )
            }
            pager.update(Pagination.slice(lines, height.toFloat()))
            layout = result
            laidOut()
        }
        val result = layout
        val slice = pager.current()
        if (result != null && slice != null) {
            Canvas(Modifier.fillMaxWidth().height(with(density) { height.toDp() })) {
                clipRect(0f, 0f, size.width, slice.height) {
                    translate(top = -slice.top) { drawText(result) }
                }
            }
        } else {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Label("Pagina’s opmaken…") }
        }
    }
}

/**
 * Een lijst die bladert in plaats van scrolt. Alle items worden gemeten en daarna
 * zo verdeeld dat geen item over een paginagrens valt.
 */
@Composable
fun <T> PagedColumn(
    items: List<T>,
    pager: ListPager,
    modifier: Modifier = Modifier,
    key: (T) -> Any,
    keepWithNext: (T) -> Boolean = { false },
    content: @Composable (T) -> Unit,
) {
    SubcomposeLayout(modifier.fillMaxSize()) { constraints ->
        val width = constraints.maxWidth
        val pageHeight = constraints.maxHeight
        val measured = items.mapIndexed { index, item ->
            subcompose("$index|${key(item)}") { content(item) }
                .map { it.measure(Constraints(minWidth = width, maxWidth = width)) }
        }
        val pages = Pagination.pack(measured.map { row -> row.sumOf { it.height } }, pageHeight) { keepWithNext(items[it]) }
        pager.update(pages)
        val visible = pages.getOrNull(pager.page) ?: IntRange.EMPTY
        layout(width, pageHeight) {
            var y = 0
            for (i in visible) {
                measured[i].forEach { placeable ->
                    placeable.place(0, y)
                    y += placeable.height
                }
            }
        }
    }
}
