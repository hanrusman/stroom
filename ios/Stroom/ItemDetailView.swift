import AVKit
import SwiftUI

struct ItemDetailView: View {
  @EnvironmentObject var store: AppStore
  @EnvironmentObject var player: AudioPlayer
  @Environment(\.dismiss) private var dismiss
  @Environment(\.dynamicTypeSize) private var typeSize
  let id: String
  @State private var item: FeedItem?
  @State private var error: String?
  @State private var updating = false
  @State private var section = "Bron"
  @State private var didChooseSection = false
  @State private var scheduled = Date.now.addingTimeInterval(86400)
  @State private var scheduling = false
  @State private var curating = false
  @State private var showingPlayer = false
  var body: some View {
    ScrollView {
      LazyVStack(alignment: .leading, spacing: 22, pinnedViews: [.sectionHeaders]) {
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
          Text(item.title).font(Brand.display(34))
          HStack {
            if let date = item.date { Text(date.formatted(date: .long, time: .omitted)) }
            Spacer()
            if let score = item.qualityScore { Label(score.formatted(), systemImage: "star") }
          }.font(.caption).foregroundStyle(.secondary)
          if let topics = item.topics, !topics.isEmpty {
            Text(topics.joined(separator: " · ")).font(.caption).foregroundStyle(Brand.blue)
          }
          if let track = item.track {
            TrackActions(track: track)
            if player.current?.id == track.id {
              Button("Open speler", systemImage: "waveform") { showingPlayer = true }
                .font(.subheadline).frame(minHeight: 44)
            }
          }
          if item.format == "video" { VideoPreview(item: item) }
          if let planned = item.scheduledFor.flatMap({ ScheduledDay.localDate($0) }) {
            Label(
              "Gepland voor \(planned.formatted(date: .abbreviated, time: .omitted))",
              systemImage: "calendar"
            ).font(.caption)
          }
          if item.status == "later" && item.scheduledFor == nil {
            Label("Later · geen datum", systemImage: "clock").font(.caption)
          }
          Section {
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
          } header: {
            readerSections(item).padding(.bottom, 10).background(Brand.paper)
          }
        } else if error == nil {
          ProgressView().frame(maxWidth: .infinity)
        }
        if let error { ErrorNotice(message: error) { await load() } }
      }.padding(24).frame(maxWidth: 680, alignment: .leading)
    }.frame(maxWidth: .infinity).background(Brand.paper).navigationTitle("In Stroom")
      .navigationBarTitleDisplayMode(.inline)
      .safeAreaInset(edge: .bottom, spacing: 0) {
        if let item { readerActions(item) }
      }
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
      .sheet(isPresented: $showingPlayer) { NowPlayingView() }
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
  func readerSections(_ item: FeedItem) -> some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("LEZEN & VERDIEPEN").font(Brand.meta).tracking(1.5).foregroundStyle(Brand.muted)
      ScrollViewReader { proxy in
        ScrollView(.horizontal, showsIndicators: false) {
          HStack(spacing: 6) {
            ForEach(
              item.format == "article"
                ? ["Bron", "Samenvatting", "Lessen", "Vraag"]
                : ["Bron", "Samenvatting", "Lessen", "Transcript", "Vraag"], id: \.self
            ) { name in
              StroomChip(title: name, selected: section == name) { section = name }
                .id(name)
            }
          }
        }.onChange(of: section) { _, value in proxy.scrollTo(value, anchor: .center) }
      }
      Divider().overlay(Brand.line).padding(.top, 6)
    }.padding(.top, 6)
  }
  func readerActions(_ item: FeedItem) -> some View {
    VStack(spacing: 0) {
      ActionFeedback()
      HStack(spacing: 12) {
        Button {
          Task { await status(item.status == "pinned" ? "new" : "pinned") }
        } label: {
          Label(
            item.status == "pinned" ? "Bewaard" : "Bewaren",
            systemImage: item.status == "pinned" ? "bookmark.fill" : "bookmark"
          )
          .labelStyle(ReaderActionLabelStyle(compact: typeSize.isAccessibilitySize))
          .font(.subheadline).frame(minWidth: 48, minHeight: 48)
        }.accessibilityLabel(item.status == "pinned" ? "Bewaard" : "Bewaren")
        Spacer(minLength: 0)
        Button {
          Task { await store.setQueued(item, queued: !store.queuedIDs.contains(id)) }
        } label: {
          Label(
            store.queuedIDs.contains(id) ? "In wachtrij" : "Wachtrij",
            systemImage: store.queuedIDs.contains(id) ? "text.badge.checkmark" : "text.badge.plus"
          )
          .labelStyle(ReaderActionLabelStyle(compact: typeSize.isAccessibilitySize))
          .font(.subheadline).frame(minWidth: 48, minHeight: 48)
        }.accessibilityLabel(store.queuedIDs.contains(id) ? "Uit wachtrij" : "In wachtrij")
          .disabled(item.status == "archived")
        Spacer(minLength: 0)
        Menu {
          Button("Plan", systemImage: "calendar") {
            scheduled =
              item.scheduledFor.flatMap { ScheduledDay.localDate($0) }
              ?? Date.now.addingTimeInterval(86400)
            scheduling = true
          }
          Button("Score en onderwerpen", systemImage: "slider.horizontal.3") { curating = true }
          if let url = stroomURL(server: store.server, query: ["item": id]) {
            ShareLink("Deel via Stroom", item: url)
          }
          Divider()
          Button(item.status == "archived" ? "Uit archief" : "Archiveer", systemImage: "archivebox")
          {
            Task {
              if item.status == "archived" {
                await status("new")
              } else {
                await store.archive(item)
                if store.actionError == nil { dismiss() }
              }
            }
          }
        } label: {
          Image(systemName: "ellipsis").frame(width: 48, height: 48)
        }
        .accessibilityLabel("Artikelacties").accessibilityIdentifier("reader-actions")
      }.padding(.horizontal, 24).disabled(updating || store.changing.contains(id))
    }.background(.regularMaterial)
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
    guard let current = item else { return }
    updating = true
    error = nil
    defer { updating = false }
    do {
      var updated: FeedItem
      if store.demo {
        updated = current
        updated.status = value
      } else {
        guard let api = store.api else { return }
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
