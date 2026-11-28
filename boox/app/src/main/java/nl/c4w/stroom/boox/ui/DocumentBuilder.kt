package nl.c4w.stroom.boox.ui

import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.ParagraphStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextIndent
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import nl.c4w.stroom.boox.data.Block
import nl.c4w.stroom.boox.data.Inline

/**
 * Zet blokken om in één opgemaakte tekst. Witruimte tussen blokken bestaat uit aparte,
 * gemarkeerde mini-alinea's, zodat de paginering ze bovenaan een pagina kan overslaan.
 */
object DocumentBuilder {
    private const val SPACER = "​"

    fun build(blocks: List<Block>, type: Typography): BuiltDocument {
        val size = type.size.toFloat()
        val spacing = type.settings.lineSpacing
        val spacers = mutableSetOf<Int>()
        val keeps = mutableListOf<IntRange>()
        val text = buildAnnotatedString {
            fun gap(height: Float) {
                spacers += length
                withStyle(ParagraphStyle(lineHeight = height.sp, lineHeightStyle = Typography.TIGHT)) {
                    withStyle(SpanStyle(fontSize = (height * 0.5f).sp)) { append(SPACER) }
                }
            }

            fun paragraph(style: ParagraphStyle, keep: Boolean = false, body: () -> Unit) {
                val start = length
                withStyle(style) { body() }
                // Het hele blok markeren, niet alleen het begin: een kop die over twee regels loopt
                // mag ook na zijn laatste regel niet onderaan een pagina achterblijven.
                if (keep && length > start) keeps.add(start until length)
            }

            blocks.forEachIndexed { index, block ->
                if (index > 0) {
                    val before = when (block) {
                        is Block.Heading -> size * 1.1f
                        is Block.Title -> size * 0.9f
                        is Block.Meta -> if (blocks[index - 1] is Block.Title) size * 0.55f else size * 0.35f
                        is Block.ListItem -> if (blocks[index - 1] is Block.ListItem) size * 0.3f else size * 0.7f
                        else -> if (blocks[index - 1] is Block.Meta) size * 1.2f else size * 0.7f
                    }
                    gap(before)
                }
                when (block) {
                    is Block.Title -> paragraph(para(size * 1.5f * 1.18f), keep = true) {
                        withStyle(
                            SpanStyle(fontFamily = type.display, fontSize = (size * 1.5f).sp, fontWeight = FontWeight(700)),
                        ) { append(block.text) }
                    }
                    is Block.Meta -> paragraph(para(size * 0.72f * 1.45f), keep = true) {
                        withStyle(
                            SpanStyle(fontFamily = FontFamily.SansSerif, fontSize = (size * 0.72f).sp, letterSpacing = 0.03.em),
                        ) { append(block.text) }
                    }
                    is Block.Heading -> {
                        val scale = when (block.level) {
                            1 -> 1.35f
                            2 -> 1.2f
                            else -> 1.05f
                        }
                        paragraph(para(size * scale * 1.25f), keep = true) {
                            withStyle(SpanStyle(fontSize = (size * scale).sp, fontWeight = type.strongWeight)) {
                                inline(block.text, type)
                            }
                        }
                    }
                    is Block.Paragraph -> paragraph(para(size * spacing)) { inline(block.text, type) }
                    is Block.ListItem -> {
                        // Hangend inspringen: vervolgregels beginnen onder de tekst, niet onder het teken.
                        val indent = 1.1f * block.depth
                        val hang = if (block.marker == "•") 0.9f else 0.55f + 0.5f * block.marker.length
                        paragraph(
                            para(size * spacing).copy(textIndent = TextIndent(firstLine = indent.em, restLine = (indent + hang).em)),
                        ) {
                            withStyle(SpanStyle(fontWeight = type.strongWeight)) { append(block.marker) }
                            append(" ")
                            inline(block.text, type)
                        }
                    }
                    is Block.Quote -> paragraph(
                        para(size * spacing).copy(textIndent = TextIndent(firstLine = 1.4.em, restLine = 1.4.em)),
                    ) {
                        withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { inline(block.text, type) }
                    }
                    Block.Rule -> paragraph(para(size * spacing).copy(textAlign = TextAlign.Center)) { append("*  *  *") }
                }
            }
        }
        return BuiltDocument(text, spacers, keeps, type.body)
    }

    private fun para(lineHeight: Float) = ParagraphStyle(lineHeight = lineHeight.sp, lineHeightStyle = Typography.TIGHT)

    private fun AnnotatedString.Builder.inline(text: Inline, type: Typography) {
        for (run in text.runs) {
            val style = SpanStyle(
                fontWeight = if (run.bold) type.strongWeight else null,
                fontStyle = if (run.italic) FontStyle.Italic else null,
                fontFamily = if (run.code) FontFamily.Monospace else null,
                fontSize = if (run.code) (type.size * 0.85f).sp else androidx.compose.ui.unit.TextUnit.Unspecified,
                textDecoration = if (run.link != null) TextDecoration.Underline else null,
            )
            withStyle(style) { append(run.text) }
        }
    }
}
