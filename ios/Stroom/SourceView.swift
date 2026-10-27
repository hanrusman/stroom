import SwiftUI

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
