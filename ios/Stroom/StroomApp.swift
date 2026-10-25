import SwiftUI

@main
struct StroomApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var store = AppStore.shared
    @Environment(\.scenePhase) private var scenePhase
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store).environmentObject(store.player).environmentObject(store.library)
                .environmentObject(store.notifications)
                .tint(Brand.blue)
                .task { await store.start() }
                .onOpenURL { url in
                    guard url.scheme == "stroom" else { return }
                    if url.host == "item", let id = url.pathComponents.last, UUID(uuidString: id) != nil { store.openItemID = id; store.tab = 0 }
                    if url.host == "podcasts" { store.tab = 1 }
                }
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background { store.notifications.scheduleRefresh() }
                    if phase == .active { Task { await store.notifications.permissionStatus(); if !store.starting { await store.refresh() } } }
                }
        }
    }
}

enum Brand {
    static let blue = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(red: 0.48, green: 0.69, blue: 0.91, alpha: 1) : UIColor(red: 0, green: 0.20, blue: 0.40, alpha: 1) })
    static let paper = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? UIColor(red: 0.06, green: 0.07, blue: 0.08, alpha: 1) : UIColor(red: 0.977, green: 0.969, blue: 0.949, alpha: 1) })
    static let card = Color(uiColor: .secondarySystemGroupedBackground)
}

struct RootView: View {
    @EnvironmentObject var store: AppStore
    @EnvironmentObject var player: AudioPlayer
    @State private var showingPlayer = false
    var body: some View {
        Group {
            if store.starting { ProgressView("Stroom openen…").frame(maxWidth: .infinity, maxHeight: .infinity).background(Brand.paper) }
            else if store.user == nil { LoginView() }
            else {
                TabView(selection: $store.tab) {
                    NavigationStack { FeedScreen(podcastsOnly: false) }.tabItem { Label("Stroom", systemImage: "water.waves") }.tag(0)
                    NavigationStack { FeedScreen(podcastsOnly: true) }.tabItem { Label("Luisteren", systemImage: "headphones") }.tag(1)
                    NavigationStack { LibraryView() }.tabItem { Label("Bibliotheek", systemImage: "books.vertical") }.tag(2)
                    NavigationStack { SettingsView() }.tabItem { Label("Instellingen", systemImage: "slider.horizontal.3") }.tag(3)
                }
                .safeAreaInset(edge: .bottom, spacing: 0) {
                    if player.current != nil { MiniPlayer(showingPlayer: $showingPlayer).padding(.horizontal, 12).padding(.bottom, 8).background(.ultraThinMaterial) }
                }
                .sheet(isPresented: $showingPlayer) { NowPlayingView() }
                .sheet(item: Binding(get: { store.openItemID.map(ItemLink.init) }, set: { store.openItemID = $0?.id })) { link in
                    NavigationStack { ItemDetailView(id: link.id) }
                }
            }
        }
    }
}
struct ItemLink: Identifiable { let id: String }

struct LoginView: View {
    @EnvironmentObject var store: AppStore
    @State private var email = ""
    @State private var password = ""
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    Image(systemName: "water.waves").font(.system(size: 48, weight: .light)).foregroundStyle(Brand.blue).padding(.top, 48)
                    Text("Een wereld aan ideeën.\nOp jouw ritme.").font(.system(.largeTitle, design: .serif).weight(.medium))
                    Text("Je onderwerpen, inzichten en podcasts.\nDezelfde Stroom, nu op je iPhone.").foregroundStyle(.secondary)
                    VStack(spacing: 14) {
                        TextField("Stroom-adres", text: $store.server).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Divider()
                        TextField("E-mailadres", text: $email).keyboardType(.emailAddress).textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                        Divider()
                        SecureField("Wachtwoord", text: $password).textContentType(.password)
                    }.padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 20))
                    if let error = store.error { Label(error, systemImage: "exclamationmark.circle").font(.callout).foregroundStyle(.red) }
                    Button {
                        Task { await store.login(email: email, password: password); password = "" }
                    } label: {
                        HStack { Text("Verbind met Stroom"); Spacer(); if store.busy { ProgressView().tint(.white) } else { Image(systemName: "arrow.right") } }
                            .fontWeight(.semibold).padding(18).foregroundStyle(.white).background(Color(red: 0, green: 0.2, blue: 0.4), in: Capsule())
                    }.disabled(store.busy || email.isEmpty || password.isEmpty)
                    Text("Log in met je bestaande Stroom-account. Je wachtwoord wordt niet opgeslagen.").font(.footnote).foregroundStyle(.secondary)
                }.padding(28).frame(maxWidth: 550)
            }.frame(maxWidth: .infinity).background(Brand.paper).navigationTitle("Stroom").navigationBarTitleDisplayMode(.inline)
        }
    }
}

