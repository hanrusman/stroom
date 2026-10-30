# Stroom op iPhone — ontwerp, 30 oktober 2026

Deze ontwerpversie bouwt voort op de vier iOS-fases en hun reviewcorrecties. De vijf vaste tabs, API-contracten, swipe-richtingen en alle bestaande curatie- en AI-functies blijven beschikbaar.

## Onderzoek

De ingelogde Stroom-website en de bronreader zijn visueel bekeken. De lokale referentie is `web/src/ds/ds.css` en `ContentCard.tsx`: warm papier, marineblauw, Playfair Display voor koppen, Newsreader voor inhoud, kleine bronlabels en een eigen vorm voor elk mediatype.

De native vertaling volgt Apple's richtlijnen voor [iOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-ios), [typografie](https://developer.apple.com/design/human-interface-guidelines/typography), [tabnavigatie](https://developer.apple.com/design/human-interface-guidelines/tab-bars) en [toegankelijkheid](https://developer.apple.com/design/human-interface-guidelines/accessibility).

## Ontwerpkeuzes

1. **De bron komt eerder in beeld.** Onderwerpkeuze blijft direct bereikbaar. Status, periode en mediatype staan in een filterpaneel met een zichtbare actieve-filterstatus en herstelknop. Dag- en weekoverzicht tonen drie regels opgeschoonde inhoud. Ze staan naast elkaar; bij grote toegankelijkheidstekst onder elkaar. Lege mediarubrieken nemen geen ruimte in.
2. **Elk medium krijgt zijn eigen vorm.** Artikelen hebben een ruime Newsreader-kop en eventueel een bronfoto. Podcasts hebben vierkante illustraties en afspeelbediening. Video’s hebben een brede thumbnail. De hele inhoud van de kaart opent de reader; losse knoppen blijven afzonderlijk bedienbaar. Score, bron en wachtrijstatus zijn ondergeschikt maar leesbaar.
3. **Lezen en handelen krijgen elk een vaste plek.** Bron, samenvatting, lessen, transcript en vraag blijven tijdens scrollen bereikbaar. Bewaren, wachtrij en het actiemenu staan onderaan. Planning, curatie, delen en archiveren zitten in dat menu. De dubbele openingsquote is verwijderd. Leesgrootte blijft instelbaar; de tekst volgt daarnaast Dynamic Type.
4. **Luisteren blijft bij de hand.** De minispeler toont voortgang en heeft play/pauze en dertig seconden vooruit. Verder luisteren is prominent op het luisterscherm. Opnieuw op Luister tikken pauzeert een actieve aflevering in plaats van haar opnieuw te openen. De volledige speler behoudt seek, tempo, timer, AirPlay en afspeelwachtrij.
5. **Terugvinden heeft duidelijke ingangen.** De leeswachtrij kan op lezen, luisteren en kijken worden gefilterd, met behoud van de volgorde. In de bibliotheek staan bewaarde items en downloads afzonderlijk, met directe ingangen naar lessen en Tips. De lege toestand geeft een bruikbare vervolgstap.

## Uitwerking

- `DesignSystem.swift` bevat kleur-, typografie- en componentkeuzes. Newsreader en Playfair Display worden met hun SIL Open Font License lokaal gebundeld; er is geen fontdownload tijdens gebruik.
- De basiskleuren volgen de website. In donkere modus zijn de tekstaccenten lichter voor contrast. Gemeten combinaties van ink, muted, blue en green op paper/card lopen van 5,29:1 tot 16,05:1 en voldoen daarmee aan 4,5:1 voor gewone tekst. Dit is een tokencontrole, geen claim dat elke pixel automatisch is geaudit.
- De belangrijke bediening heeft minimaal 44 punten raakvlak. Bij grote tekst worden de bibliotheeksnelkoppelingen gestapeld en de readeracties compact weergegeven met volledige toegankelijkheidslabels.
- Kleurmodus: Volg iPhone, Licht of Donker. Motion gebruikt de bestaande native overgangen; er zijn geen doorlopende decoratieve animaties toegevoegd.
- De oorspronkelijke links/rechts-swipes blijven archiveren en toevoegen aan de gedeelde leeswachtrij. Elke contentkaart heeft ook een gelabelde leeswachtrijknop. De afspeelwachtrij heet in de speler **Hierna**, met een eigen afspeelvolgorde-icoon en expliciete verwijderlabels.
- Bibliotheekknoppen zetten een bestemming op schermniveau; ook dag- en weekoverzicht navigeren vanuit de volledige lijst. Navigatiebestemmingen hangen niet aan hergebruikte lijstrijen. Wis filters en Opnieuw proberen gebruiken afzonderlijke tikvlakken.

## Controle

De UI-tests doorlopen home, onderwerpwissel, reader, lessen, vragen, bewaren/archiveren, planning, curatie, insturen, Tips, bibliotheek, filters en grote tekst. Er zijn aanvullende controles voor de gebundelde lettertypen en de spelerpresentatie. Screenshots gebruiken expliciete demodata. `--design-preview` initialiseert uitsluitend een visuele spelerfixture; er wordt daarmee geen audiostream geopend.

Op de iPhone 17 Pro-simulator zijn 33 unittests en alle 11 UI-tests geslaagd. Deze volledige run omvat beide bibliotheekknoppen, dag- en weeknavigatie, het behouden van filters bij tikken op de kop en de onafhankelijkheid van leeswachtrij en Hierna. De screenshots in `review/design/` zijn echte simulatorbeelden uit deze tests, in lichte en donkere modus en met grote tekst. De projectkopie compileert ook voor een generiek iOS-apparaat met signing uitgeschakeld.

Audio, AirPlay, het deelmenu en notificatiegedrag moeten ook op een fysieke iPhone worden beoordeeld. De visuele spelerfixture test geen audiostream of achtergrondweergave.
