package nl.c4w.stroom.boox.data

/**
 * Feedtekst mengt HTML en Markdown. Dit is dezelfde opschoning als in de iOS-app
 * (ContentText.swift): eerst entities decoderen, dan HTML omzetten naar Markdown.
 * Er wordt nooit externe inhoud geladen.
 */
object ContentText {
    private val BASIC_ENTITIES = mapOf(
        "amp" to "&", "lt" to "<", "gt" to ">", "quot" to "\"", "apos" to "'", "nbsp" to "\u00A0",
        "hellip" to "…", "mdash" to "—", "ndash" to "–", "lsquo" to "‘", "rsquo" to "’",
        "ldquo" to "“", "rdquo" to "”", "euro" to "€", "eacute" to "é", "euml" to "ë", "iuml" to "ï",
    )

    @Volatile
    private var entities: Map<String, String> = BASIC_ENTITIES

    /** De volledige HTML5-tabel komt uit assets/html_entities.json (gedeeld met iOS). */
    fun installEntities(map: Map<String, String>) {
        if (map.isNotEmpty()) entities = map
    }

    private val entityRegex = Regex("&(#[xX][0-9a-fA-F]+|#\\d+|[A-Za-z][A-Za-z0-9]+);")

    fun decodeEntities(raw: String): String = entityRegex.replace(raw) { match ->
        val name = match.groupValues[1]
        if (name.startsWith("#")) {
            val hex = name.length > 1 && (name[1] == 'x' || name[1] == 'X')
            val number = name.drop(if (hex) 2 else 1).toIntOrNull(if (hex) 16 else 10)
            if (number != null && number > 0 && Character.isValidCodePoint(number)) String(Character.toChars(number)) else ""
        } else {
            entities[name] ?: match.value
        }
    }

    fun markdown(raw: String): String {
        // Eerst decoderen: geëscapete HTML mag na het strippen geen zichtbare opmaak worden.
        var text = raw
        repeat(2) { text = decodeEntities(text) }
        text = text.replace(Regex("(?is)<(script|style|iframe|object|noscript)\\b[^>]*>.*?</\\1\\s*>"), "")
        text = text.replace(Regex("(?s)<!--.*?-->"), "")
        text = Regex("(?is)<a\\b[^>]*href\\s*=\\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a\\s*>").replace(text) { m ->
            val href = m.groupValues[1]
            val label = m.groupValues[2]
            val scheme = href.substringBefore(':', "").lowercase()
            if (scheme in setOf("http", "https", "mailto")) {
                "[$label](${href.replace("(", "%28").replace(")", "%29")})"
            } else {
                label
            }
        }
        text = text.replace(Regex("(?i)<br\\s*/?>"), "\n")
        text = Regex("(?i)<(h[1-6])\\b[^>]*>(.*?)</\\1\\s*>").replace(text) { m ->
            val level = m.groupValues[1].drop(1).toInt().coerceIn(1, 4)
            "\n\n${"#".repeat(level)} ${m.groupValues[2].trim()}\n\n"
        }
        text = text.replace(Regex("(?i)</?(p|div|section|article|ul|ol|blockquote|h[1-6]|pre)\\b[^>]*>"), "\n\n")
        text = text.replace(Regex("(?i)<li\\b[^>]*>"), "\n• ")
        text = text.replace(Regex("(?i)</li\\s*>"), "\n")
        text = text.replace(Regex("(?i)</?(strong|b)\\b[^>]*>"), "**")
        text = text.replace(Regex("(?i)</?(em|i)\\b[^>]*>"), "*")
        text = text.replace(Regex("</?[A-Za-z][A-Za-z0-9:-]*(?:\\s[^<>]*?)?\\s*/?>"), "")
        return text.replace("\r\n", "\n").replace(Regex("\n[ \t]*\n(?:[ \t]*\n)+"), "\n\n").trim()
    }

    /** Platte tekst voor kaartjes: geen opmaak, geen afbeeldingen, één regel. */
    fun excerpt(raw: String?): String {
        if (raw.isNullOrBlank()) return ""
        val clean = markdown(raw).replace(Regex("!\\[([^\\]]*)]\\([^)]*\\)"), "$1")
        return clean.lines().joinToString(" ") { line ->
            parseInline(stripBlockMarker(line)).plain
        }.replace(Regex("\\s+"), " ").trim()
    }

