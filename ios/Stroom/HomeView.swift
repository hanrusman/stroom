import SwiftUI

struct FeedScreen: View {
  @EnvironmentObject var store: AppStore
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

  var isRanked: Bool {
    store.selectedTopic != "__all__" && filter == "all" && window == "all" && format == "all"
  }
  var selection: String { "\(store.selectedTopic)|\(filter)|\(window)|\(format)" }
  var rails: [HuygensRail] {
    (store.topicFeeds[store.selectedTopic]?.orderedRails ?? []).filter {
      !podcastsOnly || $0.format == "podcast"
    }
  }
  var visible: [FeedItem] {
    filtered.map(store.current).filter {
      (filter == "archived" ? $0.status == "archived" : $0.status != "archived")
        && (filter != "saved" || $0.status == "pinned")
        && (filter != "scheduled" || $0.scheduledFor != nil)
    }
  }
  var body: some View {
    List {
      Section {
        Text(podcastsOnly ? "Goed gezelschap voor onderweg." : "Volg je nieuwsgierigheid.")
          .font(.system(.title2, design: .serif).weight(.medium))
        if store.demo {
          Text("Voorbeeldweergave · geen live gegevens").font(.caption).foregroundStyle(.secondary)
        }
        if store.offline {
          Label("Offline · laatst opgehaalde inhoud", systemImage: "wifi.slash").font(.callout)
        }
        topicChips
        Button {
          showFilters.toggle()
        } label: {
          Label(
            showFilters
              ? "Filters verbergen"
              : (isRanked ? "Filter op status of periode" : "Filters aanpassen"),
            systemImage: "line.3.horizontal.decrease")
        }.font(.callout)
        if showFilters { filters }
        if let error { ErrorNotice(message: error) { await reload() } }
      }.listRowBackground(Color.clear)
      if !query.trimmingCharacters(in: .whitespaces).isEmpty {
        SearchResultsView(query: query, podcastsOnly: podcastsOnly)
      } else {
        if !podcastsOnly && store.selectedTopic != "__all__" && !store.selectedTopic.isEmpty {
          Section {
            DigestPreview(topic: store.selectedTopic, window: "daily")
            DigestPreview(topic: store.selectedTopic, window: "weekly")
          }.listRowBackground(Brand.card)
        }
        if loading { ProgressView().frame(maxWidth: .infinity) }
        if isRanked {
          ForEach(rails) { rail in
            Section(rail.title) {
              let rows = rail.items.map(store.current).filter { $0.status != "archived" }
              if rows.isEmpty {
                Text("Geen \(rail.title.lowercased()) in dit onderwerp.").font(.callout)
                  .foregroundStyle(.secondary)
              }
              ForEach(rows) { item in card(item) }
            }
          }
        } else {
          Section("Gefilterde selectie") {
            ForEach(visible) { item in card(item) }
            if visible.isEmpty && !loading {
              ContentUnavailableView(
                "Nog niets hier", systemImage: "water.waves",
                description: Text("Kies een ander onderwerp of filter."))
            }
            if more { Button("Meer ophalen") { Task { await loadMore() } }.disabled(loading) }
          }
        }
        if podcastsOnly { generatedSection }
      }
    }
    .listStyle(.insetGrouped).scrollContentBackground(.hidden).background(Brand.paper)
    .navigationTitle(podcastsOnly ? "Luisteren" : "Stroom").navigationBarTitleDisplayMode(.inline)
    .searchable(text: $query, prompt: "Zoek in Stroom")
    .refreshable { await reload() }
    .task(id: selection) { await loadTopic() }
  }
  var topicChips: some View {
    ScrollView(.horizontal, showsIndicators: false) {
      HStack(spacing: 8) {
        ForEach(store.topics) { topic in topicButton(topic.name, slug: topic.slug) }
        topicButton("Alle onderwerpen · chronologisch", slug: "__all__")
      }
    }.listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
  }
  func topicButton(_ name: String, slug: String) -> some View {
    Button(name) { store.selectedTopic = slug }
      .font(.subheadline.weight(.medium)).padding(.horizontal, 14).frame(minHeight: 44)
      .background(
        store.selectedTopic == slug ? Brand.blue.opacity(0.14) : Color.secondary.opacity(0.06),
        in: Capsule()
      )
      .accessibilityIdentifier("topic-\(slug)")
      .accessibilityAddTraits(store.selectedTopic == slug ? .isSelected : [])
      .buttonStyle(.plain)
  }
  var filters: some View {
    VStack {
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
  }
  func card(_ item: FeedItem) -> some View {
    FeedCard(item: item).listRowInsets(EdgeInsets()).listRowBackground(Color.clear).stroomActions(
      item)
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
    loading = true
    error = nil
    if loadedSelection != ticket {
      filtered = []
      more = false
    }
    defer { if ticket == selection { loading = false } }
    if store.demo {
      filtered = store.items.filter {
        (!podcastsOnly || $0.isPodcast) && (format == "all" || $0.format == format)
      }
      loadedSelection = ticket
      return
    }
    guard let api = store.api else { return }
    do {
      if isRanked {
        let topic: HuygensTopic = try await api.request("huygens/\(store.selectedTopic)")
        try Task.checkCancellation()
        guard ticket == selection else { return }
        store.remember(topic)
      } else {
        let rows = try await fetch(api: api, offset: 0)
        try Task.checkCancellation()
        guard ticket == selection else { return }
        filtered = rows
        offset = rows.count
        more = rows.count == 100
      }
      loadedSelection = ticket
    } catch {
      if !Task.isCancelled && ticket == selection { self.error = error.localizedDescription }
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
    loading = true
    defer { if ticket == selection { loading = false } }
    do {
      let rows = try await fetch(api: api, offset: offset)
      guard ticket == selection else { return }
      let existing = Set(filtered.map(\.id))
      filtered += rows.filter { !existing.contains($0.id) }
      offset += rows.count
      more = rows.count == 100
    } catch { if ticket == selection { self.error = error.localizedDescription } }
  }
}
