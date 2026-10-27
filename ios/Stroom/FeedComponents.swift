import SwiftUI

struct FeedCard: View {
  @EnvironmentObject var store: AppStore
  let item: FeedItem
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack(alignment: .top, spacing: 14) {
        VStack(alignment: .leading, spacing: 10) {
          HStack {
            Text(item.sourceName.uppercased()).font(.caption2.weight(.semibold)).tracking(1)
            Spacer()
            if let score = item.qualityScore {
              Text(score, format: .number.precision(.fractionLength(1))).font(
                .caption.monospacedDigit()
              ).padding(6).background(Brand.blue.opacity(0.09), in: Capsule())
            }
          }.foregroundStyle(Brand.blue)
          Button {
            store.openItemID = item.id
          } label: {
            Text(item.title).font(.system(.title3, design: .serif).weight(.semibold))
              .foregroundStyle(.primary).multilineTextAlignment(.leading)
          }.buttonStyle(.plain)
          if let text = item.description {
            Text(ContentText.excerpt(text)).font(.subheadline).foregroundStyle(.secondary)
              .lineLimit(2)
          }
        }
        Artwork(raw: item.artwork, symbol: item.isPodcast ? "waveform" : "text.alignleft").frame(
          width: 64, height: 74
        ).clipShape(RoundedRectangle(cornerRadius: 12))
      }
      HStack(spacing: 12) {
        if item.hasSummary == true || item.summary?.isEmpty == false {
          Label("Samenvatting", systemImage: "sparkles")
        }
        if item.hasTranscript == true || item.transcript?.isEmpty == false {
          Label("Tekst", systemImage: "text.alignleft")
        }
        if store.queuedIDs.contains(item.id) {
          Label("Wachtrij", systemImage: "text.badge.checkmark")
        }
        if item.isProcessing { Label("Verwerking", systemImage: "clock") }
      }.font(.caption2).foregroundStyle(.secondary)
      if let track = item.track {
        TrackActions(track: track)
      } else {
        Button(
          item.hasSummary == true ? "Lees met samenvatting" : "Lees artikel",
          systemImage: "arrow.up.right"
        ) { store.openItemID = item.id }.font(.caption.weight(.semibold))
      }
    }.padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 22))
  }
}

struct Artwork: View {
  let raw: String?
  var symbol = "waveform"
  var body: some View {
    ZStack {
      LinearGradient(
        colors: [
          Color(red: 0.03, green: 0.18, blue: 0.32), Color(red: 0.15, green: 0.38, blue: 0.48),
        ], startPoint: .topLeading, endPoint: .bottomTrailing)
      Image(systemName: symbol).font(.title).foregroundStyle(.white.opacity(0.85))
      if let raw, let url = URL(string: raw), url.scheme == "https" {
        AsyncImage(url: url) { image in
          image.resizable().scaledToFill()
        } placeholder: {
          Color.clear
        }
      }
    }.clipped().accessibilityHidden(true)
  }
}

struct TrackActions: View {
  @EnvironmentObject var store: AppStore
  @EnvironmentObject var player: AudioPlayer
  @EnvironmentObject var library: LibraryStore
  let track: AudioTrack
  @State private var error: String?
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(spacing: 18) {
        Button {
          player.play(track)
        } label: {
          Label("Luister", systemImage: "play.fill").font(.subheadline.weight(.semibold))
        }
        Spacer()
        Button {
          player.enqueue(track)
        } label: {
          Image(
            systemName: player.queue.contains(where: { $0.id == track.id })
              ? "checkmark" : "text.badge.plus")
        }.accessibilityLabel("Speel hierna af")
        if library.downloading.contains(track.id) {
          ProgressView().accessibilityLabel("Downloaden")
        } else if library.localURL(for: track) != nil {
          Image(systemName: "checkmark.circle.fill").foregroundStyle(.green).accessibilityLabel(
            "Offline beschikbaar")
        } else {
          Button {
            Task {
              do { if let api = store.api { try await library.download(track, api: api) } } catch {
                self.error = error.localizedDescription
              }
            }
          } label: {
            Image(systemName: "arrow.down.circle")
          }.accessibilityLabel("Download voor offline luisteren")
        }
      }.buttonStyle(.borderless)
      if let error { Text(error).font(.caption).foregroundStyle(.red) }
    }
  }
}

struct ErrorNotice: View {
  let message: String
  let retry: () async -> Void
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Label(message, systemImage: "exclamationmark.circle").font(.callout)
      Button("Opnieuw proberen") { Task { await retry() } }.font(.callout.weight(.semibold))
    }.foregroundStyle(.secondary).padding(16).frame(maxWidth: .infinity, alignment: .leading)
      .background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
  }
}
