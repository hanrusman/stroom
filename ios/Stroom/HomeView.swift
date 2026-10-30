import SwiftUI

struct FeedScreen: View {
  @EnvironmentObject var store: AppStore
  @Environment(\.dynamicTypeSize) private var typeSize
  let podcastsOnly: Bool
  @State private var query = ""
  @State private var filtered: [FeedItem] = []
  @State private var loading = false
  @State private var error: String?
  @State private var offset = 0
  @State private var more = false
  @State private var filter = "all"
  @State private var window = "all"
  @State private var format = "all"
  @State private var showFilters = false
  @State private var loadedSelection = ""
  @State private var requestID = UUID()
  @State private var archiveTarget: HuygensRail?
  @State private var archiving = false

  var isRanked: Bool {
    store.selectedTopic != "__all__" && filter == "all" && window == "all" && format == "all"
  }
  var selection: String { "\(store.selectedTopic)|\(filter)|\(window)|\(format)" }
  var rails: [HuygensRail] {
    (store.topicFeeds[store.selectedTopic]?.orderedRails ?? []).filter {
      !$0.items.isEmpty && (!podcastsOnly || $0.format == "podcast")
    }
  }
  var visible: [FeedItem] {
    filtered.map(store.current).filter {
      (filter == "archived" ? $0.status == "archived" : $0.status != "archived")
        && (filter != "saved" || $0.status == "pinned")
        && (filter != "scheduled" || $0.scheduledFor != nil)
    }
  }
  var activeFilters: Int { [filter, window, format].filter { $0 != "all" }.count }
  var topicName: String {
    store.topics.first { $0.slug == store.selectedTopic }?.name ?? "Alle onderwerpen"
  }
  var body: some View {
    List {
      VStack(alignment: .leading, spacing: 16) {
        EditorialHeader(
          eyebrow: podcastsOnly ? "Op jouw ritme" : "Jouw selectie",
          title: podcastsOnly ? "Luisteren" : topicName)
        topicChips
        if store.demo {
          Text("Voorbeeldweergave · geen live gegevens").font(Brand.meta).foregroundStyle(
            Brand.muted)
        }
        if store.offline {
          Label("Offline · laatst opgehaalde inhoud", systemImage: "wifi.slash").font(.callout)
        }
        if activeFilters > 0 {
          HStack {
            Label("\(activeFilters) filters actief", systemImage: "line.3.horizontal.decrease")
              .font(.subheadline)
            Spacer()
            Button("Wis filters") { resetFilters() }.frame(minHeight: 44)
          }
        }
        if let error { ErrorNotice(message: error) { await reload() } }
      }.editorialRow()
      if !query.trimmingCharacters(in: .whitespaces).isEmpty {
        SearchResultsView(query: query, podcastsOnly: podcastsOnly)
      } else {
        if podcastsOnly { ContinueListeningSection() }
        if !podcastsOnly && store.selectedTopic != "__all__" && !store.selectedTopic.isEmpty {
          Group {
            if typeSize.isAccessibilitySize {
              VStack(spacing: 12) { digestLinks }
            } else {
              HStack(alignment: .top, spacing: 12) { digestLinks }
            }
          }.editorialRow()
        }
        if loading && (isRanked ? rails.isEmpty : visible.isEmpty) {
          FeedSkeleton().editorialRow()
          FeedSkeleton().editorialRow()
        }
        if isRanked {
          ForEach(rails) { rail in
            let rows = rail.items.map(store.current).filter { $0.status != "archived" }
            Section {
              ForEach(rows) { item in card(item) }
              if rows.isEmpty && !loading {
                Text("Je bent bij. Nieuwe \(rail.title.lowercased()) verschijnen hier.")
                  .font(.subheadline).foregroundStyle(Brand.muted).editorialRow()
              }
            } header: {
              HStack {
                SectionHeading(title: rail.title, count: rows.count)
                Spacer()
                if !rows.isEmpty {
                  Menu {
                    Button("Archiveer alle en laad nieuwe", systemImage: "archivebox") {
                      archiveTarget = HuygensRail(format: rail.format, items: rows)
                    }.disabled(archiving).accessibilityIdentifier("archive-rail-\(rail.format)")
                  } label: {
                    Image(systemName: "ellipsis").frame(width: 44, height: 44).contentShape(
                      Rectangle())
                  }.accessibilityLabel("Opties voor \(rail.title.lowercased())")
                }
              }.padding(.top, 14).textCase(nil)
            }
          }
          if rails.isEmpty && !loading && error == nil {
            ContentUnavailableView(
              "Nog geen selectie", systemImage: "water.waves",
              description: Text("Kies een ander onderwerp of bekijk alle onderwerpen.")
            )
            .editorialRow()
          }
        } else {
          Section {
            ForEach(visible) { item in card(item) }
            if visible.isEmpty && !loading {
              ContentUnavailableView {
                Label("Geen resultaten", systemImage: "line.3.horizontal.decrease")
              } description: {
                Text("Probeer een ander onderwerp of verruim je filters.")
              } actions: {
                Button("Wis filters") { resetFilters() }
              }.editorialRow()
            }
            if more {
              Button("Meer ophalen") { Task { await loadMore() } }.disabled(loading).editorialRow()
            }
          } header: {
            SectionHeading(title: "Je selectie", count: visible.count)
          }
        }
        if podcastsOnly { generatedSection }
      }
    }
    .listStyle(.plain).scrollContentBackground(.hidden).background(Brand.paper)
    .navigationTitle(podcastsOnly ? "Luisteren" : "Stroom").navigationBarTitleDisplayMode(.inline)
    .toolbar {
      ToolbarItem(placement: .principal) {
        Text("Stroom").font(Brand.display(25, relativeTo: .title2)).italic().foregroundStyle(
          Brand.ink)
      }
      ToolbarItem(placement: .topBarLeading) {
        NavigationLink {
          SubmitView()
        } label: {
          Image(systemName: "plus").frame(minWidth: 44, minHeight: 44)
        }
        .accessibilityLabel("Content insturen")
      }
      ToolbarItem(placement: .topBarTrailing) {
        Button {
          showFilters = true
        } label: {
          Image(
            systemName: activeFilters > 0
              ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease"
          )
          .frame(minWidth: 44, minHeight: 44)
        }.accessibilityLabel("Filters").accessibilityValue("\(activeFilters) actief")
      }
    }
    .searchable(text: $query, prompt: "Zoek in Stroom")
    .refreshable { await reload() }
    .task(id: selection + "|" + String(describing: store.lastSync)) { await loadTopic() }
    .sheet(isPresented: $showFilters) {
      NavigationStack {
        Form {
          Section("Verfijn je selectie") { filters }
          Section { Button("Wis alle filters") { resetFilters() } }
        }.scrollContentBackground(.hidden).background(Brand.paper)
          .navigationTitle("Filters").navigationBarTitleDisplayMode(.inline)
          .toolbar {
            ToolbarItem(placement: .confirmationAction) { Button("Gereed") { showFilters = false } }
          }
      }.presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
    }
    .confirmationDialog(
      "Deze selectie archiveren?",
      isPresented: Binding(get: { archiveTarget != nil }, set: { if !$0 { archiveTarget = nil } }),
      presenting: archiveTarget
    ) { rail in
      Button("Archiveer \(rail.items.count) \(rail.title.lowercased())", role: .destructive) {
        Task {
          archiving = true
          let succeeded = await store.archiveRail(rail.items)
          if succeeded { await loadTopic() }
          archiving = false
        }
      }
      Button("Annuleer", role: .cancel) {}
    } message: { _ in
      Text(
        "De zichtbare selectie wordt gearchiveerd. Daarna haalt Stroom nieuwe items op. Bij een fout stopt de actie; al gearchiveerde items blijven in het archief."
      )
    }
  }
  @ViewBuilder var digestLinks: some View {
    DigestPreview(topic: store.selectedTopic, window: "daily")
    DigestPreview(topic: store.selectedTopic, window: "weekly")
  }
  var topicChips: some View {
    ScrollView(.horizontal, showsIndicators: false) {
      HStack(spacing: 8) {
        ForEach(store.topics) { topic in topicButton(topic.name, slug: topic.slug) }
        topicButton("Alle onderwerpen", slug: "__all__")
      }
    }
  }
  func topicButton(_ name: String, slug: String) -> some View {
    StroomChip(title: name, selected: store.selectedTopic == slug) { store.selectedTopic = slug }
      .accessibilityIdentifier("topic-\(slug)")
  }
  @ViewBuilder var filters: some View {
    Picker("Status", selection: $filter) {
      Text("Alles").tag("all")
      Text("Bewaard").tag("saved")
      Text("Samengevat").tag("summarized")
      Text("Gepland").tag("scheduled")
      Text("Archief").tag("archived")
      Text("Inbox").tag("inbox")
    }
    Picker("Periode", selection: $window) {
      Text("Alle tijd").tag("all")
      Text("24 uur").tag("24h")
      Text("7 dagen").tag("7d")
      Text("30 dagen").tag("30d")
    }
    if !podcastsOnly {
      Picker("Soort", selection: $format) {
        Text("Alles").tag("all")
        Text("Artikelen").tag("article")
        Text("Podcasts").tag("podcast")
        Text("Video’s").tag("video")
      }
    }
  }
  func resetFilters() {
    filter = "all"
    window = "all"
    format = "all"
  }
  func card(_ item: FeedItem) -> some View {
    FeedCard(item: item).editorialRow().stroomActions(item)
  }
  @ViewBuilder var generatedSection: some View {
    Section("Door Stroom gemaakt") {
      if let message = store.jobsError { Text(message).font(.caption).foregroundStyle(.secondary) }
      ForEach(store.jobs.prefix(10)) { job in
        VStack(alignment: .leading, spacing: 12) {
          Text(String(job.text.prefix(120))).font(.subheadline).lineLimit(2)
          if let track = job.track {
            TrackActions(track: track)
          } else {
            Label(
              job.status == "failed" ? (job.message ?? "Maken mislukt") : "Wordt gemaakt…",
              systemImage: job.status == "failed" ? "exclamationmark.circle" : "clock"
            ).font(.caption)
          }
        }
      }
      if store.jobs.isEmpty && store.jobsError == nil {
        Text("Je zelfgemaakte podcasts verschijnen hier.").foregroundStyle(.secondary)
      }
    }
  }
  func reload() async {
    await store.refresh()
    await loadTopic()
  }
  func loadTopic() async {
    guard !store.selectedTopic.isEmpty else { return }
    let ticket = selection
    let request = UUID()
    requestID = request
    loading = true
    error = nil
    if loadedSelection != ticket {
      filtered = []
      more = false
    }
    defer { if request == requestID { loading = false } }
    if store.demo {
      filtered = store.items.filter {
        (!podcastsOnly || $0.isPodcast) && (format == "all" || $0.format == format)
      }
      loadedSelection = ticket
      return
    }
    guard let api = store.api else { return }
    if store.offline && store.selectedTopic == "__all__" && filter == "all"
      && window == "all" && format == "all" && filtered.isEmpty
    {
      filtered = store.items.filter { !podcastsOnly || $0.isPodcast }
    }
    do {
      if isRanked {
        let topic: HuygensTopic = try await api.request("huygens/\(store.selectedTopic)")
        try Task.checkCancellation()
        guard ticket == selection && request == requestID else { return }
        store.remember(topic)
      } else {
        let rows = try await fetch(api: api, offset: 0)
        try Task.checkCancellation()
        guard ticket == selection && request == requestID else { return }
        filtered = rows
        offset = rows.count
        more = rows.count == 100
      }
      loadedSelection = ticket
    } catch {
      if !Task.isCancelled && ticket == selection && request == requestID {
        self.error = error.localizedDescription
      }
    }
  }
  func fetch(api: APIClient, offset: Int) async throws -> [FeedItem] {
    try await api.items(
      topic: store.selectedTopic == "__all__" ? nil : store.selectedTopic, offset: offset,
      filter: filter, window: window,
      format: podcastsOnly ? "podcast" : (format == "all" ? nil : format))
  }
  func loadMore() async {
    guard let api = store.api, !loading else { return }
    let ticket = selection
    let request = UUID()
    requestID = request
    loading = true
    defer { if request == requestID { loading = false } }
    do {
      let rows = try await fetch(api: api, offset: offset)
      guard ticket == selection && request == requestID else { return }
      let existing = Set(filtered.map(\.id))
      filtered += rows.filter { !existing.contains($0.id) }
      offset += rows.count
      more = rows.count == 100
    } catch {
      if ticket == selection && request == requestID { self.error = error.localizedDescription }
    }
  }
}
