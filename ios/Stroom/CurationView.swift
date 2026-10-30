import SwiftUI

struct ItemCurationView: View {
  @EnvironmentObject var store: AppStore
  @Environment(\.dismiss) var dismiss
  let item: FeedItem
  let onChange: (FeedItem) -> Void
  @State private var choices: [TopicChoice] = []
  @State private var score = 0
  @State private var reason = "personal_interest"
  @State private var note = ""
  @State private var busy = false
  @State private var error: String?
  @State private var message: String?
  var body: some View {
    NavigationStack {
      Form {
        Section("Jouw kwaliteitsscore") {
          Picker("Score", selection: $score) {
            Text("Neutraal").tag(0)
            ForEach(1...10, id: \.self) { Text("\($0) / 10").tag($0) }
          }
          Picker("Reden", selection: $reason) {
            Text("Persoonlijke interesse").tag("personal_interest")
            Text("Hoge kwaliteit").tag("high_quality")
            Text("Lage kwaliteit").tag("low_quality")
            Text("Verkeerd onderwerp").tag("wrong_topic")
            Text("Te veel reclame").tag("too_many_ads")
            Text("Niet interessant").tag("not_interesting")
            Text("Anders").tag("other")
          }
          TextField("Toelichting (optioneel)", text: $note, axis: .vertical)
          Button("Score opslaan") { Task { await saveScore() } }.disabled(busy)
          ScoreExplanation(detail: item.qualityScoreDetail)
        }
        Section("Onderwerpen") {
          ForEach(choices) { topic in
            let included =
              (item.topics ?? []).contains(topic.name) || (item.topics ?? []).contains(topic.slug)
            Button {
              Task { await setTopic(topic, included: !included) }
            } label: {
              HStack {
                Text(topic.name)
                Spacer()
                Image(systemName: included ? "checkmark.circle.fill" : "circle")
              }
            }.disabled(busy).accessibilityLabel(
              "\(topic.name), \(included ? "toegevoegd" : "niet toegevoegd")")
          }
        }
        if busy { ProgressView("Opslaan…") }
        if let message { Text(message).foregroundStyle(.secondary) }
        if let error { Text(error).foregroundStyle(.red) }
      }.navigationTitle("Score en onderwerpen").navigationBarTitleDisplayMode(.inline)
        .toolbar { Button("Gereed") { dismiss() }.accessibilityIdentifier("curation-done") }
        .task {
          score = Int(item.qualityScore ?? 0)
          if store.demo {
            choices = store.topics.map { TopicChoice(slug: $0.slug, name: $0.name) }
            return
          }
          guard let api = store.api else { return }
          do { choices = try await api.request("inbox/topics") } catch {
            self.error = error.localizedDescription
          }
        }
    }
  }
  func saveScore() async {
    busy = true
    error = nil
    message = nil
    defer { busy = false }
    do {
      var updated = item
      if store.demo {
        updated.qualityScore = score == 0 ? nil : Double(score)
      } else {
        guard let api = store.api else { throw APIError.unauthorized }
        updated = try await api.request(
          "huygens/items/\(item.id)/quality-score", method: "PATCH",
          body: [
            "quality_score": score == 0 ? NSNull() : score as Any, "reason": reason, "note": note,
          ])
      }
      onChange(updated)
      message = "Score opgeslagen"
    } catch { self.error = error.localizedDescription }
  }
  func setTopic(_ topic: TopicChoice, included: Bool) async {
    busy = true
    error = nil
    message = nil
    defer { busy = false }
    do {
      var updated = item
      if store.demo {
        var names = Set(item.topics ?? [])
        if included {
          names.insert(topic.name)
        } else {
          names.remove(topic.name)
          names.remove(topic.slug)
        }
        updated.topics = names.sorted()
      } else {
        guard let api = store.api else { throw APIError.unauthorized }
        let path = "huygens/items/\(item.id)/topics" + (included ? "" : "/\(topic.slug)")
        updated = try await api.request(
          path, method: included ? "POST" : "DELETE",
          body: included ? ["topic_slug": topic.slug] : nil)
      }
      onChange(updated)
    } catch { self.error = error.localizedDescription }
  }
}
struct ScoreExplanation: View {
  let detail: QualityScoreDetail?
  var body: some View {
    DisclosureGroup("Waarom deze score?") {
      if let detail {
        if let error = detail.error { Text(error) }
        if let calibration = detail.calibration, calibration.method == "percentile" {
          Text(
            "Beter dan \(calibration.percentile.formatted(.percent.precision(.fractionLength(0)))) van de laatste \(calibration.days) dagen (\(calibration.n) items)."
          )
        }
        if let quality = detail.quality { rubric("Kwaliteit", quality) }
        if let interest = detail.interest {
          rubric("Interesse", interest)
          Text("Telt \((detail.interestWeight ?? 0).formatted(.percent)) mee.")
        }
        if let clickbait = detail.clickbait {
          Text("Kans op clickbait/reclame: \(clickbait.formatted(.percent))")
        }
        if let model = detail.model { Text(model).foregroundStyle(.secondary) }
      } else {
        Text("Geen uitleg beschikbaar bij deze score.").foregroundStyle(.secondary)
      }
    }.font(.caption)
  }
  func rubric(_ title: String, _ rubric: ScoreRubric) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("\(title) · \(rubric.score10.formatted())/10").fontWeight(.semibold)
      ForEach(rubric.probabilities.keys.sorted(), id: \.self) { label in
        VStack(alignment: .leading) {
          Text(label)
          ProgressView(value: min(1, max(0, rubric.probabilities[label] ?? 0)))
          Text((rubric.probabilities[label] ?? 0).formatted(.percent))
        }
      }
    }.padding(.vertical, 8)
  }
}
