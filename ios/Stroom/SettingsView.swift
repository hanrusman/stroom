import SwiftUI
import UserNotifications

struct SettingsView: View {
  @EnvironmentObject var store: AppStore
  @EnvironmentObject var notifications: Notifications
  @AppStorage("archiveAfterListening") private var archiveAfterListening = false
  @State private var rules = NotificationRules()
  @State private var message: String?
  @State private var saving = false
  @State private var confirmLogout = false
  var body: some View {
    Form {
      Section {
        Text("Maak ruimte voor wat telt.").font(.system(.title2, design: .serif))
        Text("Jij kiest wanneer Stroom je aandacht vraagt.").font(.subheadline).foregroundStyle(
          .secondary)
      }
      Section("Luisteren") {
        Toggle("Na afloop automatisch archiveren", isOn: $archiveAfterListening)
        Text(
          "Alleen bij volledig afgespeelde bronafleveringen. Zelfgemaakte podcasts blijven staan."
        ).font(.caption).foregroundStyle(.secondary)
      }
      Section {
        Toggle("Nieuwe inhoud melden", isOn: $rules.enabled)
        Text(
          "Stroom controleert bij openen en wanneer iOS verversen op de achtergrond toestaat. Dit zijn lokale meldingen; het tijdstip is niet gegarandeerd."
        ).font(.caption).foregroundStyle(.secondary)
        if notifications.authorization == .denied {
          Button("Sta meldingen toe in Instellingen") { openSystemSettings() }
        }
      } header: {
        Text("Meldingen op maat")
      }
      if rules.enabled {
        Section {
          ForEach(store.topics) { topic in
            Toggle(
              topic.name,
              isOn: Binding(
                get: { rules.topicSlugs.contains(topic.slug) },
                set: { value in
                  if value {
                    rules.topicSlugs.insert(topic.slug)
                  } else {
                    rules.topicSlugs.remove(topic.slug)
                  }
                }))
          }
        } header: {
          Text("Onderwerpen")
        } footer: {
          Text("Geen selectie betekent alle onderwerpen. Gegenereerde podcasts staan hier los van.")
        }
        Section("Wat wil je volgen?") {
          formatToggle("Podcasts", value: "podcast")
          formatToggle("Artikelen", value: "article")
          formatToggle("Video’s", value: "video")
          Toggle("Eigen podcast klaar", isOn: $rules.generatedPodcasts)
          VStack(alignment: .leading) {
            Text(
              rules.minimumScore == 0
                ? "Alle scores" : "Minimale score: \(rules.minimumScore.formatted())")
            Slider(value: $rules.minimumScore, in: 0...10, step: 1)
          }
        }
        Section("Rusturen") {
          Toggle("Stil tijdens rusturen", isOn: $rules.quietEnabled)
          if rules.quietEnabled {
            Picker("Vanaf", selection: $rules.quietStart) { hours }
            Picker("Tot", selection: $rules.quietEnd) { hours }
            Text(
              "Inhoudsmeldingen worden uitgesteld tot na je rusturen. De dagelijkse herinnering volgt zijn eigen tijdstip."
            ).font(.caption).foregroundStyle(.secondary)
          }
        }
      }
      Section {
        Toggle("Dagelijkse herinnering", isOn: $rules.dailyReminder)
        if rules.dailyReminder {
          DatePicker(
            "Tijdstip",
            selection: Binding(
              get: {
                Calendar.current.date(
                  from: DateComponents(hour: rules.reminderHour, minute: rules.reminderMinute))
                  ?? Date()
              },
              set: {
                rules.reminderHour = Calendar.current.component(.hour, from: $0)
                rules.reminderMinute = Calendar.current.component(.minute, from: $0)
              }), displayedComponents: .hourAndMinute)
        }
        Text(
          "Een vast lees- of luistermoment. Deze herinnering wordt lokaal gepland en controleert niet of er nieuwe inhoud is."
        ).font(.caption).foregroundStyle(.secondary)
      } header: {
        Text("Een moment voor jezelf")
      }
      Section {
        Button {
          saving = true
          message = nil
          Task {
            let previous = notifications.rules
            notifications.rules = rules
            do {
              try await notifications.save()
              if let api = store.api {
                do { try await notifications.check(api: api) } catch {
                  notifications.schedulingMessage =
                    "Voorkeuren opgeslagen; eerste controle mislukt: \(error.localizedDescription)"
                }
              }
              message = "Opgeslagen. De huidige inhoud is het startpunt voor nieuwe meldingen."
            } catch {
              notifications.rules = previous
              message = error.localizedDescription
            }
            saving = false
          }
        } label: {
          HStack {
            Text("Bewaar meldingsvoorkeuren")
            Spacer()
            if saving { ProgressView() } else { Image(systemName: "checkmark.circle") }
          }
        }.disabled(saving || store.demo)
        if let message { Text(message).font(.caption).foregroundStyle(.secondary) }
        if let date = notifications.lastCheck {
          LabeledContent(
            "Laatst gecontroleerd", value: date.formatted(date: .abbreviated, time: .shortened)
          ).font(.caption)
        }
        if let message = notifications.schedulingMessage {
          Text(message).font(.caption).foregroundStyle(.orange)
        }
      }
      Section("Verbinding") {
        LabeledContent("Account", value: store.user?.email ?? "—")
        Text(store.server).font(.caption).foregroundStyle(.secondary)
        if let date = store.lastSync {
          LabeledContent("Bijgewerkt", value: date.formatted(date: .abbreviated, time: .shortened))
            .font(.caption)
        }
        Button("Alles verversen") { Task { await store.refresh() } }
        if let error = store.error { Text(error).font(.caption).foregroundStyle(.red) }
        Button("Uitloggen", role: .destructive) { confirmLogout = true }.disabled(
          store.busy || store.demo)
      }
      Section("Over deze app") {
        Text("Stroom voor iPhone · 1.0").font(.subheadline)
        Text(
          "Je website en app delen dezelfde inhoud en bewaarde items. Downloads, luisterposities, wachtrij en meldingsvoorkeuren zijn lokaal op dit apparaat."
        ).font(.caption).foregroundStyle(.secondary)
      }
    }.scrollContentBackground(.hidden).background(Brand.paper).navigationTitle("Jouw Stroom")
      .onAppear { rules = notifications.rules }
      .confirmationDialog(
        "Uitloggen verwijdert de offline audio van deze iPhone. Je inhoud op Stroom blijft bewaard.",
        isPresented: $confirmLogout, titleVisibility: .visible
      ) { Button("Uitloggen", role: .destructive) { Task { await store.logout() } } }
  }
  @ViewBuilder var hours: some View {
    ForEach(0..<24, id: \.self) { hour in Text(String(format: "%02d:00", hour)).tag(hour) }
  }
  func formatToggle(_ title: String, value: String) -> some View {
    Toggle(
      title,
      isOn: Binding(
        get: { rules.formats.contains(value) },
        set: { enabled in
          if enabled { rules.formats.insert(value) } else { rules.formats.remove(value) }
        }))
  }
  func openSystemSettings() {
    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
  }
}
