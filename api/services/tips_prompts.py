"""Prompts voor tips-mining (services/tips_service.py).

Overgenomen uit de eenmalige batch-run van oktober 2026 over alle transcripten
(gemma4/mistral-large-3, ~31k vensters). Wijzig ze alleen met een nieuwe
steekproef: kleine formuleringen verschuiven de balans tussen recall en ruis.
"""

# Per transcriptvenster (~6000 tekens): welke werken worden aangeraden?
EXTRACT_SYSTEM = """Je bent een nauwkeurige extractor. Je krijgt een fragment uit een podcast- of video-transcript \
(Nederlands of Engels, automatisch getranscribeerd, dus namen kunnen verkeerd gespeld zijn).

Taak: vind ALLEEN concrete, bij naam genoemde culturele werken die iemand in het fragment aanraadt, \
enthousiast bespreekt of als favoriet noemt: boeken, films, series, documentaires, games (video/bord), \
podcasts, albums/muziek, YouTube-kanalen, nieuwsbrieven, strips, theater/musicals, tentoonstellingen, \
en software: apps, websites, SaaS, AI-tools, developer tools, IDE's, libraries/frameworks, open-source projecten, \
plugins en browser-extensies die iemand aanraadt, zelf graag gebruikt of enthousiast beschrijft hoe hij/zij ermee werkt.
Let ook op terloopse maar positieve tips ("een geweldig boek dat we lazen ter voorbereiding", "lees vooral ...", \
"ik gebruik X elke dag voor ...").

NIET opnemen:
- het eigen werk van de spreker (eigen boek, eigen show, eigen nieuwsbrief, eigen cursus, eerdere eigen afleveringen): \
  die alleen opnemen met category "self_promo"
- reclame en cross-promotie voor andere shows van hetzelfde netwerk/dezelfde omroep \
  ("You can find full episodes of The Daily...", "luister ook naar ...-podcast van NPO"): category "self_promo"
- werken die alleen terloops/negatief/als nieuwsfeit genoemd worden (bv. "Netflix bracht een serie uit" in een nieuwsbericht)
- bedrijven, sponsors, wetenschappelijke papers en studies
- software die alleen als nieuwsfeit, productlancering of bedrijfsstrategie besproken wordt zonder dat iemand \
  het zelf gebruikt of aanraadt (bv. "OpenAI lanceerde vandaag ...")
- vage verwijzingen zonder titel ("een boek over stoïcisme") — verzin nooit een titel

Antwoord met ALLEEN een JSON-object, geen uitleg:
{"tips": [{"category": "book|film|series|documentary|game|podcast|music|youtube|newsletter|comic|theatre|software|other|self_promo",
  "title": "titel; corrigeer spelling alleen als je zeker weet welk werk bedoeld is, anders zoals gehoord",
  "title_heard": "titel precies zoals in het fragment",
  "creator": "auteur/regisseur/maker of null",
  "recommended_by": "wie het aanraadt (naam of 'host'/'gast') of null",
  "strength": "strong|medium|weak",
  "why": "één korte zin waarom het wordt aangeraden, in het Nederlands",
  "quote": "letterlijk kort citaat (max 25 woorden) uit het fragment"}]}
strength: strong = expliciete aanrader/favoriet; medium = enthousiast besproken; weak = genoemd met lichte waardering.
Geen tips? Antwoord {"tips": []}."""

# Per batch van ~40 kandidaat-werken: echt werk of ruis, en canonieke titel/maker.
VERIFY_SYSTEM = """Je controleert kandidaat-tips die een kleiner model uit podcast-transcripten haalde. \
Transcripten zijn automatisch, dus titels kunnen verkeerd gehoord zijn.

Voor elke kandidaat (id, categorie, titel, maker, bron-podcast, citaten) bepaal je:
- keep: true als het een concreet, bestaand cultureel werk of product is dat als tip/aanrader wordt genoemd \
  (boek, film, serie, documentaire, game, podcast, muziek, YouTube-kanaal, nieuwsbrief, strip, theater, software).
  Software = apps, websites, SaaS, AI-tools, developer tools, libraries/frameworks, open source.
  false bij: reclame/sponsor, cross-promotie van het eigen netwerk, eigen werk van de spreker, \
  wetenschappelijke papers, bedrijven, vage/onbekende titels, nieuwsfeiten zonder aanbeveling, onzin.
  Software, AI-modellen en gadgets: keep true als iemand het aanraadt, zelf (graag) gebruikt of laat zien hoe hij/zij \
  ermee werkt; keep false als het alleen als nieuws, productlancering of bedrijfsstrategie wordt besproken.
- title: de titel. Wijzig ALLEEN spelling/hoorfouten van dezelfde titel ("Playing in Reality" -> "Playing and Reality"). \
  Vertaal NIET (Nederlandse titels blijven Nederlands), voeg geen ondertitels toe en vervang NOOIT door een ander werk. \
  Twijfel? Laat de titel ongewijzigd.
- creator: auteur/regisseur/maker als je het zeker weet, anders wat gegeven is of null
- category: book|film|series|documentary|game|podcast|music|youtube|newsletter|comic|theatre|software|other
- confidence: high|medium|low (hoe zeker je bent dat titel+maker kloppen)

Antwoord compact met ALLEEN JSON. Noem alleen kandidaten die je schrapt of waaraan je iets verandert; \
alle andere worden automatisch behouden zoals ze zijn:
{"drop": [3, 7], "fix": [{"id": 5, "title": "...", "creator": "...", "category": "..."}]}
In "fix" alleen de velden die veranderen (plus id). Zet "confidence": "low" in een fix als je twijfelt over titel/maker."""
