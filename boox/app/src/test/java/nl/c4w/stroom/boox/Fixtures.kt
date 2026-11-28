package nl.c4w.stroom.boox

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import nl.c4w.stroom.boox.data.FeedItem
import nl.c4w.stroom.boox.data.HuygensRail
import nl.c4w.stroom.boox.data.HuygensTopic
import nl.c4w.stroom.boox.data.Lesson
import nl.c4w.stroom.boox.data.MemorySessionStore
import nl.c4w.stroom.boox.data.OfflineCache
import nl.c4w.stroom.boox.data.ReadingPositions
import nl.c4w.stroom.boox.data.Settings
import nl.c4w.stroom.boox.data.StroomUser
import nl.c4w.stroom.boox.data.Topic
import java.io.File

/** Expliciete voorbeeldinhoud voor schermafbeeldingen; er wordt geen server aangesproken. */
object Fixtures {
    private const val SUMMARY = """
## Waar het over gaat

De auteur onderzoekt waarom teams die **minder** vergaderen vaak betere beslissingen nemen. Het argument: een besluit wordt beter als de afwegingen eerst *op papier* staan, zodat iedereen ze in eigen tempo kan lezen.

## De belangrijkste punten

- Schrijf het voorstel uit vóór de vergadering; gebruik de bijeenkomst alleen voor de open vragen.
- Een goed memo noemt expliciet wat er níét wordt besloten.
- Lezen is sneller dan luisteren: twintig minuten stil lezen vervangt een uur presenteren.
- Teams die zo werken, rapporteren minder herhaalde discussies en duidelijkere eigenaarschap.

## Kanttekening

Niet alles past in een memo. Bij onzekerheid en emotie helpt een gesprek juist meer dan een document, en een cultuur van alleen schrijven kan nieuwe collega’s buitensluiten.

> „Het document is niet het doel; het denkwerk is het doel. Het document maakt het denkwerk zichtbaar.”

## Wat je ermee kunt

Probeer het één keer met een beslissing die je nu voor je uit schuift. Schrijf op wat je weet, wat je niet weet en wat je voorstelt. Deel het een dag van tevoren en kijk of de vergadering korter wordt.

De auteur sluit af met een pleidooi voor rust: wie leest, denkt na voordat hij reageert. Dat geldt voor teams, maar ook voor je eigen leesgewoonten — minder tijdlijn, meer tekst die je echt afmaakt.
"""

    val article = FeedItem(
        id = "a1",
        title = "Waarom de beste teams minder vergaderen en meer schrijven",
        description = "Een essay over memo’s, stille leesminuten en betere besluiten.",
        sourceName = "Voorbeeldblog",
        sourceId = "s1",
        publishedAt = "2026-11-26T08:15:00Z",
        format = "article",
        status = "new",
        qualityScore = 8.0,
        hasSummary = true,
        summary = SUMMARY.trimIndent(),
        summaryModel = "stroom-long",
        topics = listOf("Werk", "Technologie"),
        sourceUrl = "https://example.org/teams",
        mediaUrl = "https://example.org/teams",
    )

    private fun item(id: String, title: String, source: String, format: String, desc: String, score: Double?, status: String = "new") =
        FeedItem(
            id = id, title = title, description = desc, sourceName = source, publishedAt = "2026-11-2${id.last()}T10:00:00Z",
            format = format, status = status, qualityScore = score, hasSummary = format != "video",
        )

    val articles = listOf(
        article,
        item("a2", "De stille revolutie van lokale taalmodellen op je eigen server", "Techblad", "article",
            "Kleine modellen draaien inmiddels prima op een thuisserver. Wat dat betekent voor privacy en kosten.", 7.0, "pinned"),
        item("a3", "Hoe e-ink schermen werken, en waarom ze zo rustig lezen", "Schermwerk", "article",
            "Elektroforetische inkt reflecteert licht in plaats van het uit te stralen. Een uitleg met de nadelen erbij.", 6.0),
        item("a4", "Een jaar zonder sociale media: wat het opleverde", "Weekblad", "article",
            "Minder ruis, meer boeken. En een paar onverwachte nadelen.", 5.0),
    )
    val podcasts = listOf(
        item("p1", "Aflevering 112: Schrijven als denkgereedschap", "De Denkpodcast", "podcast",
            "Een gesprek over schrijven om te leren denken, en waarom het eerste concept altijd slecht mag zijn.", 8.0),
        item("p2", "Slaap, focus en de middagdip", "Gezond Gesprek", "podcast",
            "Een slaaponderzoeker over wat wel en niet werkt tegen de middagdip.", 6.0),
    )
    val videos = listOf(
        item("v1", "Waarom kleur-e-ink er gedempt uitziet", "Uitlegkanaal", "video",
            "Een close-up van een Kaleido-filter onder de microscoop.", 7.0),
    )

    val lessons = listOf(
        Lesson("l1", "Schrijf vóór je vergadert", "Een uitgeschreven voorstel maakt de vergadering korter en de beslissing beter, omdat iedereen de afwegingen in eigen tempo kan lezen.", rating = 1),
        Lesson("l2", "Benoem wat je níét besluit", "Grenzen aan een besluit voorkomen dat dezelfde discussie later terugkomt.", vikunjaTaskId = 12),
        Lesson("l3", "Lezen is sneller dan luisteren", "Twintig minuten stil lezen vervangt een uur presenteren en laat ruimte voor betere vragen.", expansion = "Uitgebreide toelichting."),
    )

    fun state(context: Context, offline: Boolean = false): AppState {
        context.getSharedPreferences("settings", Context.MODE_PRIVATE).edit().clear().putString("server", "voorbeeld").commit()
        val state = AppState(
            Settings(context),
            MemorySessionStore(),
            OfflineCache(File(context.cacheDir, "test-offline")),
            ReadingPositions(context),
            CoroutineScope(SupervisorJob() + Dispatchers.Main),
        )
        state.user = StroomUser("demo", "lezer@example.org")
        state.starting = false
        state.topics = listOf(
            Topic("tech", "Technologie", 42),
            Topic("werk", "Werk", 18),
            Topic("gezondheid", "Gezondheid", 9),
        )
        state.topicFeeds = mapOf(
            "tech" to HuygensTopic("tech", "Technologie", listOf(HuygensRail("article", articles), HuygensRail("podcast", podcasts), HuygensRail("video", videos))),
        )
        state.selectTopic("tech", load = false)
        state.allItems = articles + podcasts + videos
        state.queue = listOf(article, podcasts[0], articles[2])
        state.queueIds = state.queue.map { it.id }.toSet()
        state.offlineIds = setOf("a1", "p1")
        state.saved = listOf(articles[1])
        state.lessons["a1"] = lessons
        state.offline = offline
        state.lastSync = 1_795_840_000_000
        return state
    }
}
