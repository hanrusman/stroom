# Uitvoering van roadmap PR #84

De vier fases worden als opeenvolgende branches opgebouwd. Elke volgende fase bouwt voort op de vorige. De bestaande website/API blijft het contract; de app voert geen productiemigraties uit.

## Fase 1 — gerangschikte home

- Onderwerpkeuze onthouden; standaard eerste onderwerp met items. Artikelen, podcasts en video’s komen in servervolgorde uit `/huygens/{slug}`. Status/periode/soortfilters openen de secundaire lijst.
- Dag- en weekoverzicht zichtbaar, met geschiedenis en native generatie via de ingestelde modellen. Een lopende generatie wordt elke acht seconden bijgewerkt.
- Artikelen tonen `transcript` onder Bron, met excerpt als terugval. Geen aparte transcript-tab voor artikelen. Leesgrootte 18–28 pt wordt onthouden.
- Afspeelsnelheid standaard 1,7×, onthouden, instelbaar van 1,0–2,5×. Ook via de externe spelerbediening.
- Schermen opgesplitst en Swift-bronnen geformatteerd met `swift-format`.

De screenshots en validatieresultaten staan onderaan dit document.

## Fase 2 — native AI-companion

- Kernlessen destilleren, verdiepen, beoordelen en naar Vikunja sturen; de serverbevestiging bepaalt het vinkje.
- Modelkeuze voor distill/expand/ask/dag- en weekoverzicht uit `/admin/settings`. Als instellingen ophalen mislukt, wordt geen ander model stilzwijgend gebruikt.
- Distill/expand hebben 480 seconden timeout; de synchrone API blijft ondersteund zonder afhankelijkheid van PR #78. De app toont zolang een bezig-status.
- Vraagvoorstellen, bronvermelding en datum bij antwoorden; modelnaam bij samenvattingen; verwerking wordt elke acht seconden bijgewerkt.
- Transcriptsegmenten met spreker, tijdcode, seek/start en markering van het actuele segment. Volgen kan uit.
- Zoeksnippets met veilige markering, publicatiedatum, matchsoort en formaatfilter.

## Fase 3 — cureren

- Lang indrukken: bewaren, later zonder datum, samenvatten en transcriberen. Kaarten tonen beschikbaarheid van tekst/samenvatting en wachtrij/verwerkingsstatus.
- Per rail: bevestigen, zichtbare items archiveren, nieuwe selectie ophalen. Bij een fout stopt de reeks en blijft de fout zichtbaar. Herstel is alleen beschikbaar na één archivering, niet na een bulkactie. Een volgende actie of het sluiten van de melding wist de oude herstelactie.
- Native kwaliteitsscore (PATCH, volgens de actuele API), reden en toelichting. Uitleg met kalibratie en deelscores. Onderwerpen toevoegen/verwijderen gebruikt de slug uit `/inbox/topics`; de detail-API levert namen terug.
- Planning met alleen een datum, Later zonder datum, en Wis. Wissen zet status `later` terug naar `new`; andere statussen blijven behouden.

## Fase 4 — delen, luisteren en ontdekken

- Native instuurformulier met preview, onderwerpkeuze, foutafhandeling en expliciete bevestiging. De server vereist een onderwerp; het formulier stelt het huidige onderwerp voor.
- App Intents/Opdrachten opent het formulier met een gedeelde URL. Dit wijkt af van de twee voorgestelde technische routes: geen aparte Share Extension en geen tokenkopie, omdat het formulier de bestaande sessie gebruikt. Zo werkt het deelmenu zonder extra capability of serverwijziging. Dit is geen claim dat gedeelde Keychain-toegang onmogelijk is met een Personal Team.
- Verder luisteren met bewaarde afleveringsgegevens en resterende tijd; migratie van bestaande luisterposities. Voltooide afleveringen verdwijnen. Optioneel archiveren na daadwerkelijk afspelen tot het einde, standaard uit. Luisterhistorie wordt opgeruimd bij uitloggen of accountwisseling.
- Video-thumbnail met afspeelknop naar de bron. Tijdcode-seek en actief volgen gelden voor de native podcastspeler; video opent bij de aanbieder.
- Native Tips met categorie, zoekterm, volgorde, sterke aanbevelingen, paginering en bronvermeldingen; native lessenbibliotheek met beoordelingen en bronlinks. Geavanceerde lesoverzichten blijven op de website.
- Eindcontrole: een automatische lesverversing wist een destilleerfout niet; het vraagveld is vergrendeld tijdens beantwoorden; onderwerpfeed ververst na synchronisatie met bescherming tegen achterhaalde antwoorden; oude offline-cache blijft bereikbaar.

