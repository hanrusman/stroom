import SwiftUI

struct ItemActions: ViewModifier {
  @EnvironmentObject var store: AppStore
  let item: FeedItem
  func body(content: Content) -> some View {
    content
      .swipeActions(edge: .leading, allowsFullSwipe: true) {
        if item.status != "archived" {
          Button {
            Task { await store.archive(item) }
          } label: {
            Label("Archiveer", systemImage: "archivebox")
          }.accessibilityIdentifier("archive-\(item.id)").tint(.orange).disabled(
            store.changing.contains(item.id))
        }
      }
      .swipeActions(edge: .trailing, allowsFullSwipe: true) {
        if item.status != "archived" {
          Button {
            Task { await store.setQueued(item, queued: !store.queuedIDs.contains(item.id)) }
          } label: {
            Label(
              store.queuedIDs.contains(item.id) ? "Uit wachtrij" : "In wachtrij",
              systemImage: "text.badge.plus")
          }
          .accessibilityIdentifier("queue-\(item.id)").tint(Brand.blue).disabled(
            store.changing.contains(item.id))
        }
      }
      .contextMenu {
        Button("Open") { store.openItemID = item.id }
        Button(item.status == "pinned" ? "Niet meer bewaren" : "Bewaren", systemImage: "bookmark") {
          Task { await store.setStatus(item, to: item.status == "pinned" ? "new" : "pinned") }
        }
        Button("Later (geen datum)", systemImage: "clock") {
          Task { await store.plan(item, date: nil, later: true) }
        }
        Button("Samenvatten", systemImage: "sparkles") {
          Task { await store.process(item, action: "summarize") }
        }.disabled(item.isProcessing)
        if item.format == "podcast" || item.format == "video" {
          Button("Transcriberen", systemImage: "waveform") {
            Task { await store.process(item, action: "transcribe") }
          }.disabled(item.isProcessing)
        }
        if item.status != "archived" {
          Button(
            store.queuedIDs.contains(item.id) ? "Uit wachtrij" : "In wachtrij",
            systemImage: "text.badge.plus"
          ) {
            Task { await store.setQueued(item, queued: !store.queuedIDs.contains(item.id)) }
          }
          Button("Archiveren", systemImage: "archivebox") { Task { await store.archive(item) } }
        }
      }.disabled(store.changing.contains(item.id))
  }
}
extension View {
  func stroomActions(_ item: FeedItem) -> some View { modifier(ItemActions(item: item)) }
}
struct ActionFeedback: View {
  @EnvironmentObject var store: AppStore
  var body: some View {
    if let text = store.actionError ?? store.actionMessage {
      HStack {
        Text(text).font(.caption).foregroundStyle(store.actionError == nil ? Color.primary : .red)
        Spacer()
        if store.canUndo {
          Button("Herstel") { Task { await store.undoArchive() } }.font(.caption.weight(.semibold))
        }
        Button {
          store.dismissActionFeedback()
        } label: {
          Image(systemName: "xmark").frame(width: 36, height: 36)
        }.accessibilityLabel("Melding sluiten")
      }.padding(.horizontal, 16).background(.regularMaterial)
    }
  }
}
struct ReadingQueueView: View {
  @EnvironmentObject var store: AppStore
  @State private var loading = false
  var body: some View {
    List {
      Section {
        Text(
          "Lezen, kijken en luisteren. Eerst toegevoegd staat bovenaan; dezelfde lijst op je iPhone en website."
        ).font(.subheadline).foregroundStyle(.secondary)
        if let message = store.queueError {
          ErrorNotice(message: message) { await store.refreshQueue() }
        }
      }
      if store.queueItems.isEmpty && store.queueError == nil {
        ContentUnavailableView(
          "Ruimte voor je volgende idee", systemImage: "text.badge.plus",
          description: Text("Veeg een artikel naar links of kies ‘In wachtrij’ in de reader."))
      }
      ForEach(store.queueItems.map(store.current)) { item in
        FeedCard(item: item).listRowInsets(EdgeInsets()).stroomActions(item)
      }
      if store.queueItems.count < store.queuedIDs.count {
        Button("Meer ophalen") { Task { await more() } }.disabled(loading)
      }
    }.navigationTitle("Wachtrij").scrollContentBackground(.hidden).background(Brand.paper)
      .task { await store.refreshQueue() }.refreshable { await store.refreshQueue() }
  }
  func more() async {
    guard let api = store.api else { return }
    loading = true
    defer { loading = false }
    do {
      let rows: [FeedItem] = try await api.request(
        "reading-queue", query: [.init(name: "offset", value: "\(store.queueItems.count)")])
      let ids = Set(store.queueItems.map(\.id))
      store.queueItems += rows.filter { !ids.contains($0.id) }
    } catch { store.queueError = error.localizedDescription }
  }
}
