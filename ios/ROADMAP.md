# Stroom voor iPhone: review en vervolgopdracht

**Voor:** Astra · **Van:** Claude, op verzoek van Han · **Basis:** `main` @ `2dd4f27` (PR #82 gemerged)

## In het kort

Het fundament is goed. Alleen is de app een nette RSS-lezer geworden, terwijl Stroom een curator is. Juist wat de website goed maakt, ontbreekt of zit half in de app, of achter een webview:

- de rangschikking per onderwerp;
- het dag- en weekoverzicht bovenaan;
- de volledige artikeltekst;
- de AI-companion die je dingen kunt laten doen.

Bijna alles hieronder kan met **bestaande API-endpoints**. Aan de server hoeft vrijwel niets te veranderen.

## Wat goed is (zo laten)

- Sessie in de Keychain, geen Stroom-cookies naar podcast-CDN's, redirects alleen binnen dezelfde origin.
- De speler: lockscreen en Control Center, AirPlay, slaaptimer, downloads en luisterposities.
- De gedeelde leeswachtrij, vegen met Herstel, de offline-cache en lokale meldingen met rusturen.
- Unit- en UI-tests, en de demomodus.

---

## Fase 1: het hart terug (eerst dit)

### 1.1 Een gerangschikte home per onderwerp, geen chronologische stortbak

**Nu:** `FeedScreen` haalt `GET /api/huygens/items?filter=all&window=30d` op: 100 items van alle onderwerpen door elkaar, nieuwste eerst. Daardoor vallen drie dingen weg: de bronweging (`sources.weight`), de kwaliteitsboost en de limiet per bron (`max_per_rail`). Eén bron die veel publiceert, vult zo het hele scherm.

**Web:** `GET /api/huygens/{slug}` → `{slug, name, rails: [{format, items}]}`, al gerangschikt (`api/main.py:3437`).

**Doen:**
- Tab *Stroom* krijgt bovenaan horizontaal scrollende onderwerp-chips. Standaard staat het eerste onderwerp met items geselecteerd, zoals op web (`web/src/App.tsx:3156`). Het laatst gekozen onderwerp wordt onthouden.
- Per onderwerp komen er drie secties: Artikelen, Podcasts en Video's, gevuld uit `rails` in die volgorde.
- De filters (Bewaard, Samengevat, Gepland, Archief, Inbox) en de periode blijven, maar als secundaire weergave. Pas als filter ≠ *Alles* of periode ≠ *Alle tijd* verschijnt de gefilterde lijst (`/huygens/items` met `topic`), net als `FilterView` op web.
- "Alle onderwerpen, chronologisch" mag blijven als laatste chip, maar niet als standaard.

### 1.2 Het grotere plaatje bovenaan

**Nu:** het dag- en weekoverzicht zit achter een icoontje. Dat icoontje verschijnt pas nadat je een onderwerp kiest, en standaard is er geen onderwerp gekozen. In de praktijk zie je de overzichten dus nooit.

**Web:** twee `DigestPanel`s (dag en week) staan direct onder de titel van het onderwerp.

**Doen:**
- Bovenaan elk onderwerp komt een kaart *Vandaag* met de eerste alinea's van `GET /api/huygens/{slug}/digest?window=daily`. Tikken opent de bestaande `DigestView`.
- *Deze week* komt erbij als tweede kaart of als segment.
- Bij `is_generating` staat er "Wordt gemaakt…".
- Opnieuw genereren wordt een native knop: `POST /api/huygens/{slug}/digest?model=…&window=…`, met het model uit de instellingen (zie 2.1).

### 1.3 Artikelen: de volledige tekst tonen

**Nu:** tab *Bron* toont `description`, het RSS-uittreksel. De volledig geëxtraheerde artikeltekst staat bij artikelen in `transcript` en komt daardoor onder een tab *Transcript* terecht.

**Web:** `ArticleBody` (`App.tsx:854`) gebruikt `format == "article" && transcript` als hoofdtekst, en anders `description`.

**Doen:**
- Bij artikelen wordt *Bron* `transcript ?? description`, en de tab *Transcript* verdwijnt.
- De leesweergave krijgt een hero-afbeelding en een openingscitaat (zie `firstParagraph`, `App.tsx:836`).
- Tekst in een serif met ruime regelafstand, en een lettergrootte A−/A+ die onthouden wordt (de E-reader op web gaat van 18 tot 28 pt).
- De begintab wordt *Samenvatting* als er een samenvatting is, en anders *Bron*.

### 1.4 Afspeelsnelheid

**Web:** standaard 1,7× (`DEFAULT_PLAYBACK_RATE` in `GlobalAudioContext.tsx`), in stappen van 0,1 tot 2,5×.
**iOS:** standaard 1×, keuze tussen 0,75 en 2×, en de keuze wordt niet onthouden.

**Doen:**
- Standaard 1,7×, en de gekozen snelheid blijft bewaard in UserDefaults.
- Keuzes van 1,0 tot 2,5× in stappen van 0,1.
- `changePlaybackRateCommand` aansluiten op `MPRemoteCommandCenter`.

**Klaar als:**
- De app opent op het laatst gekozen onderwerp, met het dagoverzicht bovenaan en de rails in dezelfde volgorde als op de website.
- Een artikel toont onder *Bron* de volledige tekst.
- Een podcast start op 1,7×.
- Er is een unit-test op het decoderen van `HuygensTopic`, en een UI-test die de home opent, van onderwerp wisselt en een item opent. De demomodus heeft rails en een digest.

---

## Fase 2: de AI-companion compleet

### 2.1 Lessen

**Nu:** je kunt lessen lezen en duimen, en een bestaande verdieping tonen.

**Ontbreekt:**
- *Destilleer kernlessen* / *Meer* (`POST /api/huygens/items/{id}/lessons/distill?model=`).
- *Verdiep deze les* (`POST /api/lessons/{id}/expand?model=`).
- *Naar Vikunja* (`POST /api/lessons/{id}/send-to-vikunja`), met een vinkje zodra `vikunja_task_id` gezet is.

**Let op de timeout:** distill is synchroon en kan tot 420 s duren, terwijl de time-out van `APIClient` 25 s is (alleen `/ask` en `/summarize` krijgen 240 s). Merge eerst PR #78 (distill als achtergrondjob), of verhoog de time-out voor distill en expand en toon zolang een duidelijke "bezig"-staat.

**Modelkeuze:** lees `GET /api/admin/settings` → `model_defaults` (`expand`, `distill`, `ask`, `digest`, `digest_weekly`) en stuur `?model=` mee, net als `getDefault()` op web. Nu stuurt de app geen model mee, waardoor de serverdefault geldt en Hans instellingen worden genegeerd.

### 2.2 Vraag

- Als er nog geen geschiedenis is: suggesties als chips ("Wat zijn de kernargumenten?", "Welk bewijs draagt de auteur aan?", "Wat is hier de tegenovergestelde positie?").
- `?model=` uit de instellingen meesturen.
- `sources_used` en `created_at` tonen.

### 2.3 Samenvatting en verwerking

- `summary_model` tonen.
- Zolang `processing_status` in de wachtrij of aan het verwerken is: elke ~8 s pollen, zoals web (`App.tsx:1623`). Dat vervangt de huidige tekst "trek omlaag om te verversen".
- `queue_position` tonen ("In de rij · #3"), en een melding bij `failed`.

### 2.4 Transcript met tijdcodes

Decodeer `transcript_segments` (`[{start, end, text, speaker}]`):
- Per segment de tijd en de spreker tonen.
- Tikken springt naar die plek. Speelt de aflevering nog niet, dan start hij eerst.
- Het actieve segment loopt mee en is gemarkeerd.

Nu is het één lap tekst.

### 2.5 Zoeken

`SearchHit` mist `snippet` (met `<mark>`), `published_at` en `match`. Toon de snippet met gemarkeerde treffers (via AttributedString), de datum en een formaatfilter.

---

## Fase 3: cureren met je duim

### 3.1 Snelle acties per item

**Web:** op elke kaart staan wachtrij, archiveren, later, samenvatten en transcriberen.
**iOS:** alleen vegen naar archief of wachtrij.

**Doen:**
- Contextmenu (en waar dat logisch is een veegactie) met: *Later* (status `later` zonder datum: bestaat op web, ontbreekt in iOS), *Samenvatten*, *Transcriberen* (bij podcast en video) en *Bewaren*.
- Kleine statusiconen op de kaart: samenvatting aanwezig, transcript aanwezig, in de rij.

### 3.2 "Archiveer alle en laad nieuwe"

Dit is het inbox-zero-ritueel van de website, per rail en met bevestiging. Archiveer per item, zoals web (`App.tsx:3313`), en laad daarna `/huygens/{slug}` opnieuw.

### 3.3 Score en onderwerpen per item

Nu kan dit alleen via de webview *Meer artikelopties*. Native maken:
- Kwaliteitsscore aanpassen: `POST /api/huygens/items/{id}/quality-score`.
- Uitleg tonen uit `quality_score_detail` (zie `web/src/ScoreDetail.tsx`).
- Onderwerp toevoegen of verwijderen: `POST /api/huygens/items/{id}/topics` en `DELETE …/topics/{slug}`. De lijst komt uit `GET /api/inbox/topics`.

### 3.4 Plannen gelijktrekken

**Web:** een datum (zonder tijd), *Later (geen datum)*, en *Wis*. *Wis* zet ook de status `later` terug.
**iOS:** datum plus tijd, geen *Later*.

---

## Fase 4: wat alleen een iPhone kan

### 4.1 Insturen via het deelmenu

Op een telefoon is dit het grootste gemis: een link uit Safari, YouTube of een podcastapp naar Stroom sturen.

- **a) Share Extension** met `POST /api/inbox/submit` (url plus een optioneel onderwerp). Daarvoor moeten app en extensie de sessie delen via een gedeelde keychain-groep of App Group. **Controleer eerst of dat met een gratis Personal Team kan.**
- **b) Kan dat niet:** branch `feat/ios-inbox-token` (juni, nooit gemerged) voegt precies hiervoor de header `X-Stroom-Inbox-Token` toe, zodat een Opdrachten-shortcut vanuit het deelmenu kan insturen. Die branch naar de huidige `main` brengen, mergen, het token in `.env` zetten en de shortcut documenteren.