## Verwerkte reviewpunten

- Een nog ontbrekend dag- of weekoverzicht toont de Nederlandse lege toestand; andere HTTP-fouten blijven zichtbaar.
- Ongeldige transcriptsegmenten en onvolledige scoredetails verbergen het artikel niet. Geldige onderdelen blijven beschikbaar, ook na opslag in de offline-cache.
- FastAPI-validatiefouten tonen de foutboodschap zonder de meegestuurde invoer uit het foutantwoord.
- Een geplande kalenderdag blijft gelijk in app en website, ook rond zomertijd en in andere tijdzones.
- Tips zonder bronnaam blijven leesbaar met het label ‘Bron onbekend’.
- Serverfix #89 voor vrije modelnamen is in de branchbasis opgenomen. De langere proxywachttijd staat in vps-stacks#54; beide PR's zijn gemerged. Dit bevestigt niet dat de server en Nginx Proxy Manager al zijn bijgewerkt.

## Levering en controle

Vier opeenvolgende branches: `feat/ios-curated-home`, `feat/ios-companion`, `feat/ios-curation`, `feat/ios-phone-workflows`. Iedere volgende PR krijgt de vorige branch als basis totdat die is gemerged. PR #84 blijft de oorspronkelijke roadmap.

De simulator gebruikt uitsluitend duidelijk gemarkeerde voorbeeldinhoud. Er zijn geen productiedata gewijzigd, geen echte AI-generaties gestart en geen Vikunja-taken aangemaakt. Op een fysieke iPhone moeten vooral Opdrachten, achtergrondgeluid, AirPlay en meldingen nog worden gecontroleerd.

Gecontroleerd op 27 oktober 2026 na verwerking van de review: 32 unit-tests en 7 UI-tests geslaagd op iPhone 17 Pro / iOS 26.3. De regressietests dekken ontbrekende overzichten, onvolledige API-data en cache-roundtrips, foutmeldingen, datumoverdracht in drie tijdzones, herstel na individuele en gedeeltelijk mislukte bulkacties, en Tips zonder bronnaam. De UI-test controleert dat bulkarchivering geen Herstel-knop toont. Alle testcases zijn afgerond; Xcode verzamelt nog simulator-diagnostiek voor `Review.xcresult`.

De screenshots gebruiken demodata en tonen de definitieve formulierverbetering. De bijgewerkte projectkopie bouwt succesvol voor `generic/platform=iOS` met signing uit. Dit bevestigt compilatie, niet installatie of werking op echte hardware.

### Screenshots

Alle beelden gebruiken demodata.

| Fase | Licht | Donker |
| --- | --- | --- |
| 1 — Home | [Home](review/fase1-home-licht.png) | [Home](review/fase1-home-donker.png) |
| 2 — Lessen | [Lessen](review/fase2-lessen-licht.png) | [Lessen](review/fase2-lessen-donker.png) |
| 3 — Curatie | [Score en onderwerpen](review/fase3-curatie-licht.png) | [Score en onderwerpen](review/fase3-curatie-donker.png) |
| 4 — Insturen | [Formulier](review/fase4-insturen-licht.png) | [Formulier](review/fase4-insturen-donker.png) |
| 4 — Tips | [Bronvermeldingen](review/fase4-tips-licht.png) | [Bronvermeldingen](review/fase4-tips-donker.png) |

[Volledige artikeltekst](review/fase1-reader-licht.png).
