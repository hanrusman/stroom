import SwiftUI
import AVKit

struct ItemDetailView: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.dismiss) private var dismiss
    let id: String
    @State private var item: FeedItem?
    @State private var error: String?
    @State private var updating = false
    @State private var section = "Samenvatting"
    @State private var scheduled = Date.now.addingTimeInterval(86400)
    @State private var scheduling = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                if let item {
                    if let source = item.sourceId {
                        NavigationLink { SourceScreen(id: source, name: item.sourceName) } label: {
                            Label(item.sourceName.uppercased(), systemImage: "antenna.radiowaves.left.and.right").font(.caption.weight(.semibold))
                        }
                    } else { Text(item.sourceName.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(Brand.blue) }
                    Text(item.title).font(.system(.largeTitle, design: .serif).weight(.medium))
                    HStack {
                        if let date = item.date { Text(date.formatted(date: .long, time: .omitted)) }
                        Spacer()
                        if let score = item.qualityScore { Label(score.formatted(), systemImage: "star") }
                    }.font(.caption).foregroundStyle(.secondary)
                    if let topics = item.topics, !topics.isEmpty { Text(topics.joined(separator: " · ")).font(.caption).foregroundStyle(Brand.blue) }
                    if let track = item.track { TrackActions(track: track) }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 20) {
                            Button(item.status == "pinned" ? "Bewaard" : "Bewaren", systemImage: item.status == "pinned" ? "bookmark.fill" : "bookmark") { Task { await status(item.status == "pinned" ? "new" : "pinned") } }
                            Button(store.queuedIDs.contains(id) ? "Uit wachtrij" : "In wachtrij", systemImage: "text.badge.plus") { Task { await store.setQueued(item, queued: !store.queuedIDs.contains(id)) } }.disabled(item.status == "archived")
                            Button("Plan", systemImage: "calendar") { scheduling = true }
                            Button(item.status == "archived" ? "Uit archief" : "Archiveer", systemImage: "archivebox") {
                                Task {
                                    if item.status == "archived" { await status("new") }
                                    else { await store.archive(item); if store.actionError == nil { dismiss() } }
                                }
                            }
                        }.font(.callout).frame(minHeight: 44)
                    }.disabled(updating || store.changing.contains(id))
                    if let planned = item.scheduledFor.flatMap(StroomDate.parse) { Label("Gepland voor \(planned.formatted(date: .abbreviated, time: .shortened))", systemImage: "calendar").font(.caption) }
                    if let message = store.actionError { Text(message).font(.callout).foregroundStyle(.red) }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(["Bron", "Samenvatting", "Lessen", "Transcript", "Vraag"], id: \.self) { name in
                                Button(name) { section = name }.font(.subheadline.weight(.medium)).padding(.horizontal, 15).frame(minHeight: 44)
                                    .background(section == name ? Brand.blue.opacity(0.14) : Color.secondary.opacity(0.06), in: Capsule())
                                    .accessibilityAddTraits(section == name ? .isSelected : [])
                            }
                        }
                    }
                    switch section {
                    case "Bron":
                        if let text = item.description, !text.isEmpty { MarkdownBody(text: text) }
                        else { Text("De bron heeft geen artikeltekst meegeleverd. Open het origineel hieronder.").foregroundStyle(.secondary) }
                    case "Samenvatting":
                        if let text = item.summary, !text.isEmpty { MarkdownBody(text: text) }
                        else { Text("Nog geen samenvatting beschikbaar.").foregroundStyle(.secondary) }
                        processing(item)
                        Button(item.summary == nil ? "Samenvatten" : "Opnieuw samenvatten", systemImage: "sparkles") { Task { await action("summarize") } }.disabled(updating || store.demo)
                    case "Lessen": ItemLessonsView(id: id)
                    case "Transcript":
                        if let text = item.transcript, !text.isEmpty { MarkdownBody(text: text) }
                        else {
                            Text("Nog geen transcript beschikbaar.").foregroundStyle(.secondary)
                            if item.format == "podcast" || item.format == "video" { Button("Transcriberen", systemImage: "waveform") { Task { await action("transcribe") } }.disabled(updating || store.demo) }
                        }
                        processing(item)
                    default: ItemQuestionsView(id: id)
                    }
                    if updating { ProgressView("Bezig…") }
                    Divider()
                    if let raw = item.mediaUrl, !item.isPodcast, let url = URL(string: raw), ["https", "http"].contains(url.scheme ?? "") {
                        Link("Open origineel", destination: url)
                    }
                    if let url = stroomURL(server: store.server, query: ["item": id]) {
                        ShareLink("Deel via Stroom", item: url)
                        NavigationLink("Meer artikelopties", destination: StroomWebView(url: url).navigationTitle("Artikelopties"))
                    }
                } else if error == nil { ProgressView().frame(maxWidth: .infinity) }
                if let error { ErrorNotice(message: error) { await load() } }
            }.padding(22).frame(maxWidth: 760, alignment: .leading)
        }.frame(maxWidth: .infinity).background(Brand.paper).navigationTitle("In Stroom").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
            .task { await load() }.refreshable { await load() }
            .sheet(isPresented: $scheduling) {
                NavigationStack {
                    Form {
                        DatePicker("Lezen op", selection: $scheduled, in: Date.now..., displayedComponents: [.date, .hourAndMinute])
                        Button("Inplannen") { Task { await schedule(scheduled) } }.disabled(updating)
                        Button("Planning verwijderen") { Task { await schedule(nil) } }.disabled(updating)
                        if let error { Text(error).foregroundStyle(.red) }
                    }.navigationTitle("Later lezen").toolbar { Button("Sluiten") { scheduling = false } }
                }.presentationDetents([.medium, .large])
            }
    }
    @ViewBuilder func processing(_ item: FeedItem) -> some View {
        if let state = item.processingStatus, ["queued", "transcribe_queued", "summarize_queued", "transcribing", "summarizing"].contains(state) {
            Label("Verwerking loopt. Trek omlaag om te verversen.", systemImage: "clock").font(.caption).foregroundStyle(.secondary)
        }
    }
    func load() async {
        if item == nil { item = (store.items + store.queueItems).first { $0.id == id }.map(store.current) }
        guard !store.demo, let api = store.api else { return }
        do { let value = try await api.item(id); item = value; store.apply(value); error = nil } catch { self.error = error.localizedDescription }
    }
    func status(_ value: String) async {
        guard let api = store.api else { return }; updating = true; error = nil; defer { updating = false }
        do {
            var updated: FeedItem
            if store.demo { updated = item!; updated.status = value } else { updated = try await api.update(id, status: value) }
            item = updated; store.apply(updated)
        } catch { self.error = error.localizedDescription }
    }
    func action(_ endpoint: String) async {
        guard let api = store.api else { return }; updating = true; error = nil; defer { updating = false }
        do { let updated: FeedItem = try await api.request("huygens/items/\(id)/\(endpoint)", method: "POST"); item = updated; store.apply(updated) }
        catch { self.error = error.localizedDescription }
    }
    func schedule(_ date: Date?) async {
        guard let api = store.api else { return }; updating = true; error = nil; defer { updating = false }
        do {
            let value: Any = date.map { ISO8601DateFormatter().string(from: $0) } as Any? ?? NSNull()
            let updated: FeedItem = try await api.request("huygens/items/\(id)/schedule", method: "POST", body: ["scheduled_for": value])
            item = updated; store.apply(updated); scheduling = false
        } catch { self.error = error.localizedDescription }
    }
}