Vervang daarnaast de webview *Content insturen* door een klein native formulier.

### 4.2 Verder luisteren

De posities staan al in UserDefaults:
- Bovenaan *Luisteren* een rij "Verder luisteren" met afleveringen die begonnen maar niet af zijn, met de resterende tijd.
- Daaronder de podcast-rail van het gekozen onderwerp, en dan *Door Stroom gemaakt*.
- Na afloop van een aflevering desgewenst automatisch archiveren.

### 4.3 Video

Nu is er alleen *Open origineel*. Beter: een YouTube-embed in de detailweergave, of op z'n minst een thumbnail met een duidelijke afspeelknop.

### 4.4 Tips en het lessenoverzicht native

Deze zijn nu webviews. Lage prioriteit; Tips eerst.

---

## Code en werkwijze

- **Leesbaarheid:** veel regels in `StroomApp.swift`, `DetailViews.swift` en `ReaderCompanion.swift` bevatten drie tot zes statements met `;`, of zelfs een hele view. Splits bij de volgende stap op in één bestand per scherm (Home/Onderwerp, Item, Reader, Speler, Zoeken, Lessen) en draai `swift-format`. De app gaat nog lang mee; dit moet over een halfjaar nog te lezen zijn.
- **Modellen aanvullen:**
  - `FeedItem` mist `author`, `hasTranscript`, `transcriptSegments`, `summaryModel`, `queuePosition` en `qualityScoreDetail`.
  - `Lesson` mist `vikunjaTaskId`, `sourceName`, `itemTitle` en `mediaUrl`.
  - `ItemQuestion` mist `sourcesUsed` en `createdAt`.
- **Server:** voor fase 1 tot en met 3 is niets nodig, behalve eventueel PR #78.
- **Per fase één PR**, met simulatorschermafbeeldingen (licht en donker) in de beschrijving, zodat Han het vanaf zijn telefoon kan beoordelen.
