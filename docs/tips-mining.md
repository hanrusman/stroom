# Tips-mining: aanbevelingen uit transcripten

Stroom doorzoekt podcast- en YouTube-transcripten op werken die iemand aanraadt
(boeken, software, films, series, games, podcasts, muziek, …) en toont ze als
één overzicht: wat wordt aangeraden, waarom, door wie, hoe vaak en wanneer.

Ontstaan uit een eenmalige batch-run in oktober 2026 over alle 6.246
transcripten (31.514 vensters → 6.059 werken). Die run leverde de prompts
(`services/tips_prompts.py`) en de ruisfilters hieronder; deze feature maakt er
een doorlopend proces van voor nieuwe items, plus een import van die run.

## Pijplijn

1. **Scan per item** (`tips_service.scan_item`): transcript → vensters van
   6000 tekens met stap 5200 (800 overlap). Per venster één LLM-call met
   `EXTRACT_SYSTEM`, JSON-modus. Gevonden tips → `tip_mentions`; het item →
   `tip_scans` (`done` of `failed`). Tips met categorie of sterkte
   `self_promo` worden niet opgeslagen.
2. **Verificatie per werk** (`tips_service.verify_new_works`): werken
   (`category`, `title_key`) zonder rij in `tip_works` en met score ≥ 2 gaan in batches van
   40 naar een tweede model met `VERIFY_SYSTEM` (compact `drop`/`fix`-formaat).
   Uitkomst → `tip_works` (`keep`, canonieke titel/maker/categorie, `confidence`).
   Een titelcorrectie telt alleen als hij sterk lijkt op het origineel
   (`same_work`), en bij `confidence = low` blijven titel en categorie
   ongewijzigd: het model "corrigeerde" in tests naar andere werken.
3. **Weergave** (`GET /tips`): vermeldingen van werken met `keep = true`,
   na ruisfilters, gegroepeerd per (categorie, `title_key`).

**Werkidentiteit** is overal (categorie, `title_key`): het boek *Dune* en de
film *Dune* zijn twee werken, met elk een eigen verificatie, ook als ze in
dezelfde aflevering vallen. Pas na verificatie kan de canonieke categorie twee
groepen samenvoegen (bv. een serie die ook als documentaire gelabeld werd).

**Antwoordschema's** worden gevalideerd voordat er iets wordt opgeslagen. Een
extractie-antwoord zonder `tips`-lijst is een mislukte call (één nieuwe poging,
daarna `failed` en later opnieuw), geen venster zonder tips. Een
verificatie-antwoord zonder `drop`/`fix`-lijsten (bv. `{"error": …}`) wordt
genegeerd; de volgende run probeert die werken opnieuw.

De job (`run_tips_job`) draait als achtergrondtaak, gestart door de volledige
nightly (niet de light-pas) en handmatig via `POST /admin/cron/tips`. Eén job
tegelijk (module-lock). Per run maximaal `TIPS_MAX_ITEMS` items (default 40),
nieuwste eerst; `failed` items opnieuw na 24 uur, maximaal 3 pogingen.

## Modellen

- `TIPS_MODEL` (default `cloud-gemma`): extractie. In de batch-run even goed
  als mistral, ~4× goedkoper, snel.
- `TIPS_VERIFY_MODEL` (default `cloud-mistral`): verificatie.
- Een lokaal model (`stroom-bulk`) kan via de env-var, maar was in de
  batch-run te traag voor bulkwerk (~34 s per venster).
