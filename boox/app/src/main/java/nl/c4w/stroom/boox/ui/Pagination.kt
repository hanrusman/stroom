package nl.c4w.stroom.boox.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/** Eén regel van een opgemaakte tekst, in pixels. */
data class LineBox(
    val top: Float,
    val bottom: Float,
    val startOffset: Int,
    /** Witregel tussen blokken: hoort nooit bovenaan een pagina. */
    val spacer: Boolean = false,
    /** Kop of titel: blijft bij de regel erna en eindigt dus geen pagina. */
    val keepWithNext: Boolean = false,
)

data class PageSlice(val firstLine: Int, val lastLine: Int, val top: Float, val bottom: Float, val startOffset: Int) {
    val height get() = bottom - top
}

object Pagination {
    /**
     * Snijdt opgemaakte regels in pagina's van hoogstens [pageHeight]. Pagina's breken alleen
     * tussen regels, nooit midden in een regel. Een regel die hoger is dan een pagina krijgt
     * een eigen pagina.
     */
    fun slice(lines: List<LineBox>, pageHeight: Float): List<PageSlice> {
        val pages = mutableListOf<PageSlice>()
        var start = 0
        while (start < lines.size) {
            while (start < lines.size && lines[start].spacer) start++
            if (start >= lines.size) break
            val top = lines[start].top
            var end = start
            while (end + 1 < lines.size && lines[end + 1].bottom - top <= pageHeight) end++
            if (end + 1 < lines.size) {
                var last = end
                while (last > start && lines[last].spacer) last--
                var keep = last
                while (keep > start && lines[keep].keepWithNext) keep--
                if (keep < last && !lines[keep].keepWithNext) end = keep
            }
            pages += PageSlice(start, end, top, lines[end].bottom, lines[start].startOffset)
            start = end + 1
        }
        return pages
    }

    /** Verdeelt lijstitems over pagina's; [keepWithNext] houdt rubriekskoppen bij hun eerste item. */
    fun pack(heights: List<Int>, pageHeight: Int, keepWithNext: (Int) -> Boolean = { false }): List<IntRange> {
        val pages = mutableListOf<IntRange>()
        var start = 0
        while (start < heights.size) {
            var used = 0
            var end = start - 1
            while (end + 1 < heights.size && (end < start || used + heights[end + 1] <= pageHeight)) {
                end++
                used += heights[end]
            }
            if (end + 1 < heights.size && end > start && keepWithNext(end)) end--
            pages += start..end
            start = end + 1
        }
        return pages
    }
}

/** Gedeelde bladerbediening voor tekst en lijsten: knoppen, vegen en toetsen gebruiken dit. */
interface Paging {
    val page: Int
    val count: Int
    fun next(): Boolean
    fun previous(): Boolean
}

class DocumentPager(initialOffset: Int = 0) : Paging {
    var slices by mutableStateOf<List<PageSlice>>(emptyList())
        private set
    private var index by mutableIntStateOf(0)

    /** Tekenpositie van de huidige pagina; blijft gelijk als de opmaak verandert. */
    var anchor: Int = initialOffset
        private set

    override val page get() = index
    override val count get() = slices.size

    fun update(next: List<PageSlice>) {
        slices = next
        index = next.indexOfLast { it.startOffset <= anchor }.coerceAtLeast(0)
    }

    fun current(): PageSlice? = slices.getOrNull(index)

    override fun next(): Boolean = go(index + 1)
    override fun previous(): Boolean = go(index - 1)

    fun go(target: Int): Boolean {
        if (target !in slices.indices || target == index) return false
        index = target
        anchor = slices[target].startOffset
        return true
    }
}

class ListPager : Paging {
    var pages by mutableStateOf<List<IntRange>>(emptyList())
        private set
    private var index by mutableIntStateOf(0)
    private var anchor = 0

    override val page get() = index
    override val count get() = pages.size

    fun update(next: List<IntRange>) {
        if (next == pages) return
        pages = next
        index = next.indexOfFirst { anchor in it }.let { if (it < 0) (next.size - 1).coerceAtLeast(0) else it }
    }

    fun reset() {
        anchor = 0
        index = 0
    }

    override fun next(): Boolean = go(index + 1)
    override fun previous(): Boolean = go(index - 1)

    private fun go(target: Int): Boolean {
        if (target !in pages.indices) return false
        index = target
        anchor = pages[target].first
        return true
    }
}
