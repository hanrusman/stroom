# Uitvoering van roadmap PR #84

De vier fases worden als opeenvolgende branches opgebouwd. Elke volgende fase bouwt voort op de vorige. De bestaande website/API blijft het contract; de app voert geen productiemigraties uit.

## Fase 1 — gerangschikte home

- Onderwerpkeuze onthouden; standaard eerste onderwerp met items. Artikelen, podcasts en video’s komen in servervolgorde uit `/huygens/{slug}`. Status/periode/soortfilters openen de secundaire lijst.
- Dag- en weekoverzicht zichtbaar, met geschiedenis en native generatie via de ingestelde modellen. Een lopende generatie wordt elke acht seconden bijgewerkt.
- Artikelen tonen `transcript` onder Bron, met excerpt als terugval. Geen aparte transcript-tab voor artikelen. Leesgrootte 18–28 pt wordt onthouden.
- Afspeelsnelheid standaard 1,7×, onthouden, instelbaar van 1,0–2,5×. Ook via de externe spelerbediening.
- Schermen opgesplitst en Swift-bronnen geformatteerd met `swift-format`.

Validatie en screenshots worden per fase toegevoegd na de simulatortests.

## Fase 2 — native AI-companion

- Kernlessen destilleren, verdiepen, beoordelen en naar Vikunja sturen; de serverbevestiging bepaalt het vinkje.
- Modelkeuze voor distill/expand/ask/dag- en weekoverzicht uit `/admin/settings`. Als instellingen ophalen mislukt, wordt geen ander model stilzwijgend gebruikt.
- Distill/expand hebben 480 seconden timeout; de synchrone API blijft ondersteund zonder afhankelijkheid van PR #78. De app toont zolang een bezig-status.
- Vraagvoorstellen, bronvermelding en datum bij antwoorden; modelnaam bij samenvattingen; verwerking wordt elke acht seconden bijgewerkt.
- Transcriptsegmenten met spreker, tijdcode, seek/start en markering van het actuele segment. Volgen kan uit.
- Zoeksnippets met veilige markering, publicatiedatum, matchsoort en formaatfilter.
