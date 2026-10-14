# Stroom Design System — sync notes

## What this DS is
This design system was **extracted** during the first sync — it did not exist before. The
components in `src/ds/` are clean, presentational re-implementations of UI patterns that
were previously inline Tailwind in `src/App.tsx`, `src/StickyPlayer.tsx`, and
`src/ModelSelect.tsx`. There is **no upstream component library**; `src/ds/` IS the source
of truth for the DS.

- Primitives: Button, IconButton, Badge, Card, Input, Textarea, Select, Spinner
- Composites: AudioPlayer (from StickyPlayer, decoupled from GlobalAudioContext →
  presentational with callbacks), ContentCard (from ArticleCard/MediaCard, decoupled from
  HuygensItem → plain props), Prose (sanitized markdown/html with `prose-stroom` styling)

## Build
- `npm run build:ds` = `tsc -p tsconfig.ds.json` (emits JS + .d.ts to `dist-ds/`) then
  `@tailwindcss/cli -i src/ds/ds.css -o dist-ds/ds.css --minify`.
- Tailwind **v4** (no JS config; tokens live in `@theme` in `src/ds/ds.css`). Content is
  auto-scanned via `@source "./"` in ds.css — only `src/ds/` utilities are compiled.
- `package.json` carries `"types": "dist-ds/index.d.ts"` **specifically so the converter's
  `findTypesRoot` discovers the entry .d.ts** (it doesn't probe `dist-ds/`). Don't remove it.
- Converter entry: `--entry ./dist-ds/index.js`, `--node-modules ./node_modules`.
- Added devDeps for the build: `@types/react`, `@types/react-dom`, `@tailwindcss/cli`
  (the repo previously had none of these; the app's own `tsc` lint was effectively untyped).

## Grouping
Groups come from `@category Primitives` / `@category Composites` JSDoc tags on each
component's main export. No subfolders.

## Fonts
Brand fonts (Playfair Display, Newsreader, Inter Tight, JetBrains Mono) load via a remote
Google Fonts `@import` at the top of `ds.css` → validate reports `[FONT_REMOTE]` (expected,
non-blocking). Nothing is shipped in `fonts/`. This mirrors how the app itself loads them.

## Known render warns (expected — not new)
- `[FONT_REMOTE]` — remote font host @import, fonts load at runtime.
- `[RENDER_SKIPPED]` — render check was skipped this run (no playwright/chromium installed).
  Verification was **human browser review** of `.review.html`, not machine-graded.

## Re-sync risks
- **Drift from the app.** `src/ds/` is a parallel codebase to the app's inline styles. If
  someone restyles `App.tsx` etc., the DS will NOT auto-track it — re-extract by hand.
- **No machine grading.** Previews were never screenshot-verified. A future sync on a
  machine WITH playwright+chromium should run the real render check (`package-validate.mjs`
  without `--no-render-check`) and `package-capture.mjs` to grade — then drop the
  `[RENDER_SKIPPED]` known-warn above.
- **Remote fonts.** Offline builds / Google Fonts changes affect appearance at runtime.
  If fonts must ship, add `@font-face` files and wire `cfg.extraFonts`.
- **`componentSrcMap` null entries** exclude PascalCase type aliases (ButtonVariant, etc.).
  The .d.ts classifier already filters these, so the nulls are belt-and-suspenders; harmless.
