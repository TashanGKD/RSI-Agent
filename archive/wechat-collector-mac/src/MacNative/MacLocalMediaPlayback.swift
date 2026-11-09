import Foundation
import AVFoundation

struct LocalMediaDisplay: Equatable {
    let text: String
    let active: Bool

    static func make(status: AVPlayerItem.Status?, waiting: Bool, ended: Bool, failed: Bool, requested: Bool, time: Double, duration: Double) -> Self {
        if failed || status == .failed { return Self(text: "无法播放，文件可能损坏", active: false) }
        if ended { return Self(text: "播放结束", active: false) }
        guard let status = status else { return Self(text: "就绪", active: false) }
        if status == .unknown || waiting || !duration.isFinite { return Self(text: "正在加载…", active: requested) }
        // Clamp before conversion so invalid AV times never trap Int conversion.
        let seconds = Int(min(Double(Int32.max), time.isFinite ? max(0, time) : 0))
        let total = Int(min(Double(Int32.max), max(0, duration)))
        return Self(text: String(format: "%02d:%02d / %02d:%02d", seconds / 60, seconds % 60, total / 60, total % 60), active: requested)
    }
}

// One local preview's player and playback lease. All access is on the main queue,
// including AVFoundation callbacks; closing invalidates pending replay callbacks.
final class MacLocalMediaPlayback {
    let player: AVPlayer
    var onChange: ((LocalMediaDisplay) -> Void)?
    private var requested = false
    private var ended = false
    private var failed = false
    private var closed = false
    private var generation = 0
    private var observations: [NSKeyValueObservation] = []
    private var notifications: [NSObjectProtocol] = []

    init(url: URL) {
        let item = AVPlayerItem(url: url)
        player = AVPlayer(playerItem: item)
        observations.append(item.observe(\.status, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.refresh() }
        })
        observations.append(player.observe(\.timeControlStatus, options: [.new]) { [weak self] _, _ in
            DispatchQueue.main.async { self?.refresh() }
        })
        notifications.append(NotificationCenter.default.addObserver(forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main) { [weak self] _ in
            guard let self = self, !self.closed else { return }
            self.ended = true; self.requested = false; self.publish()
        })
        notifications.append(NotificationCenter.default.addObserver(forName: .AVPlayerItemFailedToPlayToEndTime, object: item, queue: .main) { [weak self] _ in
            guard let self = self, !self.closed else { return }
            self.failed = true; self.requested = false; self.publish()
        })
    }

    var display: LocalMediaDisplay {
        LocalMediaDisplay.make(status: player.currentItem?.status, waiting: player.timeControlStatus == .waitingToPlayAtSpecifiedRate, ended: ended, failed: failed, requested: requested, time: player.currentTime().seconds, duration: player.currentItem?.duration.seconds ?? .nan)
    }

    func play() {
        guard !closed, !failed, player.currentItem?.status != .failed else { refresh(); return }
        // Ignore repeated play clicks, matching the original two-button behavior.
        guard !requested else { return }
        requested = true
        generation += 1
        if ended {
            let replayGeneration = generation
            ended = false
            player.seek(to: .zero, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] finished in
                DispatchQueue.main.async {
                    guard let self = self, !self.closed, self.requested, self.generation == replayGeneration else { return }
                    if finished { self.player.play() }
                    else { self.requested = false }
                    self.publish()
                }
            }
        } else { player.play() }
        publish()
    }

    func pause() {
        generation += 1
        requested = false
        player.pause()
        publish()
    }

    func close() {
        guard !closed else { return }
        closed = true
        pause()
        observations.removeAll()
        notifications.forEach { NotificationCenter.default.removeObserver($0) }
        notifications.removeAll()
        onChange = nil
    }

    private func refresh() {
        guard !closed else { return }
        if player.currentItem?.status == .failed { requested = false }
        publish()
    }

    private func publish() { onChange?(display) }

    deinit {
        player.pause()
        notifications.forEach { NotificationCenter.default.removeObserver($0) }
    }
}
