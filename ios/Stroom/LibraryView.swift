import AVKit
import SwiftUI

private enum LibraryDestination: Hashable {
  case lessons, tips
}

struct LibraryView: View {
  @EnvironmentObject var store: AppStore
  @EnvironmentObject var player: AudioPlayer
  @EnvironmentObject var library: LibraryStore
  @Environment(\.dynamicTypeSize) private var typeSize
  @State private var saved: [FeedItem] = []
  @State private var error: String?
  @State private var loading = true
  @State private var selection = "saved"
  @State private var destination: LibraryDestination?
  var body: some View {
    List {
      VStack(alignment: .leading, spacing: 18) {
        EditorialHeader(eyebrow: "Om bij terug te komen", title: "Jouw verzameling")
        let layout =
          typeSize.isAccessibilitySize
          ? AnyLayout(VStackLayout(spacing: 12)) : AnyLayout(HStackLayout(spacing: 12))
        layout {
          Button {
            destination = .lessons
          } label: {
            Label("Alle lessen", systemImage: "book.closed").frame(
              maxWidth: .infinity, minHeight: 48)
          }
          Button {
            destination = .tips
          } label: {
            Label("Tips", systemImage: "lightbulb").frame(maxWidth: .infinity, minHeight: 48)
          }
        }.font(.subheadline).buttonStyle(.bordered).tint(Brand.blue)
        Picker("Verzameling", selection: $selection) {
          Text("Bewaard").tag("saved")
          Text("Downloads (\(library.downloads.count))").tag("downloads")
        }.pickerStyle(.segmented)
      }.editorialRow()
      if let error { ErrorNotice(message: error) { await load() }.editorialRow() }
      if selection == "downloads" {
        if library.downloads.isEmpty {
          ContentUnavailableView(
            "Ook zonder internet", systemImage: "arrow.down.circle",
            description: Text(
              "Download een podcast via de downloadknop naast Luister. Je vindt hem daarna hier.")
          )
          .editorialRow()
        }
        ForEach(library.downloads) { track in
          VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 14) {
              Artwork(raw: track.artwork, symbol: "headphones").frame(width: 64, height: 64)
                .clipShape(RoundedRectangle(cornerRadius: 12))
              VStack(alignment: .leading, spacing: 8) {
                Text(track.title).font(Brand.editorial(23))
                Text(track.author).font(Brand.meta).foregroundStyle(Brand.muted)
              }
            }
            TrackActions(track: track)
          }.padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 20))
            .editorialRow()
            .swipeActions {
              Button("Verwijder download", role: .destructive) {
                do {
                  if player.current?.id == track.id { player.stop() }
                  try library.remove(track)
                } catch { self.error = error.localizedDescription }
              }
            }
        }
      } else {
        let rows = saved.map(store.current).filter { $0.status == "pinned" }
        if rows.isEmpty && loading {
          FeedSkeleton().editorialRow()
        } else if rows.isEmpty && error == nil {
          ContentUnavailableView {
            Label("Een plek voor blijvers", systemImage: "bookmark")
          } description: {
            Text(
              "Bewaar een artikel of aflevering met het bladwijzertje. Je verzameling blijft gelijk op de website en je iPhone."
            )
          } actions: {
            Button("Ontdek in Stroom") { store.tab = 0 }.buttonStyle(.borderedProminent).tint(
              Brand.navy)
          }
          .editorialRow()
        }
        ForEach(rows) { item in FeedCard(item: item).editorialRow().stroomActions(item) }
      }
    }.listStyle(.plain).scrollContentBackground(.hidden).background(Brand.paper)
      .navigationTitle("Bibliotheek").navigationBarTitleDisplayMode(.inline)
      .navigationDestination(item: $destination) { destination in
        switch destination {
        case .lessons: AllLessonsView()
        case .tips: TipsView()
        }
      }
      .task { await load() }.refreshable { await load() }
  }
  func load() async {
    loading = true
    defer { loading = false }
    if store.demo {
      saved = store.allKnownItems.filter { $0.status == "pinned" }
      return
    }
    guard let api = store.api else { return }
    do {
      saved = try await api.items(saved: true, limit: 500)
      error = nil
    } catch { self.error = error.localizedDescription }
  }
}
