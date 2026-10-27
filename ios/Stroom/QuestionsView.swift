import SwiftUI

struct ItemQuestionsView: View {
  @EnvironmentObject var store: AppStore
  let id: String
  @State private var question = ""
  @State private var history: [ItemQuestion] = []
  @State private var error: String?
  @State private var asking = false
  private let suggestions = [
    "Wat zijn de kernargumenten?", "Welk bewijs draagt de auteur aan?",
    "Wat is hier de tegenovergestelde positie?",
  ]
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text("Vraag door op de bron, samenvatting en lessen.").foregroundStyle(.secondary)
      if history.isEmpty {
        ForEach(suggestions, id: \.self) { suggestion in
          Button(suggestion) { question = suggestion }.buttonStyle(.bordered).disabled(asking)
        }
      }
      TextField("Je vraag", text: $question, axis: .vertical).accessibilityIdentifier(
        "question-input"
      ).disabled(asking).lineLimit(3...8).padding(14)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
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
          if let date = answer.createdAt.flatMap(StroomDate.parse) {
            Text(date.formatted(date: .abbreviated, time: .shortened)).font(.caption)
              .foregroundStyle(.secondary)
          }
          if let sources = answer.sourcesUsed, !sources.isEmpty {
            Text(
              "Gebruikt: "
                + sources.map {
                  [
                    "transcript": "volledige tekst", "description": "bronbeschrijving",
                    "summary": "samenvatting", "lessons": "lessen",
                  ][$0] ?? $0
                }.joined(separator: ", ")
            )
            .font(.caption).foregroundStyle(.secondary)
          }
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
      let query = try await store.modelQuery("ask")
      let answer: ItemQuestion = try await api.request(
        "huygens/items/\(id)/ask", query: query, method: "POST",
        body: ["question": question.trimmingCharacters(in: .whitespacesAndNewlines)])
      history.insert(answer, at: 0)
      question = ""
    } catch { self.error = error.localizedDescription }
  }
}
