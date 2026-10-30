import Combine
import CryptoKit
import Foundation

@MainActor
final class LibraryStore: ObservableObject {
  @Published private(set) var downloads: [AudioTrack] = []
  @Published private(set) var downloading: Set<String> = []
  private let directory: URL
  private var tasks: [String: Task<Void, Error>] = [:]
  private var generation = UUID()

  init(directory: URL? = nil) {
    self.directory =
      directory
      ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("Audio", isDirectory: true)
    do {
      try FileManager.default.createDirectory(at: self.directory, withIntermediateDirectories: true)
      var url = self.directory
      var values = URLResourceValues()
      values.isExcludedFromBackup = true
      try url.setResourceValues(values)
      if let data = try? Data(contentsOf: self.directory.appendingPathComponent("library.json")) {
        downloads = try JSONDecoder().decode([AudioTrack].self, from: data)
        downloads = downloads.filter { localURL(for: $0) != nil }
      }
    } catch { downloads = [] }
  }
  private func fileURL(_ track: AudioTrack) -> URL {
    let key = SHA256.hash(data: Data(track.id.utf8)).map { String(format: "%02x", $0) }.joined()
    return directory.appendingPathComponent(key).appendingPathExtension("mp3")
  }
  func localURL(for track: AudioTrack) -> URL? {
    let url = fileURL(track)
    return FileManager.default.fileExists(atPath: url.path) ? url : nil
  }
  func download(_ track: AudioTrack, api: APIClient) async throws {
    if localURL(for: track) != nil { return }
    if let task = tasks[track.id] { return try await task.value }
    let ticket = generation
    let task = Task { @MainActor in
      downloading.insert(track.id)
      defer {
        downloading.remove(track.id)
        tasks[track.id] = nil
      }
      let url = try ServerAddress.media(track.url, base: api.baseURL)
      let temporary: URL
      let response: URLResponse
      if ServerAddress.sameOrigin(url, api.baseURL) {
        (temporary, response) = try await api.downloadPrivate(url)
      } else {
        // No shared cookie storage for third-party audio; normal CDN redirects work.
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }
        (temporary, response) = try await session.download(from: url)
      }
      defer { try? FileManager.default.removeItem(at: temporary) }
      try Task.checkCancellation()
      guard generation == ticket else { throw CancellationError() }
      guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
        throw APIError.message(
          "De audio kon niet worden gedownload. Log opnieuw in als je sessie verlopen is.")
      }
      let mime = response.mimeType ?? ""
      guard !mime.contains("mpegurl"), url.pathExtension.lowercased() != "m3u8",
        mime.hasPrefix("audio/") || mime == "application/octet-stream" || mime == "video/mp4"
      else {
        throw APIError.message("Deze URL levert geen downloadbaar audiobestand op (\(mime)).")
      }
      try FileManager.default.moveItem(at: temporary, to: fileURL(track))
      try FileManager.default.setAttributes(
        [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
        ofItemAtPath: fileURL(track).path)
      downloads.removeAll { $0.id == track.id }
      downloads.insert(track, at: 0)
      try persist()
    }
    tasks[track.id] = task
    try await task.value
  }
  func remove(_ track: AudioTrack) throws {
    if let url = localURL(for: track) { try FileManager.default.removeItem(at: url) }
    downloads.removeAll { $0.id == track.id }
    try persist()
  }
  func clear() throws {
    generation = UUID()
    tasks.values.forEach { $0.cancel() }
    for track in downloads {
      if let url = localURL(for: track) { try FileManager.default.removeItem(at: url) }
    }
    downloads = []
    try persist()
  }
  private func persist() throws {
    try JSONEncoder().encode(downloads).write(
      to: directory.appendingPathComponent("library.json"),
      options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
  }
}