- Max 2 gelijktijdige LLM-calls (Ollama Cloud geeft 429 "too many concurrent
  requests" boven ~4, en Stroom deelt dat budget). 429/5xx → exponentiële
  backoff, max 6 pogingen; daarna telt het venster als mislukt en het item als
  `failed`.

## Datamodel (migratie 025)

- `tip_mentions`: één rij per gevonden tip per venster: `item_id`,
  `window_offset`, `category`, `title`, `title_key`, `creator`,
  `recommended_by`, `strength` (`strong|medium|weak`), `why`, `quote`, `model`.
- `tip_works`: verificatie per werk (`category`, `title_key`): `keep`, `title`,
  `creator`, `canon_category`, `confidence`, `model`.
- `tip_scans`: welke items gescand zijn: `status` (`done|failed`), `windows`,
  `attempts`, `model`, `error`, `scanned_at`.

`title_key` = genormaliseerde titel: ASCII, lowercase, lidwoord vooraan weg
(the/de/het/een/a/an), ondertitel na `: ( - – —` weg, alleen `[a-z0-9 ]`,
telwoorden naar cijfers (zodat *Seven Powers* = *7 Powers*).

## Ruisfilters (bij weergave, op vermeldingsniveau)

Gemeten in de batch-run; zonder deze filters domineren sponsors de top.
Eerst blijft per (aflevering, werk) alleen de sterkste vermelding over:
overlappende vensters en meerdere modellen leveren hetzelfde citaat anders
2-3× uit één aflevering, en dan gaat de sponsor-read-regel ten onrechte af.

- **Sponsor-tekst**: `AD`-regex op citaat + waarom (sponsor, promo code,
  "slash acquired", "one of our favorite companies", `.com/…`, …).
- **Sponsor-read**: hetzelfde citaat (genormaliseerd, eerste 60 tekens, ≥ 25
  tekens) komt ≥ 3× voor in alle vermeldingen.
- **Sponsor van een show**: heeft een werk in een show ≥ 2 vermeldingen die
  hierboven als advertentie gelden, dan vervallen al zijn vermeldingen uit die show.
- **Netwerkpromo**: maker hoort bij het netwerk van de show (NYT, Vox,
  Goalhanger, NPO, BNR, De Correspondent; mapping in de code).
- **Eigen werk**: titel ≈ shownaam, maker ≈ aanbeveler, of maker staat in de
  shownaam ("Deep Questions with Cal Newport").
- **Terugkerende ad**: podcast/nieuwsbrief/software met ≥ 4 vermeldingen in
  slechts één show valt in z'n geheel weg.

## API

- `GET /tips?category=&since=YYYY-MM-DD&q=&source=&strong_only=&min_episodes=&sort=score|episodes|recent|title&limit=&offset=`
  → `{total, categories: {cat: n}, sources: [{name, n}], works: [...]}`.
  Met `since` tellen alleen vermeldingen uit afleveringen vanaf die
  publicatiedatum mee (aantallen, sterren, wie, blurb, rangorde).
- `GET /tips/mentions?title_key=&category=&since=` → vermeldingen van één werk.
- `POST /admin/cron/tips?max_items=` (intern token/admin) → start de job;
  `GET /admin/cron/tips` → status en resultaat van de laatste run.

Score = som van sterktes (strong 3, medium 2, weak 1), per aflevering de
sterkste vermelding.

## Import van de batch-run

`api/scripts/import_tips.py` leest de ruwe venster-uitvoer (JSONL per model:
`{item_id, offset, model, tips: [...]}`) en de verificaties (JSONL met
`key, v_keep, v_title, v_creator, v_category, v_confidence`), en vult de drie
tabellen. Idempotent: bestaande `tip_scans` worden overgeslagen. Alle items die
in de uitvoer voorkomen worden `done`. De batch-run verifieerde per titel; dat
oordeel geldt bij de import alleen voor de categorie waar het over ging (die van
de verifier als die voorkomt, anders de meest voorkomende). Andere categorieën
met dezelfde titel verifieert de eerste job daarna zelf (~1.400 werken).

## Code

- `api/services/tips_prompts.py` — prompts (uit de batch-run).
- `api/services/tips_helpers.py` — vensters, titelnormalisatie, parsing van
  modelantwoorden, "door wie"-labels.
- `api/services/tips_aggregate.py` — ruisfilters, `aggregate`, `query_works`.
- `api/services/tips_service.py` — DB/LLM: scannen, verifiëren, de job.
- `api/routers/tips.py` — `/tips` en `/tips/mentions` (aggregatie 5 min gecachet,
  geleegd na elke job).
- `web/src/TipsPage.tsx` — de pagina (lamp-icoon in de header, `?tips=1`).
- Tests: `api/tests/test_tips_pure.py` (unit), `api/tests/test_tips_db.py` (db).
