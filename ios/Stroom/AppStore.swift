import Combine
import Foundation

@MainActor
final class AppStore: ObservableObject {
  static let shared = AppStore()
  @Published var server: String
  @Published var user: StroomUser?
  @Published var topics: [Topic] = []
  @Published var selectedTopic = UserDefaults.standard.string(forKey: "selectedTopic") ?? "" {
    didSet { UserDefaults.standard.set(selectedTopic, forKey: "selectedTopic") }
  }
  @Published var topicFeeds: [String: HuygensTopic] = [:]
  @Published var items: [FeedItem] = []
  @Published var jobs: [PodcastJob] = []
  @Published var queuedIDs: Set<String> = []
  @Published var queueItems: [FeedItem] = []
  @Published var queueError: String?
  @Published var mutations: [String: FeedItem] = [:]
  @Published var actionError: String?
  @Published var actionMessage: String?
  @Published var changing: Set<String> = []
  private(set) var contentVersion = 0
  private var queueVersion = 0
  private var undoItem: FeedItem?
  private var undoWasQueued = false
  private var archivingRail = false
  @Published var aiTasks: Set<String> = []
  @Published var busy = false
  @Published var starting = true
  @Published var error: String?
  @Published var tab = 0
  @Published var openItemID: String?
  @Published var incomingURL: String?
  @Published var lastSync: Date?
  @Published var offline = false
  @Published var jobsError: String?
  let player = AudioPlayer()
  let library = LibraryStore()
  let notifications = Notifications()
  private(set) var api: APIClient?
  private var started = false
  private var refreshing = false
  let demo: Bool
  private let cacheURL = FileManager.default.urls(
    for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("feed.json")

  init(demo: Bool = ProcessInfo.processInfo.arguments.contains("--demo")) {
    self.demo = demo
    server = UserDefaults.standard.string(forKey: "server") ?? "https://stroom.c4w.nl"
    if let base = try? ServerAddress.parse(server) { api = APIClient(baseURL: base) }
    if let api { player.configure(api: api, library: library) }
    player.onFinished = { [weak self] track in
      guard let self, UserDefaults.standard.bool(forKey: "archiveAfterListening"),
        UUID(uuidString: track.id) != nil
      else { return }
      Task { @MainActor in
        let account = self.user?.id
        guard account != nil, let api = self.api else { return }
        do {
          let item = try await api.item(track.id)
          guard self.user?.id == account else { return }
          await self.archive(item)
        } catch {
          self.actionError = "Automatisch archiveren mislukt: \(error.localizedDescription)"
        }
      }
    }
  }
  func start() async {
    guard !started else { return }
    started = true
    defer { starting = false }
    if demo {
      loadDemo()
      return
    }
    await notifications.permissionStatus()
    guard let api else { return }
    do {
      let response: UserResponse = try await api.request("auth/me")
      user = response.user
      await refresh()
      notifications.scheduleRefresh()
    } catch APIError.unauthorized { api.clearSession() } catch {
      // Cached content and downloads remain accessible without pretending a network login succeeded.
      if let data = try? Data(contentsOf: cacheURL),
        let cache = try? JSONDecoder().decode(FeedCache.self, from: data), cache.server == server
      {
        user = cache.user
        items = cache.items
        topics = cache.topics
        lastSync = cache.date
        offline = true
        topicFeeds = cache.topicFeeds ?? [:]
        selectInitialTopic()
        if topicFeeds[selectedTopic] == nil { selectedTopic = "__all__" }
        player.restoreHistory(tracks: allKnownItems.compactMap(\.track) + library.downloads)
      } else {
        self.error = error.localizedDescription
      }
    }
  }
  func login(email: String, password: String) async {
    busy = true
    error = nil
    defer { busy = false }
    do {
      let base = try ServerAddress.parse(server)
      let client = APIClient(baseURL: base)
      let account = try await client.login(email: email, password: password)
      // Old account audio/content must not be exposed to a different login.
      if let old = UserDefaults.standard.string(forKey: "account"),
        old != "\(base.absoluteString)|\(account.id)"
      {
        player.stop()
        player.clearHistory()
        items = []
        jobs = []
        jobsError = nil
        queueItems = []
        queuedIDs = []
        mutations = [:]
        topicFeeds = [:]
        topics = []
        try library.clear()
        notifications.reset()
        try? FileManager.default.removeItem(at: cacheURL)
      }
      server = base.absoluteString
      UserDefaults.standard.set(server, forKey: "server")
      UserDefaults.standard.set("\(server)|\(account.id)", forKey: "account")
      api = client
      user = account
      player.configure(api: client, library: library)
      await refresh()
      notifications.scheduleRefresh()
    } catch { self.error = error.localizedDescription }
  }
  func refresh() async {
    guard !demo, let api, user != nil, !refreshing else { return }
    refreshing = true
    let version = contentVersion
    defer { refreshing = false }
    do {
      async let fetchedTopics: [Topic] = api.request("topics")
      async let fetchedItems = api.items(limit: 100)
      let result = try await (fetchedTopics, fetchedItems)
      topics = result.0
      selectInitialTopic()
      if version == contentVersion {
        items = result.1
        for row in result.1 { mutations.removeValue(forKey: row.id) }
      }
      offline = false
      lastSync = Date()
      error = nil
      if let user {
        let cache = FeedCache(
          server: server, user: user, topics: topics, items: items, date: Date(),
          topicFeeds: topicFeeds)
        try JSONEncoder().encode(cache).write(
          to: cacheURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
      }
      await refreshQueue()
      do {
        jobs = try await api.request("podcast-tests")
        jobsError = nil
      } catch { jobsError = error.localizedDescription }
      player.restoreHistory(
        tracks: allKnownItems.compactMap(\.track) + library.downloads + jobs.compactMap(\.track))
      do { try await notifications.check(api: api) } catch {
        notifications.schedulingMessage =
          "De laatste meldingencontrole is mislukt: \(error.localizedDescription)"
      }
    } catch APIError.unauthorized {
      player.stop()
      user = nil
      api.clearSession()
      self.error = APIError.unauthorized.localizedDescription
    } catch {
      offline = true
      self.error = error.localizedDescription
    }
  }
  func logout() async {
    guard let api else { return }
    busy = true
    defer { busy = false }
    do {
      try await api.logout()
      player.stop()
      player.clearHistory()
      try library.clear()
      notifications.reset()
      try? FileManager.default.removeItem(at: cacheURL)
      user = nil
      items = []
      jobs = []
      topics = []
      topicFeeds = [:]
      error = nil
      queuedIDs = []
      queueItems = []
      mutations = [:]
      actionError = nil
      actionMessage = nil
      undoItem = nil
    } catch { self.error = "Uitloggen is niet afgerond: \(error.localizedDescription)" }
  }
  func apply(_ item: FeedItem) {
    contentVersion += 1
    mutations[item.id] = item
    if let index = items.firstIndex(where: { $0.id == item.id }) { items[index] = item }
    if item.status == "archived" {
      queueVersion += 1
      queuedIDs.remove(item.id)
      queueItems.removeAll { $0.id == item.id }
    }
  }
  func current(_ item: FeedItem) -> FeedItem { mutations[item.id] ?? item }
  func refreshQueue() async {
    guard !demo, let api else { return }
    queueVersion += 1
    let version = queueVersion
    do {
      let ids: [String] = try await api.request("reading-queue/ids")
      let rows: [FeedItem] = try await api.request(
        "reading-queue", query: [.init(name: "limit", value: "100")])
      guard version == queueVersion, changing.isEmpty else { return }
      queuedIDs = Set(ids)
      queueItems = rows
      queueError = nil
    } catch {
      queueError =
        "Wachtrij niet beschikbaar. Controleer je verbinding en of de Stroom-server is bijgewerkt. \(error.localizedDescription)"
    }
  }
  func setQueued(_ item: FeedItem, queued: Bool) async {
    guard !changing.contains(item.id) else { return }
    dismissActionFeedback()
    changing.insert(item.id)
    queueVersion += 1
    contentVersion += 1
    defer {
      changing.remove(item.id)
      queueVersion += 1
      contentVersion += 1
    }
    do {
      if !demo, let api {
        let _: ActionOK = try await api.request(
          "reading-queue/\(item.id)", method: queued ? "PUT" : "DELETE")
      }
      if queued {
        queuedIDs.insert(item.id)
        if !queueItems.contains(where: { $0.id == item.id }) { queueItems.append(item) }
      } else {
        queuedIDs.remove(item.id)
        queueItems.removeAll { $0.id == item.id }
      }
      actionError = nil
      queueError = nil
      actionMessage = queued ? "Toegevoegd aan je wachtrij" : "Uit je wachtrij gehaald"
    } catch { actionError = error.localizedDescription }
  }
  func archive(_ item: FeedItem) async {
    guard !changing.contains(item.id) else { return }
    dismissActionFeedback()
    changing.insert(item.id)
    queueVersion += 1
    contentVersion += 1
    defer {
      changing.remove(item.id)
      queueVersion += 1
      contentVersion += 1
    }
    do {
      var updated = item
      if !demo, let api {
        updated = try await api.update(item.id, status: "archived")
      } else {
        updated.status = "archived"
      }
      undoItem = item
      undoWasQueued = queuedIDs.contains(item.id)
      apply(updated)
      actionError = nil
      actionMessage = "Gearchiveerd"
    } catch { actionError = error.localizedDescription }
  }
  var canUndo: Bool {
    undoItem != nil && !archivingRail && actionError == nil && actionMessage == "Gearchiveerd"
  }
  func dismissActionFeedback() {
    undoItem = nil
    undoWasQueued = false
    actionError = nil
    actionMessage = nil
  }
  func undoArchive() async {
    guard canUndo, let item = undoItem else { return }
    do {
      if !demo, let api {
        apply(try await api.update(item.id, status: item.status ?? "new"))
      } else {
        apply(item)
      }
      if undoWasQueued { await setQueued(item, queued: true) }
      undoItem = nil
      actionMessage = "Teruggezet"
    } catch { actionError = error.localizedDescription }
  }
  func selectInitialTopic() {
    if selectedTopic == "__all__" { return }
    if !topics.contains(where: { $0.slug == selectedTopic }) {
      selectedTopic = topics.first(where: { $0.itemCount > 0 })?.slug ?? topics.first?.slug ?? ""
    }
  }
  func remember(_ topic: HuygensTopic) {
    topicFeeds[topic.slug] = topic
    guard let user else { return }
    let cache = FeedCache(
      server: server, user: user, topics: topics, items: items, date: lastSync ?? Date(),
      topicFeeds: topicFeeds)
    try? JSONEncoder().encode(cache).write(
      to: cacheURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
  }
  var allKnownItems: [FeedItem] {
    items + queueItems + topicFeeds.values.flatMap { $0.rails.flatMap(\.items) }
  }
  func modelQuery(_ purpose: String) async throws -> [URLQueryItem] {
    guard let api else { throw APIError.unauthorized }
    let settings: ModelSettings = try await api.request("admin/settings")
    guard let model = settings.modelDefaults[purpose], !model.isEmpty else {
      throw APIError.message(
        "Geen model ingesteld voor deze actie. Controleer je Stroom-instellingen.")
    }
    return [.init(name: "model", value: model)]
  }
  @discardableResult
  func setStatus(_ item: FeedItem, to status: String) async -> Bool {
    await change(item) { api in
      try await api.update(item.id, status: status)
    } demoChange: {
      $0.status = status
    }
  }
  @discardableResult
  func process(_ item: FeedItem, action: String) async -> Bool {
    guard !item.isProcessing else { return false }
    return await change(item) { api in
      try await api.request("huygens/items/\(item.id)/\(action)", method: "POST")
    } demoChange: {
      $0.processingStatus = action == "transcribe" ? "transcribe_queued" : "summarize_queued"
    }
  }
  @discardableResult
  private func change(
    _ item: FeedItem, operation: (APIClient) async throws -> FeedItem,
    demoChange: (inout FeedItem) -> Void
  ) async -> Bool {
    guard !changing.contains(item.id) else { return false }
    dismissActionFeedback()
    changing.insert(item.id)
    contentVersion += 1
    defer {
      changing.remove(item.id)
      contentVersion += 1
    }
    do {
      var updated = current(item)
      if demo {
        demoChange(&updated)
      } else {
        guard let api else { throw APIError.unauthorized }
        updated = try await operation(api)
      }
      apply(updated)
      actionError = nil
      actionMessage = "Bijgewerkt"
      return true
    } catch {
      actionError = error.localizedDescription
      return false
    }
  }
  @discardableResult
  func plan(_ item: FeedItem, date: Date?, later: Bool = false) async -> Bool {
    await change(item) { api in
      let stamp = date.map { ScheduledDay.apiStamp($0) }
      let updated: FeedItem = try await api.request(
        "huygens/items/\(item.id)/schedule", method: "POST",
        body: ["scheduled_for": stamp as Any? ?? NSNull()])
      self.apply(updated)
      if date == nil && (later || updated.status == "later") {
        return try await api.update(item.id, status: later ? "later" : "new")
      }
      return updated
    } demoChange: { row in
      row.scheduledFor = date.map { ScheduledDay.apiStamp($0) }
      if date != nil || later {
        row.status = "later"
      } else if row.status == "later" {
        row.status = "new"
      }
    }
  }
  func archiveRail(_ rows: [FeedItem]) async -> Bool {
    guard !archivingRail else { return false }
    archivingRail = true
    dismissActionFeedback()
    defer {
      undoItem = nil
      undoWasQueued = false
      archivingRail = false
    }
    for row in rows {
      guard !Task.isCancelled else { return false }
      guard !changing.contains(row.id) else {
        actionError = "Een item wordt nog bijgewerkt. Probeer opnieuw zodra dat klaar is."
        return false
      }
      await archive(current(row))
      if actionError != nil { return false }
    }
    actionMessage = "\(rows.count) items gearchiveerd"
    return true
  }
  func loadDemo() {
    if ProcessInfo.processInfo.arguments.contains("--reset-topic") { selectedTopic = "ai" }
    user = StroomUser(id: "demo", email: "demo@stroom.local")
    topics = [
      Topic(slug: "ai", name: "AI & technologie", itemCount: 24),
      Topic(slug: "science", name: "Wetenschap", itemCount: 18),
    ]
    items = [
      FeedItem(
        id: "demo-1", title: "Wat verandert er als AI echt met je meedenkt?",
        description:
          "Een gesprek over nieuwsgierigheid, creativiteit en de volgende stap in kunstmatige intelligentie.",
        sourceName: "De Technoloog", format: "podcast", qualityScore: 8.7,
        summary:
          "## Een nieuwe manier van samenwerken\n\nTechnologie is het interessantst wanneer ze ruimte maakt voor betere vragen. Deze aflevering verkent de rol van AI als denkpartner."
      ),
      FeedItem(
        id: "demo-2", title: "De stille revolutie in onze oceanen",
        description: "Nieuwe inzichten uit de wereld onder de golven.",
        sourceName: "NRC Wetenschap", format: "article", qualityScore: 8.2,
        transcript:
          "De oceaan is voortdurend in beweging. Onderzoekers ontdekken hoe kleine veranderingen grote ecosystemen beïnvloeden.\n\nDit is de volledige artikeltekst, met meer context dan het korte RSS-uittreksel."
      ),
      FeedItem(
        id: "demo-3", title: "Een goed idee begint met een omweg",
        description: "Over aandacht, wandelen en de kunst van het nietsdoen.",
        sourceName: "Nooit meer slapen", format: "podcast", qualityScore: 9.1),
    ]
    items[0].summaryModel = "Voorbeeldmodel"
    items[0].transcriptSegments = [
      TranscriptSegment(
        start: 0, end: 30, text: "Goede technologie begint met betere vragen.",
        speaker: "Presentator"),
      TranscriptSegment(
        start: 30, end: 65,
        text: "Nieuwsgierigheid helpt ons om verder te kijken dan het eerste antwoord.",
        speaker: "Gast"),
    ]
    for topic in topics {
      let selected = topic.slug == "ai" ? [items[0], items[2]] : [items[1]]
      topicFeeds[topic.slug] = HuygensTopic(
        slug: topic.slug, name: topic.name,
        rails: ["article", "podcast", "video"].map { format in
          HuygensRail(format: format, items: selected.filter { $0.format == format })
        })
    }
    selectInitialTopic()
    lastSync = Date()
  }
}
private struct FeedCache: Codable {
  let server: String
  let user: StroomUser
  let topics: [Topic]
  let items: [FeedItem]
  let date: Date
  var topicFeeds: [String: HuygensTopic]?
}
