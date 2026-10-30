import SwiftUI

struct FeedCard: View {
  @EnvironmentObject var store: AppStore
  @Environment(\.dynamicTypeSize) private var typeSize
  let item: FeedItem
  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      Button {
        store.openItemID = item.id
      } label: {
        VStack(alignment: .leading, spacing: 0) {
          if item.format == "video" {
            ZStack {
              Artwork(raw: item.artwork, symbol: "video").frame(height: 180)
              Image(systemName: "play.circle.fill").font(.system(size: 48)).foregroundStyle(.white)
                .shadow(color: .black.opacity(0.3), radius: 8)
            }
          } else if !item.isPodcast, let art = item.thumbnailUrl {
            Artwork(raw: art, symbol: "photo").frame(height: 170)
          }
          VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 16) {
              if item.isPodcast && !typeSize.isAccessibilitySize {
                Artwork(raw: item.artwork, symbol: "headphones").frame(width: 80, height: 80)
                  .clipShape(RoundedRectangle(cornerRadius: 14))
              }
              VStack(alignment: .leading, spacing: 8) {
                Text(item.sourceName.uppercased()).font(Brand.meta).tracking(1)
                  .foregroundStyle(Brand.blue).lineLimit(2)
                Text(item.title).font(
                  Brand.editorial(item.isPodcast ? 23 : 27, relativeTo: .title2)
                )
                .fontWeight(.medium).foregroundStyle(Brand.ink).fixedSize(
                  horizontal: false, vertical: true
                )
                .multilineTextAlignment(.leading)
              }.frame(maxWidth: .infinity, alignment: .leading)
            }
            if !item.isPodcast, let raw = item.description {
              let text = ContentText.excerpt(raw)
              if !text.isEmpty {
                Text(text).font(.subheadline).lineSpacing(3).foregroundStyle(Brand.muted).lineLimit(
                  3)
              }
            }
            ViewThatFits(in: .horizontal) {
              HStack(spacing: 12) { metadata }
              VStack(alignment: .leading, spacing: 6) { metadata }
            }
          }.padding(20)
        }.contentShape(Rectangle())
      }.buttonStyle(.plain).accessibilityLabel(item.title)
        .accessibilityValue(
          item.sourceName + (item.qualityScore.map { ", kwaliteit \($0.formatted()) op 10" } ?? "")
        )
        .accessibilityHint("Open bron, samenvatting en inzichten")
      if let track = item.track {
        TrackActions(track: track).padding(.horizontal, 20).padding(.bottom, 4)
      }
      HStack(spacing: 10) {
        if item.hasSummary == true || item.summary?.isEmpty == false {
          Label("Samengevat", systemImage: "sparkles").font(.caption).foregroundStyle(Brand.blue)
        } else {
          Label(
            item.format == "video" ? "Bekijk bron en inzichten" : "Lees artikel",
            systemImage: item.format == "video" ? "play.rectangle" : "text.alignleft"
          )
          .font(.caption).foregroundStyle(Brand.muted)
        }
        Spacer(minLength: 0)
        Button {
          Task { await store.setQueued(item, queued: !store.queuedIDs.contains(item.id)) }
        } label: {
          Label(
            "Wachtrij",
            systemImage: store.queuedIDs.contains(item.id)
              ? "text.badge.checkmark" : "text.badge.plus"
          )
          .font(.caption).frame(minWidth: 44, minHeight: 44)
        }.accessibilityLabel(
          store.queuedIDs.contains(item.id) ? "Uit leeswachtrij" : "In leeswachtrij"
        )
        .accessibilityHint("Gedeeld met de Stroom-website")
        .disabled(item.status == "archived" || store.changing.contains(item.id))
      }.buttonStyle(.borderless).padding(.horizontal, 20).padding(.bottom, 10)
    }.background(Brand.card, in: RoundedRectangle(cornerRadius: 22))
      .clipShape(RoundedRectangle(cornerRadius: 22))
  }
  @ViewBuilder var metadata: some View {
    if let date = item.date {
      Text(date, format: .dateTime.day().month(.abbreviated).locale(Locale(identifier: "nl_NL")))
        .font(Brand.meta).foregroundStyle(Brand.muted)
    }
    if let score = item.qualityScore {
      Label(
        "\(score.formatted(.number.precision(.fractionLength(0...1))))/10", systemImage: "star.fill"
      )
      .font(Brand.meta).foregroundStyle(Brand.green)
      .accessibilityLabel("Kwaliteit \(score.formatted()) op 10")
    }
    if item.status == "pinned" {
      Image(systemName: "bookmark.fill").foregroundStyle(Brand.blue).accessibilityLabel("Bewaard")
    }
    if item.isProcessing {
      Label("Wordt verwerkt", systemImage: "clock").font(.caption).foregroundStyle(Brand.muted)
    }
    if store.queuedIDs.contains(item.id) {
      Label("Wachtrij", systemImage: "text.badge.checkmark").font(.caption).foregroundStyle(
        Brand.blue)
    }
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
      Image(systemName: symbol).font(.title).foregroundStyle(
        Color(red: 0.85, green: 0.91, blue: 0.95))
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
          if player.current?.id == track.id { player.toggle() } else { player.play(track) }
        } label: {
          Label(
            player.current?.id == track.id && player.playing ? "Pauzeer" : "Luister",
            systemImage: player.current?.id == track.id && player.playing
              ? "pause.fill" : "play.fill"
          )
          .font(.subheadline.weight(.semibold)).padding(.horizontal, 16).frame(minHeight: 44)
          .foregroundStyle(.white).background(Brand.navy, in: Capsule())
        }
        Spacer()
        Button {
          player.enqueue(track)
        } label: {
          Image(
            systemName: player.queue.contains(where: { $0.id == track.id })
              ? "checkmark" : "text.line.last.and.arrowtriangle.forward")
        }.frame(minWidth: 44, minHeight: 44).accessibilityLabel("Speel hierna af")
          .accessibilityValue(
            player.queue.contains(where: { $0.id == track.id }) ? "Staat in Hierna" : "")
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
          }.frame(minWidth: 44, minHeight: 44).accessibilityLabel("Download voor offline luisteren")
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
        .buttonStyle(.borderless)
    }.foregroundStyle(.secondary).padding(16).frame(maxWidth: .infinity, alignment: .leading)
      .background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
  }
}
