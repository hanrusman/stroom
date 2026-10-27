import SwiftUI

struct ItemLessonsView: View {
  @EnvironmentObject var store: AppStore
  let id: String
  @State private var lessons: [Lesson] = []
  @State private var loaded = false
  @State private var error: String?
  @State private var distilling = false
  var isDistilling: Bool { distilling || store.aiTasks.contains("distill-\(id)") }
  var body: some View {
    VStack(alignment: .leading, spacing: 24) {
      if let error { ErrorNotice(message: error) { await load() } }
      if !loaded && error == nil { ProgressView() }
      if loaded && lessons.isEmpty {
        Text("Nog geen lessen bij dit item. Maak eerst een samenvatting.").foregroundStyle(
          .secondary)
      }
      Button(lessons.isEmpty ? "Destilleer kernlessen" : "Meer kernlessen", systemImage: "sparkles")
      { Task { await distill() } }
      .disabled(isDistilling || store.demo)
      if isDistilling { ProgressView("Lessen destilleren… Dit kan enkele minuten duren.") }
      ForEach($lessons) { $lesson in LessonCard(lesson: $lesson) }
    }.task(id: isDistilling) { if !isDistilling { await load() } }
  }
  func load() async {
    guard !store.demo, let api = store.api else {
      if ProcessInfo.processInfo.arguments.contains("--companion-fixtures") {
        lessons = [
          Lesson(
            id: "lesson-demo", title: "Stel eerst een betere vraag",
            body:
              "Een denkpartner helpt je aannames te onderzoeken voordat je een oplossing kiest.",
            rating: 1)
        ]
      }
      loaded = true
      return
    }
    do {
      lessons = try await api.request("huygens/items/\(id)/lessons")
      loaded = true
      error = nil
    } catch { self.error = error.localizedDescription }
  }
  func distill() async {
    guard let api = store.api else { return }
    let key = "distill-\(id)"
    guard !store.aiTasks.contains(key) else { return }
    store.aiTasks.insert(key)
    distilling = true
    error = nil
    defer {
      distilling = false
      store.aiTasks.remove(key)
    }
    do {
      let query = try await store.modelQuery("distill")
      lessons = try await api.request(
        "huygens/items/\(id)/lessons/distill", query: query, method: "POST")
      loaded = true
    } catch {
      self.error =
        "Destilleren niet afgerond: \(error.localizedDescription). Vernieuw de lessen voordat je opnieuw probeert."
    }
  }
}
struct LessonCard: View {
  @EnvironmentObject var store: AppStore
  @Binding var lesson: Lesson
  @State private var busy: String?
  @State private var error: String?
  @State private var expansionOpen = false
  var processing: Bool { busy != nil || store.aiTasks.contains(lesson.id) }
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text(lesson.title).font(.system(.title3, design: .serif).weight(.semibold))
      MarkdownBody(text: lesson.body)
      HStack(spacing: 24) {
        Button(lesson.rating == 1 ? "Nuttig ✓" : "Nuttig", systemImage: "hand.thumbsup") {
          Task { await rate(1) }
        }
        Button(
          lesson.rating == -1 ? "Niet nuttig ✓" : "Niet nuttig", systemImage: "hand.thumbsdown"
        ) { Task { await rate(-1) } }
      }.font(.callout).frame(minHeight: 44).disabled(processing || store.demo)
      if let expansion = lesson.expansion {
        DisclosureGroup("Verdieping", isExpanded: $expansionOpen) { MarkdownBody(text: expansion) }
      } else {
        Button("Verdiep deze les", systemImage: "text.magnifyingglass") { Task { await expand() } }
          .disabled(processing || store.demo)
      }
      Button(
        lesson.vikunjaTaskId == nil ? "Naar Vikunja" : "In Vikunja ✓", systemImage: "checklist"
      ) { Task { await send() } }
      .disabled(processing || lesson.vikunjaTaskId != nil || store.demo)
      if let busy { ProgressView(busy) }
      if let error { Text(error).font(.callout).foregroundStyle(.red) }
      Divider()
    }
  }
  func rate(_ value: Int) async {
    guard let api = store.api else { return }
    busy = "Beoordeling opslaan…"
    error = nil
    defer { busy = nil }
    do {
      lesson = try await api.request(
        "lessons/\(lesson.id)/rate", method: "POST",
        body: ["rating": lesson.rating == value ? NSNull() : value as Any])
    } catch { self.error = error.localizedDescription }
  }
  func expand() async {
    guard let api = store.api else { return }
    guard !store.aiTasks.contains(lesson.id) else { return }
    let key = lesson.id
    store.aiTasks.insert(key)
    defer { store.aiTasks.remove(key) }
    busy = "Verdiepen… Dit kan enkele minuten duren."
    error = nil
    defer { busy = nil }
    do {
      let query = try await store.modelQuery("expand")
      lesson = try await api.request("lessons/\(lesson.id)/expand", query: query, method: "POST")
      expansionOpen = true
    } catch { self.error = error.localizedDescription }
  }
  func send() async {
    guard let api = store.api else { return }
    guard !store.aiTasks.contains(lesson.id) else { return }
    let key = lesson.id
    store.aiTasks.insert(key)
    defer { store.aiTasks.remove(key) }
    busy = "Naar Vikunja sturen…"
    error = nil
    defer { busy = nil }
    do {
      let result: VikunjaResult = try await api.request(
        "lessons/\(lesson.id)/send-to-vikunja", method: "POST")
      guard result.success else { throw APIError.message("Vikunja heeft de taak niet bevestigd.") }
      lesson.vikunjaTaskId = result.taskId
    } catch { self.error = error.localizedDescription }
  }
}