struct MarkdownBody: View {
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(ContentText.markdown(text).components(separatedBy: "\n").enumerated()), id: \.offset) { _, line in
                if line.trimmingCharacters(in: .whitespaces).isEmpty { Spacer().frame(height: 3) }
                else {
                    let heading = line.range(of: #"^#{1,6}\s"#, options: .regularExpression) != nil
                    let clean = line.replacingOccurrences(of: #"^#{1,6}\s+"#, with: "", options: .regularExpression)
                        .replacingOccurrences(of: #"^\s*[-*+]\s+"#, with: "• ", options: .regularExpression)
                        .replacingOccurrences(of: #"^>\s?"#, with: "│ ", options: .regularExpression)
                    if !clean.hasPrefix("```") {
                        Text((try? AttributedString(markdown: clean, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(clean))
                            .font(heading ? .system(.title3, design: .serif).weight(.semibold) : .body)
                            .lineSpacing(5).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
                    }
                }
            }
        }
    }
}

struct DigestRun: Decodable, Identifiable {
    let id: String; let generatedAt: String; let markdown: String; let model: String?
}
struct DigestView: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.dismiss) var dismiss
    let topic: String
    @State private var digest: Digest?
    @State private var history: [DigestRun] = []
    @State private var error: String?
    @State private var window = "daily"
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Picker("Periode", selection: $window) { Text("Dag").tag("daily"); Text("Week").tag("weekly") }.pickerStyle(.segmented)
                Text("Het grotere plaatje").font(.system(.largeTitle, design: .serif))
                if let date = digest?.generatedAt.flatMap(StroomDate.parse) { Text(date.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(.secondary) }
                if let markdown = digest?.markdown { MarkdownBody(text: markdown) }
                else if digest?.isGenerating == true { Text("Je overzicht wordt nog gemaakt.") }
                else if let error { ErrorNotice(message: error) { await load() } }
                else { ProgressView() }
                if let url = stroomURL(server: store.server, query: ["topic": topic]) {
                    NavigationLink("Overzicht maken of model kiezen", destination: StroomWebView(url: url).navigationTitle("Onderwerpoverzicht"))
                }
                ForEach(history) { run in
                    DisclosureGroup("\(StroomDate.parse(run.generatedAt)?.formatted(date: .abbreviated, time: .shortened) ?? run.generatedAt) · \(run.model ?? "")") { MarkdownBody(text: run.markdown).padding(.top) }
                }
            }.padding(22)
        }.background(Brand.paper).navigationTitle("Overzichten").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
            .task(id: window) { await load() }.refreshable { await load() }
    }
    func load() async {
        guard let api = store.api, !store.demo else { error = "Overzichten zijn beschikbaar met je eigen account."; return }
        digest = nil; history = []; error = nil
        do { let value: Digest = try await api.request("huygens/\(topic)/digest", query: [.init(name: "window", value: window)]); try Task.checkCancellation(); digest = value }
        catch { if !Task.isCancelled { self.error = error.localizedDescription } }
        do { let value: [DigestRun] = try await api.request("huygens/\(topic)/digest/history", query: [.init(name: "window", value: window)]); try Task.checkCancellation(); history = value }
        catch { if !Task.isCancelled { self.error = error.localizedDescription } }
    }
}

