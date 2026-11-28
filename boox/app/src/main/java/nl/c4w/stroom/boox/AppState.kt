package nl.c4w.stroom.boox

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import nl.c4w.stroom.boox.data.ActionOK
import nl.c4w.stroom.boox.data.ApiClient
import nl.c4w.stroom.boox.data.ApiException
import nl.c4w.stroom.boox.data.FeedCache
import nl.c4w.stroom.boox.data.FeedItem
import nl.c4w.stroom.boox.data.HuygensTopic
import nl.c4w.stroom.boox.data.ItemQuestion
import nl.c4w.stroom.boox.data.Lesson
import nl.c4w.stroom.boox.data.OfflineCache
import nl.c4w.stroom.boox.data.ReaderSettings
import nl.c4w.stroom.boox.data.ReadingPositions
import nl.c4w.stroom.boox.data.ServerAddress
import nl.c4w.stroom.boox.data.SessionStore
import nl.c4w.stroom.boox.data.Settings
import nl.c4w.stroom.boox.data.StroomUser
import nl.c4w.stroom.boox.data.Topic
import nl.c4w.stroom.boox.data.VikunjaResult
import nl.c4w.stroom.boox.ui.ListPager
import nl.c4w.stroom.boox.ui.PageTurns

sealed interface Screen {
    data object Home : Screen
    data object Queue : Screen
    data object Saved : Screen
    data object More : Screen
    data class Reader(val id: String) : Screen
    data class Digest(val topic: String, val name: String) : Screen
    data class Doc(val title: String, val markdown: String, val meta: String? = null) : Screen
    data object Topics : Screen
    data object Search : Screen
    data object Options : Screen
    data class Submit(val url: String = "") : Screen
}

data class BannerState(val text: String, val action: String? = null, val onAction: (() -> Unit)? = null)

const val ALL_TOPICS = "__all__"

/**
 * Alle gedeelde toestand van de app. Lijsten komen van de server; lokale wijzigingen
 * (bewaren, archiveren) staan in [mutations] tot de volgende verversing ze bevestigt.
 */
