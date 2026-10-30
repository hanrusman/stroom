import AppIntents
import SwiftUI

struct InboxPreview: Decodable {
  let url: String
  let title: String?
  let description: String?
  let author: String?
  let format: String
}
struct InboxResult: Decodable {
  let id: String
  let title: String
  let message: String
}
enum IncomingLink {
  static func validated(_ raw: String) -> URL? {
    guard let url = URL(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
      ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
      url.host?.isEmpty == false, url.user == nil, url.password == nil
    else { return nil }
    return url
  }
  static func submission(from url: URL) -> URL? {
    guard url.scheme == "stroom", url.host == "submit",
      let value = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(
        where: { $0.name == "url" })?.value
    else { return nil }
    return validated(value)
  }
}
struct OpenStroomInbox: AppIntent {
  static var title: LocalizedStringResource = "Open link in Stroom"
  static var description = IntentDescription(
    "Open een gedeelde link in het Stroom-instuurformulier. Controleer de titel en het onderwerp voordat je instuurt."
  )
  static var openAppWhenRun = true
  @Parameter(title: "Link") var link: URL
  @MainActor func perform() async throws -> some IntentResult {
    guard let url = IncomingLink.validated(link.absoluteString) else {
      throw APIError.message("Kies een geldige web-link.")
    }
    AppStore.shared.incomingURL = url.absoluteString
    return .result()
  }
}
struct StroomShortcuts: AppShortcutsProvider {
  static var appShortcuts: [AppShortcut] {
    AppShortcut(
      intent: OpenStroomInbox(), phrases: ["Bewaar een link in \(.applicationName)"],
      shortTitle: "Stuur naar Stroom", systemImageName: "tray.and.arrow.down")
  }
}
struct SubmitView: View {
  @EnvironmentObject var store: AppStore
  @Environment(\.dismiss) var dismiss
  @State private var url: String
  @State private var title = ""
  @State private var description = ""
  @State private var format = "article"
  @State private var topic = ""
  @State private var topics: [TopicChoice] = []
  @State private var busy = false
  @State private var error: String?
  @State private var result: InboxResult?
  @FocusState private var editing: Bool
  let presentedAsSheet: Bool
  init(initialURL: String = "", presentedAsSheet: Bool = false) {
    _url = State(initialValue: initialURL)
    self.presentedAsSheet = presentedAsSheet
  }
  var body: some View {
    Form {
      if let result {
        Section {
          Label("Toegevoegd aan Stroom", systemImage: "checkmark.circle.fill").foregroundStyle(
            .green)
          Text(result.title).font(.headline)
          Text(result.message)
          Button("Gereed") { dismiss() }
        }
      } else {
        Section("Link") {
          TextField("https://…", text: $url).textContentType(.URL).keyboardType(.URL)
            .focused($editing)
            .autocorrectionDisabled().textInputAutocapitalization(.never)
            .accessibilityIdentifier("submit-url")
          Button("Haal titel en beschrijving op", systemImage: "arrow.down.doc") {
            Task { await preview() }
          }
          .disabled(busy || IncomingLink.validated(url) == nil)
        }
        Section("Controleer voor je instuurt") {
          TextField("Titel", text: $title, axis: .vertical).focused($editing)
            .accessibilityIdentifier("submit-title")
          Picker("Soort", selection: $format) {
            Text("Artikel").tag("article")
            Text("Podcast").tag("podcast")
            Text("Video").tag("video")
          }
          Picker("Onderwerp", selection: $topic) {
            Text("Kies een onderwerp").tag("")
            ForEach(topics) { Text($0.name).tag($0.slug) }
          }
          TextField("Beschrijving (optioneel)", text: $description, axis: .vertical).focused(
            $editing
          ).lineLimit(
            3...6)
        }
        Section {
          Button("Stuur naar Stroom", systemImage: "tray.and.arrow.down") {
            Task { await submit() }
          }
          .disabled(
            busy || IncomingLink.validated(url) == nil
              || title.trimmingCharacters(in: .whitespacesAndNewlines).count < 3 || topic.isEmpty)
          if busy { ProgressView("Bezig…") }
          if let error { Text(error).foregroundStyle(.red) }
        } footer: {
          Text(
            "Stroom haalt de bron op en zet de verwerking in de wachtrij. Een link delen opent alleen dit formulier; jij bevestigt het insturen."
          )
        }
      }
    }.navigationTitle("Content insturen").navigationBarTitleDisplayMode(.inline)
      .disabled(busy)
      .scrollDismissesKeyboard(.interactively)
      .toolbar {
        if presentedAsSheet {
          ToolbarItem(placement: .cancellationAction) { Button("Sluiten") { dismiss() } }
        }
        ToolbarItemGroup(placement: .keyboard) {
          Spacer()
          Button("Gereed") { editing = false }
        }
      }
      .task {
        if store.demo {
          topics = store.topics.map { TopicChoice(slug: $0.slug, name: $0.name) }
        } else if let api = store.api {
          do { topics = try await api.request("inbox/topics") } catch {
            self.error = error.localizedDescription
          }
        }
        topic =
          topics.first(where: { $0.slug == store.selectedTopic })?.slug ?? topics.first?.slug ?? ""
      }
  }
  func preview() async {
    guard let api = store.api, let link = IncomingLink.validated(url) else { return }
    editing = false
    busy = true
    error = nil
    defer { busy = false }
    do {
      let value: InboxPreview
      if store.demo {
        value = InboxPreview(
          url: link.absoluteString, title: "Een gedeeld idee",
          description: "Voorbeeld van een gedeelde link.", author: nil, format: "article")
      } else {
        value = try await api.request(
          "inbox/fetch", method: "POST", body: ["url": link.absoluteString])
      }
      title = value.title ?? title
      description = value.description ?? description
      format = value.format
    } catch {
      self.error =
        "Ophalen mislukt. Je kunt titel en soort ook zelf invullen. \(error.localizedDescription)"
    }
  }
  func submit() async {
    guard let api = store.api, let link = IncomingLink.validated(url), !busy else { return }
    editing = false
    busy = true
    error = nil
    defer { busy = false }
    do {
      if store.demo {
        result = InboxResult(
          id: "demo-2", title: title, message: "Voorbeeld · er is niets naar de server verstuurd.")
      } else {
        result = try await api.request(
          "inbox/submit", method: "POST",
          body: [
            "url": link.absoluteString,
            "title": title.trimmingCharacters(in: .whitespacesAndNewlines), "format": format,
            "topic_slug": topic, "description": description,
          ])
      }
    } catch { self.error = error.localizedDescription }
  }
}
