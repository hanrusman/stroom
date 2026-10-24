# Stroom: tekst naar podcast

Geïnstalleerd op Strongbad op 22 oktober 2026. Open
`https://stroom.c4w.nl/?podcast=1` of de microfoon in de navigatie.
Plak Engelse tekst (maximaal 4.000 tekens), kies een beschikbaar model en genereer.
De tekst wordt uitgesproken zonder LLM-bewerking of digestkoppeling. De historie
bewaart tekst, model, generatietijd en MP3. Audio blijft achter Stroom-login.

## Capaciteit en modelkeuze

De Incus-guest waarin Stroom draait heeft ongeveer 6 GB RAM. De veel grotere
RAM-teller op strongbad.nl geldt voor de fysieke host. De A2 wordt gedeeld.

| Model-ID | Standaard vrijgegeven | Kiesbaar zodra |
|---|---|---|
| `kittentts` | Ja | VoiceStudio het model meldt (CPU, KittenML/kitten-tts-mini-0.8) |
| `omnivoice` | Ja | VoiceStudio het model geïnstalleerd en `accelerated` meldt |
| `cosyvoice` | Ja | VoiceStudio het model geïnstalleerd en `accelerated` meldt |

Sinds de GPU-route werkt staan alle drie standaard in `PODCAST_ENABLED_MODELS`.
Een model zonder bevestigde GPU-versnelling blijft in de keuzelijst uitgeschakeld.
Beperk tot `PODCAST_ENABLED_MODELS=kittentts` als een GPU-model het guestbudget
overschrijdt.

VoiceStudio draait apart van de API: 3 GiB hard geheugenmaximum, geen extra swap,
1 CPU en maximaal drie herstartpogingen. Meet ook het totale guestgebruik: andere
containers hebben eigen limieten waarvan de som groter is dan het guestgeheugen.

Stroom verwerkt één conversie tegelijk; maximaal drie aanvragen wachten/verwerken
en maximaal dertig tests blijven bewaard (maximaal 32 MiB audio per test). Een test
wacht maximaal één uur en genereert maximaal vijftien minuten.

Postgres-sloten: een eigen converterslot zorgt voor één conversie tegelijk. Het
GPU-slot nemen de decision-scorer en de transcriptieclaimer *gedeeld* (ze blokkeren
elkaar dus niet), een OmniVoice/CosyVoice-conversie neemt het *exclusief* en wacht
daarnaast op lopende transcriptie. KittenTTS draait op de CPU en raakt het GPU-slot
niet aan, en wacht ook niet op transcriptie of A2-cijfers. Een test verwijderen
kan altijd, behalve de test die op dat moment wordt gemaakt. Andere aanroepers van
de GPU vallen buiten deze sloten.

De hostcontrole wacht bij load1/cores > 0,85, <12 GiB vrij host-RAM, <15 GB vrije
host-rootdisk, ontbrekende cijfers of cijfers ouder dan vijf minuten. Voor de twee
GPU-modellen geldt bovendien A2-gebruik <=20% en respectievelijk >=6/8 GiB vrij
VRAM. Dit zijn toelatingsgrenzen, geen gemeten modelvereisten of reservering van
Immich-capaciteit. Een HTTP-timeout kan een upstream generatie nog laten doorlopen.

## Reproduceerbare installatie

`vps-stacks/docker-compose.yml` neemt deze overlay op in dezelfde `include.path`
als `stroom/docker-compose.yml`. Gebruik de normale root-Compose; voeg deze overlay
niet nogmaals toe met `-f` (dat verdubbelt onder andere security_opt).

1. Werk `stroom-src` en `vps-stacks` via Git bij; behoud lokale bestanden.
2. Bij een nieuwe installatie: voer vanuit `stroom-src` migratie 026 uit vóór
   inschakeling van de worker:
   `docker exec -i stroom-db psql -U stroom -d stroom -v ON_ERROR_STOP=1 < schema/migrations/026-podcast-tests.sql`.
3. Bewaar een willekeurige `STROOM_VOICESTUDIO_KEY` uitsluitend in de private
   root-`.env`. Stroom en VoiceStudio gebruiken dezelfde sleutel; niet loggen.
4. Vanuit `/opt/stacks/vps-stacks`: `docker compose config --quiet`,
   `docker compose build stroom-voice`, vervolgens
   `docker compose up -d --no-deps stroom-voice`.
5. Controleer `/health` en de ingelogde `/engines/tts`. De koppeling verwacht
   `backends` met `id`, `available` en `routing_status`. De runtimecatalogus
   bewijst niet dat gewichten al gedownload zijn. Test een korte generatie.