struct LibraryView: View {
    @EnvironmentObject var store: AppStore
    @EnvironmentObject var player: AudioPlayer
    @EnvironmentObject var library: LibraryStore
    @State private var saved: [FeedItem] = []
    @State private var error: String?
    var body: some View {
        List {
            Section {
                Text("Jouw eigen verzameling").font(.system(.title, design: .serif)).listRowBackground(Color.clear)
            }
            if let error { Section { Text(error).font(.callout).foregroundStyle(.red) } }
            Section("Offline beschikbaar · \(library.downloads.count)") {
                if library.downloads.isEmpty { Text("Download een podcast met het pijltje. Daarna luister je ook zonder internet.").foregroundStyle(.secondary) }
                ForEach(library.downloads) { track in
                    VStack(alignment: .leading, spacing: 10) { Text(track.title).font(.headline); Text(track.author).font(.caption).foregroundStyle(.secondary); TrackActions(track: track) }
                        .swipeActions { Button("Verwijder download", role: .destructive) { do { if player.current?.id == track.id { player.stop() }; try library.remove(track) } catch { self.error = error.localizedDescription } } }
                }
            }
            Section("Bewaard in Stroom") {
                if saved.isEmpty { Text("Bewaar een artikel of aflevering via het bladwijzertje.").foregroundStyle(.secondary) }
                ForEach(saved.map(store.current).filter { $0.status == "pinned" }) { item in Button { store.openItemID = item.id } label: { VStack(alignment: .leading, spacing: 6) { Text(item.title).foregroundStyle(.primary); Text(item.sourceName).font(.caption).foregroundStyle(.secondary) } }.stroomActions(item) }
            }
        }.scrollContentBackground(.hidden).background(Brand.paper).navigationTitle("Bibliotheek")
            .task { await load() }.refreshable { await load() }
    }
    func load() async {
        guard !store.demo, let api = store.api else { return }
        do { saved = try await api.items(saved: true, limit: 500); error = nil }
        catch { self.error = error.localizedDescription }
    }
}

