import SwiftUI

struct DigestRun: Decodable, Identifiable {
  let id: String
  let generatedAt: String
  let markdown: String
  let model: String?
}

struct DigestPreview: View {
  @EnvironmentObject var store: AppStore
  let topic: String
  let window: String
  let open: () -> Void
  @State private var digest: Digest?
  @State private var error: String?
  @State private var loading = true
  var body: some View {
    Button(action: open) {
      VStack(alignment: .leading, spacing: 10) {
        HStack {
          Image(systemName: window == "daily" ? "sun.max" : "calendar")
          Spacer()
          Image(systemName: "arrow.up.right").font(.caption)
        }.foregroundStyle(Brand.blue).accessibilityHidden(true)
        Text(window == "daily" ? "Vandaag" : "Deze week")
          .font(Brand.editorial(22)).foregroundStyle(Brand.ink)
        if let markdown = digest?.markdown, !ContentText.excerpt(markdown).isEmpty {
          Text(ContentText.excerpt(markdown)).font(.caption).foregroundStyle(Brand.muted)
            .lineLimit(3).multilineTextAlignment(.leading)
            .accessibilityIdentifier("digest-excerpt-\(window)")
          if digest?.isGenerating == true {
            Text("Wordt vernieuwd…").font(.caption).foregroundStyle(Brand.muted)
          }
        } else {
          Text(
            digest?.isGenerating == true
              ? "Wordt gemaakt…"
              : (loading
                ? "Ophalen…" : (error != nil ? "Ophalen mislukt · open" : "Maak een overzicht"))
          )
          .font(.caption).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
        }
      }.frame(minWidth: 120, maxWidth: .infinity, alignment: .leading)
        .padding(16).background(Brand.card, in: RoundedRectangle(cornerRadius: 18))
    }.buttonStyle(.plain).accessibilityHint(
      "Open het \(window == "daily" ? "dagoverzicht" : "weekoverzicht")"
    )
    .accessibilityIdentifier("digest-\(window)")
    .task(id: "\(topic)|\(window)") {
      digest = nil
      error = nil
      loading = true
      if store.demo {
        digest = demoDigest(window)
        loading = false
        return
      }
      guard let api = store.api else {
        loading = false
        return
      }
      repeat {
        do {
          let value = try await api.digest(topic: topic, window: window)
          try Task.checkCancellation()
          digest = value
          error = nil
        } catch {
          if !Task.isCancelled { self.error = "Open het overzicht om het op te halen of te maken." }
        }
        loading = false
        if digest?.isGenerating != true || Task.isCancelled { return }
        do { try await Task.sleep(for: .seconds(8)) } catch { return }
      } while !Task.isCancelled
    }
  }
}
func demoDigest(_ window: String) -> Digest {
  Digest(
    markdown: window == "daily"
      ? "Vandaag draait het om betere vragen. AI als denkpartner, aandacht als vaardigheid: deze bronnen helpen je het grotere plaatje te zien."
      : "Deze week verbinden wetenschap en technologie zich rond één vraag: hoe houden we ruimte voor nieuwsgierigheid?",
    generatedAt: "2026-10-27T08:00:00Z", isGenerating: false)
}
struct DigestView: View {
  @EnvironmentObject var store: AppStore
  @Environment(\.dismiss) var dismiss
  let topic: String
  @State private var window: String
  @State private var digest: Digest?
  @State private var history: [DigestRun] = []
  @State private var error: String?
  @State private var loading = false
  @State private var generating = false
  init(topic: String, initialWindow: String = "daily") {
    self.topic = topic
    _window = State(initialValue: initialWindow)
  }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 24) {
        Picker("Periode", selection: $window) {
          Text("Dag").tag("daily")
          Text("Week").tag("weekly")
        }.pickerStyle(.segmented)
        Text("Het grotere plaatje").font(Brand.display())
        if let date = digest?.generatedAt.flatMap(StroomDate.parse) {
          Text(date.formatted(date: .abbreviated, time: .shortened)).font(.caption).foregroundStyle(
            .secondary)
        }
        if digest?.isGenerating == true { Label("Wordt gemaakt…", systemImage: "clock") }
        if let markdown = digest?.markdown {
          MarkdownBody(text: markdown)
        } else if loading {
          ProgressView()
        } else if digest?.isGenerating != true {
          Text("Er is nog geen overzicht voor deze periode.").foregroundStyle(.secondary)
        }
        if let error { ErrorNotice(message: error) { await load() } }
        Button(
          digest?.markdown == nil ? "Maak overzicht" : "Opnieuw genereren", systemImage: "sparkles"
        ) { Task { await generate() } }
        .disabled(generating || digest?.isGenerating == true || store.demo)
        if generating { ProgressView("Overzicht aanvragen…") }
        ForEach(history) { run in
          DisclosureGroup(
            "\(StroomDate.parse(run.generatedAt)?.formatted(date: .abbreviated, time: .shortened) ?? run.generatedAt) · \(run.model ?? "")"
          ) { MarkdownBody(text: run.markdown).padding(.top) }
        }
      }.padding(22)
    }.background(Brand.paper).navigationTitle("Overzichten").navigationBarTitleDisplayMode(.inline)
      .task(id: window) {
        digest = nil
        history = []
        await load()
      }
      .task(id: digest?.isGenerating == true) {
        while digest?.isGenerating == true && !Task.isCancelled {
          do {
            try await Task.sleep(for: .seconds(8))
            try Task.checkCancellation()
          } catch { return }
          await load()
        }
      }.refreshable { await load() }
  }
  func load() async {
    if store.demo {
      digest = demoDigest(window)
      return
    }
    guard let api = store.api else { return }
    let ticket = window
    loading = true
    error = nil
    defer { if ticket == window { loading = false } }
    do {
      let value = try await api.digest(topic: topic, window: ticket)
      try Task.checkCancellation()
      guard ticket == window else { return }
      digest = value
    } catch { if !Task.isCancelled && ticket == window { self.error = error.localizedDescription } }
    do {
      let rows: [DigestRun] = try await api.request(
        "huygens/\(topic)/digest/history", query: [.init(name: "window", value: ticket)])
      try Task.checkCancellation()
      if ticket == window { history = rows }
    } catch { if !Task.isCancelled && ticket == window { self.error = error.localizedDescription } }
  }
  func generate() async {
    guard let api = store.api else { return }
    let ticket = window
    generating = true
    error = nil
    defer { generating = false }
    do {
      let parameters = try await store.modelQuery(ticket == "weekly" ? "digest_weekly" : "digest")
      let value: Digest = try await api.request(
        "huygens/\(topic)/digest", query: parameters + [.init(name: "window", value: ticket)],
        method: "POST")
      if ticket == window { digest = value }
    } catch { if ticket == window { self.error = error.localizedDescription } }
  }
}