    private fun stripBlockMarker(line: String): String =
        line.trim()
            .replace(Regex("^#{1,6}\\s+"), "")
            .replace(Regex("^>\\s?"), "")
            .replace(Regex("^([-*+•]|\\d+[.)])\\s+"), "")

    // --- Markdown → blokken voor de gepagineerde lezer ---

    fun document(raw: String?): List<Block> {
        if (raw.isNullOrBlank()) return emptyList()
        val text = markdown(raw).replace(Regex("!\\[([^\\]]*)]\\([^)]*\\)"), "")
        val blocks = mutableListOf<Block>()
        val paragraph = StringBuilder()
        var inFence = false
        val fence = StringBuilder()

        fun flush() {
            val body = paragraph.toString().trim()
            if (body.isNotEmpty()) blocks += Block.Paragraph(parseInline(body))
            paragraph.clear()
        }

        for (rawLine in text.lines()) {
            val line = rawLine.trimEnd()
            val trimmed = line.trim()
            if (trimmed.startsWith("```")) {
                if (inFence) {
                    if (fence.isNotBlank()) blocks += Block.Paragraph(Inline(listOf(Run(fence.toString().trimEnd(), code = true))))
                    fence.clear()
                } else {
                    flush()
                }
                inFence = !inFence
                continue
            }
            if (inFence) {
                fence.append(line).append('\n')
                continue
            }
            when {
                trimmed.isEmpty() -> flush()
                RULE.matches(trimmed) -> {
                    flush()
                    blocks += Block.Rule
                }
                HEADING.containsMatchIn(trimmed) -> {
                    flush()
                    val match = HEADING.find(trimmed)!!
                    val content = trimmed.substring(match.range.last + 1).trim().trimEnd('#').trim()
                    if (content.isNotEmpty()) blocks += Block.Heading(match.groupValues[1].length, parseInline(content))
                }
                LIST.containsMatchIn(line) -> {
                    flush()
                    val match = LIST.find(line)!!
                    val indent = match.groupValues[1].replace("\t", "    ").length
                    val marker = match.groupValues[2].let { if (it.first().isDigit()) it.trimEnd(')').trimEnd('.') + "." else "•" }
                    blocks += Block.ListItem(marker, parseInline(line.substring(match.range.last + 1).trim()), (indent / 2).coerceAtMost(3))
                }
                trimmed.startsWith(">") -> {
                    flush()
                    val content = trimmed.trimStart('>', ' ')
                    val previous = blocks.lastOrNull()
                    if (previous is Block.Quote && content.isNotEmpty()) {
                        blocks[blocks.lastIndex] = Block.Quote(Inline(previous.text.runs + Run(" ") + parseInline(content).runs))
                    } else if (content.isNotEmpty()) {
                        blocks += Block.Quote(parseInline(content))
                    }
                }
                else -> {
                    // Een losse regel na een lijstitem hoort bij dat item (lazy continuation).
                    val previous = blocks.lastOrNull()
                    if (paragraph.isEmpty() && previous is Block.ListItem && rawLine.startsWith(" ")) {
                        blocks[blocks.lastIndex] = previous.copy(text = Inline(previous.text.runs + Run(" ") + parseInline(trimmed).runs))
                    } else {
                        if (paragraph.isNotEmpty()) paragraph.append(' ')
                        paragraph.append(trimmed)
                    }
                }
            }
        }
        if (inFence && fence.isNotBlank()) blocks += Block.Paragraph(Inline(listOf(Run(fence.toString().trimEnd(), code = true))))
        flush()
        return blocks
    }