struct MiniPlayer: View {
    @EnvironmentObject var player: AudioPlayer
    @Binding var showingPlayer: Bool
    var body: some View {
        HStack(spacing: 14) {
            Button { showingPlayer = true } label: {
                HStack(spacing: 12) {
                    Artwork(raw: player.current?.artwork).frame(width: 42, height: 42).clipShape(RoundedRectangle(cornerRadius: 9))
                    VStack(alignment: .leading, spacing: 3) { Text(player.current?.title ?? "").font(.subheadline.weight(.medium)).lineLimit(1); Text(player.error != nil ? "Afspelen mislukt · tik voor details" : (player.current?.author ?? "")).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.buttonStyle(.plain)
            if player.loading { ProgressView() }
            Button { player.toggle() } label: { Image(systemName: player.playing ? "pause.fill" : "play.fill").font(.title3).frame(width: 44, height: 44) }.accessibilityLabel(player.playing ? "Pauzeer" : "Speel af")
        }.padding(10).background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct NowPlayingView: View {
    @EnvironmentObject var player: AudioPlayer
    @Environment(\.dismiss) var dismiss
    @State private var scrubbing = false
    @State private var position: Double = 0
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 28) {
                    Text("NU IN JE OREN").font(.caption.weight(.semibold)).tracking(3).foregroundStyle(Brand.blue)
                    Artwork(raw: player.current?.artwork).frame(maxWidth: 340).aspectRatio(1, contentMode: .fit).clipShape(RoundedRectangle(cornerRadius: 30)).shadow(color: Brand.blue.opacity(0.12), radius: 22, y: 12)
                    VStack(spacing: 8) { Text(player.current?.title ?? "Kies een podcast").font(.system(.title2, design: .serif).weight(.medium)).multilineTextAlignment(.center); Text(player.current?.author ?? "").foregroundStyle(.secondary) }
                    if let error = player.error { Text(error).font(.caption).foregroundStyle(.red) }
                    VStack(spacing: 4) {
                        Slider(value: Binding(get: { scrubbing ? position : player.elapsed }, set: { position = $0 }), in: 0...max(1, player.duration), onEditingChanged: { editing in
                            if editing { position = player.elapsed }; scrubbing = editing
                            if !editing { player.seek(position) }
                        }).disabled(player.duration <= 0).accessibilityLabel("Luisterpositie")
                        HStack { Text(timestamp(player.elapsed)); Spacer(); Text("−\(timestamp(max(0, player.duration - player.elapsed)))") }.font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                    }
                    HStack(spacing: 34) {
                        Button { player.skip(-15) } label: { Image(systemName: "gobackward.15").font(.title) }.accessibilityLabel("15 seconden terug")
                        Button { player.toggle() } label: { Image(systemName: player.playing ? "pause.fill" : "play.fill").font(.system(size: 32)).frame(width: 78, height: 78).foregroundStyle(.white).background(Color(red: 0, green: 0.2, blue: 0.4), in: Circle()) }.accessibilityLabel(player.playing ? "Pauzeer" : "Speel af")
                        Button { player.skip(30) } label: { Image(systemName: "goforward.30").font(.title) }.accessibilityLabel("30 seconden vooruit")
                    }
                    HStack {
                        Menu { ForEach([0.75, 1, 1.25, 1.5, 1.75, 2], id: \.self) { speed in Button("\(speed.formatted())×") { player.speed = Float(speed) } } } label: { Text("\(Double(player.speed).formatted())×").font(.headline).frame(width: 64, height: 44) }.accessibilityLabel("Afspeelsnelheid")
                        Spacer()
                        AirPlayButton().frame(width: 44, height: 44).accessibilityLabel("AirPlay")
                        Spacer()
                        Menu { Button("Uit") { player.sleep(minutes: nil) }; ForEach([15, 30, 45, 60], id: \.self) { minute in Button("\(minute) minuten") { player.sleep(minutes: minute) } } } label: { Image(systemName: player.sleepUntil == nil ? "moon" : "moon.fill").frame(width: 64, height: 44) }.accessibilityLabel("Slaaptimer")
                    }
                    if let until = player.sleepUntil { Text("Stopt om \(until.formatted(date: .omitted, time: .shortened))").font(.caption).foregroundStyle(.secondary) }
                    if !player.queue.isEmpty {
                        VStack(alignment: .leading, spacing: 18) {
                            HStack { Text("Hierna").font(.headline); Spacer(); Button("Volgende") { player.next() } }
                            ForEach(Array(player.queue.enumerated()), id: \.element.id) { index, track in
                                HStack { Text(track.title).font(.subheadline).lineLimit(2); Spacer(); Button { player.removeFromQueue(at: IndexSet(integer: index)) } label: { Image(systemName: "minus.circle") }.accessibilityLabel("Verwijder uit wachtrij") }
                            }
                        }
                    }
                }.padding(28).frame(maxWidth: 560)
            }.frame(maxWidth: .infinity).background(Brand.paper)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
        }
    }
    func timestamp(_ value: Double) -> String { let seconds = Int(value.isFinite ? max(0, value) : 0); return String(format: "%d:%02d", seconds / 60, seconds % 60) }
}
struct AirPlayButton: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView { let view = AVRoutePickerView(); view.prioritizesVideoDevices = false; return view }
    func updateUIView(_ uiView: AVRoutePickerView, context: Context) { }
}
