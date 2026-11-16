import AVKit
import SwiftUI

struct MiniPlayer: View {
  @EnvironmentObject var player: AudioPlayer
  @Binding var showingPlayer: Bool
  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 8) {
        Button {
          showingPlayer = true
        } label: {
          HStack(spacing: 12) {
            Artwork(raw: player.current?.artwork).frame(width: 46, height: 46)
              .clipShape(RoundedRectangle(cornerRadius: 10))
            VStack(alignment: .leading, spacing: 4) {
              Text(player.current?.title ?? "").font(Brand.editorial(18, relativeTo: .headline))
                .lineLimit(1)
              Text(
                player.error != nil
                  ? "Afspelen mislukt · bekijk details" : (player.current?.author ?? "")
              )
              .font(.caption).foregroundStyle(Brand.muted).lineLimit(1)
            }
          }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityLabel("Open speler: \(player.current?.title ?? "")")
        if player.loading { ProgressView().accessibilityLabel("Audio laden") }
        Button {
          player.toggle()
        } label: {
          Image(systemName: player.playing ? "pause.fill" : "play.fill").font(.title3)
            .frame(width: 48, height: 48)
        }.accessibilityLabel(player.playing ? "Pauzeer" : "Speel af")
        Button {
          player.skip(30)
        } label: {
          Image(systemName: "goforward.30").font(.title3).frame(width: 44, height: 48)
        }.frame(minWidth: 44, minHeight: 48).accessibilityLabel("30 seconden vooruit")
      }.padding(10)
      if player.duration > 0 {
        ProgressView(value: min(1, max(0, player.elapsed / player.duration)))
          .tint(Brand.blue).accessibilityLabel("Luistervoortgang")
      }
    }.background(Brand.card, in: RoundedRectangle(cornerRadius: 18))
      .clipShape(RoundedRectangle(cornerRadius: 18))
      .overlay(RoundedRectangle(cornerRadius: 18).stroke(Brand.line.opacity(0.5), lineWidth: 0.5))
  }
}

struct NowPlayingView: View {
  @EnvironmentObject var player: AudioPlayer
  @Environment(\.dismiss) var dismiss
  @State private var scrubbing = false
  @State private var position: Double = 0
  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(spacing: 20) {
          Text("NU AAN HET LUISTEREN").font(Brand.meta).tracking(3).foregroundStyle(
            Brand.blue)
          Artwork(raw: player.current?.artwork).frame(width: 240, height: 240)
            .clipShape(RoundedRectangle(cornerRadius: 30)).shadow(
              color: Brand.blue.opacity(0.12), radius: 22, y: 12)
          VStack(spacing: 8) {
            Text(player.current?.title ?? "Kies een podcast").font(
              Brand.editorial(29, relativeTo: .title)
            ).multilineTextAlignment(.center)
            Text(player.current?.author ?? "").foregroundStyle(.secondary)
          }
          if let error = player.error { Text(error).font(.caption).foregroundStyle(.red) }
          VStack(spacing: 4) {
            Slider(
              value: Binding(
                get: { scrubbing ? position : player.elapsed }, set: { position = $0 }),
              in: 0...max(1, player.duration),
              onEditingChanged: { editing in
                if editing { position = player.elapsed }
                scrubbing = editing
                if !editing { player.seek(position) }
              }
            ).disabled(player.duration <= 0).accessibilityLabel("Luisterpositie")
            HStack {
              Text(timestamp(player.elapsed))
              Spacer()
              Text("−\(timestamp(max(0, player.duration - player.elapsed)))")
            }.font(.caption.monospacedDigit()).foregroundStyle(.secondary)
          }
          HStack(spacing: 34) {
            Button {
              player.skip(-15)
            } label: {
              Image(systemName: "gobackward.15").font(.title)
            }.frame(width: 48, height: 48).accessibilityLabel("15 seconden terug")
            Button {
              player.toggle()
            } label: {
              ZStack {
                Circle().fill(Brand.navy)
                Image(systemName: player.playing ? "pause.fill" : "play.fill")
                  .symbolRenderingMode(.monochrome).font(.system(size: 32))
                  .foregroundStyle(Color(red: 0.98, green: 0.97, blue: 0.95))
              }.frame(width: 78, height: 78)
            }.buttonStyle(.plain).accessibilityLabel(player.playing ? "Pauzeer" : "Speel af")
            Button {
              player.skip(30)
            } label: {
              Image(systemName: "goforward.30").font(.title)
            }.frame(minWidth: 44, minHeight: 48).accessibilityLabel("30 seconden vooruit")
          }
          HStack {
            Menu {
              ForEach(AudioPlayer.playbackRates, id: \.self) { speed in
                Button("\(speed.formatted())×") { player.speed = Float(speed) }
              }
            } label: {
              Text("\(Double(player.speed).formatted())×").font(.headline).frame(
                width: 64, height: 44)
            }.accessibilityLabel("Afspeelsnelheid")
            Spacer()
            AirPlayButton().frame(width: 44, height: 44).accessibilityLabel("AirPlay")
            Spacer()
            Menu {
              Button("Uit") { player.sleep(minutes: nil) }
              ForEach([15, 30, 45, 60], id: \.self) { minute in
                Button("\(minute) minuten") { player.sleep(minutes: minute) }
              }
            } label: {
              Image(systemName: player.sleepUntil == nil ? "moon" : "moon.fill").frame(
                width: 64, height: 44)
            }.accessibilityLabel("Slaaptimer")
          }
          if let until = player.sleepUntil {
            Text("Stopt om \(until.formatted(date: .omitted, time: .shortened))").font(.caption)
              .foregroundStyle(.secondary)
          }
          if !player.queue.isEmpty {
            VStack(alignment: .leading, spacing: 18) {
              HStack {
                Text("Hierna").font(Brand.display(25, relativeTo: .title2))
                Spacer()
                Button("Volgende") { player.next() }
              }
              ForEach(Array(player.queue.enumerated()), id: \.element.id) { index, track in
                HStack {
                  Text(track.title).font(.subheadline).lineLimit(2)
                  Spacer()
                  Button {
                    player.removeFromQueue(at: IndexSet(integer: index))
                  } label: {
                    Image(systemName: "minus.circle").frame(width: 44, height: 44)
                  }.accessibilityLabel("Verwijder uit Hierna: \(track.title)")
                }
              }
            }
          }
        }.padding(24).frame(maxWidth: 560)
      }.frame(maxWidth: .infinity).background(Brand.paper)
        .presentationDragIndicator(.visible)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Gereed") { dismiss() } } }
    }
  }
  func timestamp(_ value: Double) -> String {
    let seconds = Int(value.isFinite ? max(0, value) : 0)
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
  }
}
struct AirPlayButton: UIViewRepresentable {
  func makeUIView(context: Context) -> AVRoutePickerView {
    let view = AVRoutePickerView()
    view.prioritizesVideoDevices = false
    return view
  }
  func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}
