import AppKit

protocol MacConnectionShadowLifetime: AnyObject {
    var state: MacShadowSession.State { get }
    var onStateChange: ((MacShadowSession.State) -> Void)? { get set }
    func start()
    func stop()
}
extension MacShadowSession: MacConnectionShadowLifetime {}

// This state machine owns one shadow session, one protected Host claim and one serialized auth context.
// A browser message is merely a hint; it never supplies a nonce, account, process or command.
final class MacConnectionSession {
    typealias Send = ([String: Any], @escaping ([String: Any]?) -> Void) -> Void
    private final class Context {
        let request: String
        var account = "", operation = ""
        let shadow: any MacConnectionShadowLifetime
        let original: any MacConnectionOriginalLifetime
        var cleanup: String?, snapshotOutstanding = false, releaseOutstanding = false, released = false
        var revoked = false, dispatched = false, stopping = false, shadowSettled = false
        var authRunning = false, stopSent = false, stopReplySettled = false, hostTerminal = false, claimOutstanding = true
        private let authority = NSLock()
        private var denied = false
        func revokeAuthority() { authority.lock(); denied = true; authority.unlock() }
        func mayAuthorize() -> Bool { authority.lock(); defer { authority.unlock() }; return !denied }
        var timer: Timer?, deadline: Timer?
        init(request: String, shadow: any MacConnectionShadowLifetime, original: any MacConnectionOriginalLifetime) { self.request = request; self.shadow = shadow; self.original = original }
        var fields: [String: Any] { ["requestId": request, "account": account, "operation": operation] }
    }
    private let send: Send
    private let originalFactory: () -> any MacConnectionOriginalLifetime
    private let shadowFactory: () -> any MacConnectionShadowLifetime
    private let authorize: (String) -> MacConnectionBootstrap.AuthorizationOutcome
    enum TerminationOutcome: String { case cleaned, cleanupUnconfirmed = "cleanup_unconfirmed" }
    // C6 permits 20 seconds for NSWorkspace's callback, then 8 seconds to stop its returned handle.
    // Add the protected Host callback's 2-second request bound and 2 seconds for run-loop scheduling.
    private static let maximumTerminationWait: TimeInterval = 32
    private let terminationBudget: TimeInterval
    private var exitSealed = false
    private var terminationRequested = false
    private var terminationTimer: Timer?
    private var terminationReply: ((TerminationOutcome) -> Void)?
    private(set) var terminationOutcome: TerminationOutcome?
    private let authorizationQueue = DispatchQueue(label: "wechat.connection.authorization")
    private var context: Context?
    var onActiveChange: ((Bool) -> Void)?
    var onSettled: (() -> Void)?
    var onStatus: ((String) -> Void)?
    var active: Bool { context != nil }
    init(send: @escaping Send) {
        self.send = send; originalFactory = { MacOriginalHandover() }; shadowFactory = { MacShadowSession() }; authorize = { MacConnectionBootstrap.authorize(operation: $0) }
        terminationBudget = Self.maximumTerminationWait
    }
    #if MAC_CONNECTION_FIXTURE
    init(send: @escaping Send, shadow: @escaping () -> any MacConnectionShadowLifetime, authorize: @escaping (String) -> Bool, terminationBudgetScale: TimeInterval = 1, original: @escaping () -> any MacConnectionOriginalLifetime = { MacFixtureAbsentOriginal() }) {
        self.send = send; originalFactory = original; shadowFactory = shadow; self.authorize = { authorize($0) ? .success : .userCancelled }
        precondition(terminationBudgetScale > 0 && terminationBudgetScale <= 1)
        terminationBudget = Self.maximumTerminationWait * terminationBudgetScale
    }
    init(send: @escaping Send, shadow: @escaping () -> any MacConnectionShadowLifetime,
         authorizationOutcome: @escaping (String) -> MacConnectionBootstrap.AuthorizationOutcome, terminationBudgetScale: TimeInterval = 1, original: @escaping () -> any MacConnectionOriginalLifetime = { MacFixtureAbsentOriginal() }) {
        self.send = send; originalFactory = original; shadowFactory = shadow; authorize = authorizationOutcome
        precondition(terminationBudgetScale > 0 && terminationBudgetScale <= 1)
        terminationBudget = Self.maximumTerminationWait * terminationBudgetScale
    }
    #endif
    // NSApplication.terminateLater runs a modal loop. Lifecycle deadlines must
    // continue there as well as during ordinary reading and menu tracking.
    private static func lifecycleTimer(withTimeInterval interval: TimeInterval, repeats: Bool,
                                       block: @escaping @Sendable (Timer) -> Void) -> Timer {
        let timer = Timer(timeInterval: interval, repeats: repeats, block: block)
        RunLoop.main.add(timer, forMode: .common)
        return timer
    }
    func begin(requestId: String) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard !exitSealed, !terminationRequested, context == nil, requestId.range(of: #"\A[0-9a-f]{32}\z"#, options: .regularExpression) != nil else { return }
        let c = Context(request: requestId, shadow: shadowFactory(), original: originalFactory()); context = c; onActiveChange?(true)
        send(["action": "claim", "requestId": requestId]) { [weak self, weak c] result in
            guard let self, let c, self.context === c else { return }
            c.claimOutstanding = false
            guard let result, Set(result.keys) == Set(["requestId", "account", "operation", "state"]),
                  result["requestId"] as? String == c.request, result["state"] as? String == "active",
                  let account = result["account"] as? String, account.range(of: #"\A[A-Za-z0-9_-]{1,256}\z"#, options: .regularExpression) != nil,
                  let operation = result["operation"] as? String, operation.range(of: #"\A[0-9a-f]{32}\z"#, options: .regularExpression) != nil else {
                self.stop(c, notify: false); self.releaseIfSettled(c); return
            }
            c.account = account; c.operation = operation
            if c.revoked {
                self.request(c, action: "cancel") { result in c.hostTerminal = c.hostTerminal || result?["state"] as? String == "stop"; c.stopSent = false; self.shadowStopped(c) }
                return
            }
            c.shadow.onStateChange = { [weak self, weak c] state in
                guard let self, let c, self.context === c else { return }
                switch state {
                case .ready:
                    guard !c.revoked, !c.dispatched else { c.shadow.stop(); return }
                    guard c.original.observeBeforeDispatch() else { self.stop(c); return }
                    c.dispatched = true
                    self.request(c, action: "dispatch") { result in
                        guard self.context === c, !c.revoked else { return }
                        guard c.original.observeBeforeDispatch() else { self.stop(c); return }
                        guard result?["state"] as? String == "active" else { self.stop(c); return }
                        c.authRunning = true
                        self.authorizationQueue.async {
                            let outcome = c.mayAuthorize() ? self.authorize(c.operation) : nil
                            DispatchQueue.main.async {
                                guard self.context === c else { return }
                                c.authRunning = false
                                if !c.revoked {
                                    switch outcome {
                                    case .failed:
                                        self.stop(c, notify: false)
                                        self.request(c, action: "failure", code: "bootstrapFailed") { result in
                                            guard self.context === c else { return }
                                            c.hostTerminal = c.hostTerminal || result?["state"] as? String == "stop"
                                            self.shadowStopped(c)
                                        }
                                    case .userCancelled: self.stop(c)
                                    default: break
                                    }
                                }
                                self.shadowStopped(c)
                                self.releaseIfSettled(c)
                            }
                        }
                    }
                case .stopped: c.shadowSettled = true; self.shadowStopped(c)
                case .failed(let code, let cleanupConfirmed):
                    if cleanupConfirmed { c.shadowSettled = true }
                    if !c.revoked {
                        self.stop(c, notify: false)
                        self.request(c, action: "failure", code: code.rawValue) { result in
                            c.hostTerminal = c.hostTerminal || result?["state"] as? String == "stop"
                            self.shadowStopped(c)
                        }
                    } else { self.stop(c) }
                    if cleanupConfirmed { self.shadowStopped(c) }
                default: break
                }
            }
            c.timer = Self.lifecycleTimer(withTimeInterval: 0.3, repeats: true) { [weak self, weak c] _ in
                guard let self, let c, self.context === c else { return }
                if c.revoked {
                    self.shadowStopped(c); self.advanceRelease(c)
                    if !c.hostTerminal, !c.stopSent, !c.snapshotOutstanding {
                        c.snapshotOutstanding = true
                        self.request(c, action: "status") { result in
                            guard self.context === c else { return }; c.snapshotOutstanding = false
                            c.hostTerminal = c.hostTerminal || result?["state"] as? String == "stop"
                            self.shadowStopped(c)
                        }
                    }
                    return
                }
                guard !c.snapshotOutstanding else { return }; c.snapshotOutstanding = true
                self.request(c, action: "status") { result in
                    guard self.context === c else { return }; c.snapshotOutstanding = false
                    guard let state = result?["state"] as? String else { self.stop(c); if c.shadowSettled { c.hostTerminal = true; self.shadowStopped(c) }; return }
                    if state == "stop" { c.hostTerminal = true; self.stop(c, notify: false) }
                }
            }
            c.deadline = Self.lifecycleTimer(withTimeInterval: 370, repeats: false) { [weak self, weak c] _ in if let self, let c { self.stop(c) } }
            c.original.onReopened = { [weak self, weak c] in if let self, let c, self.context === c { self.stop(c) } }
            c.original.onChange = { [weak self, weak c] in if let self, let c, self.context === c { self.advanceRelease(c) } }
            c.original.prepare { [weak self, weak c] ready in
                guard let self, let c, self.context === c else { return }
                guard !c.revoked else { self.shadowStopped(c); self.advanceRelease(c); return }
                guard ready, c.original.observeBeforeDispatch() else {
                    if c.revoked { self.shadowStopped(c); self.advanceRelease(c); return }
                    self.stop(c, notify: false)
                    self.request(c, action: "failure", code: "originalHandoverFailed") { reply in c.hostTerminal = c.hostTerminal || reply?["state"] as? String == "stop"; self.shadowStopped(c) }
                    return
                }
                c.shadow.start()
            }
        }
    }
    func cancel() {
        dispatchPrecondition(condition: .onQueue(.main))
        if let c = context { stop(c) }
    }
    /// Returns false only for an idle session. Repeated quit requests share one cancellation and reply.
    @discardableResult func requestTermination(_ completion: @escaping (TerminationOutcome) -> Void) -> Bool {
        dispatchPrecondition(condition: .onQueue(.main))
        if terminationRequested { return true }
        guard context != nil else { return false }
        terminationOutcome = nil; terminationRequested = true; terminationReply = completion
        if context?.cleanup == "unconfirmed" {
            // A new explicit Quit rechecks the retained immutable failure; it never takes the idle path.
            cancel()
            DispatchQueue.main.async { [weak self] in self?.resolveTermination(.cleanupUnconfirmed) }
            return true
        }
        terminationTimer = Self.lifecycleTimer(withTimeInterval: terminationBudget, repeats: false) { [weak self] _ in
            guard let self, self.terminationOutcome == nil else { return }
            // This bound is an explicit uncertainty result, never a claim that a late handle is gone.
            // Retain the context and C6 callback so any arrival before AppKit actually exits still stops only our target.
            if let c = self.context { self.stop(c) }
            self.resolveTermination(.cleanupUnconfirmed)
        }
        cancel()
        if context == nil { resolveTermination(.cleaned) }
        return true
    }
    private func resolveTermination(_ outcome: TerminationOutcome) {
        guard terminationRequested, terminationOutcome == nil else { return }
        terminationOutcome = outcome; terminationTimer?.invalidate(); terminationTimer = nil
        let reply = terminationReply; terminationReply = nil
        if outcome == .cleanupUnconfirmed { terminationRequested = false }
        else { exitSealed = true; context?.original.sealForApplicationExit() }
        reply?(outcome)
    }
    private func request(_ c: Context, action: String, code: String? = nil, completion: @escaping ([String: Any]?) -> Void) {
        var value = c.fields; value["action"] = action
        if let code { value["code"] = code }
        send(value) { result in
            guard let result, result["requestId"] as? String == c.request,
                  result["account"] as? String == c.account, result["operation"] as? String == c.operation,
                  Set(result.keys) == Set(["requestId", "account", "operation", "state"]),
                  ["active", "stop"].contains(result["state"] as? String ?? "") else { completion(nil); return }
            completion(result)
        }
    }
    private func stop(_ c: Context, notify: Bool = true) {
        guard context === c else { return }
        c.revoked = true; c.revokeAuthority(); c.original.cancel()
        if !c.stopping {
            c.stopping = true
            if notify && !c.account.isEmpty { request(c, action: "cancel") { result in c.hostTerminal = c.hostTerminal || result?["state"] as? String == "stop"; self.shadowStopped(c) } }
            c.shadow.stop()
            if c.shadow.state == .stopped || c.shadow.state == .idle { c.shadowSettled = true }
            c.deadline?.invalidate(); c.deadline = nil
        }
        if c.shadowSettled { shadowStopped(c) }
    }
    private func shadowStopped(_ c: Context) {
        // The Host barrier covers both our GUI lifetime and the serialized authorization call.
        guard c.revoked, c.shadowSettled, !c.authRunning, !c.stopSent, c.account.isEmpty || c.hostTerminal else { return }
        c.stopSent = true
        if c.account.isEmpty { releaseIfSettled(c); return }
        // A late claim can follow local account-empty cleanup; this accountful barrier
        // owns a fresh callback fact rather than carrying any earlier phase completion.
        c.stopReplySettled = false
        // Awaiting this protected callback is the Host's barrier before ordinary import.
        request(c, action: "stopped") { result in
            guard self.context === c else { return }
            c.stopReplySettled = result?["state"] as? String == "stop"
            if !c.stopReplySettled { c.stopSent = false }
            self.advanceRelease(c)
        }
    }
    #if MAC_CONNECTION_FIXTURE
    var fixtureHostTerminal: Bool { context?.hostTerminal ?? false }
    #endif
    private func advanceRelease(_ c: Context) {
        guard context === c, c.revoked, !c.claimOutstanding, c.shadowSettled, !c.authRunning,
              c.stopReplySettled, !c.account.isEmpty else { releaseIfSettled(c); return }
        if c.cleanup == nil || c.cleanup == "pending" {
            guard !c.snapshotOutstanding else { return }; c.snapshotOutstanding = true
            var message = c.fields; message["action"] = "cleanup"
            send(message) { reply in
                guard self.context === c else { return }; c.snapshotOutstanding = false
                guard let reply, Set(reply.keys) == Set(["requestId", "account", "operation", "state", "cleanup"]),
                      reply["requestId"] as? String == c.request, reply["account"] as? String == c.account,
                      reply["operation"] as? String == c.operation, reply["state"] as? String == "stop",
                      let cleanup = reply["cleanup"] as? String, ["pending", "complete", "unconfirmed"].contains(cleanup) else { return }
                c.cleanup = cleanup
                if cleanup != "pending" { self.advanceRelease(c) }
            }
            return
        }
        if c.cleanup == "complete" { onStatus?("正在确认连接结束并恢复微信…"); c.original.finishAfterProtectedCleanup() }
        else { onStatus?("连接清理尚未确认，新连接和导入已暂停；已保存记录仍可查看。"); c.original.finishUnconfirmedCleanup() }
        if c.original.restorationFailed { onStatus?("微信未能自动重新打开，请手动打开微信。") }
        guard c.original.settled, !c.original.pending, !c.releaseOutstanding, !c.released else { return }
        c.releaseOutstanding = true
        request(c, action: "released") { reply in
            guard self.context === c else { return }; c.releaseOutstanding = false
            c.released = reply?["state"] as? String == "stop"
            self.releaseIfSettled(c)
        }
    }
    func sealForApplicationExit() {
        dispatchPrecondition(condition: .onQueue(.main)); precondition(context == nil); exitSealed = true
    }
    private func releaseIfSettled(_ c: Context) {
        guard context === c, c.stopSent, c.shadowSettled, !c.authRunning, !c.claimOutstanding else { return }
        if !c.account.isEmpty { guard c.stopReplySettled, c.released, c.original.settled, !c.original.pending else { return } }
        else { guard !c.original.pending else { return } }
        if !c.account.isEmpty && c.cleanup != "complete" {
            // released finalizes Host failure only. Retain Native ownership and sticky uncertainty.
            c.timer?.invalidate(); c.timer = nil; c.deadline?.invalidate(); c.deadline = nil
            onStatus?("连接清理尚未确认，新连接和导入已暂停；已保存记录仍可查看。")
            if terminationRequested {
                DispatchQueue.main.async { [weak self] in self?.resolveTermination(.cleanupUnconfirmed) }
            }
            return
        }
        c.original.sealForApplicationExit()
        if c.cleanup == "complete" && !c.original.restorationFailed { onStatus?("本机连接已结束。") }
        c.timer?.invalidate(); c.deadline?.invalidate(); context = nil; onActiveChange?(false); onSettled?()
        if terminationRequested { resolveTermination(.cleaned) }
    }
}
#if MAC_CONNECTION_FIXTURE
// Old connection fixtures are absent-original by construction; no real installation access.
final class MacFixtureAbsentOriginal: MacConnectionOriginalLifetime {
    var pending = false, settled = false
    var restorationFailed: Bool { false }
    var onReopened: (() -> Void)?, onChange: (() -> Void)?
    func prepare(_ completion: @escaping (Bool) -> Void) { completion(true) }
    func cancel() {}
    func observeBeforeDispatch() -> Bool { true }
    func finishAfterProtectedCleanup() { settled = true }
    func finishUnconfirmedCleanup() { settled = true }
    func sealForApplicationExit() {}
}
#endif
