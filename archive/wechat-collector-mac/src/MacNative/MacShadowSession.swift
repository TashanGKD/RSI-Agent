import AppKit
import CryptoKit
import Darwin
import Security

/// Owner-UID GUI lifetime only. Ready means process identity accepted, never login or key readiness.
/// The executable FD is a userspace file lease, NOT a kernel text-vnode/provenance attestation.
final class MacShadowSession {
    enum FailureCode: String, Error {
        case ownerInvalid, managedBundleInvalid, signatureInvalid, existingApplication
        case launchFailed, launchDeadline, identityChanged, stopDeadline
    }
    struct Witness: Equatable, CustomStringConvertible, CustomDebugStringConvertible {
        let uid: UInt32, ruid: UInt32, pid: Int32
        let startSeconds: UInt64, startMicroseconds: UInt64
        // Fixed managed target metadata may be passed directly to a future broker, never a key.
        let bundleIdentifier: String
        let executableURL: URL
        let executableDevice: UInt64, executableInode: UInt64
        var description: String { "ownerUID=\(uid) pid=\(pid) processReady" }
        var debugDescription: String { description }
    }
    enum State: Equatable {
        case idle, launching, ready(Witness), stopping, stopped
        case failed(FailureCode, cleanupConfirmed: Bool)
    }
    private(set) var state: State = .idle
    var onStateChange: ((State) -> Void)?
    private var started = false
    private var cancelled = false
    private var pendingOpen = false
    private var retainedApplication: NSRunningApplication?
    private var accepted: NativeIdentity?
    private var target: ValidatedTarget?
    private var launchTime = timespec()
    private var launchTimer: Timer?
    private var stopTimer: Timer?
    private var monitorTimer: Timer?
    private var stopBegan: UInt64 = 0
    private var forced = false
    private var gracefulSent = false
    private var gracefulSentAt: UInt64 = 0
    private var uncertaintyBegan: UInt64?
    private var failure: FailureCode?
    private var keepAlive: MacShadowSession?
    #if MAC_SHADOW_SESSION_FIXTURE
    private let fixture: Bool
    init() { fixture = false }
    /// This target is compiled away from the normal product. It accepts no path/PID/environment input.
    static func generatedC5Fixture() -> MacShadowSession { MacShadowSession(fixture: true) }
    private init(fixture: Bool) { self.fixture = fixture }
    #else
    init() {} // Intentionally no filesystem, process, AppKit, or owner lookup.
    #endif

