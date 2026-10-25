import SwiftUI
import AVKit

struct ItemDetailView: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.dismiss) private var dismiss
    let id: String
    @State private var item: FeedItem?
    @State private var error: String?
    @State private var updating = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if let item {
                    Text(item.sourceName.uppercased()).font(.caption.weight(.semibold)).tracking(2).foregroundStyle(Brand.blue)
                    Text(item.title).font(.system(.largeTitle, design: .serif).weight(.medium))
                    if let date = item.date { Text(date.formatted(date: .long, time: .omitted)).font(.caption).foregroundStyle(.secondary) }
                    if let track = item.track { TrackActions(track: track) }
                    HStack(spacing: 24) {
                        Button(item.status == "pinned" ? "Bewaard" : "Bewaren", systemImage: item.status == "pinned" ? "bookmark.fill" : "bookmark") { Task { await updateStatus(item.status == "pinned" ? "new" : "pinned") } }
                        Button("Archiveren", systemImage: "archivebox") { Task { await updateStatus("archived"); if error == nil { dismiss() } } }
                    }.font(.callout).disabled(updating || store.demo)
                    Divider()
                    if let summary = item.summary, !summary.isEmpty { MarkdownBody(text: summary) }
                    else {
                        Text(item.description ?? "Er is nog geen samenvatting beschikbaar.").textSelection(.enabled)
                        if !store.demo {
                            Button("Samenvatting aanvragen", systemImage: "sparkles") {
                                Task {
                                    updating = true; defer { updating = false }
                                    do { if let api = store.api { self.item = try await api.request("huygens/items/\(id)/summarize", method: "POST") } }
                                    catch { self.error = error.localizedDescription }
                                }
                            }.disabled(updating)
                            if let status = item.processingStatus, ["queued", "transcribe_queued", "summarize_queued", "transcribing", "summarizing"].contains(status) {
                                Text("Verwerking loopt. Trek omlaag om de status te verversen.").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if let transcript = item.transcript, !transcript.isEmpty {
                        DisclosureGroup("Transcript") { Text(transcript).font(.body).textSelection(.enabled).padding(.top) }
                    }
                    if let raw = item.mediaUrl, !item.isPodcast, let url = URL(string: raw), ["https", "http"].contains(url.scheme ?? "") {
                        Link("Open origineel", destination: url)
                        ShareLink(item: url)
                    }
                    if let base = try? ServerAddress.parse(store.server), var parts = URLComponents(url: base, resolvingAgainstBaseURL: false) {
                        let _ = parts.queryItems = [URLQueryItem(name: "item", value: id)]
                        if let url = parts.url { ShareLink("Deel via Stroom", item: url) }
                    }
                } else if error == nil { ProgressView().frame(maxWidth: .infinity) }
                if let error { ErrorNotice(message: error) { await load() } }
            }.padding(24).frame(maxWidth: 760, alignment: .leading)
        }.frame(maxWidth: .infinity).background(Brand.paper).navigationTitle("In Stroom").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
            .task { await load() }.refreshable { await load() }
    }
    func load() async {
        item = store.items.first { $0.id == id }
        guard !store.demo, let api = store.api else { return }
        do { item = try await api.item(id); error = nil } catch { self.error = error.localizedDescription }
    }
    func updateStatus(_ status: String) async {
        guard let api = store.api else { return }; updating = true; error = nil
        defer { updating = false }
        do { let updated = try await api.update(id, status: status); item = updated; store.apply(updated) }
        catch { self.error = error.localizedDescription }
    }
}

struct MarkdownBody: View {
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            ForEach(Array(text.components(separatedBy: "\n\n").enumerated()), id: \.offset) { _, block in
                let heading = block.hasPrefix("#")
                let clean = heading ? block.replacingOccurrences(of: "^#{1,6}\\s+", with: "", options: .regularExpression) : block
                Text((try? AttributedString(markdown: clean, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(clean))
                    .font(heading ? .system(.title3, design: .serif).weight(.semibold) : .body)
                    .lineSpacing(5).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled)
            }
        }
    }
}

struct DigestView: View {
    @EnvironmentObject var store: AppStore
    @Environment(\.dismiss) var dismiss
    let topic: String
    @State private var digest: Digest?
    @State private var error: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("Het grotere plaatje").font(.system(.largeTitle, design: .serif))
                if let markdown = digest?.markdown { MarkdownBody(text: markdown) }
                else if let error { Text(error).foregroundStyle(.secondary) }
                else if digest?.isGenerating == true { Text("Je dagoverzicht wordt nog gemaakt.") }
                else if digest != nil { Text("Er is nog geen dagoverzicht beschikbaar.") }
                else { ProgressView() }
            }.padding(24)
        }.background(Brand.paper).navigationTitle("Dagoverzicht").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
            .task {
                do { if let api = store.api { digest = try await api.request("huygens/\(topic)/digest") } }
                catch { self.error = error.localizedDescription }
            }
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
                ForEach(saved) { item in Button { store.openItemID = item.id } label: { VStack(alignment: .leading, spacing: 6) { Text(item.title).foregroundStyle(.primary); Text(item.sourceName).font(.caption).foregroundStyle(.secondary) } } }
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
