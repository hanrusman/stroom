import AVKit
import SwiftUI

struct MarkdownBody: View {
  let text: String
  var readingSize: Double? = nil
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      ForEach(
        Array(ContentText.markdown(text).components(separatedBy: "\n").enumerated()), id: \.offset
      ) { _, line in
        if line.trimmingCharacters(in: .whitespaces).isEmpty {
          Spacer().frame(height: 3)
        } else {
          let heading = line.range(of: #"^#{1,6}\s"#, options: .regularExpression) != nil
          let clean = line.replacingOccurrences(
            of: #"^#{1,6}\s+"#, with: "", options: .regularExpression
          )
          .replacingOccurrences(of: #"^\s*[-*+]\s+"#, with: "• ", options: .regularExpression)
          .replacingOccurrences(of: #"^>\s?"#, with: "│ ", options: .regularExpression)
          if !clean.hasPrefix("```") {
            Text(
              (try? AttributedString(
                markdown: clean, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
                ?? AttributedString(clean)
            )
            .font(
              heading
                ? .system(.title3, design: .serif).weight(.semibold)
                : readingSize.map { .system(size: $0, design: .serif) } ?? .body
            )
            .lineSpacing(readingSize.map { $0 * 0.4 } ?? 5).frame(
              maxWidth: .infinity, alignment: .leading
            ).textSelection(.enabled)
          }
        }
      }
    }
  }
}

struct ArticleBody: View {
  let item: FeedItem
  @AppStorage("readerFontSize") private var fontSize = 20.0
  var body: some View {
    VStack(alignment: .leading, spacing: 24) {
      if let artwork = item.artwork {
        Artwork(raw: artwork).frame(height: 200).clipShape(RoundedRectangle(cornerRadius: 18))
      }
      if let quote = item.openingQuote {
        HStack(alignment: .top, spacing: 16) {
          Rectangle().fill(Brand.blue.opacity(0.4)).frame(width: 2)
          Text(quote).font(.system(size: fontSize, design: .serif).italic()).foregroundStyle(
            .secondary)
        }.fixedSize(horizontal: false, vertical: true)
      }
      HStack {
        Text("Leesgrootte").font(.caption).foregroundStyle(.secondary)
        Spacer()
        Button("A−") { fontSize = max(18, fontSize - 1) }.accessibilityLabel("Kleinere letters")
          .disabled(fontSize <= 18)
        Button("A+") { fontSize = min(28, fontSize + 1) }.accessibilityLabel("Grotere letters")
          .disabled(fontSize >= 28)
      }.buttonStyle(.bordered).frame(minHeight: 44)
      if let text = item.sourceBody { MarkdownBody(text: text, readingSize: fontSize) }
    }
  }
}
