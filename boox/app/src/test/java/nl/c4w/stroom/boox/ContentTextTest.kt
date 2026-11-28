package nl.c4w.stroom.boox

import nl.c4w.stroom.boox.data.Block
import nl.c4w.stroom.boox.data.ContentText
import nl.c4w.stroom.boox.data.FeedItem
import nl.c4w.stroom.boox.data.StroomJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ContentTextTest {
    @Test
    fun decodesNamedAndNumericEntities() {
        assertEquals("Tom & Jerry’s “film” — é", ContentText.decodeEntities("Tom &amp; Jerry&rsquo;s &#8220;film&#x201D; &mdash; &eacute;"))
        assertEquals("&onbekend;", ContentText.decodeEntities("&onbekend;"))
    }

    @Test
    fun escapedHtmlDoesNotBecomeMarkup() {
        // Dubbel geëscapete tags worden eerst gedecodeerd en daarna alsnog gestript.
        assertEquals("Hallo wereld", ContentText.excerpt("&amp;lt;b&amp;gt;Hallo&amp;lt;/b&amp;gt; wereld"))
    }

    @Test
    fun removesScriptsAndKeepsSafeLinks() {
        val md = ContentText.markdown("<p>Lees <a href=\"https://x.nl/a(b)\">dit</a> en <a href=\"javascript:alert(1)\">niet dit</a></p><script>evil()</script>")
        assertEquals("Lees [dit](https://x.nl/a%28b%29) en niet dit", md)
    }

    @Test
    fun excerptIsPlainSingleLine() {
        val text = "## Kop\n\nEen **vette** zin met *nadruk*.\n\n- punt een\n- punt twee ![plaatje](https://x/y.png)"
        assertEquals("Kop Een vette zin met nadruk. punt een punt twee plaatje", ContentText.excerpt(text))
    }

    @Test
    fun documentRecognisesBlocks() {
        val blocks = ContentText.document("# Titel\n\nAlinea één\nloopt door.\n\n- a\n- b\n\n> citaat\n\n---\n\n1. eerste")
        assertTrue(blocks[0] is Block.Heading)
        assertEquals("Alinea één loopt door.", (blocks[1] as Block.Paragraph).text.plain)
        assertEquals(listOf("•", "•"), blocks.filterIsInstance<Block.ListItem>().take(2).map { it.marker })
        assertTrue(blocks.any { it is Block.Quote })
        assertTrue(blocks.contains(Block.Rule))
        assertEquals("1.", blocks.filterIsInstance<Block.ListItem>().last().marker)
    }

    @Test
    fun inlineMarkupBecomesRuns() {
        val runs = ContentText.parseInline("Een **vet** en *schuin* en [link](https://a.nl) en `code`").runs
        assertTrue(runs.any { it.text == "vet" && it.bold })
        assertTrue(runs.any { it.text == "schuin" && it.italic })
        assertTrue(runs.any { it.text == "link" && it.link == "https://a.nl" })
        assertTrue(runs.any { it.text == "code" && it.code })
    }

    @Test
    fun loneAsterisksAndUnderscoresStayLiteral() {
        assertEquals("5 * 3 = 15 en snake_case_naam", ContentText.parseInline("5 * 3 = 15 en snake_case_naam").plain)
        assertFalse(ContentText.parseInline("5 * 3").runs.any { it.italic })
    }

    @Test
    fun transcriptGroupsBySpeakerAndSkipsBrokenSegments() {
        val segments = StroomJson.parseToJsonElement(
            """[{"start":0,"end":4,"text":"Welkom.","speaker":"Han"},
                {"start":4,"end":9,"text":"Fijn dat je er bent.","speaker":"Han"},
                {"start":9,"end":3,"text":"kapot"},
                {"start":9,"end":12,"text":"Dank je.","speaker":"Gast"}]""",
        ).jsonArray
        val item = FeedItem(id = "1", title = "x", format = "podcast", transcriptSegments = segments as JsonArray)
        val blocks = ContentText.transcriptDocument(item).map { (it as Block.Paragraph).text.plain }
        assertEquals(listOf("0:00  Han: Welkom. Fijn dat je er bent.", "0:09  Gast: Dank je."), blocks)
    }
}
