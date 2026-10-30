# Ontwerpreview — 30 oktober 2026

Onbewerkte screenshots van iPhone 17 Pro (iOS 26.3), met expliciete demodata.

- `home-*`: selectie, compacte overzichten en contentkaarten.
- `reader-*`: Newsreader, vaste sectiekeuze en onderste actiebalk.
- `luisteren-*` en `speler-*`: visuele spelerfixture, zonder audiostream.
- `bibliotheek-*`: bewaarde inhoud en downloads, inclusief lege toestand.
- `filters-*`: status, periode en formaat.
- `wachtrij-licht`: toevoegen aan de gedeelde wachtrij.
- `*-grote-tekst`: Dynamic Type op toegankelijkheidsniveau 2.

Validatie: 33 unittests en 9 UI-tests geslaagd; de definitieve speler en de doorgifte van tekstgrootte naar sheets daarna afzonderlijk opnieuw gecontroleerd. De leverbare projectkopie compileert voor een generiek iOS-apparaat met signing uitgeschakeld. Dit bevestigt geen installatie of audio-/notificatiegedrag op een fysieke iPhone.

Zie [DESIGN.md](../../DESIGN.md) voor onderzoek en ontwerpkeuzes.
