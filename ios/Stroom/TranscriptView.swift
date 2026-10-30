import SwiftUI

struct TranscriptView: View {
  @EnvironmentObject var player: AudioPlayer
  let item: FeedItem
  let segments: [TranscriptSegment]
  @State private var follow = true
  var active: Int? {
    guard player.current?.id == item.id else { return nil }
    return TranscriptSegment.activeIndex(in: segments, at: player.elapsed)
  }
  var body: some View {
    ScrollViewReader { proxy in
      LazyVStack(alignment: .leading, spacing: 16) {
        Toggle("Volg het gesproken woord", isOn: $follow).font(.callout)
        ForEach(Array(segments.enumerated()), id: \.offset) { index, segment in
          VStack(alignment: .leading, spacing: 8) {
            HStack {
              if let track = item.track {
                Button(timeLabel(segment.start), systemImage: "play.circle") {
                  if player.current?.id == track.id {
                    player.seek(segment.start)
                    player.resume()
                  } else {
                    player.play(track, at: segment.start)
                  }
                }.disabled(!segment.start.isFinite)
              } else {
                Text(timeLabel(segment.start)).foregroundStyle(Brand.blue)
              }
              if let speaker = segment.speaker { Text(speaker).foregroundStyle(.secondary) }
            }.font(.caption.monospacedDigit()).frame(minHeight: 44)
            Text(segment.text).lineSpacing(5).textSelection(.enabled)
          }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(
              active == index ? Brand.blue.opacity(0.12) : Color.clear,
              in: RoundedRectangle(cornerRadius: 12)
            )
            .id(index)
        }
      }.onChange(of: active) { _, index in
        if follow, let index { withAnimation { proxy.scrollTo(index, anchor: .center) } }
      }
    }
  }
}
func timeLabel(_ seconds: Double) -> String {
  let value = Int(seconds.isFinite ? max(0, min(seconds, 1_000_000)) : 0)
  return String(format: "%d:%02d", value / 60, value % 60)
}
