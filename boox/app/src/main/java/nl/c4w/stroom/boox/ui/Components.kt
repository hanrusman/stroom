package nl.c4w.stroom.boox.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

@Composable
fun Txt(
    text: String,
    style: TextStyle,
    modifier: Modifier = Modifier,
    maxLines: Int = Int.MAX_VALUE,
    align: TextAlign? = null,
) {
    BasicText(
        text = text,
        style = if (align != null) style.copy(textAlign = align) else style,
        modifier = modifier,
        maxLines = maxLines,
        overflow = if (maxLines == Int.MAX_VALUE) TextOverflow.Clip else TextOverflow.Ellipsis,
    )
}

@Composable
fun Label(text: String, modifier: Modifier = Modifier, bold: Boolean = false, maxLines: Int = Int.MAX_VALUE) {
    val type = LocalType.current
    Txt(text, if (bold) type.label.copy(fontWeight = FontWeight.Bold) else type.label, modifier, maxLines)
}

@Composable
fun Meta(text: String, modifier: Modifier = Modifier, maxLines: Int = 1) {
    Txt(text, LocalType.current.meta, modifier, maxLines)
}

@Composable
fun Rule(heavy: Boolean = false, modifier: Modifier = Modifier, color: Color = Ink.Black) {
    Box(modifier.fillMaxWidth().height(if (heavy) Space.heavyRule else Space.rule).background(color))
}

/** Knop met zwarte rand; `filled` is wit op de accentkleur, voor de hoofdactie of actieve keuze. */
@Composable
fun EButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    filled: Boolean = false,
    enabled: Boolean = true,
    borderless: Boolean = false,
    description: String? = null,
) {
    val type = LocalType.current
    val palette = LocalPalette.current
    val color = when {
        !enabled -> Ink.Disabled
        filled -> palette.onAccent
        else -> Ink.Black
    }
    Box(
        modifier
            .defaultMinSize(minWidth = Space.touch, minHeight = Space.touch)
            .then(if (filled && enabled) Modifier.background(palette.accent) else Modifier)
            .then(
                when {
                    borderless -> Modifier
                    filled && enabled -> Modifier.border(1.5.dp, palette.accent)
                    else -> Modifier.border(1.5.dp, if (enabled) Ink.Black else Ink.Disabled)
                },
            )
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Txt(label, type.label.copy(color = color, fontWeight = FontWeight.SemiBold), maxLines = 1, align = TextAlign.Center)
    }
}

/** Bovenbalk: terug-knop of titel links, acties rechts, dikke lijn eronder. */
@Composable
fun TopBar(
    title: String,
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    val type = LocalType.current
    Column(Modifier.fillMaxWidth().background(Ink.Paper)) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (onBack != null) {
                EButton("‹ Terug", onBack, borderless = true, description = "Terug")
            } else {
                Spacer(Modifier.width(8.dp))
            }
            Txt(
                title,
                if (onBack == null) type.screenTitle else type.label.copy(fontWeight = FontWeight.Bold),
                Modifier.weight(1f).padding(horizontal = 8.dp),
                maxLines = 1,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                actions()
            }
        }
        Rule(heavy = true, color = LocalPalette.current.accent)
    }
}

data class Tab(val label: String, val selected: Boolean, val onClick: () -> Unit)

