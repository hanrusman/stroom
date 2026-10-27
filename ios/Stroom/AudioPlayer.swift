import AVFoundation
import Combine
import MediaPlayer
import UIKit

@MainActor
final class AudioPlayer: ObservableObject {
  @Published private(set) var current: AudioTrack?
  @Published private(set) var queue: [AudioTrack] = []
  @Published private(set) var playing = false
  @Published private(set) var loading = false
  @Published var elapsed: Double = 0
  @Published private(set) var duration: Double = 0
  @Published var error: String?
  static let playbackRates = (10...25).map { Float($0) / 10 }
  static func savedSpeed(in defaults: UserDefaults = .standard) -> Float {
    let value = defaults.float(forKey: "playbackSpeed")
    return playbackRates.contains(where: { abs($0 - value) < 0.001 }) ? value : 1.7
  }
  @Published var speed: Float = AudioPlayer.savedSpeed() {
    didSet {
      UserDefaults.standard.set(speed, forKey: "playbackSpeed")
      if playing { player.rate = speed }
      updateNowPlaying()
    }
  }
  @Published private(set) var sleepUntil: Date?
  private let player = AVPlayer()
  private var timer: Any?
  private var statusObservation: NSKeyValueObservation?
  private var itemObservation: NSKeyValueObservation?
  private var observers: [NSObjectProtocol] = []
  private var sleepTask: Task<Void, Never>?
  private var loadTask: Task<Void, Never>?
  private var requestID = UUID()
  private var api: APIClient?
  private var library: LibraryStore?
  private var lastSavedSecond = -1
  private var preparing = false
  private var wantsPlayback = false
  private var resumeAfterInterruption = false