struct FeedScreen: View {
    @EnvironmentObject var store: AppStore
    let podcastsOnly: Bool
    @State private var topic = ""
    @State private var query = ""
    @State private var filtered: [FeedItem]?
    @State private var searchResults: [SearchHit] = []
    @State private var loading = false
    @State private var error: String?
    @State private var offset = 0
    @State private var more = true
    @State private var showDigest = false
    var visible: [FeedItem] { (filtered ?? store.items).filter { !podcastsOnly || $0.isPodcast } }
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(podcastsOnly ? "ZET DE WERELD EVEN AAN" : Date.now.formatted(.dateTime.weekday(.wide).day().month(.wide).locale(Locale(identifier: "nl_NL"))).uppercased())
                        .font(.caption.weight(.semibold)).tracking(2).foregroundStyle(Brand.blue)
                    Text(podcastsOnly ? "Goed gezelschap\nvoor onderweg." : "Volg je nieuwsgierigheid.")
                        .font(.system(.largeTitle, design: .serif).weight(.medium))
                    Text(podcastsOnly ? "Luister verder. Neem een nieuw idee mee." : "Een selectie uit jouw wereld van ideeën.").foregroundStyle(.secondary)
                }.padding(.top, 12)
                if store.demo { Text("Voorbeeldweergave · geen live gegevens").font(.caption).foregroundStyle(.secondary) }
                if store.offline { Label("Offline · laatst opgehaalde inhoud", systemImage: "wifi.slash").font(.callout).foregroundStyle(.orange) }
                if let error = error ?? store.error { ErrorNotice(message: error) { await reload() } }
                if podcastsOnly && query.isEmpty { generatedSection }
                HStack {
                    Menu {
                        Button("Alle onderwerpen") { topic = "" }
                        ForEach(store.topics) { t in Button(t.name) { topic = t.slug } }
                    } label: { Label(store.topics.first(where: { $0.slug == topic })?.name ?? "Alle onderwerpen", systemImage: "line.3.horizontal.decrease") }
                    Spacer()
                    if !topic.isEmpty { Button("Dagoverzicht", systemImage: "text.book.closed") { showDigest = true }.labelStyle(.iconOnly).accessibilityLabel("Dagoverzicht van onderwerp") }
                }.font(.subheadline.weight(.medium))
                if loading { ProgressView().frame(maxWidth: .infinity) }
                if !query.trimmingCharacters(in: .whitespaces).isEmpty {
                    ForEach(searchResults) { hit in
                        Button { store.openItemID = hit.id } label: {
                            VStack(alignment: .leading, spacing: 8) { Text(hit.sourceName.uppercased()).font(.caption).foregroundStyle(Brand.blue); Text(hit.title).font(.headline).foregroundStyle(.primary) }
                                .frame(maxWidth: .infinity, alignment: .leading).padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 18))
                        }.buttonStyle(.plain)
                    }
                    if !loading && searchResults.isEmpty { ContentUnavailableView.search(text: query) }
                } else {
                    ForEach(visible) { item in FeedCard(item: item) }
                    if visible.isEmpty && !loading { ContentUnavailableView("Nog niets hier", systemImage: podcastsOnly ? "headphones" : "water.waves", description: Text("Kies een ander onderwerp of haal meer inhoud op.")) }
                    if more && !store.demo { Button("Meer ophalen") { Task { await loadMore() } }.frame(maxWidth: .infinity).disabled(loading) }
                }
                Text("STROOM · RUIMTE VOOR NIEUWE IDEEËN").font(.caption2).tracking(1.6).foregroundStyle(.tertiary).frame(maxWidth: .infinity).padding(.vertical, 20)
            }.padding(.horizontal, 20).frame(maxWidth: 760)
        }.frame(maxWidth: .infinity).background(Brand.paper)
        .navigationTitle(podcastsOnly ? "Luisteren" : "Stroom").navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: "Zoek in Stroom")
        .refreshable { await reload() }
        .task(id: topic) { await loadTopic() }
        .task(id: query) { await search() }
        .sheet(isPresented: $showDigest) { NavigationStack { DigestView(topic: topic) } }
    }
    @ViewBuilder var generatedSection: some View {
        if !store.jobs.isEmpty || store.jobsError != nil {
            VStack(alignment: .leading, spacing: 12) {
                Label("Door Stroom gemaakt", systemImage: "waveform").font(.headline)
                if let message = store.jobsError { Text(message).font(.caption).foregroundStyle(.secondary) }
                ForEach(store.jobs.prefix(10)) { job in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(String(job.text.prefix(120))).font(.subheadline).lineLimit(2)
                        if let track = job.track { TrackActions(track: track) }
                        else { Label(job.status == "failed" ? (job.message ?? "Maken mislukt") : "Wordt gemaakt…", systemImage: job.status == "failed" ? "exclamationmark.circle" : "clock").font(.caption).foregroundStyle(.secondary) }
                    }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
                }
            }
        }
    }
    func reload() async { await store.refresh(); await loadTopic() }
    func loadTopic() async {
        guard !store.demo, let api = store.api else { return }
        loading = true; error = nil
        defer { loading = false }
        do {
            let batch = try await api.items(topic: topic.isEmpty ? nil : topic, limit: podcastsOnly ? 500 : 100)
            try Task.checkCancellation()
            filtered = batch; offset = batch.count; more = batch.count == (podcastsOnly ? 500 : 100)
        } catch is CancellationError { }
        catch { if !Task.isCancelled { self.error = error.localizedDescription } }
    }
    func loadMore() async {
        guard let api = store.api else { return }; loading = true
        defer { loading = false }
        let selected = topic
        do {
            let batch = try await api.items(topic: selected.isEmpty ? nil : selected, offset: offset, limit: podcastsOnly ? 500 : 100)
            guard selected == topic else { return }
            var all = filtered ?? store.items
            let existing = Set(all.map(\.id)); all += batch.filter { !existing.contains($0.id) }
            filtered = all; offset += batch.count; more = batch.count == (podcastsOnly ? 500 : 100)
        } catch { self.error = error.localizedDescription }
    }
    func search() async {
        let term = query.trimmingCharacters(in: .whitespaces)
        guard !term.isEmpty, let api = store.api else { searchResults = []; return }
        do {
            try await Task.sleep(for: .milliseconds(350))
            var parameters = [URLQueryItem(name: "q", value: term), URLQueryItem(name: "limit", value: "50")]
            if podcastsOnly { parameters.append(URLQueryItem(name: "format", value: "podcast")) }
            let hits: [SearchHit] = try await api.request("search", query: parameters)
            try Task.checkCancellation(); searchResults = hits
        } catch is CancellationError { }
        catch { if !Task.isCancelled { self.error = error.localizedDescription } }
    }
}

