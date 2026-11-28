package nl.c4w.stroom.boox.ui

import androidx.compose.foundation.IndicationNodeFactory
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.node.DelegatableNode
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.invalidateDraw
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import nl.c4w.stroom.boox.R
import nl.c4w.stroom.boox.data.ReaderSettings

/**
 * Tekst is altijd zwart op wit: op Kaleido 3 is alleen zwart scherp (300 ppi), kleur wordt
 * met 150 ppi getoond. Hiërarchie komt uit lettergrootte, gewicht, cursief en lijnen.
 */
object Ink {
    val Black = Color(0xFF000000)
    val Paper = Color(0xFFFFFFFF)
    val Muted = Color(0xFF2B2B2B)
    val Disabled = Color(0xFF8A8A8A)
}

/**
 * Kleur alleen als accent: actieve keuzes, hoofdknoppen en een smalle balk per soort item.
 * Kaleido dempt kleuren sterk, daarom verzadigde, donkere tinten; pasteltinten verdwijnen.
 * [Mono] is voor zwart-wit Boox-modellen.
 */
@Immutable
data class Palette(
    val accent: Color,
    val onAccent: Color,
    val article: Color,
    val podcast: Color,
    val video: Color,
) {
    fun format(format: String?) = when (format) {
        "podcast" -> podcast
        "video" -> video
        else -> article
    }

    companion object {
        val Kaleido = Palette(
            accent = Color(0xFF0D4A8F),
            onAccent = Ink.Paper,
            article = Color(0xFF0D4A8F),
            podcast = Color(0xFFA3123A),
            video = Color(0xFF17713A),
        )
        val Mono = Palette(Ink.Black, Ink.Paper, Ink.Black, Ink.Black, Ink.Black)

        fun of(color: Boolean) = if (color) Kaleido else Mono
    }
}

val LocalPalette = compositionLocalOf { Palette.Kaleido }

@OptIn(ExperimentalTextApi::class)
private fun newsreader(weight: Int) =
    Font(R.font.newsreader, FontWeight(weight), FontStyle.Normal, variationSettings = FontVariation.Settings(FontVariation.weight(weight)))

@OptIn(ExperimentalTextApi::class)
private fun playfair(weight: Int) =
    Font(R.font.playfair, FontWeight(weight), FontStyle.Normal, variationSettings = FontVariation.Settings(FontVariation.weight(weight)))

@Immutable
data class Typography(
    val settings: ReaderSettings,
    val serif: FontFamily,
    val display: FontFamily,
    val sans: FontFamily,
) {
    val size get() = settings.textSize
    val bodyWeight get() = FontWeight(if (settings.serif) settings.weight else (settings.weight + 50).coerceAtMost(700))
    val strongWeight get() = FontWeight((settings.weight + 250).coerceIn(650, 800))

    /** Lettergrootte voor bediening: groeit mee met de leesgrootte tot 24, daarna niet meer. */
    fun ui(scale: Float = 0.8f): TextUnit = (size.coerceAtMost(24) * scale).coerceAtLeast(14f).sp

    val label get() = TextStyle(fontFamily = sans, fontSize = ui(0.78f), fontWeight = FontWeight.Medium, color = Ink.Black)
    val meta get() = TextStyle(fontFamily = sans, fontSize = ui(0.68f), letterSpacing = 0.4.sp, color = Ink.Muted)
    val cardTitle
        get() = TextStyle(
            fontFamily = serif, fontSize = (size * 1.0f).sp, fontWeight = strongWeight,
            lineHeight = (size * 1.22f).sp, color = Ink.Black, lineHeightStyle = TIGHT,
        )
    val cardBody
        get() = TextStyle(
            fontFamily = serif, fontSize = (size * 0.82f).sp, fontWeight = bodyWeight,
            lineHeight = (size * 1.18f).sp, color = Ink.Black, lineHeightStyle = TIGHT,
        )
    val screenTitle
        get() = TextStyle(fontFamily = display, fontSize = ui(1.15f), fontWeight = FontWeight(700), color = Ink.Black)
    val body
        get() = TextStyle(
            fontFamily = serif, fontSize = size.sp, fontWeight = bodyWeight,
            lineHeight = (size * settings.lineSpacing).sp, color = Ink.Black, lineHeightStyle = TIGHT,
        )

    companion object {
        val TIGHT = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.None)

        fun create(settings: ReaderSettings): Typography {
            val w = settings.weight
            val strong = (w + 250).coerceIn(650, 800)
            // Newsreader heeft geen cursieve variant in dit bestand; door er geen te registreren
            // zet Android de letter zelf schuin (font synthesis).
            val serif = if (settings.serif) {
                FontFamily(newsreader(w), newsreader(strong))
            } else {
                FontFamily.SansSerif
            }
            val display = FontFamily(playfair(700), playfair(800))
            return Typography(settings, serif, display, FontFamily.SansSerif)
        }
    }
}

val LocalType = compositionLocalOf { Typography.create(ReaderSettings()) }

object Space {
    val gutter: Dp = 20.dp
    val touch: Dp = 48.dp
    val rule: Dp = 1.dp
    val heavyRule: Dp = 2.dp

    fun margin(setting: Int): Dp = when (setting) {
        0 -> 14.dp
        2 -> 40.dp
        else -> 26.dp
    }
}

/**
 * Directe drukfeedback zonder animatie: een zwarte rand zolang je drukt. Een ripple
 * zou op e-ink een reeks tussenbeelden en dus nabeelden opleveren.
 */
object EinkIndication : IndicationNodeFactory {
    override fun create(interactionSource: InteractionSource): DelegatableNode = PressNode(interactionSource)
    override fun equals(other: Any?) = other === this
    override fun hashCode() = 7

    private class PressNode(private val source: InteractionSource) : Modifier.Node(), DrawModifierNode {
        private var pressed = false

        override fun onAttach() {
            coroutineScope.launch {
                source.interactions.collect {
                    val next = when (it) {
                        is PressInteraction.Press -> true
                        is PressInteraction.Release, is PressInteraction.Cancel -> false
                        else -> pressed
                    }
                    if (next != pressed) {
                        pressed = next
                        invalidateDraw()
                    }
                }
            }
        }

        override fun ContentDrawScope.draw() {
            drawContent()
            if (pressed) drawRect(Ink.Black, style = Stroke(width = 3.dp.toPx()))
        }
    }
}

@Composable
fun rememberTypography(settings: ReaderSettings) = remember(settings) { Typography.create(settings) }