class AppState(
    private val settings: Settings,
    private val sessions: SessionStore,
    val cache: OfflineCache,
    val positions: ReadingPositions,
    val scope: CoroutineScope,
) {
    var api by mutableStateOf(runCatching { ApiClient(ServerAddress.parse(settings.server), sessions) }.getOrNull())
        private set
    var server by mutableStateOf(settings.server)
        private set
    var user by mutableStateOf<StroomUser?>(null)
    var starting by mutableStateOf(true)
    var busy by mutableStateOf(false)
        private set
    var loginError by mutableStateOf<String?>(null)
    var offline by mutableStateOf(false)
    var lastSync by mutableStateOf<Long?>(null)
    var syncing by mutableStateOf(false)
        private set
    var offlineSync by mutableStateOf<String?>(null)
        private set

    var topics by mutableStateOf<List<Topic>>(emptyList())
    var selectedTopic by mutableStateOf(settings.selectedTopic)
        private set
    var topicFeeds by mutableStateOf<Map<String, HuygensTopic>>(emptyMap())
    var topicLoading by mutableStateOf(false)
        private set
    var topicError by mutableStateOf<String?>(null)
        private set
    var allItems by mutableStateOf<List<FeedItem>>(emptyList())
    var queue by mutableStateOf<List<FeedItem>>(emptyList())
    var queueIds by mutableStateOf<Set<String>>(emptySet())
    var queueError by mutableStateOf<String?>(null)
    var saved by mutableStateOf<List<FeedItem>>(emptyList())
    var offlineIds by mutableStateOf<Set<String>>(emptySet())
    val mutations = mutableStateMapOf<String, FeedItem>()
    val pending = mutableStateMapOf<String, String>()
    var homeFormat by mutableStateOf("all")
    var queueFormat by mutableStateOf("all")

    var reader by mutableStateOf(settings.reader)
        private set
    var stack by mutableStateOf<List<Screen>>(listOf(Screen.Home))
        private set
    var banner by mutableStateOf<BannerState?>(null)

    /** Item waarvan het actiemenu open staat (lang indrukken of „Acties” in de lezer). */
    var actionItem by mutableStateOf<FeedItem?>(null)
    var flashTick by mutableIntStateOf(0)
        private set
    private var turns = 0
    private var pendingShare: String? = null
    private var bannerJob: Job? = null
    private var offlineJob: Job? = null
    private var topicLoads = 0

    /** Telt geslaagde itemacties; zo merkt een verversing dat haar lijsten al verouderd zijn. */
    private var actionsDone = 0

    /** Zoekopdracht en resultaten blijven staan als je een resultaat opent en terugkomt. */
    var searchQuery by mutableStateOf("")
    var searchResults by mutableStateOf<List<FeedItem>?>(null)
    var searchSnippets by mutableStateOf<Map<String, String>>(emptyMap())

    /** Gekozen tabblad per geopend item; blijft staan als je vanuit de lezer een antwoord of verdieping opent. */
    val readerSections = mutableStateMapOf<String, String>()

    /** Lessen en vragen per item, zodat lange AI-taken doorlopen als je het scherm verlaat. */
    val lessons = mutableStateMapOf<String, List<Lesson>>()
    val questions = mutableStateMapOf<String, List<ItemQuestion>>()

    init {
        PageTurns.onTurn = {
            turns++
            val every = reader.refreshEvery
            if (every > 0 && turns % every == 0) flash()
        }
    }

    // --- Navigatie ---

    private val pagers = mutableMapOf<String, ListPager>()

    /** Lijstpagina's blijven bewaard als je een item opent en terugkomt. */
    fun listPager(key: String): ListPager = pagers.getOrPut(key) { ListPager() }

    val screen get() = stack.last()
    val root get() = stack.first()

    fun open(screen: Screen) {
        stack = stack + screen
    }

    fun back(): Boolean {
        if (stack.size <= 1) return false
        val closed = stack.last()
        stack = stack.dropLast(1)
        if (closed is Screen.Reader) readerSections.remove(closed.id)
        return true
    }

    fun tab(screen: Screen) {
        stack = listOf(screen)
    }

    /** Eén zwart beeld over het hele scherm: wist nabeelden op e-ink. */
    fun flash() {
        flashTick++
    }

    fun updateReader(value: ReaderSettings) {
        reader = value
        settings.reader = value
    }

    fun notify(text: String, action: String? = null, onAction: (() -> Unit)? = null, sticky: Boolean = false) {
        banner = BannerState(text, action, onAction)
        bannerJob?.cancel()
        if (!sticky) {
            val shown = banner
            bannerJob = scope.launch {
                delay(if (action != null) 8000 else 4000)
                if (banner == shown) banner = null
            }
        }
    }

    // --- Inloggen en verversen ---

    fun start() = scope.launch {
        val client = api
        if (client == null || !client.hasSession) {
            starting = false
            return@launch
        }
        try {
            user = client.me()
            starting = false
            takePendingShare()
            refreshNow()
        } catch (e: ApiException) {
            if (e.isUnauthorized) {
                client.clearSession()
            } else if (!loadCache()) {
                loginError = e.message
            }
        } finally {
            starting = false
        }
    }

    fun login(serverText: String, email: String, password: String) = scope.launch {
        busy = true
        loginError = null
        try {
            val base = ServerAddress.parse(serverText)
            val client = ApiClient(base, sessions)
            val account = client.login(email, password)
            val key = "$base|${account.id}"
            // Inhoud van een ander account mag nooit zichtbaar blijven.
            if (settings.account != null && settings.account != key) clearLocal()
            server = base.toString().trimEnd('/')
            settings.server = server
            settings.account = key
            api = client
            user = account
            stack = listOf(Screen.Home)
            takePendingShare()
            refreshNow()
        } catch (e: ApiException) {
            loginError = e.message
        } finally {
            busy = false
        }
    }

    fun logout() = scope.launch {
        val client = api ?: return@launch
        busy = true
        try {
            try {
                client.logout()
            } catch (e: ApiException) {
                // Een verlopen sessie is op de server al weg: dan hier gewoon opruimen. Bij andere
                // fouten (geen wifi) blijf je bewust ingelogd, net als op de iPhone; zie de README.
                if (!e.isUnauthorized) throw e
                client.clearSession()
            }
            clearLocal()
            user = null
            stack = listOf(Screen.Home)
        } catch (e: ApiException) {
            notify("Uitloggen is niet afgerond: ${e.message}")
        } finally {
            busy = false
        }
    }

    private fun clearLocal() {
        offlineJob?.cancel()
        offlineSync = null
        bannerJob?.cancel()
        banner = null
        actionItem = null
        pending.clear()
        lastSync = null
        offline = false
        queueError = null
        topicError = null
        searchQuery = ""
        searchResults = null
        searchSnippets = emptyMap()
        readerSections.clear()
        cache.clear()
        positions.clear()
        topics = emptyList()
        topicFeeds = emptyMap()
        allItems = emptyList()
        queue = emptyList()
        queueIds = emptySet()
        saved = emptyList()
        offlineIds = emptySet()
        mutations.clear()
        lessons.clear()
        questions.clear()
        settings.account = null
    }

    private fun loadCache(): Boolean {
        val account = settings.account ?: return false
        val stored = cache.load(account) ?: return false
        user = stored.user
        topics = stored.topics
        topicFeeds = stored.topicFeeds
        allItems = stored.all
        queue = stored.queue
        queueIds = stored.queue.map { it.id }.toSet()
        saved = stored.saved
        lastSync = stored.savedAt
        offline = true
        offlineIds = cache.cachedIds() intersect queueIds
        selectInitialTopic()
        return true
    }

    private fun persist() {
        val account = settings.account ?: return
        val owner = user ?: return
        // Lokale wijzigingen (archiveren, later) gaan mee de cache in; anders staat een
        // gearchiveerd item na een herstart zonder wifi weer in de lijst.
        val feeds = topicFeeds.mapValues { (_, feed) ->
            feed.copy(rails = feed.rails.map { rail -> rail.copy(items = visible(rail.items)) })
        }
        cache.save(FeedCache(account, owner, topics, feeds, visible(allItems), visible(queue), visible(saved), lastSync ?: 0))
    }

    fun refresh() = scope.launch { refreshNow() }

    suspend fun refreshNow() {
        val client = api ?: return
        if (syncing || user == null) return
        syncing = true
        val actionsAtStart = actionsDone
        var again = false
        try {
            coroutineScope {
                val fetchedTopics = async { client.get<List<Topic>>("topics") }
                val fetchedAll = async { client.items(window = "30d") }
                val fetchedSaved = async { runCatching { client.items(filter = "saved", limit = 300) } }
                val fetchedQueue = async {
                    runCatching {
                        client.get<List<String>>("reading-queue/ids") to
                            client.get<List<FeedItem>>("reading-queue", mapOf("limit" to "200"))
                    }
                }
                topics = fetchedTopics.await()
                allItems = fetchedAll.await()
                fetchedSaved.await().onSuccess { saved = it }
                fetchedQueue.await().onSuccess { (ids, rows) ->
                    queueIds = ids.toSet()
                    queue = rows
                    queueError = null
                }.onFailure {
                    queueError = "Wachtrij niet beschikbaar. Is de Stroom-server bijgewerkt? ${it.message}"
                }
            }
            // Slaagde er tijdens het ophalen een actie (bewaren, archiveren, wachtrij), dan kunnen
            // deze lijsten nog de oude stand bevatten: houd de lokale wijziging aan en haal opnieuw op.
            if (actionsDone == actionsAtStart) mutations.clear() else again = true
            selectInitialTopic()
            if (selectedTopic != ALL_TOPICS && selectedTopic.isNotEmpty()) loadTopicNow(selectedTopic)
            offline = false
            lastSync = System.currentTimeMillis()
            persist()
            offlineJob?.cancel()
            offlineJob = scope.launch { syncOffline() }
        } catch (e: ApiException) {
            if (e.isUnauthorized) {
                expire(client, e.message)
            } else {
                offline = true
                // Nog niets geladen sinds de start: toon de laatst bewaarde lijsten, geen leeg scherm.
                if (lastSync == null) loadCache()
                notify(e.message ?: "Verversen mislukt.")
            }
        } finally {
            syncing = false
        }
        if (again) refreshNow()
    }

    /** De server kent de sessie niet meer: terug naar het inlogscherm, zonder open menu of melding. */
    private fun expire(client: ApiClient, message: String?) {
        client.clearSession()
        user = null
        loginError = message
        actionItem = null
        bannerJob?.cancel()
        banner = null
    }

    /** Haalt de volledige tekst van elk wachtrij-item op, zodat je ook zonder wifi kunt lezen. */
    private suspend fun syncOffline() {
        val client = api ?: return
        val ids = queue.map { it.id }
        val stale = System.currentTimeMillis() - 6 * 3600_000L
        ids.forEachIndexed { index, id ->
            val cached = cache.detail(id)
            if (cached == null || cached.fetchedAt < stale) {
                offlineSync = "Offline kopieën bijwerken: ${index + 1} van ${ids.size}"
                // Bewust geen runCatching: een geannuleerde sync (nieuwe verversing, uitloggen) stopt hier.
                try {
                    cache.saveDetail(client.item(id))
                } catch (e: ApiException) {
                    // Dit item komt bij de volgende verversing opnieuw aan de beurt.
                }
            }
        }
        // De wachtrij kan intussen zijn veranderd: ruim op met de actuele stand, niet met de momentopname.
        val keep = queueIds
        cache.prune(keep)
        offlineIds = cache.cachedIds() intersect keep
        offlineSync = null
    }

    private fun selectInitialTopic() {
        if (selectedTopic == ALL_TOPICS) return
        if (topics.none { it.slug == selectedTopic }) {
            selectTopic(topics.firstOrNull { it.itemCount > 0 }?.slug ?: topics.firstOrNull()?.slug ?: ALL_TOPICS, load = false)
        }
    }

    fun selectTopic(slug: String, load: Boolean = true) {
        selectedTopic = slug
        settings.selectedTopic = slug
        topicError = null
        if (load && slug != ALL_TOPICS && !offline) scope.launch { loadTopicNow(slug) }
    }

    fun reloadTopic() = scope.launch { loadTopicNow(selectedTopic) }

    private suspend fun loadTopicNow(slug: String) {
        val client = api ?: return
        if (slug == ALL_TOPICS || slug.isEmpty()) return
        // Bij snel wisselen lopen er meerdere aanvragen; pas als de laatste klaar is, is het laden voorbij.
        topicLoads++
        topicLoading = true
        try {
            val topic = client.get<HuygensTopic>("huygens/$slug")
            topicFeeds = topicFeeds + (slug to topic)
            if (slug == selectedTopic) topicError = null
            persist()
        } catch (e: ApiException) {
            if (slug == selectedTopic && topicFeeds[slug] == null) topicError = e.message
        } finally {
            topicLoads--
            topicLoading = topicLoads > 0
        }
    }

    val topicName: String
        get() = if (selectedTopic == ALL_TOPICS) "Alles" else topics.firstOrNull { it.slug == selectedTopic }?.name
            ?: topicFeeds[selectedTopic]?.name ?: "Stroom"

    // --- Itemacties ---

    fun current(item: FeedItem): FeedItem = mutations[item.id]?.let { item.merged(it) } ?: item

    fun visible(items: List<FeedItem>): List<FeedItem> = items.map(::current).filterNot { it.isArchived }

    fun isQueued(item: FeedItem) = item.id in queueIds

    private fun apply(updated: FeedItem) {
        val previous = mutations[updated.id]
        mutations[updated.id] = previous?.merged(updated) ?: updated
        if (updated.isSaved && saved.none { it.id == updated.id }) saved = listOf(updated) + saved
        if (!updated.isSaved) saved = saved.filterNot { it.id == updated.id }
        if (updated.isArchived) {
            queueIds = queueIds - updated.id
            queue = queue.filterNot { it.id == updated.id }
        }
    }

    private fun action(item: FeedItem, label: String, block: suspend (ApiClient) -> Unit) {
        val client = api ?: return
        if (pending.containsKey(item.id)) return
        pending[item.id] = label
        scope.launch {
            try {
                block(client)
                actionsDone++
            } catch (e: ApiException) {
                if (e.isUnauthorized) expire(client, e.message) else notify(e.message ?: "Dat lukte niet.")
            } finally {
                pending.remove(item.id)
            }
        }
    }

    fun toggleQueue(item: FeedItem) = action(item, "Wachtrij") { client ->
        val queued = isQueued(item)
        client.send<ActionOK>("reading-queue/${item.id}", method = if (queued) "DELETE" else "PUT")
        if (queued) {
            queueIds = queueIds - item.id
            queue = queue.filterNot { it.id == item.id }
            notify("Uit je wachtrij gehaald")
        } else {
            queueIds = queueIds + item.id
            if (queue.none { it.id == item.id }) queue = queue + current(item)
            notify("In je wachtrij gezet · wordt offline bewaard")
            runCatching { client.item(item.id) }.onSuccess {
                cache.saveDetail(it)
                offlineIds = offlineIds + it.id
            }
        }
        persist()
    }

    fun toggleSaved(item: FeedItem) = action(item, "Bewaren") { client ->
        val now = current(item)
        val updated = client.setStatus(item.id, if (now.isSaved) "new" else "pinned")
        apply(updated)
        notify(if (updated.isSaved) "Bewaard" else "Niet meer bewaard")
        persist()
    }

    fun later(item: FeedItem) = action(item, "Later") { client ->
        apply(client.setStatus(item.id, "later"))
        notify("Op later gezet")
        persist()
    }

    fun archive(item: FeedItem, leaveReader: Boolean = false) = action(item, "Archiveren") { client ->
        val before = current(item)
        val wasQueued = isQueued(item)
        val updated = client.setStatus(item.id, "archived")
        apply(updated)
        // Alleen de lezer van dít item sluiten; intussen kan er een ander scherm bovenop staan.
        if (leaveReader && (screen as? Screen.Reader)?.id == item.id) back()
        persist()
        notify("Gearchiveerd: ${before.title.take(60)}", action = "Herstel", onAction = { restore(before, wasQueued) })
    }

    private fun restore(item: FeedItem, wasQueued: Boolean) = action(item, "Herstellen") { client ->
        val status = item.status?.takeIf { it != "archived" } ?: "new"
        apply(client.setStatus(item.id, status))
        if (wasQueued) {
            client.send<ActionOK>("reading-queue/${item.id}", method = "PUT")
            queueIds = queueIds + item.id
            if (queue.none { it.id == item.id }) queue = queue + item
        }
        notify("Teruggezet")
        persist()
    }

    /** Samenvatten of transcriberen: de server zet het in de rij; de lezer ververst zelf. */
    fun process(item: FeedItem, what: String, onDone: (FeedItem) -> Unit) = action(item, "Bezig") { client ->
        val updated: FeedItem = client.send("huygens/items/${item.id}/$what")
        apply(updated)
        onDone(updated)
        notify(if (what == "transcribe") "Transcriptie aangevraagd" else "Samenvatting aangevraagd")
    }

    /** Haalt een item op; zonder verbinding valt de lezer terug op de offline kopie. */
    suspend fun loadItem(id: String): Pair<FeedItem, Long?> {
        val client = api ?: throw ApiException.unauthorized()
        return try {
            val item = client.item(id)
            if (id in queueIds) {
                cache.saveDetail(item)
                offlineIds = offlineIds + id
            }
            item to null
        } catch (e: ApiException) {
            if (e.isUnauthorized) throw e
            val cached = cache.detail(id) ?: throw e
            cached.item to cached.fetchedAt
        }
    }

    // --- Lessen en vragen ---

    suspend fun loadLessons(id: String) {
        val client = api ?: return
        lessons[id] = client.get("huygens/items/$id/lessons")
    }

    suspend fun distill(id: String) {
        val client = api ?: return
        lessons[id] = client.send("huygens/items/$id/lessons/distill", query = client.model("distill"))
    }

    private fun replaceLesson(itemId: String, lesson: Lesson) {
        lessons[itemId] = lessons[itemId].orEmpty().map { if (it.id == lesson.id) lesson else it }
    }

    suspend fun rate(itemId: String, lesson: Lesson, value: Int) {
        val client = api ?: return
        val updated: Lesson = client.send(
            "lessons/${lesson.id}/rate",
            body = buildJsonObject {
                if (lesson.rating == value) put("rating", JsonNull) else put("rating", value)
            },
        )
        replaceLesson(itemId, updated)
    }

    suspend fun expand(itemId: String, lesson: Lesson): Lesson {
        val client = api ?: throw ApiException.unauthorized()
        val updated: Lesson = client.send("lessons/${lesson.id}/expand", query = client.model("expand"))
        replaceLesson(itemId, updated)
        return updated
    }

    suspend fun sendToVikunja(itemId: String, lesson: Lesson) {
        val client = api ?: return
        val result: VikunjaResult = client.send("lessons/${lesson.id}/send-to-vikunja")
        if (!result.success) throw ApiException("Vikunja heeft de taak niet bevestigd.")
        replaceLesson(itemId, lesson.copy(vikunjaTaskId = result.taskId))
    }

    suspend fun loadQuestions(id: String) {
        val client = api ?: return
        questions[id] = client.get("huygens/items/$id/questions")
    }

    suspend fun ask(id: String, question: String): ItemQuestion {
        val client = api ?: throw ApiException.unauthorized()
        val answer: ItemQuestion = client.send(
            "huygens/items/$id/ask",
            query = client.model("ask"),
            body = buildJsonObject { put("question", question.trim()) },
        )
        questions[id] = listOf(answer) + questions[id].orEmpty()
        return answer
    }

    // --- Delen vanuit andere apps ---

    fun share(text: String?) {
        val url = text?.let { URL_REGEX.find(it)?.value } ?: return
        if (user != null && !starting) {
            open(Screen.Submit(url))
        } else {
            // Bij een koude start is de sessie nog niet gecontroleerd; open het formulier daarna.
            pendingShare = url
            if (!starting) loginError = "Log in om de gedeelde link naar Stroom te sturen."
        }
    }

    private fun takePendingShare() {
        val url = pendingShare ?: return
        pendingShare = null
        open(Screen.Submit(url))
    }

    fun webUrl(query: String): String = "$server/?$query"

    private companion object {
        val URL_REGEX = Regex("https?://[^\\s<>\"]+")
    }
}
