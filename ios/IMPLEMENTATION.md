# Uitvoering van roadmap PR #84

De vier fases worden als opeenvolgende branches opgebouwd. Elke volgende fase bouwt voort op de vorige. De bestaande website/API blijft het contract; de app voert geen productiemigraties uit.

## Fase 1 — gerangschikte home

- Onderwerpkeuze onthouden; standaard eerste onderwerp met items. Artikelen, podcasts en video’s komen in servervolgorde uit `/huygens/{slug}`. Status/periode/soortfilters openen de secundaire lijst.
- Dag- en weekoverzicht zichtbaar, met geschiedenis en native generatie via de ingestelde modellen. Een lopende generatie wordt elke acht seconden bijgewerkt.
- Artikelen tonen `transcript` onder Bron, met excerpt als terugval. Geen aparte transcript-tab voor artikelen. Leesgrootte 18–28 pt wordt onthouden.
- Afspeelsnelheid standaard 1,7×, onthouden, instelbaar van 1,0–2,5×. Ook via de externe spelerbediening.
- Schermen opgesplitst en Swift-bronnen geformatteerd met `swift-format`.

Validatie en screenshots worden per fase toegevoegd na de simulatortests.
