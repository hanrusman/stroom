import AVKit
import SwiftUI

struct ItemDetailView: View {
  @EnvironmentObject var store: AppStore
  @Environment(\.dismiss) private var dismiss
  let id: String
  @State private var item: FeedItem?
  @State private var error: String?
  @State private var updating = false
  @State private var section = "Bron"
  @State private var didChooseSection = false
  @State private var scheduled = Date.now.addingTimeInterval(86400)
  @State private var scheduling = false
  @State private var curating = false
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 22) {
        if let item {
          if let source = item.sourceId {
            NavigationLink {
              SourceScreen(id: source, name: item.sourceName)
            } label: {
              Label(item.sourceName.uppercased(), systemImage: "antenna.radiowaves.left.and.right")
                .font(.caption.weight(.semibold))
            }
          } else {
            Text(item.sourceName.uppercased()).font(.caption.weight(.semibold)).foregroundStyle(
              Brand.blue)
          }
          Text(item.title).font(.system(.largeTitle, design: .serif).weight(.medium))
          HStack {
            if let date = item.date { Text(date.formatted(date: .long, time: .omitted)) }
            Spacer()
            if let score = item.qualityScore { Label(score.formatted(), systemImage: "star") }
          }.font(.caption).foregroundStyle(.secondary)
          if let topics = item.topics, !topics.isEmpty {
            Text(topics.joined(separator: " · ")).font(.caption).foregroundStyle(Brand.blue)
          }
          if let track = item.track { TrackActions(track: track) }
          ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 20) {
              Button(
                item.status == "pinned" ? "Bewaard" : "Bewaren",
                systemImage: item.status == "pinned" ? "bookmark.fill" : "bookmark"
              ) { Task { await status(item.status == "pinned" ? "new" : "pinned") } }
              Button(
                store.queuedIDs.contains(id) ? "Uit wachtrij" : "In wachtrij",
                systemImage: "text.badge.plus"
              ) { Task { await store.setQueued(item, queued: !store.queuedIDs.contains(id)) } }
              .disabled(item.status == "archived")
              Button("Plan", systemImage: "calendar") {
                scheduled =
                  item.scheduledFor.flatMap { ScheduledDay.localDate($0) }
                  ?? Date.now.addingTimeInterval(86400)
                scheduling = true
              }
              Button("Score en onderwerpen", systemImage: "slider.horizontal.3") { curating = true }
              Button(
                item.status == "archived" ? "Uit archief" : "Archiveer", systemImage: "archivebox"
              ) {
                Task {
                  if item.status == "archived" {
                    await status("new")
                  } else {
                    await store.archive(item)
                    if store.actionError == nil { dismiss() }
                  }
                }
              }
            }.font(.callout).frame(minHeight: 44)
          }.disabled(updating || store.changing.contains(id))
          if let planned = item.scheduledFor.flatMap({ ScheduledDay.localDate($0) }) {
            Label(
              "Gepland voor \(planned.formatted(date: .abbreviated, time: .omitted))",
              systemImage: "calendar"
            ).font(.caption)
          }
          if item.status == "later" && item.scheduledFor == nil {
            Label("Later · geen datum", systemImage: "clock").font(.caption)
          }
          if let message = store.actionError { Text(message).font(.callout).foregroundStyle(.red) }
          ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
              ForEach(
                item.format == "article"
                  ? ["Bron", "Samenvatting", "Lessen", "Vraag"]
                  : ["Bron", "Samenvatting", "Lessen", "Transcript", "Vraag"], id: \.self
              ) { name in
                Button(name) { section = name }.font(.subheadline.weight(.medium)).padding(
                  .horizontal, 15
                ).frame(minHeight: 44)
                  .background(
                    section == name ? Brand.blue.opacity(0.14) : Color.secondary.opacity(0.06),
                    in: Capsule()
                  )
                  .accessibilityAddTraits(section == name ? .isSelected : [])
              }
            }
          }
          switch section {
          case "Bron":
            ArticleBody(item: item)
            if item.sourceBody?.isEmpty != false {
              Text("De bron heeft geen artikeltekst meegeleverd. Open het origineel hieronder.")
                .foregroundStyle(.secondary)
            }

          case "Samenvatting":
            if let text = item.summary, !text.isEmpty {
              MarkdownBody(text: text)
            } else {
              Text("Nog geen samenvatting beschikbaar.").foregroundStyle(.secondary)
            }
            if let model = item.summaryModel {
              Text("Samengevat met \(model)").font(.caption).foregroundStyle(.secondary)
            }
            processing(item)
            Button(
              item.summary == nil ? "Samenvatten" : "Opnieuw samenvatten", systemImage: "sparkles"
            ) { Task { await action("summarize") } }.disabled(updating || store.demo)
          case "Lessen": ItemLessonsView(id: id)
          case "Transcript":
            if let segments = item.transcriptSegments, !segments.isEmpty {
              TranscriptView(item: item, segments: segments)
            } else if let text = item.transcript, !text.isEmpty {
              MarkdownBody(text: text)
            } else {
              Text("Nog geen transcript beschikbaar.").foregroundStyle(.secondary)
              if item.format == "podcast" || item.format == "video" {
                Button("Transcriberen", systemImage: "waveform") {
                  Task { await action("transcribe") }
                }.disabled(updating || store.demo)
              }
            }
            processing(item)
          default: ItemQuestionsView(id: id)
          }
          if updating { ProgressView("Bezig…") }
          Divider()
          if let raw = item.mediaUrl, !item.isPodcast, let url = URL(string: raw),
            ["https", "http"].contains(url.scheme ?? "")
          {
            Link("Open origineel", destination: url)
          }
          if let url = stroomURL(server: store.server, query: ["item": id]) {
            ShareLink("Deel via Stroom", item: url)
            NavigationLink(
              "Meer artikelopties",
              destination: StroomWebView(url: url).navigationTitle("Artikelopties"))
          }
        } else if error == nil {
          ProgressView().frame(maxWidth: .infinity)
        }
        if let error { ErrorNotice(message: error) { await load() } }
      }.padding(22).frame(maxWidth: 760, alignment: .leading)
    }.frame(maxWidth: .infinity).background(Brand.paper).navigationTitle("In Stroom")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
      .task { await load() }
      .task(id: item?.isProcessing == true) {
        while item?.isProcessing == true && !Task.isCancelled {
          do {
            try await Task.sleep(for: .seconds(8))
            try Task.checkCancellation()
          } catch { return }
          await load()
        }
      }.refreshable { await load() }
      .sheet(isPresented: $curating) {
        if let item {
          ItemCurationView(item: item) { updated in
            self.item = updated
            store.apply(updated)
          }
        }
      }
      .sheet(isPresented: $scheduling) {
        NavigationStack {
          Form {
            DatePicker(
              "Lezen op", selection: $scheduled,
              displayedComponents: [.date])
            Button("Inplannen") { Task { await schedule(scheduled) } }.disabled(updating)
            Button("Later (geen datum)") { Task { await schedule(nil, later: true) } }.disabled(
              updating)
            Button("Wis planning") { Task { await schedule(nil) } }.disabled(updating)
            if let error { Text(error).foregroundStyle(.red) }
          }.navigationTitle("Later lezen").toolbar { Button("Sluiten") { scheduling = false } }
        }.presentationDetents([.medium, .large])
      }
  }
  @ViewBuilder func processing(_ item: FeedItem) -> some View {
    if item.isProcessing {
      Label(
        item.queuePosition.map { "In de rij · #\($0)" } ?? "Wordt verwerkt…", systemImage: "clock"
      )
      .font(.caption).foregroundStyle(.secondary)
    } else if item.processingStatus == "failed" {
      Label(
        "Verwerking mislukt. Probeer de actie opnieuw.", systemImage: "exclamationmark.triangle"
      )
      .font(.callout).foregroundStyle(.red)
    }
  }
  func load() async {
    if item == nil { item = store.allKnownItems.first { $0.id == id }.map(store.current) }
    defer {
      if !didChooseSection, let item {
        section = item.initialSection
        didChooseSection = true
      }
    }
    guard !store.demo, let api = store.api else { return }
    do {
      let value = try await api.item(id)
      item = value
      store.apply(value)
      error = nil
    } catch { self.error = error.localizedDescription }
  }
  func status(_ value: String) async {
    guard let api = store.api else { return }
    updating = true
    error = nil
    defer { updating = false }
    do {
      var updated: FeedItem
      if store.demo {
        updated = item!
        updated.status = value
      } else {
        updated = try await api.update(id, status: value)
      }
      item = updated
      store.apply(updated)
    } catch { self.error = error.localizedDescription }
  }
  func action(_ endpoint: String) async {
    guard let api = store.api else { return }
    updating = true
    error = nil
    defer { updating = false }
    do {
      let updated: FeedItem = try await api.request(
        "huygens/items/\(id)/\(endpoint)", method: "POST")
      item = updated
      store.apply(updated)
    } catch { self.error = error.localizedDescription }
  }
  func schedule(_ date: Date?, later: Bool = false) async {
    guard let item else { return }
    updating = true
    defer { updating = false }
    if await store.plan(item, date: date, later: later) {
      self.item = store.current(item)
      scheduling = false
      error = nil
    } else {
      self.item = store.current(item)
      error = store.actionError
    }
  }
}
