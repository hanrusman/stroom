import BackgroundTasks
import Combine
import UIKit
import UserNotifications

@MainActor
final class Notifications: ObservableObject {
  static let refreshID = "nl.c4w.stroom.refresh"
  @Published var rules: NotificationRules
  @Published var authorization: UNAuthorizationStatus = .notDetermined
  @Published var lastCheck: Date?
  @Published var schedulingMessage: String?
  private var checking = false
  private var revision = UUID()
  private let defaults: UserDefaults

  init(defaults: UserDefaults = .standard) {
    self.defaults = defaults
    rules =
      defaults.data(forKey: "notificationRules").flatMap {
        try? JSONDecoder().decode(NotificationRules.self, from: $0)
      } ?? NotificationRules()
    lastCheck = defaults.object(forKey: "notificationLastCheck") as? Date
  }
  func permissionStatus() async {
    authorization = await UNUserNotificationCenter.current().notificationSettings()
      .authorizationStatus
  }
  func save() async throws {
    revision = UUID()
    if rules.enabled || rules.dailyReminder {
      let granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [
        .alert, .sound,
      ])
      await permissionStatus()
      guard granted else {
        throw APIError.message(
          "Meldingen zijn uitgeschakeld. Sta ze toe via iPhone-instellingen → Stroom → Meldingen.")
      }
    }
    defaults.set(try JSONEncoder().encode(rules), forKey: "notificationRules")
    // Settings changes establish a fresh baseline to avoid retroactive alerts.
    defaults.removeObject(forKey: "notificationSnapshot")
    let center = UNUserNotificationCenter.current()
    center.removeAllPendingNotificationRequests()
    if rules.dailyReminder {
      let content = UNMutableNotificationContent()
      content.title = "Even tijd voor Stroom"
      content.body = "Ontdek je onderwerpen of luister verder met een podcast."
      content.sound = .default
      content.userInfo = ["destination": "feed"]
      let trigger = UNCalendarNotificationTrigger(
        dateMatching: DateComponents(hour: rules.reminderHour, minute: rules.reminderMinute),
        repeats: true)
      try await center.add(
        UNNotificationRequest(identifier: "daily-reminder", content: content, trigger: trigger))
    }
    scheduleRefresh()
  }
  func scheduleRefresh() {
    BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: Self.refreshID)
    guard rules.enabled else { return }
    let request = BGAppRefreshTaskRequest(identifier: Self.refreshID)
    request.earliestBeginDate = Date(timeIntervalSinceNow: 30 * 60)
    do {
      try BGTaskScheduler.shared.submit(request)
      schedulingMessage = nil
    } catch {
      schedulingMessage =
        "Verversen is nu niet beschikbaar. Controleer ‘Ververs op achtergrond’ in de iPhone-instellingen."
    }
  }
  func check(api: APIClient) async throws {
    guard rules.enabled, !checking else { return }
    checking = true
    defer { checking = false }
    let ticket = revision
    let currentRules = rules
    var items: [FeedItem] = []
    if currentRules.topicSlugs.isEmpty {
      items = try await api.items(limit: 500)
    } else {
      for slug in currentRules.topicSlugs.sorted() {
        try Task.checkCancellation()
        items += try await api.items(topic: slug, limit: 500)
      }
    }
    var unique: [String: FeedItem] = [:]
    items.forEach { unique[$0.id] = $0 }
    let jobs: [PodcastJob] =
      currentRules.generatedPodcasts ? try await api.request("podcast-tests") : []
    try Task.checkCancellation()
    guard revision == ticket else { return }
    var snapshot =
      defaults.data(forKey: "notificationSnapshot").flatMap {
        try? JSONDecoder().decode(NotificationSnapshot.self, from: $0)
      } ?? NotificationSnapshot()
    let fresh = snapshot.ingest(items: Array(unique.values), jobs: jobs, rules: currentRules)
    let count = fresh.items.count + fresh.jobs.count
    if count > 0 {
      let content = UNMutableNotificationContent()
      content.title = count == 1 ? "Nieuw in Stroom" : "\(count) nieuwe updates in Stroom"
      let titles =
        fresh.jobs.map { "Podcast klaar: \(String($0.text.prefix(60)))" }
        + fresh.items.sorted { ($0.publishedAt ?? "") > ($1.publishedAt ?? "") }.map(\.title)
      content.body = titles.prefix(3).joined(separator: "\n")
      content.sound = .default
      content.threadIdentifier = "stroom-updates"
      if count == 1, let item = fresh.items.first {
        content.userInfo = ["itemID": item.id]
      } else {
        content.userInfo = ["destination": fresh.jobs.isEmpty ? "feed" : "podcasts"]
      }
      var trigger: UNNotificationTrigger?
      if currentRules.isQuiet(at: Date()) {
        let next = Calendar.current.nextDate(
          after: Date(), matching: DateComponents(hour: currentRules.quietEnd, minute: 0),
          matchingPolicy: .nextTime)!
        trigger = UNTimeIntervalNotificationTrigger(
          timeInterval: max(1, next.timeIntervalSinceNow), repeats: false)
      }
      // Coalesce bursts into one pending update, staying below iOS's pending-request limit.
      try await UNUserNotificationCenter.current().add(
        UNNotificationRequest(identifier: "content-update", content: content, trigger: trigger))
    }
    guard revision == ticket else { return }
    defaults.set(try JSONEncoder().encode(snapshot), forKey: "notificationSnapshot")
    lastCheck = Date()
    defaults.set(lastCheck, forKey: "notificationLastCheck")
  }
  func reset() {
    revision = UUID()
    rules.enabled = false
    rules.dailyReminder = false
    defaults.set(try? JSONEncoder().encode(rules), forKey: "notificationRules")
    defaults.removeObject(forKey: "notificationSnapshot")
    defaults.removeObject(forKey: "notificationLastCheck")
    lastCheck = nil
    BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: Self.refreshID)
    UNUserNotificationCenter.current().removeAllPendingNotificationRequests()
    UNUserNotificationCenter.current().removeAllDeliveredNotifications()
  }
}

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
  ) -> Bool {
    UNUserNotificationCenter.current().delegate = self
    BGTaskScheduler.shared.register(forTaskWithIdentifier: Notifications.refreshID, using: .main) {
      task in
      Task { @MainActor in
        let store = AppStore.shared
        store.notifications.scheduleRefresh()
        let work = Task { @MainActor in
          do {
            if let api = store.api {
              try await store.notifications.check(api: api)
            } else {
              task.setTaskCompleted(success: false)
              return
            }
            task.setTaskCompleted(success: true)
          } catch { task.setTaskCompleted(success: false) }
        }
        task.expirationHandler = { work.cancel() }
      }
    }
    return true
  }
  func userNotificationCenter(
    _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
  ) async {
    let info = response.notification.request.content.userInfo
    let item = info["itemID"] as? String
    let destination = info["destination"] as? String
    await MainActor.run {
      if let item { AppStore.shared.openItemID = item }
      AppStore.shared.tab = destination == "podcasts" ? 1 : 0
    }
  }
  func userNotificationCenter(
    _ center: UNUserNotificationCenter, willPresent notification: UNNotification
  ) async -> UNNotificationPresentationOptions {
    []  // The foreground already shows refreshed content.
  }
}
