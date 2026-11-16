import SwiftUI

struct SearchResultsView: View {
  @EnvironmentObject var store: AppStore
  let query: String
  let podcastsOnly: Bool
  @State private var format = "all"
  @State private var hits: [SearchHit] = []
  @State private var loading = false
  @State private var error: String?
  var body: some View {
    Section("Zoekresultaten") {
      if !podcastsOnly {
        Picker("Zoeken in", selection: $format) {
          Text("Alles").tag("all")
          Text("Artikelen").tag("article")
          Text("Podcasts").tag("podcast")
          Text("Video’s").tag("video")
        }.pickerStyle(.menu)
      }
      if loading { ProgressView() }
      if let error { Text(error).foregroundStyle(.red) }
      ForEach(hits) { hit in
        Button {
          store.openItemID = hit.id
        } label: {
          VStack(alignment: .leading, spacing: 8) {
            Text(hit.sourceName.uppercased()).font(.caption).foregroundStyle(Brand.blue)
            Text(hit.title).font(Brand.editorial(23)).foregroundStyle(.primary)
            if let snippet = hit.snippet {
              Text(highlightedSnippet(snippet)).font(.subheadline).foregroundStyle(.secondary)
                .lineLimit(4)
            }
            HStack {
              if let date = hit.publishedAt.flatMap(StroomDate.parse) {
                Text(date.formatted(date: .abbreviated, time: .omitted))
              }
              if let match = hit.match {
                Text(
                  [
                    "keyword": "Trefwoord", "semantic": "Betekenis",
                    "both": "Trefwoord en betekenis",
                  ][match] ?? match)
              }
            }.font(.caption).foregroundStyle(.secondary)
          }.padding(.vertical, 8)
        }
      }
      if !loading && hits.isEmpty && error == nil { ContentUnavailableView.search(text: query) }
    }.task(id: "\(query)|\(format)") { await search() }
  }
  func search() async {
    loading = true
    error = nil
    hits = []
    defer { if !Task.isCancelled { loading = false } }
    guard query.trimmingCharacters(in: .whitespacesAndNewlines).count >= 2 else { return }
    guard !store.demo, let api = store.api else { return }
    do {
      try await Task.sleep(for: .milliseconds(350))
      var parameters = [URLQueryItem(name: "q", value: query), .init(name: "limit", value: "50")]
      if podcastsOnly || format != "all" {
        parameters.append(.init(name: "format", value: podcastsOnly ? "podcast" : format))
      }
      let result: [SearchHit] = try await api.request("search", query: parameters)
      try Task.checkCancellation()
      hits = result
    } catch { if !Task.isCancelled { self.error = error.localizedDescription } }
  }
}

// Only <mark> contributes styling. All other source markup is reduced to text.
func highlightedSnippet(_ raw: String) -> AttributedString {
  let plain = ContentText.excerpt(raw)
  var result = AttributedString(plain)
  guard let regex = try? NSRegularExpression(pattern: "(?is)<mark[^>]*>(.*?)</mark>") else {
    return result
  }
  for match in regex.matches(in: raw, range: NSRange(raw.startIndex..., in: raw)) {
    guard let rawRange = Range(match.range(at: 1), in: raw) else { continue }
    let word = ContentText.excerpt(String(raw[rawRange]))
    guard !word.isEmpty else { continue }
    var remaining = plain.startIndex..<plain.endIndex
    while let range = plain.range(of: word, options: .caseInsensitive, range: remaining) {
      if let start = AttributedString.Index(range.lowerBound, within: result),
        let end = AttributedString.Index(range.upperBound, within: result)
      {
        result[start..<end].backgroundColor = .yellow.opacity(0.3)
        result[start..<end].foregroundColor = .primary
        result[start..<end].font = .body.bold()
      }
      remaining = range.upperBound..<plain.endIndex
    }
  }
  return result
}
