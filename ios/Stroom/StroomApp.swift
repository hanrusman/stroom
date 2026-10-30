import SwiftUI

@main
struct StroomApp: App {
  @UIApplicationDelegateAdaptor(AppDelegate.self) var delegate
  @StateObject private var store = AppStore.shared
  @Environment(\.scenePhase) private var scenePhase
  var body: some Scene {
    WindowGroup {
      RootView().environmentObject(store).environmentObject(store.player).environmentObject(
        store.library
      )
      .environmentObject(store.notifications)
      .tint(Brand.blue)
        .preferredColorScheme(store.demo && ProcessInfo.processInfo.arguments.contains("--dark") ? .dark : nil)
      .task { await store.start() }
      .onOpenURL { url in
        guard url.scheme == "stroom" else { return }
        if url.host == "item", let id = url.pathComponents.last, UUID(uuidString: id) != nil {
          store.openItemID = id
          store.tab = 0
        }
        if url.host == "podcasts" { store.tab = 1 }
      }
      .onChange(of: scenePhase) { _, phase in
        if phase == .background { store.notifications.scheduleRefresh() }
        if phase == .active {
          Task {
            await store.notifications.permissionStatus()
            if !store.starting { await store.refresh() }
          }
        }
      }
    }
  }
}

enum Brand {
  static let blue = Color(
    uiColor: UIColor {
      $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.48, green: 0.69, blue: 0.91, alpha: 1)
        : UIColor(red: 0, green: 0.20, blue: 0.40, alpha: 1)
    })
  static let paper = Color(
    uiColor: UIColor {
      $0.userInterfaceStyle == .dark
        ? UIColor(red: 0.06, green: 0.07, blue: 0.08, alpha: 1)
        : UIColor(red: 0.977, green: 0.969, blue: 0.949, alpha: 1)
    })
  static let card = Color(uiColor: .secondarySystemGroupedBackground)
}

struct RootView: View {
  @EnvironmentObject var store: AppStore
  @EnvironmentObject var player: AudioPlayer
  @State private var showingPlayer = false
  var body: some View {
    Group {
      if store.starting {
        ProgressView("Stroom openen…").frame(maxWidth: .infinity, maxHeight: .infinity).background(
          Brand.paper)
      } else if store.user == nil {
        LoginView()
      } else {
        TabView(selection: $store.tab) {
          tabRoot { FeedScreen(podcastsOnly: false) }.tabItem {
            Label("Stroom", systemImage: "water.waves")
          }.tag(0)
          tabRoot { FeedScreen(podcastsOnly: true) }.tabItem {
            Label("Luisteren", systemImage: "headphones")
          }.tag(1)
          tabRoot { LibraryView() }.tabItem { Label("Bibliotheek", systemImage: "books.vertical") }
            .tag(2)
          tabRoot { ReadingQueueView() }.tabItem {
            Label("Wachtrij", systemImage: "text.line.first.and.arrowtriangle.forward")
          }.tag(3)
          tabRoot { MoreView() }.tabItem { Label("Meer", systemImage: "ellipsis.circle") }.tag(4)
        }
        .sheet(isPresented: $showingPlayer) { NowPlayingView() }
        .sheet(
          item: Binding(
            get: { store.openItemID.map(ItemLink.init) }, set: { store.openItemID = $0?.id })
        ) { link in
          NavigationStack { ItemDetailView(id: link.id) }
        }
      }
    }
  }
  func tabRoot<Content: View>(@ViewBuilder content: () -> Content) -> some View {
    NavigationStack { content() }
      .safeAreaInset(edge: .bottom, spacing: 0) {
        VStack(spacing: 0) {
          ActionFeedback()
          if player.current != nil {
            MiniPlayer(showingPlayer: $showingPlayer).padding(.horizontal, 12).padding(.bottom, 8)
          }
        }.background(.ultraThinMaterial)
      }
  }

}
struct ItemLink: Identifiable { let id: String }

struct LoginView: View {
  @EnvironmentObject var store: AppStore
  @State private var email = ""
  @State private var password = ""
  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(alignment: .leading, spacing: 26) {
          Image(systemName: "water.waves").font(.system(size: 48, weight: .light)).foregroundStyle(
            Brand.blue
          ).padding(.top, 48)
          Text("Een wereld aan ideeën.\nOp jouw ritme.").font(
            .system(.largeTitle, design: .serif).weight(.medium))
          Text("Je onderwerpen, inzichten en podcasts.\nDezelfde Stroom, nu op je iPhone.")
            .foregroundStyle(.secondary)
          VStack(spacing: 14) {
            TextField("Stroom-adres", text: $store.server).keyboardType(.URL)
              .textInputAutocapitalization(.never).autocorrectionDisabled()
            Divider()
            TextField("E-mailadres", text: $email).keyboardType(.emailAddress).textContentType(
              .username
            ).textInputAutocapitalization(.never).autocorrectionDisabled()
            Divider()
            SecureField("Wachtwoord", text: $password).textContentType(.password)
          }.padding(20).background(Brand.card, in: RoundedRectangle(cornerRadius: 20))
          if let error = store.error {
            Label(error, systemImage: "exclamationmark.circle").font(.callout).foregroundStyle(.red)
          }
          Button {
            Task {
              await store.login(email: email, password: password)
              password = ""
            }
          } label: {
            HStack {
              Text("Verbind met Stroom")
              Spacer()
              if store.busy {
                ProgressView().tint(.white)
              } else {
                Image(systemName: "arrow.right")
              }
            }
            .fontWeight(.semibold).padding(18).foregroundStyle(.white).background(
              Color(red: 0, green: 0.2, blue: 0.4), in: Capsule())
          }.disabled(store.busy || email.isEmpty || password.isEmpty)
          Text("Log in met je bestaande Stroom-account. Je wachtwoord wordt niet opgeslagen.").font(
            .footnote
          ).foregroundStyle(.secondary)
        }.padding(28).frame(maxWidth: 550)
      }.frame(maxWidth: .infinity).background(Brand.paper).navigationTitle("Stroom")
        .navigationBarTitleDisplayMode(.inline)
    }
  }
}