    fun parseInline(source: String): Inline {
        val runs = mutableListOf<Run>()
        val buffer = StringBuilder()
        var bold = false
        var italic = false
        var i = 0

        fun flush() {
            if (buffer.isNotEmpty()) {
                runs += Run(buffer.toString(), bold = bold, italic = italic)
                buffer.clear()
            }
        }

        fun closes(marker: String, from: Int): Boolean {
            val end = source.indexOf(marker, from)
            return end > from && !source[end - 1].isWhitespace()
        }

        while (i < source.length) {
            val c = source[i]
            val next = source.getOrNull(i + 1)
            when {
                c == '\\' && next != null && next in ESCAPABLE -> {
                    buffer.append(next)
                    i += 2
                }
                (source.startsWith("**", i) || source.startsWith("__", i)) &&
                    (bold || (next != null && closes(source.substring(i, i + 2), i + 2) && source.getOrNull(i + 2)?.isWhitespace() == false)) -> {
                    flush()
                    bold = !bold
                    i += 2
                }
                (c == '*' || (c == '_' && (italic || i == 0 || !source[i - 1].isLetterOrDigit()))) &&
                    (italic || (next != null && !next.isWhitespace() && closes(c.toString(), i + 1))) -> {
                    flush()
                    italic = !italic
                    i += 1
                }
                c == '`' && source.indexOf('`', i + 1) > i -> {
                    flush()
                    val end = source.indexOf('`', i + 1)
                    runs += Run(source.substring(i + 1, end), code = true)
                    i = end + 1
                }
                c == '[' -> {
                    val match = LINK.matchAt(source, i)
                    if (match != null) {
                        flush()
                        val label = parseInline(match.groupValues[1]).runs.ifEmpty { listOf(Run(match.groupValues[2])) }
                        runs += label.map { it.copy(bold = it.bold || bold, italic = it.italic || italic, link = match.groupValues[2]) }
                        i = match.range.last + 1
                    } else {
                        buffer.append(c)
                        i++
                    }
                }
                else -> {
                    buffer.append(c)
                    i++
                }
            }
        }
        flush()
        return Inline(runs.filter { it.text.isNotEmpty() })
    }

    /** Transcript als leesbare alinea's: per spreker gebundeld, met tijdcode ervoor. */
    fun transcriptDocument(item: FeedItem): List<Block> {
        val segments = item.segments
        if (segments.isEmpty()) return document(item.transcript)
        val blocks = mutableListOf<Block>()
        var speaker: String? = null
        var start = 0.0
        val text = StringBuilder()

        fun flush() {
            if (text.isEmpty()) return
            val runs = mutableListOf(Run(timestamp(start) + "  ", bold = true))
            if (speaker != null) runs += Run("$speaker: ", italic = true)
            runs += Run(text.toString())
            blocks += Block.Paragraph(Inline(runs))
            text.clear()
        }

        for (segment in segments) {
            val changed = segment.speaker != null && segment.speaker != speaker
            if (text.isNotEmpty() && (changed || text.length > 700)) flush()
            if (text.isEmpty()) {
                start = segment.start
                if (segment.speaker != null) speaker = segment.speaker
            }
            if (text.isNotEmpty()) text.append(' ')
            text.append(decodeEntities(segment.text))
        }
        flush()
        return blocks
    }

    fun timestamp(seconds: Double): String {
        val total = seconds.toLong()
        val h = total / 3600
        val m = (total % 3600) / 60
        val s = total % 60
        return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
    }

    private val HEADING = Regex("^(#{1,6})\\s+")
    private val LIST = Regex("^(\\s*)([-*+•]|\\d{1,3}[.)])\\s+")
    private val RULE = Regex("^(\\*\\s*){3,}$|^(-\\s*){3,}$|^(_\\s*){3,}$")
    private val LINK = Regex("\\[([^\\]]*)]\\(([^)\\s]+)\\)")
    private const val ESCAPABLE = "\\`*_{}[]()#+-.!>|"
}

data class Run(
    val text: String,
    val bold: Boolean = false,
    val italic: Boolean = false,
    val code: Boolean = false,
    val link: String? = null,
)

data class Inline(val runs: List<Run>) {
    val plain get() = runs.joinToString("") { it.text }

    companion object {
        fun plain(text: String) = Inline(listOf(Run(text)))
    }
}

sealed interface Block {
    data class Heading(val level: Int, val text: Inline) : Block
    data class Paragraph(val text: Inline) : Block
    data class ListItem(val marker: String, val text: Inline, val depth: Int = 0) : Block
    data class Quote(val text: Inline) : Block
    data object Rule : Block

    /** Kleine regel in schreefloos, voor bron, datum en modelnaam. */
    data class Meta(val text: String) : Block

    /** De titel bovenaan een artikel. */
    data class Title(val text: String) : Block
}