6. Activeer alleen de API: `docker compose up -d --no-deps stroom-api`.
   Maak de audiomap aan met eigenaar UID/GID 1000: `docker exec --user 0 stroom-api
   sh -c 'mkdir -p /data/podcast-tests && chown 1000:1000 /data/podcast-tests && chmod 750 /data/podcast-tests'`.
   De bestaande /data-parent is van UID 1001; wijzig alleen deze nieuwe submap.
   Bouw `web` naar een stagingmap. Kopieer eerst nieuwe assets naar `web/dist/assets`
   en vervang daarna `web/dist/index.html`. De bestaande stroom-web bindmount
   leest die map. Deze container is een compose-orphan: geen `down` of
   `--remove-orphans` gebruiken.
7. Test ingelogd generatie, historie, afspelen en downloaden. Zonder login moeten
   de historie, catalogus en MP3 401 teruggeven.

De lokale image `stroom-voice:0.5.6-cpu1` bouwt op de gepinde upstream image:
`ghcr.io/debpalash/voicestudio:0.5.6@sha256:588fe119082bb97e722f5e53fe7b0fe1a406885bf72a4c60889d3d03376d7768`.
`voicestudio/Dockerfile` beperkt uitsluitend Kittens ONNX-session tot één intra- en
inter-op thread en schakelt thread-spinning uit. De standaardruntime maakte pools
voor de fysieke host, waardoor de één-CPU-container ernstig werd vertraagd en
Incus-affiniteitsfouten logde. De build faalt als de verwachte upstream regel verandert.

`OMNIVOICE_DATA_DIR` staat expliciet op het permanente volume. De beheerspagina
is uitsluitend via 127.0.0.1:3900/SSH-tunnel bereikbaar. ASR- en watermark-preload
staan uit; het normale audiowatermerk tijdens generatie blijft behouden.

## Zwaardere modellen

Het optionele `podcast.gpu.compose.yml` geeft alleen CDI-device 0 door. Controleer
vooraf dat dit de A2 is: de hostcontrole meet de A2, dus een ander device maakt die
controle zinloos. Test nieuwe modellen afzonderlijk, inclusief koude laadpiek en
lange tekst; verhoog niet automatisch het geheugenmaximum. `PODCAST_VOICE_<MODELID>` kan een bestaand stemprofiel kiezen.

VoiceStudio kan geïnstalleerde OmniVoice-gewichten bij opstarten voorladen. Kitten
als actieve backend kiezen schakelt dit niet aantoonbaar uit. Meet herstarts opnieuw
nadat andere modellen zijn geïnstalleerd. De koppeling accepteert modellicenties
niet automatisch.

## Terugdraaien

Verwijder de podcast-overlay uit de root-include en hermaak alleen stroom-api.
Zonder PODCAST_VOICESTUDIO_URL start geen converterworker. Stop alleen stroom-voice
als dat nodig is; database en audio kunnen behouden blijven. De eerdere podcast-
en digestfunctionaliteit is ongewijzigd.

## Verificatie

175 unit-/databasetests geslaagd met tijdelijke Postgres; Python-lint, TypeScript en
productiebuild geslaagd. Desktop en 390 px browsercontrole: generatieverzoek,
wachtrij, gereedstatus, historie, concepttekst, verwijderen, navigatie en overflow.
Compose is tegen de bestaande serverconfiguratie gevalideerd.

Eerste echte proef na de ONNX-correctie: 8,376 seconden MP3 (134.060 bytes),
40,6 seconden inclusief eerste model-/watermark-load; circa 1,1 GiB container-RAM
na afloop. Geen nieuwe OOM-events in de guest. Dit is één korte proef, geen
benchmark of garantie voor lange teksten of de twee GPU-modellen.

De volledige Stroom-proef leverde een MP3 van 531.884 bytes op in 137,4 seconden
met circa 1,3 GiB container-RAM tijdens verwerking. De historie bleef bewaard;
ingelogd downloaden gaf 200, historie/catalogus/audio zonder login gaven 401.
Proef-ID: `649640da-6f76-4f62-a534-102b4d527b3d`. Begin met korte teksten;
langere teksten kunnen op één CPU de limiet van vijftien minuten bereiken.

Bronnen: [VoiceStudio Docker-installatie](https://github.com/debpalash/VoiceStudio/blob/main/docs/install/docker.md),
[VoiceStudio broncode](https://github.com/debpalash/VoiceStudio),
[Strongbad dashboard](https://strongbad.nl/dashboard.html).
