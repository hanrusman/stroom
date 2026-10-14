# Stroom Design System — conventions for building with it

Stroom is an **editorial** content system: serif display type, a warm cream/ink palette, a single deep-blue accent, and generous rounded surfaces. Build calm, reading-first layouts — not dense dashboards.

## Setup & wrapping

- **No provider or theme wrapper is required.** Every component is self-contained; import and render it directly (`window.StroomDS.<Name>`).
- **Fonts load automatically.** The stylesheet `@import`s the brand families from Google Fonts — Playfair Display, Newsreader, Inter Tight, JetBrains Mono. Don't add font links; just use the font utilities below.
- **Dark mode** is opt-in: add `class="dark"` to a root ancestor (e.g. `<html>` or a wrapper `<div>`). Every `brand-*` token has a dark value, so components and your own utility-styled glue both flip automatically. `color-scheme` is set for you.
- The page background is `bg-brand-cream` and default body text is `text-brand-ink` in the **Inter Tight** sans family. Set these on your outermost element.

## Styling idiom — Tailwind utilities with brand tokens

Style your own layout glue with **Tailwind v4 utility classes**, always reaching for the `brand-*` token scale (never raw hex, never invented color names). Opacity modifiers work (`text-brand-ink/70`, `border-brand-ink/10`). The real vocabulary:

| Concern | Classes |
|---|---|
| Page / surfaces | `bg-brand-cream` (page), `bg-brand-surface`, `bg-brand-surface-low`, `bg-brand-green-tint` (soft panel) |
| Accent | `bg-brand-accent`, `text-brand-accent` (deep blue) |
| Text | `text-brand-ink` (default), `text-brand-cream` (on dark/accent) |
| Borders | `border-brand-ink/10`, `border-brand-ink/15` (hairlines) |
| Type families | `font-serif` (Newsreader — headings & body copy), `font-display` (Playfair — hero titles), `font-mono` (JetBrains — labels/meta) |
| Radius | `rounded-2xl` (24px), `rounded-3xl` (32px), `rounded-full` (pills) |

Two idioms carry the brand: **uppercase mono labels** (`font-mono text-[11px] uppercase tracking-[0.18em]`) for meta/eyebrows, and **serif headlines** (`font-serif font-semibold tracking-[-0.01em]`).

## Components

Primitives: `Button` (pill; `primary`/`secondary`/`ghost`), `IconButton` (round; `filled` for media), `Badge` (mono pill; `neutral`/`accent`/`tint`), `Card` (`surface`/`tint`/`outline`, `large`, `interactive`), `Input`, `Textarea`, `Select`, `Spinner`.
Composites: `AudioPlayer` (podcast bar — presentational, wire callbacks), `ContentCard` (feed item — `article`/`podcast`/`video`), `Prose` (long-form `markdown` or `html`, sanitized; `size` + `invert`).

Prefer a library component over hand-rolling one. For long-form/AI summaries always use `Prose` — it carries the `prose-stroom` typography you can't reproduce with utilities alone.

## Where the truth lives

- The compiled stylesheet `styles.css` (it `@import`s `_ds_bundle.css`, which defines every `brand-*` token and the `prose-stroom` rules) — read it before inventing any class.
- Per-component API + usage: each component's `<Name>.prompt.md` (props, variants, examples).

## Idiomatic snippet

```tsx
const { ContentCard, Badge, Button } = window.StroomDS;

<main className="bg-brand-cream text-brand-ink min-h-screen p-8">
  <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand-ink/45">Digest · week 25</p>
  <h1 className="font-serif font-semibold text-3xl tracking-[-0.01em] mt-1 mb-6">Wat ertoe doet</h1>
  <div className="flex flex-wrap gap-4">
    <ContentCard format="article" title="De stille kracht van langzaam lezen"
      summary="Weg van de tijdlijn neemt een nieuwe generatie de regie over hun aandacht terug."
      sourceName="De Correspondent" meta="8 min" />
  </div>
  <Button variant="primary" className="mt-6">Lees de digest</Button>
</main>
```
