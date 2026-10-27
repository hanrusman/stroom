import AVKit
import SwiftUI

struct MiniPlayer: View {
  @EnvironmentObject var player: AudioPlayer
  @Binding var showingPlayer: Bool
  var body: some View {
    HStack(spacing: 14) {
      Button {
        showingPlayer = true
      } label: {
        HStack(spacing: 12) {
          Artwork(raw: player.current?.artwork).frame(width: 42, height: 42).clipShape(
            RoundedRectangle(cornerRadius: 9))
          VStack(alignment: .leading, spacing: 3) {
            Text(player.current?.title ?? "").font(.subheadline.weight(.medium)).lineLimit(1)
            Text(
              player.error != nil
                ? "Afspelen mislukt · tik voor details" : (player.current?.author ?? "")
            ).font(.caption).foregroundStyle(.secondary).lineLimit(1)
          }
        }.frame(maxWidth: .infinity, alignment: .leading)
      }.buttonStyle(.plain)
      if player.loading { ProgressView() }
      Button {
        player.toggle()
      } label: {
        Image(systemName: player.playing ? "pause.fill" : "play.fill").font(.title3).frame(
          width: 44, height: 44)
      }.accessibilityLabel(player.playing ? "Pauzeer" : "Speel af")
    }.padding(10).background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
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
        VStack(spacing: 28) {
          Text("NU IN JE OREN").font(.caption.weight(.semibold)).tracking(3).foregroundStyle(
            Brand.blue)
          Artwork(raw: player.current?.artwork).frame(maxWidth: 340).aspectRatio(
            1, contentMode: .fit
          ).clipShape(RoundedRectangle(cornerRadius: 30)).shadow(
            color: Brand.blue.opacity(0.12), radius: 22, y: 12)
          VStack(spacing: 8) {
            Text(player.current?.title ?? "Kies een podcast").font(
              .system(.title2, design: .serif).weight(.medium)
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
            }.accessibilityLabel("15 seconden terug")
            Button {
              player.toggle()
            } label: {
              Image(systemName: player.playing ? "pause.fill" : "play.fill").font(.system(size: 32))
                .frame(width: 78, height: 78).foregroundStyle(.white).background(
                  Color(red: 0, green: 0.2, blue: 0.4), in: Circle())
            }.accessibilityLabel(player.playing ? "Pauzeer" : "Speel af")
            Button {
              player.skip(30)
            } label: {
              Image(systemName: "goforward.30").font(.title)
            }.accessibilityLabel("30 seconden vooruit")
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
                Text("Hierna").font(.headline)
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
                    Image(systemName: "minus.circle")
                  }.accessibilityLabel("Verwijder uit wachtrij")
                }
              }
            }
          }
        }.padding(28).frame(maxWidth: 560)
      }.frame(maxWidth: .infinity).background(Brand.paper)
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
