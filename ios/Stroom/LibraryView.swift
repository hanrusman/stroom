import AVKit
import SwiftUI

struct LibraryView: View {
  @EnvironmentObject var store: AppStore
  @EnvironmentObject var player: AudioPlayer
  @EnvironmentObject var library: LibraryStore
  @State private var saved: [FeedItem] = []
  @State private var error: String?
  var body: some View {
    List {
      Section {
        Text("Jouw eigen verzameling").font(.system(.title, design: .serif)).listRowBackground(
          Color.clear)
      }
      if let error { Section { Text(error).font(.callout).foregroundStyle(.red) } }
      Section("Offline beschikbaar · \(library.downloads.count)") {
        if library.downloads.isEmpty {
          Text("Download een podcast met het pijltje. Daarna luister je ook zonder internet.")
            .foregroundStyle(.secondary)
        }
        ForEach(library.downloads) { track in
          VStack(alignment: .leading, spacing: 10) {
            Text(track.title).font(.headline)
            Text(track.author).font(.caption).foregroundStyle(.secondary)
            TrackActions(track: track)
          }
          .swipeActions {
            Button("Verwijder download", role: .destructive) {
              do {
                if player.current?.id == track.id { player.stop() }
                try library.remove(track)
              } catch { self.error = error.localizedDescription }
            }
          }
        }
      }
      Section("Bewaard in Stroom") {
        if saved.isEmpty {
          Text("Bewaar een artikel of aflevering via het bladwijzertje.").foregroundStyle(
            .secondary)
        }
        ForEach(saved.map(store.current).filter { $0.status == "pinned" }) { item in
          Button {
            store.openItemID = item.id
          } label: {
            VStack(alignment: .leading, spacing: 6) {
              Text(item.title).foregroundStyle(.primary)
              Text(item.sourceName).font(.caption).foregroundStyle(.secondary)
            }
          }.stroomActions(item)
        }
      }
    }.scrollContentBackground(.hidden).background(Brand.paper).navigationTitle("Bibliotheek")
      .task { await load() }.refreshable { await load() }
  }
  func load() async {
    guard !store.demo, let api = store.api else { return }
    do {
      saved = try await api.items(saved: true, limit: 500)
      error = nil
    } catch { self.error = error.localizedDescription }
  }
}
