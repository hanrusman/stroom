package nl.c4w.stroom.boox

import nl.c4w.stroom.boox.ui.DocumentPager
import nl.c4w.stroom.boox.ui.LineBox
import nl.c4w.stroom.boox.ui.ListPager
import nl.c4w.stroom.boox.ui.Pagination
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PaginationTest {
    private fun lines(vararg kinds: Char): List<LineBox> {
        var y = 0f
        return kinds.mapIndexed { i, kind ->
            val height = if (kind == 's') 10f else 30f
            LineBox(y, y + height, i * 10, spacer = kind == 's', keepWithNext = kind == 'h').also { y += height }
        }
    }

    @Test
    fun pagesBreakBetweenLinesAndFitHeight() {
        val pages = Pagination.slice(lines('t', 't', 't', 't', 't'), pageHeight = 70f)
        assertEquals(listOf(0..1, 2..3, 4..4), pages.map { it.firstLine..it.lastLine })
        assertTrue(pages.all { it.height <= 70f })
    }

    @Test
    fun spacerNeverStartsAPage() {
        val pages = Pagination.slice(lines('t', 't', 's', 't'), pageHeight = 60f)
        assertEquals(3, pages[1].firstLine)
    }

    @Test
    fun headingMovesToNextPageInsteadOfEndingOne() {
        val pages = Pagination.slice(lines('t', 's', 'h', 't', 't'), pageHeight = 75f)
        assertEquals(2, pages[1].firstLine)
        assertFalse(pages[0].lastLine == 2)
    }

    @Test
    fun oversizedLineGetsOwnPage() {
        val tall = listOf(LineBox(0f, 500f, 0), LineBox(500f, 520f, 5))
        assertEquals(2, Pagination.slice(tall, 100f).size)
    }

    @Test
    fun documentPagerKeepsPositionAcrossRelayout() {
        val pager = DocumentPager()
        pager.update(Pagination.slice(lines('t', 't', 't', 't', 't', 't'), 70f))
        pager.next()
        pager.next()
        val anchor = pager.anchor
        assertEquals(40, anchor)
        // Grotere letter: minder regels per pagina, maar dezelfde tekst blijft in beeld.
        pager.update(Pagination.slice(lines('t', 't', 't', 't', 't', 't'), 40f))
        assertEquals(4, pager.page)
        assertEquals(40, pager.current()!!.startOffset)
    }

    @Test
    fun listPackingKeepsHeadersWithFirstItem() {
        val heights = listOf(20, 50, 50, 20, 50)
        val pages = Pagination.pack(heights, 130) { it == 0 || it == 3 }
        assertEquals(listOf(0..2, 3..4), pages)
    }

    @Test
    fun listPagerStaysOnAnchorAfterItemsChange() {
        val pager = ListPager()
        pager.update(listOf(0..2, 3..5, 6..8))
        pager.next()
        pager.update(listOf(0..1, 2..3, 4..5))
        assertEquals(1, pager.page)
        assertTrue(pager.previous())
    }
}
