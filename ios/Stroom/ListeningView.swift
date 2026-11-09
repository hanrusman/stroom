import SwiftUI

struct ContinueListeningSection: View {
  @EnvironmentObject var player: AudioPlayer
  var body: some View {
    if !player.listening.isEmpty {
      Section("Verder luisteren") {
        ForEach(player.listening.filter(\.canResume)) { record in
          VStack(alignment: .leading, spacing: 10) {
            Text(record.track.title).font(Brand.editorial(23))
            Text(record.track.author).font(.caption).foregroundStyle(.secondary)
            if let remaining = record.remaining {
              ProgressView(value: min(1, record.position / record.duration))
              Text("Nog \(timeLabel(remaining))").font(.caption.monospacedDigit()).foregroundStyle(
                .secondary)
            } else {
              Text("Verder vanaf \(timeLabel(record.position))").font(.caption).foregroundStyle(
                .secondary)
            }
            Button("Verder luisteren", systemImage: "play.fill") {
              player.play(record.track, at: record.position)
            }.buttonStyle(.borderedProminent).tint(Brand.navy).controlSize(.large)
          }.padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 20))
            .editorialRow()
        }
      }
    }
  }
}
struct VideoPreview: View {
  let item: FeedItem
  var body: some View {
    if let raw = item.mediaUrl, let url = IncomingLink.validated(raw) {
      Link(destination: url) {
        ZStack {
          Artwork(raw: item.artwork, symbol: "video").frame(height: 200)
          VStack(spacing: 12) {
            Image(systemName: "play.circle.fill").font(.system(size: 54))
            Text("Speel video af").font(.headline)
          }.foregroundStyle(.white).shadow(radius: 8)
        }.clipShape(RoundedRectangle(cornerRadius: 18))
      }.accessibilityLabel("Speel video af bij de bron")
    }
  }
}
