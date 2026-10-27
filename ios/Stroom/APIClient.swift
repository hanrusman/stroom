import Foundation
import Security

enum APIError: LocalizedError {
  case invalidServer, unauthorized
  case response(Int)
  case http(Int, String)
  case message(String)
  var statusCode: Int? {
    switch self {
    case .response(let code), .http(let code, _): return code
    case .unauthorized: return 401
    default: return nil
    }
  }
  static func fromResponse(status: Int, data: Data) -> APIError {
    if status == 401 { return .unauthorized }
    let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    if let detail = json?["detail"] as? String, !detail.isEmpty {
      return .http(status, detail)
    }
    if let details = json?["detail"] as? [[String: Any]],
      let message = details.compactMap({ $0["msg"] as? String }).first(where: { !$0.isEmpty })
    {
      return .http(status, message)
    }
    return .response(status)
  }
  var errorDescription: String? {
    switch self {
    case .invalidServer:
      return "Gebruik een geldig HTTPS-adres zonder pad, bijvoorbeeld https://stroom.c4w.nl."
    case .unauthorized:
      return "Je sessie is verlopen of je inloggegevens kloppen niet. Log opnieuw in."
    case .response(let code): return "Stroom antwoordde met HTTP \(code). Probeer het opnieuw."
    case .http(_, let text): return text
    case .message(let text): return text
    }
  }
}

enum ServerAddress {
  static func parse(_ text: String) throws -> URL {
    guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
      url.scheme == "https", let host = url.host, !host.isEmpty,
      url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
      url.path.isEmpty || url.path == "/"
    else { throw APIError.invalidServer }
    return url
  }
  static func sameOrigin(_ a: URL, _ b: URL) -> Bool {
    a.scheme?.lowercased() == b.scheme?.lowercased() && a.host?.lowercased() == b.host?.lowercased()
      && (a.port ?? 443) == (b.port ?? 443)
  }
  static func media(_ raw: String, base: URL) throws -> URL {
    guard let url = URL(string: raw, relativeTo: base)?.absoluteURL,
      url.scheme == "https", url.host != nil, url.user == nil, url.password == nil
    else {
      throw APIError.message("Deze audio heeft geen geldig HTTPS-adres.")
    }
    return url
  }
}

// API requests must never redirect the session cookie to another origin.
final class SameOriginRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
  func urlSession(
    _ session: URLSession, task: URLSessionTask,
    willPerformHTTPRedirection response: HTTPURLResponse,
    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void
  ) {
    guard let original = task.originalRequest?.url, let next = request.url,
      ServerAddress.sameOrigin(original, next)
    else {
      completionHandler(nil)
      return
    }
    completionHandler(request)
  }
}

@MainActor
final class APIClient {
  let baseURL: URL
  private let session: URLSession
  private var cookie: String?
  static let decoder: JSONDecoder = {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return decoder
  }()

