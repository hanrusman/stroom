# Stroom — browser-extensie "Stuur naar inbox"

Eén klik in je browser-toolbar stuurt de pagina waar je op zit naar je
Stroom-inbox. Doet exact hetzelfde als de "Content insturen"-modal in de web-UI:
URL → `/api/inbox/fetch` (titel/type/auteur/beschrijving prefill) → je kiest een
topic → `/api/inbox/submit`.

Werkt op Chrome, Edge, Brave en alle andere Chromium-browsers (Manifest V3).

## Bestanden

| Bestand | Rol |
|---|---|
| `manifest.json` | MV3-manifest (permissions, popup, iconen) |
| `popup.html` / `popup.js` | De popup-UI en logica |
| `icons/` | Toolbar-iconen (16/48/128) |
| `test.html` / `popup-test.css` | Headless testharnas (mockt `chrome.tabs` + `fetch`) — niet nodig voor gebruik |

## Installeren (unpacked)

1. Open `chrome://extensions` (of `edge://extensions` / `brave://extensions`).
2. Zet rechtsboven **Developer mode** aan.
3. Klik **Load unpacked** en kies deze map (`browser-extension`).
4. De extensie verschijnt met een navy "S"-icoon. Pin 'm desgewenst vast.

## ⚠️ Eénmalige server-stap (anders krijg je 403)

De Stroom-API heeft een CSRF-guard die alleen bekende origins toelaat. Na het
laden krijgt de extensie een vast ID, bijvoorbeeld `abcdefghijklmnop...`.

1. Lees het ID af op `chrome://extensions` (staat onder de extensie-naam).
2. Voeg `chrome-extension://<dat-id>` toe aan `STROOM_ALLOWED_ORIGINS` in
   `/opt/stacks/vps-stacks/.env` op Strongbad (komma-gescheiden).
3. `docker compose up -d stroom-api` op de stroom-stack.

Tot die stap geeft de extensie een nette melding ("Geweigerd door Stroom
(origin)…"). Inloggen gebeurt via de bestaande sessie: zorg dat je in dezelfde
browser bent ingelogd op https://stroom.c4w.nl.

## Gebruik

Klik op het icoon → titel/type/auteur/beschrijving zijn voorgevuld → kies een
topic → **Toevoegen aan inbox**. Het item komt in de queue net als via de web-UI.

## Testen

De logica is headless getest via `test.html`, dat `chrome.tabs` en `fetch`
mockt. Serveer de map statisch en open `test.html`:

```sh
python3 -m http.server 8777 --directory .
# open http://localhost:8777/test.html
```

Getest: prefill uit `/inbox/fetch`, topic-dropdown uit `/inbox/topics`,
submit-payload naar `/inbox/submit`, titel-validatie (<3 tekens) en de
401/403-foutmeldingen.
