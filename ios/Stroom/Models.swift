import Foundation

struct StroomUser: Codable { let id: String; let email: String }
struct UserResponse: Decodable { let user: StroomUser }
struct Topic: Codable, Identifiable, Hashable {
    let slug: String
    let name: String
    let itemCount: Int
    var id: String { slug }
}
struct FeedItem: Codable, Identifiable, Hashable {
    let id: String
    var title: String
    var description: String?
    var sourceName: String
    var sourceId: String?
    var mediaUrl: String?
    var thumbnailUrl: String?
    var sourceImageUrl: String?
    var publishedAt: String?
    var format: String?
    var status: String?
    var processingStatus: String?
    var qualityScore: Double?
    var hasSummary: Bool?
    var summary: String?
    var transcript: String?
    var topics: [String]?
    var sourceUrl: String?
    var scheduledFor: String?
    var isPodcast: Bool { format == "podcast" }
    var artwork: String? { thumbnailUrl ?? sourceImageUrl }
    var track: AudioTrack? {
        guard isPodcast, let mediaUrl, !mediaUrl.isEmpty else { return nil }
        return AudioTrack(id: id, title: title, author: sourceName, url: mediaUrl, artwork: artwork)
    }
    var date: Date? { publishedAt.flatMap(StroomDate.parse) }
}
struct PodcastJob: Decodable, Identifiable {
    let id: String
    let text: String
    let modelName: String
    let status: String
    let message: String?
    let audioUrl: String?
    var track: AudioTrack? {
        guard status == "ready", let audioUrl else { return nil }
        return AudioTrack(id: "generated-\(id)", title: String(text.prefix(90)), author: "Stroom · \(modelName)", url: audioUrl, artwork: nil)
    }
}
struct AudioTrack: Codable, Identifiable, Equatable, Hashable {
    let id: String
    let title: String
    let author: String
    let url: String
    let artwork: String?
}
struct Digest: Decodable {
    let markdown: String?
    let generatedAt: String?
    let isGenerating: Bool
}
struct SearchHit: Decodable, Identifiable {
    let id: String
    let title: String
    let sourceName: String
    let format: String
}

enum StroomDate {
    static func parse(_ value: String) -> Date? {
        let normalized = value.replacingOccurrences(of: " ", with: "T")
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: normalized) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: normalized)
    }
}

struct NotificationRules: Codable, Equatable {
    var enabled = false
    var topicSlugs: Set<String> = [] // Empty means every topic.
    var formats: Set<String> = ["podcast", "article", "video"]
    var minimumScore: Double = 0
    var generatedPodcasts = true
    var quietEnabled = true
    var quietStart = 22
    var quietEnd = 8
    var dailyReminder = false
    var reminderHour = 8
    var reminderMinute = 0

    func matches(_ item: FeedItem) -> Bool {
        formats.contains(item.format ?? "") && (minimumScore == 0 || (item.qualityScore ?? -1) >= minimumScore)
    }
    func isQuiet(at date: Date, calendar: Calendar = .current) -> Bool {
        guard quietEnabled, quietStart != quietEnd else { return false }
        let hour = calendar.component(.hour, from: date)
        return quietStart < quietEnd ? (quietStart..<quietEnd).contains(hour) : hour >= quietStart || hour < quietEnd
    }
}

struct NotificationSnapshot: Codable {
    var itemIds: Set<String> = []
    var readyJobIds: Set<String> = []
    var initialized = false
    // Keep only the current window. Initial sync establishes a baseline, never a flood.
    mutating func ingest(items: [FeedItem], jobs: [PodcastJob], rules: NotificationRules) -> (items: [FeedItem], jobs: [PodcastJob]) {
        let fresh = initialized ? items.filter { !itemIds.contains($0.id) && rules.matches($0) } : []
        let ready = jobs.filter { $0.status == "ready" }
        let newJobs = initialized && rules.generatedPodcasts ? ready.filter { !readyJobIds.contains($0.id) } : []
        itemIds = Set(items.map(\.id))
        readyJobIds = Set(ready.map(\.id))
        initialized = true
        return (fresh, newJobs)
    }
}

struct ActionOK: Decodable { let ok: Bool }
struct Lesson: Decodable, Identifiable {
    let id: String; let title: String; let body: String; var rating: Int?
    var expansion: String?
}
struct ItemQuestion: Decodable, Identifiable {
    var id: String?; let question: String; let answer: String; var model: String?
}
