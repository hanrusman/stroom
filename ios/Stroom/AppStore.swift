import Foundation
import Combine

@MainActor
final class AppStore: ObservableObject {
    static let shared = AppStore()
    @Published var server: String
    @Published var user: StroomUser?
    @Published var topics: [Topic] = []
    @Published var items: [FeedItem] = []
    @Published var jobs: [PodcastJob] = []
    @Published var busy = false
    @Published var starting = true
    @Published var error: String?
    @Published var tab = 0
    @Published var openItemID: String?
    @Published var lastSync: Date?
    @Published var offline = false
    @Published var jobsError: String?
    let player = AudioPlayer()
    let library = LibraryStore()
    let notifications = Notifications()
    private(set) var api: APIClient?
    private var started = false
    private var refreshing = false
    let demo = ProcessInfo.processInfo.arguments.contains("--demo")
    private let cacheURL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("feed.json")

    init() {
        server = UserDefaults.standard.string(forKey: "server") ?? "https://stroom.c4w.nl"
        if let base = try? ServerAddress.parse(server) { api = APIClient(baseURL: base) }
        if let api { player.configure(api: api, library: library) }
    }
    func start() async {
        guard !started else { return }; started = true
        defer { starting = false }
        if demo { loadDemo(); return }
        await notifications.permissionStatus()
        guard let api else { return }
        do {
            let response: UserResponse = try await api.request("auth/me")
            user = response.user
            await refresh()
            notifications.scheduleRefresh()
        } catch APIError.unauthorized { api.clearSession() }
        catch {
            // Cached content and downloads remain accessible without pretending a network login succeeded.
            if let data = try? Data(contentsOf: cacheURL), let cache = try? JSONDecoder().decode(FeedCache.self, from: data), cache.server == server {
                user = cache.user; items = cache.items; topics = cache.topics; lastSync = cache.date; offline = true
            } else { self.error = error.localizedDescription }
        }
    }
    func login(email: String, password: String) async {
        busy = true; error = nil
        defer { busy = false }
        do {
            let base = try ServerAddress.parse(server)
            let client = APIClient(baseURL: base)
            let account = try await client.login(email: email, password: password)
            // Old account audio/content must not be exposed to a different login.
            if let old = UserDefaults.standard.string(forKey: "account"), old != "\(base.absoluteString)|\(account.id)" {
                player.stop(); try library.clear(); notifications.reset()
                try? FileManager.default.removeItem(at: cacheURL)
            }
            server = base.absoluteString
            UserDefaults.standard.set(server, forKey: "server")
            UserDefaults.standard.set("\(server)|\(account.id)", forKey: "account")
            api = client; user = account; player.configure(api: client, library: library)
            await refresh(); notifications.scheduleRefresh()
        } catch { self.error = error.localizedDescription }
    }
    func refresh() async {
        guard !demo, let api, user != nil, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            async let fetchedTopics: [Topic] = api.request("topics")
            async let fetchedItems = api.items(limit: 100)
            let result = try await (fetchedTopics, fetchedItems)
            topics = result.0; items = result.1; offline = false; lastSync = Date(); error = nil
            if let user {
                let cache = FeedCache(server: server, user: user, topics: topics, items: items, date: Date())
                try JSONEncoder().encode(cache).write(to: cacheURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            }
            do { jobs = try await api.request("podcast-tests"); jobsError = nil }
            catch { jobsError = error.localizedDescription }
            do { try await notifications.check(api: api) }
            catch { notifications.schedulingMessage = "De laatste meldingencontrole is mislukt: \(error.localizedDescription)" }
        } catch APIError.unauthorized {
            player.stop(); user = nil; api.clearSession(); self.error = APIError.unauthorized.localizedDescription
        } catch { offline = true; self.error = error.localizedDescription }
    }
    func logout() async {
        guard let api else { return }
        busy = true; defer { busy = false }
        do {
            try await api.logout()
            player.stop(); try library.clear(); notifications.reset()
            try? FileManager.default.removeItem(at: cacheURL)
            user = nil; items = []; jobs = []; topics = []; error = nil
        } catch { self.error = "Uitloggen is niet afgerond: \(error.localizedDescription)" }
    }
    func apply(_ item: FeedItem) { if let index = items.firstIndex(where: { $0.id == item.id }) { items[index] = item } }
    func loadDemo() {
        user = StroomUser(id: "demo", email: "demo@stroom.local")
        topics = [Topic(slug: "ai", name: "AI & technologie", itemCount: 24), Topic(slug: "science", name: "Wetenschap", itemCount: 18)]
        items = [
            FeedItem(id: "demo-1", title: "Wat verandert er als AI echt met je meedenkt?", description: "Een gesprek over nieuwsgierigheid, creativiteit en de volgende stap in kunstmatige intelligentie.", sourceName: "De Technoloog", format: "podcast", qualityScore: 8.7, summary: "## Een nieuwe manier van samenwerken\n\nTechnologie is het interessantst wanneer ze ruimte maakt voor betere vragen. Deze aflevering verkent de rol van AI als denkpartner."),
            FeedItem(id: "demo-2", title: "De stille revolutie in onze oceanen", description: "Nieuwe inzichten uit de wereld onder de golven.", sourceName: "NRC Wetenschap", format: "article", qualityScore: 8.2),
            FeedItem(id: "demo-3", title: "Een goed idee begint met een omweg", description: "Over aandacht, wandelen en de kunst van het nietsdoen.", sourceName: "Nooit meer slapen", format: "podcast", qualityScore: 9.1)
        ]
        lastSync = Date()
    }
}
private struct FeedCache: Codable {
    let server: String
    let user: StroomUser
    let topics: [Topic]
    let items: [FeedItem]
    let date: Date
}
