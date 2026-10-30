import SwiftUI

struct SearchResultsView: View {
  @EnvironmentObject var store: AppStore
  let query: String
  let podcastsOnly: Bool
  @State private var hits: [SearchHit] = []
  @State private var loading = false
  @State private var error: String?
  var body: some View {
    Section("Zoekresultaten") {
      if loading { ProgressView() }
      if let error { Text(error).foregroundStyle(.red) }
      ForEach(hits) { hit in
        Button {
          store.openItemID = hit.id
        } label: {
          VStack(alignment: .leading, spacing: 8) {
            Text(hit.sourceName.uppercased()).font(.caption).foregroundStyle(Brand.blue)
            Text(hit.title).font(.headline).foregroundStyle(.primary)
          }.padding(.vertical, 8)
        }
      }
      if !loading && hits.isEmpty && error == nil { ContentUnavailableView.search(text: query) }
    }.task(id: query) { await search() }
  }
  func search() async {
    loading = true
    error = nil
    hits = []
    defer { if !Task.isCancelled { loading = false } }
    guard !store.demo, let api = store.api else { return }
    do {
      try await Task.sleep(for: .milliseconds(350))
      var parameters = [URLQueryItem(name: "q", value: query), .init(name: "limit", value: "50")]
      if podcastsOnly { parameters.append(.init(name: "format", value: "podcast")) }
      let result: [SearchHit] = try await api.request("search", query: parameters)
      try Task.checkCancellation()
      hits = result
    } catch { if !Task.isCancelled { self.error = error.localizedDescription } }
  }
}
