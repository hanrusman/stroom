import SwiftUI

struct TipPage: Decodable {
  let total: Int
  let categories: [String: Int]
  let works: [Tip]
}
struct Tip: Decodable, Identifiable {
  let title: String
  let titleKey: String
  let category: String
  let creator: String?
  let episodes: Int
  let blurb: String?
  let sources: [String]
  var id: String { category + "|" + titleKey }
}
struct TipMentions: Decodable {
  let mentions: [TipMention]
}
struct TipMention: Decodable, Identifiable {
  let itemId: String
  let source: String
  let episode: String?
  let quote: String?
  let why: String?
  let by: String?
  let published: String?
  var id: String { itemId }
}
func tipCategory(_ value: String) -> String {
  [
    "book": "Boeken", "film": "Films", "movie": "Films", "series": "Series", "tv": "Series",
    "podcast": "Podcasts", "article": "Artikelen", "music": "Muziek", "software": "Software",
    "newsletter": "Nieuwsbrieven",
  ][value] ?? value.capitalized
}
struct TipsView: View {
  @EnvironmentObject var store: AppStore
  @State private var query = ""
  @State private var category = ""
  @State private var sort = "score"
  @State private var strongOnly = false
  @State private var tips: [Tip] = []
  @State private var categories: [String: Int] = [:]
  @State private var total = 0
  @State private var loading = false
  @State private var error: String?
  var selection: String { "\(query)|\(category)|\(sort)|\(strongOnly)" }
  var body: some View {
    List {
      Section {
        Text("Aanbevolen door de stemmen die je volgt.").font(.system(.title2, design: .serif))
        Picker("Categorie", selection: $category) {
          Text("Alles").tag("")
          ForEach(categories.keys.sorted(), id: \.self) {
            Text("\(tipCategory($0)) · \(categories[$0] ?? 0)").tag($0)
          }
        }
        Picker("Volgorde", selection: $sort) {
          Text("Beste tips").tag("score")
          Text("Meest genoemd").tag("episodes")
          Text("Recent").tag("recent")
          Text("Titel").tag("title")
        }
        Toggle("Alleen sterke aanbevelingen", isOn: $strongOnly)
      }
      if loading { ProgressView() }
      if let error { ErrorNotice(message: error) { await load(reset: true) } }
      ForEach(tips) { tip in
        NavigationLink {
          TipDetailView(tip: tip)
        } label: {
          VStack(alignment: .leading, spacing: 10) {
            Text(tipCategory(tip.category)).font(.caption).foregroundStyle(Brand.blue)
            Text(tip.title).font(.system(.title3, design: .serif).weight(.medium))
            if let creator = tip.creator { Text(creator).font(.subheadline) }
            if let blurb = tip.blurb {
              Text(ContentText.excerpt(blurb)).font(.subheadline).foregroundStyle(.secondary)
                .lineLimit(3)
            }
            Text("\(tip.episodes) afleveringen · \(tip.sources.joined(separator: ", "))").font(
              .caption
            ).foregroundStyle(.secondary)
          }.padding(.vertical, 8)
        }
      }
      if !loading && tips.isEmpty && error == nil {
        ContentUnavailableView(
          "Nog geen tips", systemImage: "lightbulb",
          description: Text("Kies een andere categorie of zoekterm."))
      }
      if tips.count < total {
        Button("Meer tips") { Task { await load(reset: false) } }.disabled(loading)
      }
    }.navigationTitle("Tips").searchable(text: $query, prompt: "Titel, maker of bron")
      .scrollContentBackground(.hidden).background(Brand.paper)
      .task(id: selection) {
        do {
          try await Task.sleep(for: .milliseconds(250))
          try Task.checkCancellation()
        } catch { return }
        await load(reset: true)
      }.refreshable { await load(reset: true) }
  }
  func load(reset: Bool) async {
    let ticket = selection
    loading = true
    error = nil
    if reset { tips = [] }
    defer { if ticket == selection { loading = false } }
    if store.demo {
      categories = ["book": 1]
      tips = [
        Tip(
          title: "Een wereld vol vragen", titleKey: "wereld-vragen", category: "book",
          creator: "Voorbeeldmaker", episodes: 2,
          blurb: "Een uitnodiging om anders naar dagelijkse dingen te kijken.",
          sources: ["De Technoloog"])
      ]
      total = 1
      return
    }
    guard let api = store.api else { return }
    do {
      var parameters: [URLQueryItem] = [
        .init(name: "limit", value: "50"),
        .init(name: "offset", value: String(reset ? 0 : tips.count)),
        .init(name: "sort", value: sort), .init(name: "strong_only", value: String(strongOnly)),
      ]
      if !category.isEmpty { parameters.append(.init(name: "category", value: category)) }
      if !query.isEmpty { parameters.append(.init(name: "q", value: query)) }
      let page: TipPage = try await api.request("tips", query: parameters)
      try Task.checkCancellation()
      guard ticket == selection else { return }
      let ids = Set(tips.map(\.id))
      tips += page.works.filter { !ids.contains($0.id) }
      categories = page.categories
      total = page.total
    } catch {
      if !Task.isCancelled && ticket == selection { self.error = error.localizedDescription }
    }
  }
}
struct TipDetailView: View {
  @EnvironmentObject var store: AppStore
  let tip: Tip
  @State private var mentions: [TipMention] = []
  @State private var error: String?
  @State private var loaded = false
  var body: some View {
    List {
      Section {
        Text(tip.title).font(.system(.largeTitle, design: .serif))
        if let creator = tip.creator { Text(creator).foregroundStyle(.secondary) }
      }
      if let error { ErrorNotice(message: error) { await load() } }
      if !loaded { ProgressView() }
      ForEach(mentions) { mention in
        Section(mention.source) {
          if let quote = mention.quote {
            Text("“\(ContentText.excerpt(quote))”").font(.system(.body, design: .serif).italic())
          }
          if let why = mention.why { Text(ContentText.excerpt(why)) }
          if let by = mention.by { Text(by).font(.caption).foregroundStyle(.secondary) }
          Button(mention.episode ?? "Open aflevering", systemImage: "arrow.up.right") {
            store.openItemID = mention.itemId
          }
        }
      }
    }.navigationTitle("Aanbevolen").navigationBarTitleDisplayMode(.inline)
      .scrollContentBackground(.hidden).background(Brand.paper).task { await load() }
  }
  func load() async {
    if store.demo {
      mentions = [
        TipMention(
          itemId: "demo-1", source: "De Technoloog",
          episode: "Wat verandert er als AI echt met je meedenkt?",
          quote: "Een goede vraag is het begin van een nieuw inzicht.",
          why: "Helpt bij het onderzoeken van je aannames.", by: "De gast", published: nil)
      ]
      loaded = true
      return
    }
    guard let api = store.api else { return }
    do {
      let result: TipMentions = try await api.request(
        "tips/mentions",
        query: [
          .init(name: "title_key", value: tip.titleKey),
          .init(name: "category", value: tip.category),
        ])
      mentions = result.mentions
      loaded = true
      error = nil
    } catch {
      self.error = error.localizedDescription
      loaded = true
    }
  }
}
struct AllLessonsView: View {
  @EnvironmentObject var store: AppStore
  @State private var lessons: [Lesson] = []
  @State private var rating = 1
  @State private var loading = false
  @State private var error: String?
  var body: some View {
    List {
      Picker("Beoordeling", selection: $rating) {
        Text("Nuttig").tag(1)
        Text("Alles").tag(0)
        Text("Niet nuttig").tag(-1)
      }.pickerStyle(.segmented)
      if loading { ProgressView() }
      if let error { ErrorNotice(message: error) { await load() } }
      ForEach($lessons) { $lesson in
        VStack(alignment: .leading, spacing: 12) {
          if let source = lesson.sourceName {
            Text(source.uppercased()).font(.caption).foregroundStyle(Brand.blue)
          }
          LessonCard(lesson: $lesson)
          if let id = lesson.itemId {
            Button(lesson.itemTitle ?? "Open bron", systemImage: "arrow.up.right") {
              store.openItemID = id
            }
          }
        }.padding(.vertical, 10)
      }
      if !loading && lessons.isEmpty && error == nil {
        ContentUnavailableView(
          "Nog geen lessen", systemImage: "book",
          description: Text("Destilleer lessen in een artikel en geef aan welke je nuttig vindt."))
      }
      if let url = stroomURL(server: store.server, query: ["lessons": "1"]) {
        NavigationLink("Lesoverzichten en verdere opties") {
          StroomWebView(url: url).navigationTitle("Lesoverzichten")
        }
      }
      if lessons.count == 1000 {
        Text("De meest recente 1.000 lessen worden getoond.").font(.caption).foregroundStyle(
          .secondary)
      }
    }.navigationTitle("Lessen").scrollContentBackground(.hidden).background(Brand.paper)
      .task(id: rating) { await load() }.refreshable { await load() }
  }
  func load() async {
    loading = true
    error = nil
    defer { if !Task.isCancelled { loading = false } }
    if store.demo {
      lessons = [
        Lesson(
          id: "lesson-demo", title: "Stel eerst een betere vraag",
          body: "Onderzoek je aannames voordat je een oplossing kiest.", rating: 1,
          sourceName: "De Technoloog", itemTitle: "Wat verandert er als AI echt met je meedenkt?",
          itemId: "demo-1")
      ]
      return
    }
    guard let api = store.api else { return }
    do {
      let values: [Lesson] = try await api.request(
        "lessons",
        query: [.init(name: "rating", value: String(rating)), .init(name: "limit", value: "1000")])
      try Task.checkCancellation()
      lessons = values
    } catch { if !Task.isCancelled { self.error = error.localizedDescription } }
  }
}
