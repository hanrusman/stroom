import SwiftUI
import WebKit

func stroomURL(server: String, query: [String: String]) -> URL? {
  guard let base = try? ServerAddress.parse(server),
    var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)
  else { return nil }
  parts.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
  return parts.url
}
struct MoreView: View {
  @EnvironmentObject var store: AppStore
  var body: some View {
    List {
      EditorialHeader(eyebrow: "Van nieuwsgierigheid naar inzicht", title: "Meer Stroom")
        .listRowBackground(Color.clear)
      Section("Ontdekken & verdiepen") {
        NavigationLink {
          TipsView()
        } label: {
          Label("Tips uit podcasts en video’s", systemImage: "lightbulb")
        }
        NavigationLink {
          AllLessonsView()
        } label: {
          Label("Alle lessen", systemImage: "book.closed")
        }
        webLink("Podcast maken uit tekst", symbol: "waveform", query: ["podcast": "1"])
        NavigationLink {
          SubmitView()
        } label: {
          Label("Content insturen", systemImage: "tray.and.arrow.down")
        }
        webLink("Volledige website", symbol: "globe", query: [:])
      }
      Section {
        webLink(
          "Bronnen, onderwerpen en modellen", symbol: "antenna.radiowaves.left.and.right",
          query: ["admin": "1"])
        NavigationLink {
          SettingsView()
        } label: {
          Label("Instellingen en meldingen", systemImage: "slider.horizontal.3")
        }
      } header: {
        Text("Jouw Stroom")
      } footer: {
        Text(
          "Podcastgeneratie en beheer openen de volledige Stroom-website binnen de app, met je bestaande sessie."
        )
      }
    }.navigationTitle("Meer").navigationBarTitleDisplayMode(.inline)
      .listRowSpacing(4).scrollContentBackground(.hidden).background(Brand.paper)
  }
  @ViewBuilder func webLink(_ title: String, symbol: String, query: [String: String]) -> some View {
    if let url = stroomURL(server: store.server, query: query) {
      NavigationLink {
        StroomWebView(url: url).navigationTitle(title).navigationBarTitleDisplayMode(.inline)
      } label: {
        Label(title, systemImage: symbol)
      }
    }
  }
}

/// Web-only workflows share the current session in a private, in-memory web store.
/// Cookies are host-scoped. External navigation always leaves this web view.
struct StroomWebView: UIViewRepresentable {
  @EnvironmentObject var store: AppStore
  let url: URL
  func makeCoordinator() -> Coordinator { Coordinator(base: url) }
  func makeUIView(context: Context) -> WKWebView {
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .nonPersistent()
    config.allowsInlineMediaPlayback = true
    let view = WKWebView(frame: .zero, configuration: config)
    view.navigationDelegate = context.coordinator
    view.uiDelegate = context.coordinator
    view.allowsBackForwardNavigationGestures = true
    if store.demo {
      view.loadHTMLString(
        "<meta name='viewport' content='width=device-width'><p style='font:20px system-ui;padding:24px'>Deze functie is beschikbaar wanneer je inlogt met je Stroom-account.</p>",
        baseURL: nil)
    } else if let cookie = store.api?.webCookie() {
      config.websiteDataStore.httpCookieStore.setCookie(cookie) { view.load(URLRequest(url: url)) }
    } else {
      view.load(URLRequest(url: url))
    }
    return view
  }
  func updateUIView(_ view: WKWebView, context: Context) {}
  class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
    let base: URL
    init(base: URL) { self.base = base }
    func webView(
      _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
      decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
      guard let url = navigationAction.request.url else {
        decisionHandler(.cancel)
        return
      }
      if url.scheme == "about" || ServerAddress.sameOrigin(url, base) {
        decisionHandler(.allow)
      } else {
        decisionHandler(.cancel)
        if ["https", "http", "mailto"].contains(url.scheme ?? ""),
          navigationAction.targetFrame?.isMainFrame != false
        {
          UIApplication.shared.open(url)
        }
      }
    }
    func webView(
      _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
      for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
      if let url = navigationAction.request.url {
        if ServerAddress.sameOrigin(url, base) {
          webView.load(URLRequest(url: url))
        } else if ["https", "http", "mailto"].contains(url.scheme ?? "") {
          UIApplication.shared.open(url)
        }
      }
      return nil
    }
    func webView(
      _ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
      withError error: Error
    ) {
      guard (error as NSError).code != NSURLErrorCancelled else { return }
      webView.loadHTMLString(
        "<meta name='viewport' content='width=device-width'><p style='font:20px system-ui;padding:24px'>Stroom kon niet worden geladen. Controleer je verbinding en open deze pagina opnieuw.</p>",
        baseURL: nil)
    }
  }
}
