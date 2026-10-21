# Stroom: tekst naar podcast

Status: geïmplementeerd en lokaal getest. Nog niet geïnstalleerd op Strongbad; echte
spraakgeneratie en de compatibiliteit van de container moeten daar worden getest.

Open na installatie `https://stroom.c4w.nl/?podcast=1` of de microfoon in de navigatie.
Plak Engelse tekst (maximaal 4.000 tekens), kies een beschikbaar model en genereer.
De tekst wordt letterlijk uitgesproken, zonder LLM-bewerking of digestkoppeling.
De historie bewaart tekst, model, generatietijd en MP3. Audio blijft achter Stroom-login.

## Capaciteit en modelkeuze

Op 21 oktober 2026 had de Incus-guest waarin Stroom draait een limiet van ongeveer
6 GB RAM; de veel grotere RAM-teller op strongbad.nl geldt voor de fysieke host.
De A2 is gedeeld met andere toepassingen. De drie keuzes zijn:

| Model-ID | Eerste installatie | Voorwaarde |
|---|---|---|
| `kittentts` | Aan | Engelse CPU-TTS, eerst een korte praktijktest |
| `omnivoice` | Uit | Werkende GPU-route en gemeten laadpiek binnen guestbudget |
| `cosyvoice` | Uit | Werkende GPU-route en gemeten laadpiek binnen guestbudget |

VoiceStudio draait apart van de API, met 3 GB hard geheugenmaximum, geen extra swap,
1 CPU en maximaal drie herstartpogingen. Deze limiet bewijst niet dat zware modellen
passen. Meet ook het totale guestgebruik: andere containers hebben eigen limieten
waarvan de som groter is dan het guestgeheugen. Begin tijdens een rustig moment.

Stroom verwerkt één conversie tegelijk; maximaal drie aanvragen wachten/verwerken
en maximaal dertig tests blijven bewaard (maximaal 32 MB audio per test). Een test
wacht maximaal één uur en genereert maximaal vijftien minuten. Er is een gedeeld
Postgres-slot met de decision-scorer en de transcriptieclaimer. Lopende transcriptie
wordt afgewacht. Andere aanroepers van de GPU vallen buiten dit slot.

De hostcontrole wacht bij load1/cores > 0,85, <12 GiB vrij host-RAM, <15 GB vrije
host-rootdisk, ontbrekende cijfers of cijfers ouder dan vijf minuten. Voor de twee
GPU-modellen geldt bovendien A2-gebruik <=20% en respectievelijk >=6/8 GiB vrij
VRAM. Dit zijn voorzichtige toelatingsgrenzen, geen gemeten modelvereisten en geen
reservering van Immich-capaciteit. Een HTTP-timeout kan een upstream generatie nog
laten doorlopen; niet meteen onbeperkt opnieuw proberen.

## Installatievolgorde

1. Publiceer de code na toestemming voor git push. Werk op Strongbad alleen
   `/opt/stacks/vps-stacks/stroom-src` bij; behoud eventuele lokale bestanden.
2. Voer migratie `schema/migrations/026-podcast-tests.sql` uit met `ON_ERROR_STOP=1`
   tegen de Stroom-database, vóór het inschakelen van de worker. Bijvoorbeeld:
   `docker exec -i stroom-db psql -U stroom -d stroom -v ON_ERROR_STOP=1 < schema/migrations/026-podcast-tests.sql`
   vanuit `stroom-src`.
3. Genereer een willekeurige `STROOM_VOICESTUDIO_KEY` en bewaar hem uitsluitend in
   de bestaande private omgeving voor Compose. Niet committen of in logs tonen.
4. Gebruik `deploy/podcast.compose.yml` als overlay op de **root**-compose van
   vps-stacks, met dezelfde projectnaam en bestaande env-file. Controleer eerst
   `docker compose ... config --quiet`. Start vervolgens uitsluitend `stroom-voice`
   met `up -d --no-deps stroom-voice`. Herstart niet de hele stack.
5. Controleer de gepinde image (standaard `0.5.6`) op `/health` en `/engines/tts`.
   De koppeling verwacht `backends` met `id`, `available` en `routing_status`.
   Installeer alleen de KittenTTS-runtime en het model via VoiceStudio als deze
   ontbreken. De beheerspagina is via een SSH-tunnel naar 127.0.0.1:3900 bereikbaar.
   De runtimecatalogus bewijst niet dat modelgewichten al gedownload zijn.
6. Genereer rechtstreeks een korte Kitten-test en controleer MP3, RSS,
   `memory.current`, `memory.peak` en `memory.events` van de guest en container.
   Controleer OOM-tellers vóór en na. Noteer de image-digest. Bij incompatibiliteit
   geen ongepinde `latest` proberen: kies en test bewust een andere exacte versie.
7. Pas na een succesvolle proef de API-overlay toe met `up -d --no-deps stroom-api`.
   Bouw de frontend (`npm ci && npm run build` in `web`); de bestaande stroom-web
   mount leest `web/dist`. Deze webcontainer is een compose-orphan: geen `down`
   of `--remove-orphans` gebruiken.
8. Test ingelogd de microfoon, Engelse voorbeeldtekst, wachten, afspelen, downloaden
   en heropenen. Controleer ook dat ongeauthenticeerde audioaanvragen geweigerd worden.

Het optionele `podcast.gpu.compose.yml` geeft alleen CDI-device 0 door. Controleer
vooraf dat dit de A2 is. Test de zware modellen afzonderlijk, inclusief koude
laadpiek en lange tekst. Geef pas daarna hun exacte IDs vrij met
`PODCAST_ENABLED_MODELS=kittentts,omnivoice,cosyvoice`; verhoog niet automatisch
het geheugenmaximum. Gebruik hetzelfde secret voor Stroom en VoiceStudio.
`PODCAST_VOICE_<MODELID>` kan desgewenst een reeds aangemaakt stemprofiel kiezen.

Let op: VoiceStudio kan al geïnstalleerde OmniVoice-gewichten bij opstarten
voorladen. Het kiezen van Kitten als actieve backend schakelt dit niet aantoonbaar
uit. Houd de eerste modelcache daarom beperkt tot Kitten en meet herstarts opnieuw
nadat andere modellen zijn geïnstalleerd. Modellicenties worden afzonderlijk door
VoiceStudio afgehandeld; de koppeling accepteert deze niet automatisch.

## Terugdraaien

Verwijder de PODCAST_* configuratie uit de API en hermaak alleen stroom-api met de
bestaande basis-compose. Zonder PODCAST_VOICESTUDIO_URL start geen converterworker.
Stop alleen stroom-voice als dat nodig is. Bestaande database en audiobestanden
kunnen behouden blijven. De eerdere podcast- en digestfunctionaliteit is ongewijzigd.

## Verificatie

- `ruff check api`
- `pytest -m 'unit or db'` met een tijdelijke Postgres via `STROOM_TEST_DB_URL`
- `npm run lint` en `npm run build` in `web`
- Browsercontrole op desktop en 390 px: generatieverzoek, wachtrij, gereedstatus,
  historie, concepttekst, verwijderen en navigatie; geen horizontale overflow.

Lokale audio-antwoorden zijn testfixtures. Er is nog geen uitspraak over echte
stemkwaliteit, snelheid of zware-modellencompatibiliteit op Strongbad.

Bronnen: [VoiceStudio Docker-installatie](https://github.com/debpalash/VoiceStudio/blob/main/docs/install/docker.md),
[VoiceStudio broncode](https://github.com/debpalash/VoiceStudio),
[Strongbad dashboard](https://strongbad.nl/dashboard.html).
