# Stroom voor iPhone

Een native SwiftUI-app naast de bestaande Stroom-website. De app gebruikt dezelfde HTTPS-API, login en bewaarde items. Er is geen backendmigratie of deployment nodig.

## Op je iPhone zetten

1. Open **Stroom.xcodeproj** in Xcode. Je hoeft geen packages te installeren; het project is al gegenereerd.
2. Voeg in **Xcode → Settings → Accounts** je Apple ID toe.
3. Selecteer links het blauwe **Stroom**-project, daarna target **Stroom** → **Signing & Capabilities**. Kies je **Personal Team** en laat **Automatically manage signing** aan.
4. Als de bundle identifier niet beschikbaar is, verander `nl.c4w.stroom.ios` in iets unieks, bijvoorbeeld `nl.hanrusman.stroom.phone`. Verander bij later herinstalleren niet steeds deze identifier, anders ziet iOS het als een nieuwe app.
5. Sluit je iPhone aan met USB, ontgrendel hem en vertrouw je Mac. Kies de iPhone als run destination bovenin Xcode.
6. Zet zo nodig **Instellingen → Privacy en beveiliging → Ontwikkelaarsmodus** aan op je iPhone, herstart en bevestig. Deze optie verschijnt na koppelen met Xcode. [Apple: Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)
7. Druk **⌘R**. Vertrouw, als iOS dit vraagt, je ontwikkelaarsprofiel bij **Instellingen → Algemeen → VPN- en apparaatbeheer**.
8. Open Stroom en gebruik het HTTPS-adres van je website en je bestaande Stroom-login. Het invulveld stelt `https://stroom.c4w.nl` voor; pas dit aan als je een ander adres gebruikt. Vul geen `/api` achter het adres in.
9. Stel onder **Jouw Stroom** de meldingen in en tik **Bewaar meldingsvoorkeuren**. Sta meldingen toe wanneer iOS daarom vraagt.

Vereist: iOS 17 of nieuwer en Xcode met ondersteuning voor de iOS-versie van je iPhone. Gecontroleerd met Xcode 27.1; de gebruikte app-API's hebben iOS 17 als minimum.