/** Tabs onderaan: tekst, geen iconen. De actieve tab staat wit op de accentkleur. */
@Composable
fun TabBar(tabs: List<Tab>) {
    val type = LocalType.current
    val palette = LocalPalette.current
    Column(Modifier.fillMaxWidth().background(Ink.Paper)) {
        Rule(heavy = true)
        Row(Modifier.fillMaxWidth().height(56.dp)) {
            tabs.forEach { tab ->
                Box(
                    Modifier.weight(1f).fillMaxSize()
                        .then(if (tab.selected) Modifier.background(palette.accent) else Modifier)
                        .clickable(role = Role.Tab, onClick = tab.onClick),
                    contentAlignment = Alignment.Center,
                ) {
                    Txt(
                        tab.label,
                        type.label.copy(
                            color = if (tab.selected) palette.onAccent else Ink.Black,
                            fontWeight = if (tab.selected) FontWeight.Bold else FontWeight.Medium,
                        ),
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

/** Keuzerij met de actieve optie op de accentkleur, voor filters en instellingen. */
@Composable
fun <T> Segmented(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    val type = LocalType.current
    val palette = LocalPalette.current
    Row(modifier.fillMaxWidth().border(1.5.dp, Ink.Black)) {
        options.forEachIndexed { index, (value, label) ->
            val active = value == selected
            if (index > 0) Box(Modifier.width(1.5.dp).height(Space.touch).background(Ink.Black))
            Box(
                Modifier.weight(1f).height(Space.touch)
                    .then(if (active) Modifier.background(palette.accent) else Modifier)
                    .clickable(role = Role.RadioButton) { onSelect(value) },
                contentAlignment = Alignment.Center,
            ) {
                Txt(
                    label,
                    type.label.copy(
                        color = if (active) palette.onAccent else Ink.Black,
                        fontWeight = if (active) FontWeight.Bold else FontWeight.Medium,
                    ),
                    maxLines = 1,
                    align = TextAlign.Center,
                )
            }
        }
    }
}

/** Voettekst met bladerknoppen en paginanummer. */
@Composable
fun PageFooter(paging: Paging, modifier: Modifier = Modifier, extra: @Composable RowScope.() -> Unit = {}) {
    Column(modifier.fillMaxWidth().background(Ink.Paper)) {
        Rule()
        Row(
            Modifier.fillMaxWidth().height(52.dp).padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            EButton("‹ Vorige", { paging.turnPrevious() }, enabled = paging.page > 0, borderless = true)
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Label(if (paging.count == 0) "" else "${paging.page + 1} / ${paging.count}", bold = true)
                    extra()
                }
            }
            EButton("Volgende ›", { paging.turnNext() }, enabled = paging.page < paging.count - 1, borderless = true)
        }
    }
}

@Composable
fun Field(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    password: Boolean = false,
    keyboard: KeyboardType = KeyboardType.Text,
    ime: ImeAction = ImeAction.Next,
    onDone: () -> Unit = {},
    singleLine: Boolean = true,
    minLines: Int = 1,
) {
    val type = LocalType.current
    Column(modifier.fillMaxWidth()) {
        Label(label, bold = true)
        Spacer(Modifier.height(6.dp))
        BasicTextField(
            value = value,
            onValueChange = onChange,
            singleLine = singleLine,
            minLines = minLines,
            textStyle = type.label.copy(fontSize = type.ui(0.9f), fontWeight = FontWeight.Normal),
            cursorBrush = SolidColor(Ink.Black),
            visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = keyboard, imeAction = ime, autoCorrectEnabled = !password && keyboard == KeyboardType.Text),
            keyboardActions = KeyboardActions(onAny = { onDone() }),
            modifier = Modifier.fillMaxWidth().border(1.5.dp, Ink.Black).padding(12.dp)
                .semantics { contentDescription = label },
        )
    }
}

/** Mededeling zonder animatie: staat er tot je hem sluit of er een nieuwe komt. */
@Composable
fun Banner(text: String, actionLabel: String? = null, onAction: () -> Unit = {}, onClose: () -> Unit) {
    Column(Modifier.fillMaxWidth().background(Ink.Paper)) {
        Rule(heavy = true)
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Label(text, Modifier.weight(1f), maxLines = 3)
            if (actionLabel != null) EButton(actionLabel, onAction, filled = true)
            EButton("Sluit", onClose, borderless = true, description = "Mededeling sluiten")
        }
    }
}

/** Keuzemenu over het scherm heen, zonder in- of uitschuiven. */
@Composable
fun Sheet(title: String, onDismiss: () -> Unit, content: @Composable ColumnScope.() -> Unit) {
    Box(
        Modifier.fillMaxSize()
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null, onClick = onDismiss),
        contentAlignment = Alignment.BottomCenter,
    ) {
        Column(
            Modifier.fillMaxWidth().background(Ink.Paper)
                .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {}
                .padding(bottom = 8.dp),
        ) {
            Rule(heavy = true)
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Txt(title, LocalType.current.label.copy(fontWeight = FontWeight.Bold), Modifier.weight(1f), maxLines = 2)
                EButton("Sluit", onDismiss, borderless = true)
            }
            Rule()
            content()
        }
    }
}

/** Een volle-breedte keuze in een Sheet of lijst. */
@Composable
fun SheetItem(label: String, onClick: () -> Unit, enabled: Boolean = true, detail: String? = null) {
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(enabled = enabled, onClick = onClick)
                .padding(horizontal = 20.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Txt(label, LocalType.current.label.copy(color = if (enabled) Ink.Black else Ink.Disabled, fontSize = LocalType.current.ui(0.9f)))
                if (detail != null) Meta(detail, maxLines = 2)
            }
        }
        Rule()
    }
}

/** Lege of foutstaat met een duidelijke vervolgstap. */
@Composable
fun Notice(
    title: String,
    message: String? = null,
    action: String? = null,
    onAction: () -> Unit = {},
    modifier: Modifier = Modifier,
    secondary: Pair<String, () -> Unit>? = null,
) {
    val type = LocalType.current
    Column(modifier.fillMaxWidth().padding(Space.gutter), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Txt(title, type.cardTitle)
        if (message != null) Txt(message, type.cardBody)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (action != null) EButton(action, onAction, filled = true)
            if (secondary != null) EButton(secondary.first, secondary.second)
        }
    }
}

@Composable
fun Gap(height: Dp) = Spacer(Modifier.height(height))

/** Klikbaar en lang-indrukbaar, met de e-ink drukrand. */
fun Modifier.pressable(onClick: () -> Unit, onLongClick: (() -> Unit)? = null, label: String? = null): Modifier =
    combinedClickable(onClick = onClick, onLongClick = onLongClick, onLongClickLabel = label)
