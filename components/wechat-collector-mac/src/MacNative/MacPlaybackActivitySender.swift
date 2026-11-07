import Foundation

// One sender belongs to the App, not an individual preview. Access and transport
// completions run on the main queue, preserving order across preview replacement.
final class MacPlaybackActivitySender {
    private let send: (Bool, @escaping (Bool) -> Void) -> Void
    private let onFailure: () -> Void
    private var desired: Bool?
    private var delivered: Bool?
    private var inFlight = false
    private var retriesRemaining = 1
    private var exhausted: Bool?

    init(send: @escaping (Bool, @escaping (Bool) -> Void) -> Void, onFailure: @escaping () -> Void) {
        self.send = send
        self.onFailure = onFailure
    }

    func update(_ active: Bool) {
        if desired != active {
            desired = active
            retriesRemaining = 1
            exhausted = nil
        }
        drain()
    }

    private func drain() {
        guard !inFlight, let active = desired, delivered != active, exhausted != active else { return }
        inFlight = true
        send(active) { [weak self] success in
            guard let self = self else { return }
            self.inFlight = false
            if success { self.delivered = active }
            else {
                // A failed response leaves the server's outcome unknown.
                self.delivered = nil
                if self.desired == active {
                    if self.retriesRemaining > 0 { self.retriesRemaining -= 1 }
                    else {
                        self.exhausted = active
                        self.onFailure()
                    }
                }
            }
            self.drain()
        }
    }
}