Met een gratis Personal Team verlopen provisioning profiles na **7 dagen**. Bouw en installeer de app dan opnieuw via Xcode met dezelfde bundle identifier. Laat de bestaande app geïnstalleerd om lokale gegevens te behouden. Apple staat maximaal drie van zulke apps per apparaat toe. [Apple: Personal Team](https://developer.apple.com/help/account/basics/about-your-developer-account)

## Wat zit erin?

- Native feed met onderwerpen, zoekfunctie, samenvattingen, transcript en bestaande dagoverzichten.
- Bewaren en archiveren synchroniseren via dezelfde API als de website.
- Podcastspeler met achtergrondgeluid, lockscreen-/Control Center-bediening, AirPlay, 15 seconden terug / 30 seconden vooruit, snelheid, slaaptimer en wachtrij.
- Luisterpositie blijft lokaal bewaard. Open dezelfde aflevering opnieuw om verder te gaan. De wachtrij geldt voor de huidige appsessie.
- Podcastdownloads voor offline luisteren; houd de app tijdens het downloaden open. Downloads worden niet automatisch opgeruimd en kun je verwijderen in Bibliotheek.
- Gegenereerde podcasts uit de bestaande `/podcast-tests`-bibliotheek. Privéaudio wordt eerst geauthenticeerd gedownload en daarna lokaal afgespeeld.
- Lokale meldingen met onderwerpen, contenttypen, minimumscore, eigen podcasts die klaar zijn en rusturen.
- Dagelijkse lees-/luisterherinnering op een zelfgekozen tijdstip.
- Donkere modus, Dynamic Type en Nederlandse bediening.

## Hoe meldingen werken met je gewone Apple ID

Dit project heeft bewust geen `aps-environment`-entitlement of APNs-registratie. Echte serverpush is nog niet aangesloten en vereist een betaald Apple Developer-account plus een APNs-provider op de backend.

**Dagelijkse herinnering:** iOS plant deze lokaal. Ze meldt geen actuele aantallen en werkt zonder verbinding met Stroom. Je vaste herinnering volgt zijn eigen tijdstip, ook als dat binnen de rusturen valt.

**Nieuwe inhoud:** bij openen/verversen en tijdens een door iOS toegestane achtergrondverversing vergelijkt de app de opgehaalde inhoud met de vorige controle. De eerste controle na inschakelen of aanpassen van voorkeuren legt alleen een startpunt vast. Bestaande inhoud veroorzaakt dan geen melding. Eigen podcasts melden bij de overgang naar `ready`.

De app vraagt een achtergrondcontrole vanaf 30 minuten later. iOS bepaalt **of en wanneer** die werkelijk plaatsvindt. Geforceerd afsluiten, energiebesparing, uitgeschakelde achtergrondverversing en verlopen sessies verhinderen controles. Dit is dus geen garantie op directe meldingen bij een gesloten app. [Apple: achtergrondplanning](https://developer.apple.com/documentation/backgroundtasks/bgtaskrequest/earliestbegindate)

Meldingen worden gebundeld. Tijdens rusturen bewaart iOS één melding met de laatste nieuwe updates tot het einde van de rusturen. De controle bekijkt de nieuwste 500 items van de afgelopen 30 dagen, of maximaal 500 per gekozen onderwerp, en de laatste 30 gegenereerde podcasts. Dit is een persoonlijke feedcontrole, geen volledige server-eventlog; bij zeer grote aantallen of lang niet openen kan inhoud buiten het venster vallen. Onderwerpen en minimumscore gelden voor feeditems; eigen gegenereerde podcasts hebben een aparte schakelaar.

## Gegevens en verbinding

- Het wachtwoord wordt alleen gebruikt voor inloggen en niet bewaard.
- De sessiecookie staat in de iOS Keychain, alleen op dit apparaat; geen tokens in broncode of UserDefaults.
- Alleen HTTPS-serveradressen zonder pad worden geaccepteerd. API-redirects naar een andere origin worden geblokkeerd.
- Stroom-cookies worden nooit naar externe podcast-CDN's gestuurd. Beschermde audio loopt via de eigen sessieclient; externe audio gebruikt een aparte sessie.
- Downloads en feedcache blijven op het apparaat. Audio wordt uitgesloten van iCloud-backup.
- Uitloggen trekt de serversessie in en ruimt de lokale feed, downloads en meldingen op. Bij een onbereikbare server blijft uitloggen onafgerond en verschijnt een foutmelding.
- Bibliotheek en laatst geladen feed zijn bij netwerkuitval beschikbaar. Alleen eerder opgehaalde details kunnen offline worden getoond; de volledige samenvatting wordt bij openen uit de API opgehaald.
- De website blijft nodig voor beheer van bronnen/modellen en het aanmaken van de tekst-naar-podcasttaken. De iOS-app speelt die resultaten af.

## Ontwikkeling en controle

De map hoort onder `ios/` in `hanrusman/stroom`. De app gebruikt uitsluitend Apple-frameworks. `project.yml` is de reproduceerbare XcodeGen-bron; `Stroom.xcodeproj` is meegeleverd.

```sh
# Alleen nodig na wijzigingen aan project.yml:
xcodegen generate

# Kies een simulator die op je Mac is geïnstalleerd:
xcodebuild -project Stroom.xcodeproj -scheme Stroom \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  CODE_SIGNING_ALLOWED=NO test

# Alleen een iPhone-build, zonder signing:
xcodebuild -project Stroom.xcodeproj -scheme Stroom \
  -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

De unit tests controleren API-decoding, oorsprong-/URL-validatie, meldingsfilters, de eerste synchronisatie, deduplicatie, rusturen en podcaststatusovergangen. De UI-test opent de feed, reader, luistertab, bibliotheek en instellingen met expliciet gemarkeerde voorbeeldinhoud (`--demo`). Normaal starten gebruikt nooit deze voorbeeldinhoud.

**Nog handmatig op je eigen iPhone testen:** echt inloggen op jouw server; een externe podcast streamen en downloaden; een gegenereerde podcast afspelen; vliegtuigmodus na download; scherm vergrendelen, AirPlay en onderbreken door een telefoongesprek; een dagelijkse herinnering ontvangen en aantikken. Die hardware-/accountchecks zijn niet door simulator-tests gedekt. Automatische achtergrondverversing kan alleen over tijd op een echt apparaat beoordeeld worden.

Als je later voor een betaald account kiest, kan de volgende stap een kleine APNs-service zijn met apparaatregistratie en serverfilters. APNs-sleutels horen uitsluitend op de server.
