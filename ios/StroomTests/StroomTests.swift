import SwiftUI
import XCTest

@testable import Stroom

final class StroomTests: XCTestCase {
  @MainActor func testTopicRailsDecodeInEditorialOrder() throws {
    let json =
      #"{"slug":"ai","name":"AI","rails":[{"format":"video","items":[]},{"format":"podcast","items":[]},{"format":"article","items":[{"id":"a","title":"Artikel","source_name":"Bron","has_summary":true,"has_transcript":true}]}]}"#
    let topic = try APIClient.decoder.decode(HuygensTopic.self, from: Data(json.utf8))
    XCTAssertEqual(topic.orderedRails.map(\.format), ["article", "podcast", "video"])
    XCTAssertEqual(topic.orderedRails[0].items.first?.initialSection, "Samenvatting")
  }
  @MainActor func testFullArticleBodyAndSummaryStart() throws {
    var article = try item()
    article.format = "article"
    article.description = "Excerpt"
    article.transcript = "Volledige tekst"
    XCTAssertEqual(article.sourceBody, "Volledige tekst")
    article.transcript = "  "
    XCTAssertEqual(article.sourceBody, "Excerpt")
    article.hasSummary = false
    XCTAssertEqual(article.initialSection, "Bron")
    article.summary = "Een samenvatting"
    XCTAssertEqual(article.initialSection, "Samenvatting")
    article.format = "podcast"
    article.transcript = "Gesproken tekst"
    XCTAssertEqual(article.sourceBody, "Excerpt")
  }
  @MainActor func testPlaybackDefaultAndStoredSpeed() {
    let defaults = UserDefaults(suiteName: "StroomTests.speed")!
    defaults.removePersistentDomain(forName: "StroomTests.speed")
    XCTAssertEqual(AudioPlayer.savedSpeed(in: defaults), 1.7)
    defaults.set(2.3, forKey: "playbackSpeed")
    XCTAssertEqual(AudioPlayer.savedSpeed(in: defaults), 2.3)
    defaults.set(99, forKey: "playbackSpeed")
    XCTAssertEqual(AudioPlayer.savedSpeed(in: defaults), 1.7)
    XCTAssertEqual(AudioPlayer.playbackRates.count, 16)
    defaults.removePersistentDomain(forName: "StroomTests.speed")
  }
  @MainActor func testCompanionFieldsDecode() throws {
    let json =
      #"{"id":"p","title":"Podcast","source_name":"Bron","format":"podcast","processing_status":"summarize_queued","queue_position":3,"summary_model":"model-x","transcript_segments":[{"start":0,"end":12.5,"text":"Hallo","speaker":"A"}]}"#
    let value = try APIClient.decoder.decode(FeedItem.self, from: Data(json.utf8))
    XCTAssertTrue(value.isProcessing)
    XCTAssertEqual(value.queuePosition, 3)
    XCTAssertEqual(value.summaryModel, "model-x")
    XCTAssertEqual(value.transcriptSegments?.first?.end, 12.5)
    let answer = try APIClient.decoder.decode(
      ItemQuestion.self,
      from: Data(
        #"{"question":"Waarom?","answer":"Daarom","sources_used":["transcript","lessons"],"created_at":"2026-10-27T08:00:00Z"}"#
          .utf8))
    XCTAssertEqual(answer.sourcesUsed, ["transcript", "lessons"])
    XCTAssertNotNil(answer.createdAt.flatMap(StroomDate.parse))
    let lesson = try APIClient.decoder.decode(
      Lesson.self,
      from: Data(
        #"{"id":"l","title":"Les","body":"Tekst","vikunja_task_id":42,"source_name":"Bron"}"#.utf8))
    XCTAssertEqual(lesson.vikunjaTaskId, 42)
  }
  func testTranscriptActiveSegmentBoundariesAndGaps() {
    let segments = [
      TranscriptSegment(start: 0, end: 10, text: "Een"),
      TranscriptSegment(start: 12, end: 20, text: "Twee"),
    ]
    XCTAssertEqual(TranscriptSegment.activeIndex(in: segments, at: 9.9), 0)
    XCTAssertNil(TranscriptSegment.activeIndex(in: segments, at: 10))
    XCTAssertEqual(TranscriptSegment.activeIndex(in: segments, at: 12), 1)
    XCTAssertNil(TranscriptSegment.activeIndex(in: segments, at: 20))
  }
  @MainActor func testLongAIRequestsAndNormalReadsHaveSeparateTimeouts() {
    XCTAssertEqual(APIClient.timeout(for: "huygens/items/id/lessons/distill"), 480)
    XCTAssertEqual(APIClient.timeout(for: "lessons/id/expand"), 480)
    XCTAssertEqual(APIClient.timeout(for: "huygens/items/id/ask"), 240)
    XCTAssertEqual(APIClient.timeout(for: "huygens/items/id"), 25)
  }
  func testSearchHighlightDropsHTMLAndMarksEveryMatch() {
    let text = highlightedSnippet("Een <mark>idee</mark> &amp; nog een idee.<script>bad()</script>")
    XCTAssertEqual(String(text.characters), "Een idee & nog een idee.")
    XCTAssertEqual(text.runs.filter { $0.backgroundColor != nil }.count, 2)
  }
  @MainActor func testScoreDetailsDecodeAndTopicsUseNames() throws {
    let json =
      #"{"id":"a","title":"Artikel","source_name":"Bron","topics":["Wetenschap"],"quality_score_detail":{"quality":{"score10":8,"probabilities":{"Well-argued with specific insights":0.8}},"interest_weight":0.3,"calibration":{"method":"percentile","score":9,"percentile":0.9,"n":100,"days":30}}}"#
    let value = try APIClient.decoder.decode(FeedItem.self, from: Data(json.utf8))
    XCTAssertEqual(value.topics, ["Wetenschap"])
    XCTAssertEqual(value.qualityScoreDetail?.quality?.score10, 8)
    XCTAssertEqual(value.qualityScoreDetail?.calibration?.percentile, 0.9)
    let choices = try APIClient.decoder.decode(
      [TopicChoice].self, from: Data(#"[{"slug":"science","name":"Wetenschap"}]"#.utf8))
    XCTAssertEqual(choices.first?.slug, "science")
  }
  func testHTMLAndMarkdownExcerpts() {
    XCTAssertEqual(
      ContentText.excerpt("<p>Han&#x27;s idee &mdash; café &amp; thee&nbsp; &#128512;</p>"),
      "Han's idee — café & thee 😀")
    XCTAssertEqual(
      ContentText.excerpt("## Kop\n\nEen **goed** [idee](https://example.com)."),
      "Kop Een goed idee.")
    XCTAssertEqual(
      ContentText.excerpt("<p>Eerste</p><p>Tweede<br>Derde</p>"), "Eerste Tweede Derde")
    XCTAssertEqual(ContentText.excerpt("2 < 3 en 5 > 4"), "2 < 3 en 5 > 4")
    XCTAssertEqual(ContentText.excerpt("👩🏾‍💻 **café**"), "👩🏾‍💻 café")
    XCTAssertEqual(ContentText.excerpt(nil), "")
  }
  func testFeedMarkupNeverLeaksScriptsOrEncodedTags() {
    XCTAssertEqual(
      ContentText.excerpt(
        "<script>alert(1)</script><style>body{}</style><p>Lees dit<img src='x'></p>"), "Lees dit")
    XCTAssertEqual(ContentText.excerpt("&lt;p&gt;Hallo &amp;amp; dag&lt;/p&gt;"), "Hallo & dag")
    XCTAssertEqual(ContentText.excerpt("<a href='javascript:alert(1)'>Lees</a>"), "Lees")
    XCTAssertTrue(
      ContentText.markdown("<a href='https://example.com'>Lees</a>").contains(
        "[Lees](https://example.com)"))
  }
  let fixture =
    #"{"id":"abc","title":"Een podcast","description":null,"source_name":"De bron","source_id":"src","media_url":"https://cdn.example/episode.mp3","thumbnail_url":null,"source_image_url":null,"published_at":"2026-10-25 08:30:00.123456+00:00","format":"podcast","status":"new","processing_status":"ready","quality_score":8.4,"has_summary":true}"#
  @MainActor func item() throws -> FeedItem {
    try APIClient.decoder.decode(FeedItem.self, from: Data(fixture.utf8))
  }

  @MainActor func testExistingAPIContractDecodesSnakeCaseAndNullableFields() throws {
    let value = try item()
    XCTAssertEqual(value.sourceName, "De bron")
    XCTAssertEqual(value.mediaUrl, "https://cdn.example/episode.mp3")
    XCTAssertEqual(value.qualityScore, 8.4)
    XCTAssertNotNil(value.date)
    XCTAssertNotNil(value.track)
    XCTAssertNil(value.summary)
  }
  @MainActor func testArticleIsNeverInterpretedAsAudio() throws {
    var article = try item()
    article.format = "article"
    XCTAssertNil(article.track)
  }
  func testServerAddressRejectsCredentialsHTTPPathsAndQueries() throws {
    for address in [
      "http://example.com", "https://user:pass@example.com", "https://example.com/api",
      "https://example.com?q=a", "https://example.com#x", "file:///a",
    ] {
      XCTAssertThrowsError(try ServerAddress.parse(address), address)
    }
    XCTAssertEqual(try ServerAddress.parse(" https://example.com ").host, "example.com")
  }
  func testCredentialsAreScopedToExactOrigin() throws {
    let origin = try ServerAddress.parse("https://stroom.example")
    XCTAssertTrue(
      ServerAddress.sameOrigin(origin, URL(string: "https://stroom.example:443/api/audio")!))
    XCTAssertFalse(ServerAddress.sameOrigin(origin, URL(string: "https://cdn.example/audio")!))
    XCTAssertFalse(
      ServerAddress.sameOrigin(origin, URL(string: "https://stroom.example:444/audio")!))
    XCTAssertFalse(ServerAddress.sameOrigin(origin, URL(string: "http://stroom.example/audio")!))
  }
  func testRelativeProtectedAudioURLResolvesToServer() throws {
    let base = try ServerAddress.parse("https://stroom.example")
    XCTAssertEqual(
      try ServerAddress.media("/api/podcast-tests/123/audio", base: base).absoluteString,
      "https://stroom.example/api/podcast-tests/123/audio")
    XCTAssertThrowsError(try ServerAddress.media("javascript:alert(1)", base: base))
    XCTAssertThrowsError(try ServerAddress.media("http://cdn.example/a.mp3", base: base))
  }
  @MainActor func testNotificationBaselineDoesNotNotifyOldContent() throws {
    var snapshot = NotificationSnapshot()
    let first = try item()
    XCTAssertTrue(
      snapshot.ingest(items: [first], jobs: [], rules: NotificationRules()).items.isEmpty)
    XCTAssertTrue(snapshot.initialized)
    XCTAssertTrue(
      snapshot.ingest(items: [first], jobs: [], rules: NotificationRules()).items.isEmpty)
    let second = try APIClient.decoder.decode(
      FeedItem.self, from: Data(fixture.replacingOccurrences(of: "\"abc\"", with: "\"def\"").utf8))
    XCTAssertEqual(
      snapshot.ingest(items: [first, second], jobs: [], rules: NotificationRules()).items.map(\.id),
      ["def"])
    XCTAssertTrue(
      snapshot.ingest(items: [first, second], jobs: [], rules: NotificationRules()).items.isEmpty)
  }
  @MainActor func testNotificationFiltersExcludeLowUnscoredAndWrongFormats() throws {
    var rules = NotificationRules()
    rules.minimumScore = 8
    rules.formats = ["podcast"]
    var value = try item()
    XCTAssertTrue(rules.matches(value))
    value.qualityScore = nil
    XCTAssertFalse(rules.matches(value))
    value.qualityScore = 7
    XCTAssertFalse(rules.matches(value))
    value.qualityScore = 9
    value.format = "article"
    XCTAssertFalse(rules.matches(value))
  }
  func testQuietHoursCrossMidnight() {
    let rules = NotificationRules()
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0)!
    for (hour, quiet) in [(0, true), (7, true), (8, false), (21, false), (22, true), (23, true)] {
      let date = calendar.date(from: DateComponents(year: 2026, month: 10, day: 25, hour: hour))!
      XCTAssertEqual(rules.isQuiet(at: date, calendar: calendar), quiet)
    }
  }
  func testDaytimeAndDisabledQuietHours() {
    var rules = NotificationRules()
    rules.quietStart = 9
    rules.quietEnd = 17
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0)!
    let noon = calendar.date(from: DateComponents(year: 2026, month: 10, day: 25, hour: 12))!
    XCTAssertTrue(rules.isQuiet(at: noon, calendar: calendar))
    rules.quietEnabled = false
    XCTAssertFalse(rules.isQuiet(at: noon, calendar: calendar))
    rules.quietEnabled = true
    rules.quietEnd = 9
    XCTAssertFalse(rules.isQuiet(at: noon, calendar: calendar))
  }
  @MainActor func testPodcastNotifiesOnTransitionToReadyOnce() throws {
    let renderingJSON =
      #"{"id":"job","text":"Hello","model_name":"OmniVoice","status":"rendering","message":null,"audio_url":null}"#
    let readyJSON = renderingJSON.replacingOccurrences(of: "rendering", with: "ready")
      .replacingOccurrences(
        of: "\"audio_url\":null", with: "\"audio_url\":\"/api/podcast-tests/job/audio\"")
    let rendering = try APIClient.decoder.decode(PodcastJob.self, from: Data(renderingJSON.utf8))
    let ready = try APIClient.decoder.decode(PodcastJob.self, from: Data(readyJSON.utf8))
    var snapshot = NotificationSnapshot()
    XCTAssertNil(rendering.track)
    XCTAssertNotNil(ready.track)
    XCTAssertTrue(
      snapshot.ingest(items: [], jobs: [rendering], rules: NotificationRules()).jobs.isEmpty)
    XCTAssertEqual(
      snapshot.ingest(items: [], jobs: [ready], rules: NotificationRules()).jobs.count, 1)
    XCTAssertTrue(
      snapshot.ingest(items: [], jobs: [ready], rules: NotificationRules()).jobs.isEmpty)
  }
  func testNotificationPreferencesRoundTrip() throws {
    var rules = NotificationRules()
    rules.topicSlugs = ["ai", "tech"]
    rules.reminderMinute = 45
    XCTAssertEqual(
      try JSONDecoder().decode(NotificationRules.self, from: JSONEncoder().encode(rules)), rules)
  }
  func testPostgresDatesWithAndWithoutFractions() {
    XCTAssertNotNil(StroomDate.parse("2026-10-25 08:30:00+00:00"))
    XCTAssertNotNil(StroomDate.parse("2026-10-25T08:30:00.123456Z"))
    XCTAssertNil(StroomDate.parse("broken"))
  }
}