    // NSApplication.terminateLater runs a modal loop. Lifecycle deadlines must
    // continue there as well as during ordinary reading and menu tracking.
    private static func lifecycleTimer(withTimeInterval interval: TimeInterval, repeats: Bool,
                                       block: @escaping @Sendable (Timer) -> Void) -> Timer {
        let timer = Timer(timeInterval: interval, repeats: repeats, block: block)
        RunLoop.main.add(timer, forMode: .common)
        return timer
    }
    private enum NativeObservation { case same, absent, unknown, changed }
    private enum LeaseObservation { case same, unknown, changed }
    private enum LifecycleObservation: String { case alive, gone, waiting, changed }
    private static func classifyLifecycle(appTerminated: Bool, before: NativeObservation, after: NativeObservation,
                                          metadata: LeaseObservation, pin: LeaseObservation) -> LifecycleObservation {
        // AppKit's time-varying properties refresh on a later main-run-loop turn.
        // Absence or unavailable evidence is not a positively observed replacement.
        if before == .changed || after == .changed || metadata == .changed || pin == .changed { return .changed }
        if appTerminated && after == .absent { return .gone }
        if !appTerminated && before == .same && after == .same && metadata == .same && pin == .same { return .alive }
        return .waiting
    }
    private enum StopAction: String { case wait, gone, failIdentity, failDeadline, terminate, forceTerminate }
    private static func stopAction(_ observation: LifecycleObservation, elapsed: UInt64,
                                   gracefulSent: Bool, forced: Bool, graceElapsed: UInt64) -> StopAction {
        if observation == .gone { return .gone }
        if observation == .changed { return .failIdentity }
        if elapsed >= 8_000_000_000 { return .failDeadline }
        guard observation == .alive else { return .wait }
        if !gracefulSent { return .terminate }
        if graceElapsed >= 3_000_000_000 && !forced { return .forceTerminate }
        return .wait
    }
    #if MAC_SHADOW_SESSION_FIXTURE
    enum FixtureNativeObservation { case same, absent, unknown, changedBirth, changedUID, changedPath }
    static func fixtureLifecycleObservation(appTerminated: Bool, before: FixtureNativeObservation,
                                            after: FixtureNativeObservation, metadataKnown: Bool = true,
                                            pinMatches: Bool = true) -> String {
        func native(_ value: FixtureNativeObservation) -> NativeObservation {
            switch value {
            case .absent: return .absent
            case .unknown: return .unknown
            case .same, .changedBirth, .changedUID, .changedPath:
                let expected = NativeIdentity(pid: 42, uid: 501, ruid: 501, seconds: 100, microseconds: 1)
                let observed = NativeIdentity(pid: 42, uid: value == .changedUID ? 502 : 501, ruid: 501,
                                              seconds: value == .changedBirth ? 101 : 100, microseconds: 1)
                return NativeIdentity.classifyValues(observed, path: value == .changedPath ? "/fixture/other" : "/fixture/managed",
                                                      expected: expected, executable: "/fixture/managed")
            }
        }
        return classifyLifecycle(appTerminated: appTerminated, before: native(before), after: native(after),
                                 metadata: metadataKnown ? .same : .unknown, pin: pinMatches ? .same : .changed).rawValue
    }
    static func fixtureStopAction(observation: String, elapsed: UInt64, gracefulSent: Bool, forced: Bool, graceElapsed: UInt64? = nil) -> String {
        guard let value = LifecycleObservation(rawValue: observation) else { return "invalid" }
        return stopAction(value, elapsed: elapsed, gracefulSent: gracefulSent, forced: forced, graceElapsed: graceElapsed ?? elapsed).rawValue
    }
    #endif

    // A bundle identifier is shared with the original app and never establishes target ownership.
    private static func matchesManagedPaths(bundle: String?, executable: String?, managedBundle: String, managedExecutable: String) -> Bool {
        bundle == managedBundle || executable == managedExecutable
    }
    #if MAC_SHADOW_SESSION_FIXTURE
    static func fixtureMatchesManagedApplication(identifier: String?, bundle: String?, executable: String?, managedBundle: String, managedExecutable: String) -> Bool {
        // Accept the identifier in this fixture-only metadata seam to prove it grants no authority.
        matchesManagedPaths(bundle: bundle, executable: executable, managedBundle: managedBundle, managedExecutable: managedExecutable)
    }
    static func fixtureRejectsGeneratedFIFO() -> Bool { ValidatedTarget.fixtureRejectsGeneratedFIFO() }
    #endif

