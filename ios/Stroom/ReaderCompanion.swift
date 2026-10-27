import SwiftUI

struct ItemLessonsView: View {
  @EnvironmentObject var store: AppStore
  let id: String
  @State private var lessons: [Lesson] = []
  @State private var loaded = false
  @State private var error: String?
  @State private var busy: String?
  var body: some View {
    VStack(alignment: .leading, spacing: 24) {
      if let error { ErrorNotice(message: error) { await load() } }
      if !loaded && error == nil { ProgressView() }
      if loaded && lessons.isEmpty {
        Text("Nog geen lessen bij dit item. Maak eerst een samenvatting.").foregroundStyle(
          .secondary)
      }
      ForEach(lessons) { lesson in
        VStack(alignment: .leading, spacing: 14) {
          Text(lesson.title).font(.system(.title3, design: .serif).weight(.semibold))
          MarkdownBody(text: lesson.body)
          HStack(spacing: 24) {
            Button(lesson.rating == 1 ? "Nuttig ✓" : "Nuttig", systemImage: "hand.thumbsup") {
              Task { await rate(lesson, value: 1) }
            }
            Button(
              lesson.rating == -1 ? "Niet nuttig ✓" : "Niet nuttig", systemImage: "hand.thumbsdown"
            ) { Task { await rate(lesson, value: -1) } }
          }.font(.callout).frame(minHeight: 44).disabled(busy != nil || store.demo)
          if let expansion = lesson.expansion {
            DisclosureGroup("Verdieping") { MarkdownBody(text: expansion) }
          }
          Divider()
        }
      }
    }.task { await load() }
  }
  func load() async {
    guard !store.demo, let api = store.api else {
      loaded = true
      return
    }
    do {
      lessons = try await api.request("huygens/items/\(id)/lessons")
      loaded = true
      error = nil
    } catch { self.error = error.localizedDescription }
  }
  func rate(_ lesson: Lesson, value: Int) async {
    guard let api = store.api else { return }
    busy = lesson.id
    defer { busy = nil }
    do {
      let updated: Lesson = try await api.request(
        "lessons/\(lesson.id)/rate", method: "POST",
        body: ["rating": lesson.rating == value ? NSNull() : value as Any])
      if let i = lessons.firstIndex(where: { $0.id == updated.id }) { lessons[i] = updated }
      error = nil
    } catch { self.error = error.localizedDescription }
  }
}
struct ItemQuestionsView: View {
  @EnvironmentObject var store: AppStore
  let id: String
  @State private var question = ""
  @State private var history: [ItemQuestion] = []
  @State private var error: String?
  @State private var asking = false
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text("Vraag door op de bron, samenvatting en lessen.").foregroundStyle(.secondary)
      TextField("Wat zijn de kernargumenten?", text: $question, axis: .vertical).lineLimit(3...8)
        .padding(14).background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
        .onChange(of: question) { _, value in
          if value.count > 500 { question = String(value.prefix(500)) }
        }
      Button(
        asking ? "Antwoord wordt gemaakt…" : "Stel je vraag",
        systemImage: "bubble.left.and.text.bubble.right"
      ) { Task { await ask() } }
      .disabled(
        asking || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.demo)
      if asking { ProgressView() }
      if let error { Text(error).font(.callout).foregroundStyle(.red) }
      ForEach(Array(history.enumerated()), id: \.offset) { _, answer in
        VStack(alignment: .leading, spacing: 12) {
          Text(answer.question).font(.headline)
          MarkdownBody(text: answer.answer)
          Text("AI-antwoord · \(answer.model ?? "Stroom")").font(.caption).foregroundStyle(
            .secondary)
          Divider()
        }
      }
    }.task {
      guard !store.demo, let api = store.api else { return }
      do { history = try await api.request("huygens/items/\(id)/questions") } catch {
        self.error = error.localizedDescription
      }
    }
  }
  func ask() async {
    guard let api = store.api else { return }
    asking = true
    error = nil
    defer { asking = false }
    do {
      let answer: ItemQuestion = try await api.request(
        "huygens/items/\(id)/ask", method: "POST",
        body: ["question": question.trimmingCharacters(in: .whitespacesAndNewlines)])
      history.insert(answer, at: 0)
      question = ""
    } catch { self.error = error.localizedDescription }
  }
}
struct SourceScreen: View {
  @EnvironmentObject var store: AppStore
  let id: String
  let name: String
  @State private var items: [FeedItem] = []
  @State private var error: String?
  @State private var more = true
  @State private var loading = false
  var body: some View {
    List {
      if let error { ErrorNotice(message: error) { await load(reset: true) } }
      ForEach(items.map(store.current).filter { $0.status != "archived" }) { item in
        FeedCard(item: item).listRowInsets(EdgeInsets()).stroomActions(item)
      }
      if more { Button("Meer ophalen") { Task { await load(reset: false) } }.disabled(loading) }
    }.navigationTitle(name).navigationBarTitleDisplayMode(.inline).scrollContentBackground(.hidden)
      .background(Brand.paper)
      .task { await load(reset: true) }.refreshable { await load(reset: true) }
  }
  func load(reset: Bool) async {
    guard let api = store.api else { return }
    loading = true
    defer { loading = false }
    do {
      let rows = try await api.items(offset: reset ? 0 : items.count, window: "all", source: id)
      items = reset ? rows : items + rows
      more = rows.count == 100
      error = nil
    } catch { self.error = error.localizedDescription }
  }
}
