import SwiftUI

/// Shared with web/src/ds/ds.css; interaction and sizing remain native to iOS.
enum Brand {
  static func adaptive(_ light: UInt32, _ dark: UInt32) -> Color {
    Color(
      uiColor: UIColor { traits in
        let hex = traits.userInterfaceStyle == .dark ? dark : light
        return UIColor(
          red: CGFloat((hex >> 16) & 255) / 255,
          green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: 1)
      })
  }
  static let blue = adaptive(0x003366, 0x91BCE8)
  static let navy = Color(red: 0, green: 0.20, blue: 0.40)
  static let paper = adaptive(0xF9F7F2, 0x121419)
  static let card = adaptive(0xF1EDEB, 0x1D1F24)
  static let ink = adaptive(0x1C1B1B, 0xE8E4DD)
  static let muted = adaptive(0x64615D, 0xAAA7A2)
  static let line = adaptive(0xDBD7D0, 0x363940)
  static let green = adaptive(0x306550, 0xA5CFBC)
  static func display(_ size: CGFloat = 32, relativeTo style: Font.TextStyle = .largeTitle) -> Font
  {
    .custom("PlayfairDisplay-Regular", size: size, relativeTo: style)
  }
  static func editorial(_ size: CGFloat = 22, relativeTo style: Font.TextStyle = .title3) -> Font {
    .custom("Newsreader16pt-Regular", size: size, relativeTo: style)
  }
  static let meta = Font.system(.caption2, design: .monospaced).weight(.medium)
}

struct EditorialHeader: View {
  let eyebrow: String
  let title: String
  var subtitle: String? = nil
  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text(eyebrow.uppercased()).font(Brand.meta).tracking(1.8).foregroundStyle(Brand.blue)
        .fixedSize(horizontal: false, vertical: true)
      Text(title).font(Brand.display()).foregroundStyle(Brand.ink).accessibilityAddTraits(.isHeader)
        .fixedSize(horizontal: false, vertical: true)
      if let subtitle { Text(subtitle).font(.subheadline).foregroundStyle(Brand.muted) }
    }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
  }
}

struct SectionHeading: View {
  let title: String
  var count: Int? = nil
  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: 10) {
      Text(title).font(Brand.display(25, relativeTo: .title2)).foregroundStyle(Brand.ink)
      if let count { Text(count.formatted()).font(Brand.meta).foregroundStyle(Brand.muted) }
    }.textCase(nil).accessibilityAddTraits(.isHeader)
  }
}

struct StroomChip: View {
  let title: String
  let selected: Bool
  let action: () -> Void
  var body: some View {
    Button(action: action) {
      Text(title).font(.subheadline.weight(selected ? .semibold : .regular))
        .padding(.horizontal, 17).padding(.vertical, 11).frame(minHeight: 44)
        .foregroundStyle(selected ? Color.white : Brand.ink)
        .background(selected ? Brand.navy : Brand.card, in: Capsule())
    }.buttonStyle(.plain).accessibilityAddTraits(selected ? .isSelected : [])
  }
}

struct FeedSkeleton: View {
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      RoundedRectangle(cornerRadius: 4).frame(width: 110, height: 12)
      RoundedRectangle(cornerRadius: 5).frame(height: 24)
      RoundedRectangle(cornerRadius: 5).frame(height: 24).padding(.trailing, 70)
      RoundedRectangle(cornerRadius: 4).frame(height: 12).padding(.trailing, 32)
    }.foregroundStyle(Brand.line.opacity(0.7)).padding(22)
      .background(Brand.card, in: RoundedRectangle(cornerRadius: 20))
      .accessibilityElement(children: .ignore).accessibilityLabel("Inhoud laden")
  }
}

extension View {
  func editorialRow() -> some View {
    listRowInsets(EdgeInsets(top: 7, leading: 22, bottom: 7, trailing: 22))
      .listRowSeparator(.hidden).listRowBackground(Color.clear)
  }
}

struct ReaderActionLabelStyle: LabelStyle {
  let compact: Bool
  func makeBody(configuration: Configuration) -> some View {
    if compact {
      configuration.icon
    } else {
      HStack(spacing: 6) {
        configuration.icon
        configuration.title
      }
    }
  }
}