    func start() {
        dispatchPrecondition(condition: .onQueue(.main))
        guard !started, !cancelled, state == .idle else { return }
        started = true
        keepAlive = self
        do {
            #if MAC_SHADOW_SESSION_FIXTURE
            target = try ValidatedTarget(fixture: fixture)
            #else
            target = try ValidatedTarget()
            #endif
            guard let target else { throw FailureCode.managedBundleInvalid }
            // Do not adopt, terminate, or otherwise touch any existing matching application.
            guard !NSWorkspace.shared.runningApplications.contains(where: {
                Self.matchesManagedPaths(bundle: $0.bundleURL?.path, executable: $0.executableURL?.path,
                                         managedBundle: target.bundlePath, managedExecutable: target.executablePath)
            }) else { throw FailureCode.existingApplication }
            try target.recheck()
            guard clock_gettime(CLOCK_REALTIME, &launchTime) == 0 else { throw FailureCode.identityChanged }
            setState(.launching)
            // Observers may synchronously cancel on launching.
            guard !cancelled else { finishGone(); return }
            pendingOpen = true
            let config = NSWorkspace.OpenConfiguration()
            config.createsNewApplicationInstance = true
            config.allowsRunningApplicationSubstitution = false
            launchTimer = Self.lifecycleTimer(withTimeInterval: 20, repeats: false) { _ in
                self.launchTimer = nil
                guard self.pendingOpen else { return }
                self.cancelled = true
                self.failure = .launchDeadline
                self.setState(.failed(.launchDeadline, cleanupConfirmed: false))
                // The open callback strongly owns self and may still deliver our application.
                // Keep the lease until that callback settles; a deadline is not proof of cleanup.
            }
            NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: target.bundlePath), configuration: config) { app, _ in
                DispatchQueue.main.async { self.openCompleted(app) }
            }
        } catch {
            finishFailure((error as? FailureCode) ?? .managedBundleInvalid, confirmed: true)
        }
    }

    func stop() {
        dispatchPrecondition(condition: .onQueue(.main))
        guard !cancelled else { return }
        cancelled = true
        switch state {
        case .idle: setState(.stopped)
        case .launching:
            setState(.stopping) // Sticky; openCompleted can no longer publish ready.
        case .ready:
            beginStop()
        case .stopping, .stopped, .failed: break
        }
    }

    private func openCompleted(_ app: NSRunningApplication?) {
        dispatchPrecondition(condition: .onQueue(.main))
        launchTimer?.invalidate(); launchTimer = nil
        pendingOpen = false
        guard let app else {
            if let failure { finishFailure(failure, confirmed: false) }
            else { finishFailure(.launchFailed, confirmed: false) }
            return
        }
        // AppKit discards identity metadata after exit. This exact returned handle is
        // already terminated: there is no live returned process to attest or signal.
        // A nil or unverified LIVE handle remains an unconfirmed failure below.
        if app.isTerminated {
            finishFailure(failure ?? .launchFailed, confirmed: true)
            return
        }
        retainedApplication = app // Only this returned handle can ever receive terminate methods.
        do {
            guard let target else { throw FailureCode.identityChanged }
            try target.recheck()
            let identity = try validateReturned(app)
            accepted = identity
            // Revalidate immediately before acceptance, including the pinned executable.
            guard try verifiedIdentity() == identity else { throw FailureCode.identityChanged }
            if cancelled { beginStop(); return }
            setState(.ready(Witness(uid: identity.uid, ruid: identity.ruid, pid: identity.pid,
                                    startSeconds: identity.seconds, startMicroseconds: identity.microseconds,
                                    bundleIdentifier: target.identifier,
                                    executableURL: URL(fileURLWithPath: target.executablePath),
                                    executableDevice: target.executableNode.device,
                                    executableInode: target.executableNode.inode)))
            // An onStateChange observer can stop synchronously.
            if !cancelled {
                monitorTimer = Self.lifecycleTimer(withTimeInterval: 0.5, repeats: true) { _ in self.monitor() }
            }
        } catch {
            // A returned but unverified process is deliberately not killed.
            finishFailure(.identityChanged, confirmed: false)
        }
    }

    #if MAC_CONNECTION_FIXTURE
    // Metadata-only test of the real callback; never invokes NSWorkspace or grants authority.
    static func fixtureReturnedObservation(_ app: NSRunningApplication?) -> State {
        let session = MacShadowSession(); session.openCompleted(app); return session.state
    }
    #endif

    private func validateReturned(_ app: NSRunningApplication) throws -> NativeIdentity {
        guard let target, !app.isTerminated, app.processIdentifier > 1,
              app.bundleIdentifier == target.identifier, app.bundleURL?.path == target.bundlePath,
              app.executableURL?.path == target.executablePath else { throw FailureCode.identityChanged }
        let first = try NativeIdentity.read(app.processIdentifier, uid: target.uid, executable: target.executablePath)
        // Kernel start must be later than this request, not an adopted old process.
        guard first.seconds > UInt64(launchTime.tv_sec) ||
                (first.seconds == UInt64(launchTime.tv_sec) && first.microseconds >= UInt64(launchTime.tv_nsec / 1000)),
              try NativeIdentity.read(app.processIdentifier, uid: target.uid, executable: target.executablePath) == first else {
            throw FailureCode.identityChanged
        }
        return first
    }

    private func verifiedIdentity() throws -> NativeIdentity {
        guard let target, let app = retainedApplication, let accepted else { throw FailureCode.identityChanged }
        try target.recheckExecutable()
        guard !app.isTerminated, app.processIdentifier == accepted.pid,
              app.bundleIdentifier == target.identifier, app.bundleURL?.path == target.bundlePath,
              app.executableURL?.path == target.executablePath else { throw FailureCode.identityChanged }
        let now = try NativeIdentity.read(accepted.pid, uid: target.uid, executable: target.executablePath)
        guard now == accepted else { throw FailureCode.identityChanged }
        try target.recheckExecutable()
        guard try NativeIdentity.read(accepted.pid, uid: target.uid, executable: target.executablePath) == accepted else {
            throw FailureCode.identityChanged
        }
        return now
    }

    private func observeLifecycle() -> LifecycleObservation {
        guard let app = retainedApplication, let accepted, let target else { return .waiting }
        let before = NativeIdentity.observe(accepted, uid: target.uid, executable: target.executablePath)
        if before == .changed { return .changed }
        let appTerminated = app.isTerminated
        var metadata: LeaseObservation = .unknown
        var pin: LeaseObservation = .unknown
        if !appTerminated {
            let pid = app.processIdentifier
            let identifier = app.bundleIdentifier
            let bundle = app.bundleURL?.path
            let executable = app.executableURL?.path
            if (pid > 1 && pid != accepted.pid) || identifier.map({ $0 != target.identifier }) == true ||
                bundle.map({ $0 != target.bundlePath }) == true || executable.map({ $0 != target.executablePath }) == true {
                metadata = .changed
            } else if pid == accepted.pid && identifier == target.identifier && bundle == target.bundlePath && executable == target.executablePath {
                metadata = .same
            }
            if before == .same && metadata == .same {
                do { try target.recheckExecutable(); pin = .same }
                catch { pin = (error as? FailureCode) == .identityChanged ? .changed : .unknown }
            }
        }
        let after = NativeIdentity.observe(accepted, uid: target.uid, executable: target.executablePath)
        return Self.classifyLifecycle(appTerminated: appTerminated, before: before, after: after, metadata: metadata, pin: pin)
    }

    private func monitor() {
        switch observeLifecycle() {
        case .gone: finishGone()
        case .changed: finishFailure(.identityChanged, confirmed: false)
        case .alive: uncertaintyBegan = nil
        case .waiting:
            let now = DispatchTime.now().uptimeNanoseconds
            if let uncertaintyBegan {
                if now - uncertaintyBegan >= 8_000_000_000 { finishFailure(.identityChanged, confirmed: false) }
            } else { uncertaintyBegan = now }
        }
    }

    private func beginStop() {
        monitorTimer?.invalidate(); monitorTimer = nil
        stopBegan = DispatchTime.now().uptimeNanoseconds
        setState(.stopping)
        stopTimer = Self.lifecycleTimer(withTimeInterval: 0.1, repeats: true) { _ in self.pollStop() }
        pollStop()
    }

    private func pollStop() {
        // Two native reads, retained handle metadata, and the executable FD lease are checked
        // immediately before every terminate method. Waiting never grants signal authority.
        let observation = observeLifecycle()
        let now = DispatchTime.now().uptimeNanoseconds
        let elapsed = now - stopBegan
        let graceElapsed = gracefulSent ? now - gracefulSentAt : 0
        switch Self.stopAction(observation, elapsed: elapsed, gracefulSent: gracefulSent, forced: forced, graceElapsed: graceElapsed) {
        case .gone: finishGone()
        case .failIdentity: finishFailure(.identityChanged, confirmed: false)
        case .failDeadline: finishFailure(.stopDeadline, confirmed: false)
        case .wait: break
        case .terminate:
            gracefulSentAt = now
            gracefulSent = true
            _ = retainedApplication?.terminate()
        case .forceTerminate:
            forced = true
            _ = retainedApplication?.forceTerminate()
        }
    }

    private func setState(_ next: State) {
        guard state != next else { return }
        state = next
        onStateChange?(next)
    }
    private func finishGone() {
        clearTimers()
        retainedApplication = nil; accepted = nil; target = nil
        if let failure { setState(.failed(failure, cleanupConfirmed: true)) }
        else { setState(.stopped) }
        keepAlive = nil
    }
    private func finishFailure(_ code: FailureCode, confirmed: Bool) {
        clearTimers()
        failure = code
        setState(.failed(code, cleanupConfirmed: confirmed))
        // No further authority is used after identity loss or a bounded stop deadline.
        // The pending-open callback alone can still resume cleanup for its late returned handle.
        if !pendingOpen { retainedApplication = nil; accepted = nil; target = nil; keepAlive = nil }
    }
    private func clearTimers() {
        launchTimer?.invalidate(); launchTimer = nil
        stopTimer?.invalidate(); stopTimer = nil
        monitorTimer?.invalidate(); monitorTimer = nil
    }

    private struct NativeIdentity: Equatable {
        let pid: Int32
        let uid: UInt32, ruid: UInt32
        let seconds: UInt64, microseconds: UInt64
        static func read(_ pid: Int32, uid: uid_t, executable: String) throws -> NativeIdentity {
            guard pid > 1, MemoryLayout<proc_bsdinfo>.size == 136,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_pid) == 12,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_uid) == 20,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_ruid) == 28,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_start_tvsec) == 120,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_start_tvusec) == 128 else { throw FailureCode.identityChanged }
            var info = proc_bsdinfo()
            let count = withUnsafeMutablePointer(to: &info) { proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, $0, 136) }
            var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
            let length = path.withUnsafeMutableBytes { proc_pidpath(pid, $0.baseAddress, UInt32($0.count)) }
            guard count == 136, info.pbi_pid == UInt32(pid), info.pbi_uid == uid, info.pbi_ruid == uid,
                  info.pbi_start_tvsec > 0, info.pbi_start_tvusec < 1_000_000,
                  length > 0, String(cString: path) == executable else { throw FailureCode.identityChanged }
            return NativeIdentity(pid: pid, uid: info.pbi_uid, ruid: info.pbi_ruid,
                                  seconds: info.pbi_start_tvsec, microseconds: info.pbi_start_tvusec)
        }
        static func classifyValues(_ observed: NativeIdentity, path: String, expected: NativeIdentity, executable: String) -> NativeObservation {
            observed == expected && path == executable ? .same : .changed
        }
        static func observe(_ expected: NativeIdentity, uid: uid_t, executable: String) -> NativeObservation {
            guard expected.pid > 1, MemoryLayout<proc_bsdinfo>.size == 136,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_pid) == 12,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_uid) == 20,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_ruid) == 28,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_start_tvsec) == 120,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_start_tvusec) == 128,
                  getuid() == uid, geteuid() == uid else { return .unknown }
            var info = proc_bsdinfo()
            errno = 0
            let count = withUnsafeMutablePointer(to: &info) { proc_pidinfo(expected.pid, PROC_PIDTBSDINFO, 0, $0, 136) }
            if count == 0 && errno == ESRCH { return .absent }
            guard count == 136, info.pbi_start_tvsec > 0, info.pbi_start_tvusec < 1_000_000 else { return .unknown }
            let observed = NativeIdentity(pid: Int32(bitPattern: info.pbi_pid), uid: info.pbi_uid, ruid: info.pbi_ruid,
                                          seconds: info.pbi_start_tvsec, microseconds: info.pbi_start_tvusec)
            if observed != expected { return .changed }
            var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
            errno = 0
            let length = path.withUnsafeMutableBytes { proc_pidpath(expected.pid, $0.baseAddress, UInt32($0.count)) }
            if length == 0 && errno == ESRCH { return .absent }
            guard length > 0 else { return .unknown }
            return classifyValues(observed, path: String(cString: path), expected: expected, executable: executable)
        }
    }

    private struct Node: Equatable {
        let device: UInt64, inode: UInt64, size: Int64, seconds: Int64, nanos: Int64, changeSeconds: Int64, changeNanos: Int64
        init(_ s: stat) {
            device = UInt64(s.st_dev); inode = UInt64(s.st_ino); size = s.st_size
            seconds = Int64(s.st_mtimespec.tv_sec); nanos = Int64(s.st_mtimespec.tv_nsec)
            changeSeconds = Int64(s.st_ctimespec.tv_sec); changeNanos = Int64(s.st_ctimespec.tv_nsec)
        }
    }
    private final class ValidatedTarget {
        let uid: uid_t
        let home: String
        let bundlePath: String
        let executablePath: String
        let identifier: String
        let executableName: String
        let executableNode: Node
        private let executableFD: Int32
        private let directories: [(String, UInt64, UInt64)]
        private let executableHash: Data
        #if MAC_SHADOW_SESSION_FIXTURE
        private let fixtureHash: String?
        init(fixture: Bool = false) throws {
            let owner = try Self.owner()
            uid = owner.0; home = owner.1
            let spec = fixture ? try Self.fixtureSpec(uid: uid, home: home) : nil
            bundlePath = spec?.0 ?? home + "/Library/Application Support/wx-mcp/WeChat-shadow.app"
            identifier = spec == nil ? "com.tencent.xinWeChat" : "org.wechatpilot.generated.launchprobe.target"
            executableName = spec == nil ? "WeChat" : "LaunchProbe"
            fixtureHash = spec?.1
            executablePath = bundlePath + "/Contents/MacOS/" + executableName
            let opened = try Self.openTarget(home: home, bundle: bundlePath, executable: executableName, uid: uid)
            directories = opened.1
            do {
                let node = try Self.fileNode(opened.0, uid: uid)
                let hash = try Self.hash(opened.0)
                try Self.checkInfo(bundlePath, uid: uid, identifier: identifier, executable: executableName)
                if let fixtureHash, Self.hex(hash) != fixtureHash { throw FailureCode.managedBundleInvalid }
                try Self.checkSignature(bundlePath)
                executableNode = node; executableHash = hash; executableFD = opened.0
            } catch { close(opened.0); throw error }
        }
        #else
        init() throws {
            let owner = try Self.owner()
            uid = owner.0; home = owner.1
            bundlePath = home + "/Library/Application Support/wx-mcp/WeChat-shadow.app"
            identifier = "com.tencent.xinWeChat"; executableName = "WeChat"
            executablePath = bundlePath + "/Contents/MacOS/" + executableName
            let opened = try Self.openTarget(home: home, bundle: bundlePath, executable: executableName, uid: uid)
            directories = opened.1
            do {
                let node = try Self.fileNode(opened.0, uid: uid)
                let hash = try Self.hash(opened.0)
                try Self.checkInfo(bundlePath, uid: uid, identifier: identifier, executable: executableName)
                try Self.checkSignature(bundlePath)
                executableNode = node; executableHash = hash; executableFD = opened.0
            } catch { close(opened.0); throw error }
        }
        #endif
        deinit { close(executableFD) }
        func recheck() throws {
            try recheckExecutable(hashContents: true)
            try Self.checkInfo(bundlePath, uid: uid, identifier: identifier, executable: executableName)
            try Self.checkSignature(bundlePath)
            try recheckExecutable(hashContents: true)
        }
        func recheckExecutable(hashContents: Bool = false) throws {
            guard getuid() == uid, geteuid() == uid, uid != 0 else { throw FailureCode.ownerInvalid }
            let opened = try Self.openTarget(home: home, bundle: bundlePath, executable: executableName, uid: uid)
            defer { close(opened.0) }
            guard opened.1.count == directories.count,
                  zip(opened.1, directories).allSatisfy({ $0.0 == $1.0 && $0.1 == $1.1 && $0.2 == $1.2 }),
                  try Self.fileNode(executableFD, uid: uid) == executableNode,
                  try Self.fileNode(opened.0, uid: uid) == executableNode else { throw FailureCode.identityChanged }
            if hashContents, try Self.hash(executableFD) != executableHash { throw FailureCode.identityChanged }
        }
        private static func owner() throws -> (uid_t, String) {
            let uid = getuid()
            guard uid != 0, geteuid() == uid else { throw FailureCode.ownerInvalid }
            var entry = passwd(), found: UnsafeMutablePointer<passwd>?
            var buffer = [CChar](repeating: 0, count: 64 * 1024)
            var ownerHome: String?
            let result = buffer.withUnsafeMutableBufferPointer { pointer -> Int32 in
                let code = getpwuid_r(uid, &entry, pointer.baseAddress, pointer.count, &found)
                if code == 0, found != nil, entry.pw_uid == uid, let directory = entry.pw_dir {
                    ownerHome = String(cString: directory)
                }
                return code
            }
            guard result == 0, let home = ownerHome else { throw FailureCode.ownerInvalid }
            guard home.hasPrefix("/"), home != "/", home == URL(fileURLWithPath: home).standardizedFileURL.path else {
                throw FailureCode.ownerInvalid
            }
            return (uid, home)
        }
        private static func openTarget(home: String, bundle: String, executable: String, uid: uid_t) throws -> (Int32, [(String, UInt64, UInt64)]) {
            guard bundle.hasPrefix(home + "/") else { throw FailureCode.managedBundleInvalid }
            let full = bundle + "/Contents/MacOS"
            var directory = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard directory >= 0 else { throw FailureCode.managedBundleInvalid }
            defer { close(directory) }
            var path = "", nodes: [(String, UInt64, UInt64)] = []
            for component in full.split(separator: "/") {
                let next = openat(directory, String(component), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
                guard next >= 0 else { throw FailureCode.managedBundleInvalid }
                close(directory); directory = next
                path += "/" + component
                var info = stat()
                guard fstat(directory, &info) == 0, info.st_mode & S_IFMT == S_IFDIR,
                      !(path == home || path.hasPrefix(home + "/")) || info.st_uid == uid else { throw FailureCode.managedBundleInvalid }
                nodes.append((path, UInt64(info.st_dev), UInt64(info.st_ino)))
            }
            let fd = openFileLeaf(directory: directory, name: executable)
            guard fd >= 0 else { throw FailureCode.managedBundleInvalid }
            do {
                _ = try fileNode(fd, uid: uid)
                var info = stat()
                guard fstat(fd, &info) == 0, info.st_mode & 0o111 != 0 else { throw FailureCode.managedBundleInvalid }
            } catch { close(fd); throw error }
            return (fd, nodes)
        }
        private static func openFileLeaf(directory: Int32, name: String) -> Int32 {
            openat(directory, name, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        }
        private static func fileNode(_ fd: Int32, uid: uid_t) throws -> Node {
            var s = stat()
            guard fstat(fd, &s) == 0, s.st_uid == uid, s.st_mode & S_IFMT == S_IFREG,
                  s.st_nlink == 1, s.st_size > 0, s.st_size <= 512 * 1024 * 1024 else { throw FailureCode.managedBundleInvalid }
            return Node(s)
        }
        private static func readFile(_ path: String, uid: uid_t, limit: Int) throws -> Data {
            var directory = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard directory >= 0 else { throw FailureCode.managedBundleInvalid }
            defer { close(directory) }
            let parts = path.split(separator: "/")
            guard let leaf = parts.last else { throw FailureCode.managedBundleInvalid }
            for component in parts.dropLast() {
                let next = openat(directory, String(component), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
                guard next >= 0 else { throw FailureCode.managedBundleInvalid }
                close(directory); directory = next
            }
            let fd = openFileLeaf(directory: directory, name: String(leaf))
            guard fd >= 0 else { throw FailureCode.managedBundleInvalid }
            defer { close(fd) }
            let node = try fileNode(fd, uid: uid)
            guard node.size <= limit else { throw FailureCode.managedBundleInvalid }
            var data = Data(count: Int(node.size))
            var done = 0
            while done < data.count {
                let n = data.withUnsafeMutableBytes { read(fd, $0.baseAddress!.advanced(by: done), $0.count - done) }
                guard n > 0 else { throw FailureCode.managedBundleInvalid }
                done += n
            }
            guard try fileNode(fd, uid: uid) == node else { throw FailureCode.managedBundleInvalid }
            return data
        }
        private static func hash(_ fd: Int32) throws -> Data {
            var digest = SHA256(), offset: off_t = 0
            var buffer = [UInt8](repeating: 0, count: 64 * 1024)
            while true {
                let count = buffer.withUnsafeMutableBytes { pread(fd, $0.baseAddress, $0.count, offset) }
                guard count >= 0, offset <= 512 * 1024 * 1024 else { throw FailureCode.managedBundleInvalid }
                if count == 0 { break }
                digest.update(data: Data(buffer.prefix(count))); offset += off_t(count)
            }
            return Data(digest.finalize())
        }
        private static func checkInfo(_ bundle: String, uid: uid_t, identifier: String, executable: String) throws {
            let data = try readFile(bundle + "/Contents/Info.plist", uid: uid, limit: 1024 * 1024)
            guard let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
                  info["CFBundleIdentifier"] as? String == identifier,
                  info["CFBundleExecutable"] as? String == executable,
                  info["CFBundlePackageType"] as? String == "APPL" else { throw FailureCode.managedBundleInvalid }
        }
        private static func checkSignature(_ bundle: String) throws {
            var code: SecStaticCode?
            guard SecStaticCodeCreateWithPath(URL(fileURLWithPath: bundle) as CFURL, SecCSFlags(), &code) == errSecSuccess,
                  let code else { throw FailureCode.signatureInvalid }
            let flags = SecCSFlags(rawValue: kSecCSCheckAllArchitectures | kSecCSCheckNestedCode | kSecCSStrictValidate)
            guard SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess else { throw FailureCode.signatureInvalid }
            var info: CFDictionary?
            guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
                  let dictionary = info as? [String: Any],
                  let signatureFlags = dictionary[kSecCodeInfoFlags as String] as? NSNumber,
                  SecCodeSignatureFlags(rawValue: signatureFlags.uint32Value).contains(.adhoc) else { throw FailureCode.signatureInvalid }
        }
        #if MAC_SHADOW_SESSION_FIXTURE
        static func fixtureRejectsGeneratedFIFO() -> Bool {
            guard getuid() == geteuid(), getuid() != 0, let executable = Bundle.main.executableURL,
                  executable.lastPathComponent == "SessionProbe.build" else { return false }
            let root = executable.deletingLastPathComponent().path
            let prefix = FileManager.default.homeDirectoryForCurrentUser.path + "/WeChatPilot/wechat-collector-mac/.runtime/shadow-session-probe-"
            guard root.hasPrefix(prefix), UUID(uuidString: String(root.dropFirst(prefix.count))) != nil else { return false }
            let directory = open(root, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
            guard directory >= 0 else { return false }
            defer { close(directory) }
            var info = stat()
            guard fstat(directory, &info) == 0, info.st_uid == getuid(), info.st_mode & 0o777 == 0o700 else { return false }
            let leaf = "fifo-test-" + UUID().uuidString.lowercased()
            guard mkfifo(root + "/" + leaf, 0o600) == 0 else { return false }
            defer { unlinkat(directory, leaf, 0) }
            let start = DispatchTime.now().uptimeNanoseconds
            do { _ = try readFile(root + "/" + leaf, uid: getuid(), limit: 4096); return false }
            catch {
                return error as? FailureCode == .managedBundleInvalid &&
                    DispatchTime.now().uptimeNanoseconds - start < 1_000_000_000
            }
        }
        private static func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }
        private static func fixtureSpec(uid: uid_t, home: String) throws -> (String, String) {
            let project = home + "/WeChatPilot/wechat-collector-mac"
            let root = project + "/.runtime/launch-probe-4b30c6be-06e0-4671-a5f4-3dfc804c174d"
            guard uid == getuid(), root.hasPrefix(home + "/"),
                  UUID(uuidString: String(root.split(separator: "/").last!.dropFirst("launch-probe-".count))) != nil else {
                throw FailureCode.managedBundleInvalid
            }
            // openTarget also walks every ancestor with O_NOFOLLOW before this fixture is launched.
            for path in [project, project + "/.runtime", root] {
                var info = stat()
                guard lstat(path, &info) == 0, info.st_uid == uid, info.st_mode & S_IFMT == S_IFDIR,
                      path != root || info.st_mode & 0o777 == 0o700 else { throw FailureCode.managedBundleInvalid }
            }
            let manifestPath = root + "/manifest.json"
            var info = stat()
            guard lstat(manifestPath, &info) == 0, info.st_mode & 0o777 == 0o600 else { throw FailureCode.managedBundleInvalid }
            let data = try readFile(manifestPath, uid: uid, limit: 4096)
            guard let m = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  m["schema"] as? Int == 1, m["uid"] as? UInt32 == uid, m["fixtureRoot"] as? String == root,
                  m["launcherBundleIdentifier"] as? String == "org.wechatpilot.generated.launchprobe.launcher",
                  m["targetBundleIdentifier"] as? String == "org.wechatpilot.generated.launchprobe.target",
                  let hash = m["targetExecutableSHA256"] as? String,
                  hash == "3f59f837763f045ff09f84d672d0ca9af0a8f5e17b6c2f61dee8cdc66412b5fd" else { throw FailureCode.managedBundleInvalid }
            return (root + "/Target.app", hash)
        }
        #endif
    }
}