  init(baseURL: URL, configuration: URLSessionConfiguration = .ephemeral) {
    self.baseURL = baseURL
    cookie = KeychainSession.read(account: baseURL.absoluteString)
    let config = configuration
    config.httpShouldSetCookies = false
    config.httpCookieStorage = nil
    config.timeoutIntervalForRequest = 25
    config.timeoutIntervalForResource = 600
    session = URLSession(configuration: config, delegate: SameOriginRedirects(), delegateQueue: nil)
  }
  func request<T: Decodable>(
    _ path: String, query: [URLQueryItem] = [], method: String = "GET", body: [String: Any]? = nil
  ) async throws -> T {
    let data = try await data(path, query: query, method: method, body: body)
    return try Self.decoder.decode(T.self, from: data)
  }
  private func data(_ path: String, query: [URLQueryItem], method: String, body: [String: Any]?)
    async throws -> Data
  {
    var parts = URLComponents(
      url: baseURL.appendingPathComponent("api").appendingPathComponent(path),
      resolvingAgainstBaseURL: false)!
    if !query.isEmpty { parts.queryItems = query }
    var request = URLRequest(url: parts.url!)
    request.httpMethod = method
    request.timeoutInterval = Self.timeout(for: path)
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    if let cookie { request.setValue("stroom_session=\(cookie)", forHTTPHeaderField: "Cookie") }
    if let body {
      request.httpBody = try JSONSerialization.data(withJSONObject: body)
      request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    let (data, response) = try await session.data(for: request)
    guard let http = response as? HTTPURLResponse else { throw APIError.response(0) }
    guard (200..<300).contains(http.statusCode) else {
      throw APIError.fromResponse(status: http.statusCode, data: data)
    }
    if path == "auth/login", let fields = http.allHeaderFields as? [String: String],
      let sessionCookie = HTTPCookie.cookies(withResponseHeaderFields: fields, for: baseURL).first(
        where: { $0.name == "stroom_session" })
    {
      try KeychainSession.save(sessionCookie.value, account: baseURL.absoluteString)
      cookie = sessionCookie.value
    }
    return data
  }
  static func timeout(for path: String) -> TimeInterval {
    if path.hasSuffix("/lessons/distill") || path.hasSuffix("/expand") { return 480 }
    if path.hasSuffix("/ask") || path.hasSuffix("/summarize") { return 240 }
    return 25
  }
  func login(email: String, password: String) async throws -> StroomUser {
    clearSession()
    let result: UserResponse = try await request(
      "auth/login", method: "POST", body: ["email": email, "password": password])
    guard cookie != nil else { throw APIError.message("De server gaf geen sessiecookie terug.") }
    return result.user
  }
  func logout() async throws {
    _ = try await data("auth/logout", query: [], method: "POST", body: nil)
    clearSession()
  }
  func clearSession() {
    cookie = nil
    KeychainSession.delete(account: baseURL.absoluteString)
  }
  func items(
    topic: String? = nil, saved: Bool = false, offset: Int = 0, limit: Int = 100,
    filter: String = "all", window: String = "30d", format: String? = nil, source: String? = nil
  ) async throws -> [FeedItem] {
    var query = [
      URLQueryItem(name: "limit", value: String(limit)),
      URLQueryItem(name: "offset", value: String(offset)),
    ]
    query.append(URLQueryItem(name: "filter", value: saved ? "saved" : filter))
    if !saved { query.append(URLQueryItem(name: "window", value: window)) }
    if let format { query.append(URLQueryItem(name: "format", value: format)) }
    if let source { query.append(URLQueryItem(name: "source_id", value: source)) }
    if let topic { query.append(URLQueryItem(name: "topic", value: topic)) }
    return try await request("huygens/items", query: query)
  }
  func item(_ id: String) async throws -> FeedItem { try await request("huygens/items/\(id)") }
  func digest(topic: String, window: String) async throws -> Digest? {
    do {
      return try await request(
        "huygens/\(topic)/digest", query: [.init(name: "window", value: window)])
    } catch let error as APIError where error.statusCode == 404 {
      return nil
    }
  }
  func update(_ id: String, status: String) async throws -> FeedItem {
    try await request("huygens/items/\(id)/status", method: "POST", body: ["status": status])
  }
  func webCookie() -> HTTPCookie? {
    guard let cookie, let host = baseURL.host else { return nil }
    return HTTPCookie(properties: [
      .name: "stroom_session", .value: cookie, .domain: host,
      .path: "/", .secure: "TRUE", HTTPCookiePropertyKey("HttpOnly"): "TRUE",
    ])
  }
  func mediaRequest(_ url: URL) -> URLRequest {
    var request = URLRequest(url: url)
    // Never send Stroom credentials to a podcast publisher/CDN.
    if ServerAddress.sameOrigin(url, baseURL), let cookie {
      request.setValue("stroom_session=\(cookie)", forHTTPHeaderField: "Cookie")
    }
    return request
  }
  func downloadPrivate(_ url: URL) async throws -> (URL, URLResponse) {
    try await session.download(for: mediaRequest(url))
  }
}

enum KeychainSession {
  private static let service = "nl.c4w.stroom.session"
  private static func query(_ account: String) -> [String: Any] {
    [
      kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
      kSecAttrAccount as String: account,
    ]
  }
  static func read(account: String) -> String? {
    var q = query(account)
    q[kSecReturnData as String] = true
    var result: CFTypeRef?
    guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess,
      let data = result as? Data
    else { return nil }
    return String(data: data, encoding: .utf8)
  }
  static func save(_ value: String, account: String) throws {
    delete(account: account)
    var q = query(account)
    q[kSecValueData as String] = Data(value.utf8)
    q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    guard SecItemAdd(q as CFDictionary, nil) == errSecSuccess else {
      throw APIError.message("De sessie kon niet veilig worden opgeslagen.")
    }
  }
  static func delete(account: String) { SecItemDelete(query(account) as CFDictionary) }
}