  init() {
    timer = player.addPeriodicTimeObserver(
      forInterval: CMTime(seconds: 1, preferredTimescale: 600), queue: .main
    ) { [weak self] time in
      Task { @MainActor in
        guard let self else { return }
        self.elapsed = time.seconds.isFinite ? max(0, time.seconds) : 0
        let length = self.player.currentItem?.duration.seconds ?? 0
        self.duration = length.isFinite ? max(0, length) : 0
        if Int(self.elapsed) % 5 == 0 && Int(self.elapsed) != self.lastSavedSecond {
          self.savePosition()
          self.lastSavedSecond = Int(self.elapsed)
        }
        self.updateNowPlaying()
      }
    }
    statusObservation = player.observe(\.timeControlStatus, options: [.new]) {
      [weak self] player, _ in
      Task { @MainActor in
        self?.playing = player.timeControlStatus == .playing
        self?.loading =
          (self?.preparing ?? false) || player.timeControlStatus == .waitingToPlayAtSpecifiedRate
        self?.updateNowPlaying()
      }
    }
    observers.append(
      NotificationCenter.default.addObserver(
        forName: .AVPlayerItemDidPlayToEndTime, object: nil, queue: .main
      ) { [weak self] note in
        guard let item = note.object as? AVPlayerItem else { return }
        Task { @MainActor in
          guard let self, item === self.player.currentItem else { return }
          if let current = self.current {
            UserDefaults.standard.removeObject(forKey: self.positionKey(current))
          }
          self.elapsed = 0
          self.next(save: false)
        }
      })
    observers.append(
      NotificationCenter.default.addObserver(
        forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
      ) { [weak self] note in
        let type = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
        let options = note.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
        Task { @MainActor in
          if type == AVAudioSession.InterruptionType.began.rawValue {
            self?.resumeAfterInterruption = self?.playing ?? false
            self?.pause()
          } else if options & AVAudioSession.InterruptionOptions.shouldResume.rawValue != 0
            && self?.resumeAfterInterruption == true
          {
            self?.resume()
            self?.resumeAfterInterruption = false
          }
        }
      })
    observers.append(
      NotificationCenter.default.addObserver(
        forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main
      ) { [weak self] note in
        let reason = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
        if reason == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue {
          Task { @MainActor in self?.pause() }
        }
      })
    configureCommands()
  }
  func configure(api: APIClient, library: LibraryStore) {
    self.api = api
    self.library = library
  }
  func play(_ track: AudioTrack) {
    savePosition()
    loadTask?.cancel()
    requestID = UUID()
    let ticket = requestID
    player.pause()
    player.replaceCurrentItem(with: nil)
    current = track
    elapsed = 0
    duration = 0
    preparing = true
    loading = true
    wantsPlayback = true
    error = nil
    loadTask = Task { @MainActor [weak self] in
      guard let self else { return }
      defer {
        if ticket == self.requestID {
          self.preparing = false
          self.loading = self.player.timeControlStatus == .waitingToPlayAtSpecifiedRate
        }
      }
      do {
        guard let api, let library else { throw APIError.message("Log eerst in.") }
        let remote = try ServerAddress.media(track.url, base: api.baseURL)
        // Protected generated audio is fetched through URLSession, then played locally.
        // AVPlayer never receives an auth header that could leak through a redirect.
        if ServerAddress.sameOrigin(remote, api.baseURL) && library.localURL(for: track) == nil {
          try await library.download(track, api: api)
        }
        try Task.checkCancellation()
        guard ticket == requestID else { return }
        try AVAudioSession.sharedInstance().setCategory(
          .playback, mode: .spokenAudio, options: [.allowAirPlay])
        try AVAudioSession.sharedInstance().setActive(true)
        let item = AVPlayerItem(url: library.localURL(for: track) ?? remote)
        itemObservation = item.observe(\.status, options: [.new]) { [weak self] item, _ in
          Task { @MainActor in
            guard let self, item === self.player.currentItem else { return }
            if item.status == .failed {
              self.error = item.error?.localizedDescription ?? "Afspelen mislukt."
              self.loading = false
            }
          }
        }
        player.replaceCurrentItem(with: item)
        let position = UserDefaults.standard.double(forKey: positionKey(track))
        if position > 0 {
          await player.seek(to: CMTime(seconds: position, preferredTimescale: 600))
        }
        guard ticket == requestID else { return }
        if wantsPlayback { player.playImmediately(atRate: speed) }
        updateNowPlaying()
      } catch is CancellationError {} catch {
        if ticket == requestID {
          self.error = error.localizedDescription
          loading = false
        }
      }
    }
  }
  func enqueue(_ track: AudioTrack) {
    if !queue.contains(where: { $0.id == track.id }) { queue.append(track) }
  }
  func removeFromQueue(at offsets: IndexSet) { queue.remove(atOffsets: offsets) }
  func toggle() { playing || (loading && wantsPlayback) ? pause() : resume() }
  func pause() {
    wantsPlayback = false
    player.pause()
    playing = false
    savePosition()
    updateNowPlaying()
  }
  func resume() {
    guard current != nil else { return }
    wantsPlayback = true
    guard !loading else { return }
    if player.currentItem == nil || player.currentItem?.status == .failed {
      if let current { play(current) }
      return
    }
    do {
      try AVAudioSession.sharedInstance().setActive(true)
      player.playImmediately(atRate: speed)
    } catch { self.error = error.localizedDescription }
  }
  func seek(_ seconds: Double) {
    guard seconds.isFinite else { return }
    let target = max(0, duration > 0 ? min(seconds, duration) : seconds)
    player.seek(to: CMTime(seconds: target, preferredTimescale: 600))
    elapsed = target
    savePosition()
    updateNowPlaying()
  }
  func skip(_ seconds: Double) { seek(elapsed + seconds) }
  func next(save: Bool = true) {
    if save { savePosition() }
    guard !queue.isEmpty else {
      pause()
      return
    }
    let track = queue.removeFirst()
    if !save { current = nil }
    play(track)
  }
  func sleep(minutes: Int?) {
    sleepTask?.cancel()
    guard let minutes else {
      sleepUntil = nil
      return
    }
    sleepUntil = Date().addingTimeInterval(Double(minutes * 60))
    sleepTask = Task { @MainActor in
      do {
        try await Task.sleep(for: .seconds(minutes * 60))
        pause()
        sleepUntil = nil
      } catch {}
    }
  }
  func stop() {
    requestID = UUID()
    loadTask?.cancel()
    preparing = false
    loading = false
    pause()
    player.replaceCurrentItem(with: nil)
    current = nil
    queue = []
    sleep(minutes: nil)
    MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
  }
  private func positionKey(_ track: AudioTrack) -> String {
    "position.\(api?.baseURL.host ?? "").\(track.id)"
  }
  private func savePosition() {
    if let current, elapsed.isFinite {
      UserDefaults.standard.set(elapsed, forKey: positionKey(current))
    }
  }
  private func updateNowPlaying() {
    guard let current else { return }
    MPNowPlayingInfoCenter.default().nowPlayingInfo = [
      MPMediaItemPropertyTitle: current.title, MPMediaItemPropertyArtist: current.author,
      MPMediaItemPropertyPlaybackDuration: duration,
      MPNowPlayingInfoPropertyElapsedPlaybackTime: elapsed,
      MPNowPlayingInfoPropertyPlaybackRate: playing ? speed : 0,
      MPNowPlayingInfoPropertyDefaultPlaybackRate: speed,
      MPNowPlayingInfoPropertyMediaType: MPNowPlayingInfoMediaType.audio.rawValue,
    ]
  }
  private func configureCommands() {
    let commands = MPRemoteCommandCenter.shared()
    commands.playCommand.addTarget { [weak self] _ in
      Task { @MainActor in self?.resume() }
      return .success
    }
    commands.pauseCommand.addTarget { [weak self] _ in
      Task { @MainActor in self?.pause() }
      return .success
    }
    commands.togglePlayPauseCommand.addTarget { [weak self] _ in
      Task { @MainActor in self?.toggle() }
      return .success
    }
    commands.skipBackwardCommand.preferredIntervals = [15]
    commands.skipForwardCommand.preferredIntervals = [30]
    commands.skipBackwardCommand.addTarget { [weak self] _ in
      Task { @MainActor in self?.skip(-15) }
      return .success
    }
    commands.skipForwardCommand.addTarget { [weak self] _ in
      Task { @MainActor in self?.skip(30) }
      return .success
    }
    commands.changePlaybackPositionCommand.addTarget { [weak self] event in
      guard let event = event as? MPChangePlaybackPositionCommandEvent else {
        return .commandFailed
      }
      Task { @MainActor in self?.seek(event.positionTime) }
      return .success
    }
    commands.changePlaybackRateCommand.supportedPlaybackRates = Self.playbackRates.map {
      NSNumber(value: $0)
    }
    commands.changePlaybackRateCommand.addTarget { [weak self] event in
      guard let event = event as? MPChangePlaybackRateCommandEvent,
        Self.playbackRates.contains(where: { abs($0 - event.playbackRate) < 0.001 })
      else { return .commandFailed }
      Task { @MainActor in self?.speed = event.playbackRate }
      return .success
    }
    commands.nextTrackCommand.addTarget { [weak self] _ in
      Task { @MainActor in self?.next() }
      return .success
    }
  }
}