struct FeedCard: View {
    @EnvironmentObject var store: AppStore
    let item: FeedItem
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 14) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack { Text(item.sourceName.uppercased()).font(.caption2.weight(.semibold)).tracking(1); Spacer(); if let score = item.qualityScore { Text(score, format: .number.precision(.fractionLength(1))).font(.caption.monospacedDigit()).padding(6).background(Brand.blue.opacity(0.09), in: Capsule()) } }.foregroundStyle(Brand.blue)
                    Button { store.openItemID = item.id } label: { Text(item.title).font(.system(.title3, design: .serif).weight(.semibold)).foregroundStyle(.primary).multilineTextAlignment(.leading) }.buttonStyle(.plain)
                    if let text = item.description { Text(text).font(.subheadline).foregroundStyle(.secondary).lineLimit(2) }
                }
                Artwork(raw: item.artwork, symbol: item.isPodcast ? "waveform" : "text.alignleft").frame(width: 64, height: 74).clipShape(RoundedRectangle(cornerRadius: 12))
            }
            if let track = item.track { TrackActions(track: track) }
            else { Button("Lees samenvatting", systemImage: "arrow.up.right") { store.openItemID = item.id }.font(.caption.weight(.semibold)) }
        }.padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 22))
    }
}

struct Artwork: View {
    let raw: String?
    var symbol = "waveform"
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.03, green: 0.18, blue: 0.32), Color(red: 0.15, green: 0.38, blue: 0.48)], startPoint: .topLeading, endPoint: .bottomTrailing)
            Image(systemName: symbol).font(.title).foregroundStyle(.white.opacity(0.85))
            if let raw, let url = URL(string: raw), url.scheme == "https" {
                AsyncImage(url: url) { image in image.resizable().scaledToFill() } placeholder: { Color.clear }
            }
        }.clipped().accessibilityHidden(true)
    }
}

struct TrackActions: View {
    @EnvironmentObject var store: AppStore
    @EnvironmentObject var player: AudioPlayer
    @EnvironmentObject var library: LibraryStore
    let track: AudioTrack
    @State private var error: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 18) {
                Button { player.play(track) } label: { Label("Luister", systemImage: "play.fill").font(.subheadline.weight(.semibold)) }
                Spacer()
                Button { player.enqueue(track) } label: { Image(systemName: player.queue.contains(where: { $0.id == track.id }) ? "checkmark" : "text.badge.plus") }.accessibilityLabel("Voeg toe aan wachtrij")
                if library.downloading.contains(track.id) { ProgressView().accessibilityLabel("Downloaden") }
                else if library.localURL(for: track) != nil { Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).accessibilityLabel("Offline beschikbaar") }
                else {
                    Button {
                        Task { do { if let api = store.api { try await library.download(track, api: api) } } catch { self.error = error.localizedDescription } }
                    } label: { Image(systemName: "arrow.down.circle") }.accessibilityLabel("Download voor offline luisteren")
                }
            }.buttonStyle(.borderless)
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
        }
    }
}

struct ErrorNotice: View {
    let message: String
    let retry: () async -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(message, systemImage: "exclamationmark.circle").font(.callout)
            Button("Opnieuw proberen") { Task { await retry() } }.font(.callout.weight(.semibold))
        }.foregroundStyle(.secondary).padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
    }
}
