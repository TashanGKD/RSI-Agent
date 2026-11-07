import AppKit
import CryptoKit
import Darwin
import Security

// Fixed Xcode distribution forms (Apple TN3127); no runtime requirement grants trust.
// Call signedMetadataMatches only after the corresponding Security validity check succeeds.
enum MacOriginalSignaturePolicy {
    static let requirement = "anchor apple generic and identifier \"com.tencent.xinWeChat\" and (certificate leaf[field.1.2.840.113635.100.6.1.9] or (certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = \"5A4RE8SF68\"))"
    static let companionRequirement = "anchor apple generic and identifier \"wxplayer\" and (certificate leaf[field.1.2.840.113635.100.6.1.9] or (certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = \"5A4RE8SF68\"))"
    static func matches(_ information: [String: Any], companion: Bool = false) -> Bool {
        information[kSecCodeInfoIdentifier as String] as? String == (companion ? "wxplayer" : "com.tencent.xinWeChat") &&
        information[kSecCodeInfoTeamIdentifier as String] as? String == "5A4RE8SF68"
    }
    static func signedMetadataMatches(_ code: SecStaticCode, companion: Bool = false) -> Bool {
        var information: CFDictionary?
        guard SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
              let information = information as? [String: Any] else { return false }
        return matches(information, companion: companion)
    }
}

protocol MacConnectionOriginalLifetime: AnyObject {
    var pending: Bool { get }
    var settled: Bool { get }
    var restorationFailed: Bool { get }
    var onReopened: (() -> Void)? { get set }
    var onChange: (() -> Void)? { get set }
    func prepare(_ completion: @escaping (Bool) -> Void)
    func cancel()
    func observeBeforeDispatch() -> Bool
    func finishAfterProtectedCleanup()
    func finishUnconfirmedCleanup()
    func sealForApplicationExit()
}

// Only one explicit protected connection owns this coordinator. Construction is inert.
// File leases below attest userspace installation identity, never a kernel text vnode.
final class MacOriginalHandover: MacConnectionOriginalLifetime {
    private struct Identity: Equatable {
        let pid: pid_t, uid: uid_t, ruid: uid_t
        let seconds: UInt64, micros: UInt64
        static func matches(pid: pid_t, uid: uid_t, ruid: uid_t, seconds: UInt64, micros: UInt64, path: String, owner: uid_t, executable: String) -> Bool {
            pid > 1 && owner != 0 && uid == owner && ruid == owner && seconds > 0 && micros < 1_000_000 && path == executable
        }
        static func read(_ pid: pid_t, path: String, owner: uid_t) throws -> Identity {
            guard pid > 1, owner != 0, getuid() == owner, geteuid() == owner,
                  MemoryLayout<proc_bsdinfo>.size == 136,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_start_tvsec) == 120,
                  MemoryLayout<proc_bsdinfo>.offset(of: \.pbi_start_tvusec) == 128 else { throw Failure.identity }
            var b = proc_bsdinfo(), name = [CChar](repeating: 0, count: 4096)
            let n = withUnsafeMutablePointer(to: &b) { proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, $0, 136) }
            let length = name.withUnsafeMutableBytes { proc_pidpath(pid, $0.baseAddress, UInt32($0.count)) }
            guard n == 136, length > 0, b.pbi_pid == UInt32(pid),
                  matches(pid: pid, uid: b.pbi_uid, ruid: b.pbi_ruid, seconds: b.pbi_start_tvsec, micros: b.pbi_start_tvusec, path: String(cString: name), owner: owner, executable: path) else { throw Failure.identity }
            return Identity(pid: pid, uid: b.pbi_uid, ruid: b.pbi_ruid, seconds: b.pbi_start_tvsec, micros: b.pbi_start_tvusec)
        }
        var positivelyAbsent: Bool {
            var b = proc_bsdinfo(); errno = 0
            let n = withUnsafeMutablePointer(to: &b) { proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, $0, 136) }
            return n == 0 && errno == ESRCH
        }
    }
    private enum Failure: Error { case identity, installation, signature }
    private struct Node: Equatable {
        let dev: Int32, inode: UInt64, size: Int64, mtime: Int64, mnano: Int64, ctime: Int64, cnano: Int64
        init(_ s: stat) { dev = s.st_dev; inode = s.st_ino; size = s.st_size; mtime = Int64(s.st_mtimespec.tv_sec); mnano = Int64(s.st_mtimespec.tv_nsec); ctime = Int64(s.st_ctimespec.tv_sec); cnano = Int64(s.st_ctimespec.tv_nsec) }
    }
    private final class Installation {
        let bundle: String, executable: String, identifier: String, owner: uid_t
        let requirement: SecRequirement
        private let pins: [(String, Node)], exeFD: Int32, exeHash: Data
        init() throws {
            owner = getuid(); guard owner != 0, geteuid() == owner else { throw Failure.identity }
            #if MAC_ORIGINAL_HANDOVER_FIXTURE
            bundle = "/private/tmp/wechatpilot-original-handover-v1-\(owner)/OriginalFixture.app"
            executable = bundle + "/Contents/MacOS/OriginalFixture"
            identifier = "org.wechatpilot.generated.originalhandover"
            let rule = "identifier \"\(identifier)\" and cdhash H\"\(OriginalFixturePins.cdhash)\""
            precondition(bundle != "/Applications/WeChat.app" && identifier != "com.tencent.xinWeChat")
            #else
            bundle = "/Applications/WeChat.app"; executable = bundle + "/Contents/MacOS/WeChat"; identifier = "com.tencent.xinWeChat"
            let rule = MacOriginalSignaturePolicy.requirement
            #endif
            var req: SecRequirement?
            guard SecRequirementCreateWithString(rule as CFString, [], &req) == errSecSuccess, let req else { throw Failure.signature }
            requirement = req
            var list: [(String, Node)] = []
            var current = ""
            for part in executable.split(separator: "/") {
                current += "/" + part; var s = stat()
                guard lstat(current, &s) == 0, s.st_mode & S_IFMT != S_IFLNK else { throw Failure.installation }
                if current == executable { guard s.st_mode & S_IFMT == S_IFREG, s.st_nlink == 1, s.st_size > 0, s.st_size <= 512*1024*1024 else { throw Failure.installation } }
                else { guard s.st_mode & S_IFMT == S_IFDIR else { throw Failure.installation } }
                list.append((current, Node(s)))
            }
            let info = bundle + "/Contents/Info.plist"; var ist = stat()
            guard lstat(info, &ist) == 0, ist.st_mode & S_IFMT == S_IFREG else { throw Failure.installation }
            list.append((info, Node(ist)))
            let fd = open(executable, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
            guard fd >= 0 else { throw Failure.installation }
            exeFD = fd; pins = list
            do { exeHash = try Self.hash(fd) } catch { close(fd); throw error }
            try recheck() // Fully initialized: deinit exclusively owns exeFD from this point.
        }
        deinit { close(exeFD) }
        private static func hash(_ fd: Int32, maxBytes: off_t = 512*1024*1024) throws -> Data {
            var digest = SHA256(), offset: off_t = 0, bytes = [UInt8](repeating: 0, count: 65536)
            while true {
                let n = bytes.withUnsafeMutableBytes { pread(fd, $0.baseAddress, $0.count, offset) }
                guard n >= 0, offset <= maxBytes else { throw Failure.installation }
                if n == 0 { return Data(digest.finalize()) }; digest.update(data: Data(bytes.prefix(n))); offset += off_t(n)
            }
        }
        func recheck() throws {
            guard getuid() == owner, geteuid() == owner else { throw Failure.identity }
            for (path, expected) in pins {
                var s = stat(); guard lstat(path, &s) == 0, s.st_mode & S_IFMT != S_IFLNK else { throw Failure.installation }
                // Ancestors may receive unrelated new entries. Their device/inode remain pinned.
                let now = Node(s)
                if path == executable || path == bundle + "/Contents/Info.plist" { guard now == expected else { throw Failure.installation } }
                else { guard now.dev == expected.dev, now.inode == expected.inode else { throw Failure.installation } }
            }
            var s = stat(); guard fstat(exeFD, &s) == 0, Node(s) == pins.first(where: {$0.0 == executable})!.1,
                try Self.hash(exeFD) == exeHash else { throw Failure.installation }
            let data = try Data(contentsOf: URL(fileURLWithPath: bundle + "/Contents/Info.plist"))
            guard let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
                  info["CFBundleIdentifier"] as? String == identifier, info["CFBundleExecutable"] as? String == URL(fileURLWithPath: executable).lastPathComponent else { throw Failure.installation }
            var code: SecStaticCode?
            guard SecStaticCodeCreateWithPath(URL(fileURLWithPath: bundle) as CFURL, [], &code) == errSecSuccess,
                  let code, SecStaticCodeCheckValidity(code, SecCSFlags(rawValue: kSecCSCheckAllArchitectures | kSecCSCheckNestedCode | kSecCSStrictValidate), requirement) == errSecSuccess,
                  Self.signedMetadataMatches(code) else { throw Failure.signature }
        }
        private static func signedMetadataMatches(_ code: SecStaticCode) -> Bool {
            #if MAC_ORIGINAL_HANDOVER_FIXTURE
            return true // Synthetic ad-hoc fixture has its own exact compiled cdhash requirement.
            #else
            return MacOriginalSignaturePolicy.signedMetadataMatches(code)
            #endif
        }
        private static func signedMetadataMatches(_ code: SecCode) -> Bool {
            // Signing information for dynamic code is its static signature, not image attestation.
            var staticCode: SecStaticCode?
            guard SecCodeCopyStaticCode(code, [], &staticCode) == errSecSuccess, let staticCode else { return false }
            return signedMetadataMatches(staticCode)
        }
        func validate(_ app: NSRunningApplication) throws -> Identity {
            guard app.bundleURL?.path == bundle, app.executableURL?.path == executable, app.bundleIdentifier == identifier, !app.isTerminated else { throw Failure.identity }
            let before = try Identity.read(app.processIdentifier, path: executable, owner: owner)
            try recheck()
            var dynamic: SecCode?
            let attributes = [kSecGuestAttributePid as String: NSNumber(value: before.pid)] as CFDictionary
            guard SecCodeCopyGuestWithAttributes(nil, attributes, [], &dynamic) == errSecSuccess, let dynamic,
                  SecCodeCheckValidity(dynamic, [], requirement) == errSecSuccess,
                  Self.signedMetadataMatches(dynamic),
                  try Identity.read(app.processIdentifier, path: executable, owner: owner) == before,
                  app.bundleURL?.path == bundle, app.executableURL?.path == executable else { throw Failure.signature }
            return before
        }
        // Only this closed AppKit role is eligible for independent companion verification.
        static func companionRoleMatches(bundle: String?, executable: String?, identifier: String?, terminated: Bool) -> Bool {
            bundle == "/Applications/WeChat.app" && executable == "/Applications/WeChat.app/Contents/Frameworks/wxplayer" && identifier == nil && !terminated
        }
        private final class Companion {
            let executable: String
            private let pins: [(String, Node)], fd: Int32, hash: Data, requirement: SecRequirement
            init() throws {
                #if MAC_ORIGINAL_COMPANION_FILE_FIXTURE
                executable = "/private/tmp/wechatpilot-original-companion-v1-\(getuid())/OriginalFixture.app/Contents/Frameworks/wxplayer"
                precondition(!executable.hasPrefix("/Applications/"))
                #else
                executable = "/Applications/WeChat.app/Contents/Frameworks/wxplayer"
                #endif
                var list: [(String, Node)] = [], current = ""
                for part in executable.split(separator: "/") {
                    current += "/" + part; var s = stat()
                    guard lstat(current, &s) == 0, s.st_mode & S_IFMT != S_IFLNK else { throw Failure.installation }
                    if current == executable {
                        guard s.st_mode & S_IFMT == S_IFREG, s.st_nlink == 1, s.st_size > 0, s.st_size <= 64*1024*1024 else { throw Failure.installation }
                    } else { guard s.st_mode & S_IFMT == S_IFDIR else { throw Failure.installation } }
                    list.append((current, Node(s)))
                }
                var req: SecRequirement?
                guard SecRequirementCreateWithString(MacOriginalSignaturePolicy.companionRequirement as CFString, [], &req) == errSecSuccess, let req else { throw Failure.signature }
                requirement = req; pins = list
                let opened = open(executable, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
                guard opened >= 0 else { throw Failure.installation }; fd = opened
                do { hash = try Installation.hash(fd, maxBytes: 64*1024*1024) } catch { close(fd); throw error }
                try recheck() // Fully initialized: deinit owns fd, including failures below.
            }
            func verifyStatic() throws {
                var code: SecStaticCode?
                guard SecStaticCodeCreateWithPath(URL(fileURLWithPath: executable) as CFURL, [], &code) == errSecSuccess, let code,
                      SecStaticCodeCheckValidity(code, SecCSFlags(rawValue: kSecCSCheckAllArchitectures | kSecCSCheckNestedCode | kSecCSStrictValidate), requirement) == errSecSuccess,
                      MacOriginalSignaturePolicy.signedMetadataMatches(code, companion: true) else { throw Failure.signature }
                try recheck()
            }
            deinit { close(fd) }
            private func recheck() throws {
                for (path, expected) in pins {
                    var s = stat(); guard lstat(path, &s) == 0, s.st_mode & S_IFMT != S_IFLNK else { throw Failure.installation }
                    let now = Node(s)
                    if path == executable { guard now == expected else { throw Failure.installation } }
                    else { guard now.dev == expected.dev, now.inode == expected.inode else { throw Failure.installation } }
                }
                var s = stat()
                guard fstat(fd, &s) == 0, Node(s) == pins.last!.1, try Installation.hash(fd, maxBytes: 64*1024*1024) == hash else { throw Failure.installation }
            }
            #if MAC_ORIGINAL_COMPANION_FILE_FIXTURE
            func fixtureReplacementFails() -> Bool {
                precondition(!executable.hasPrefix("/Applications/"))
                do {
                    try Data("atomic replacement helper".utf8).write(to: URL(fileURLWithPath: executable), options: .atomic)
                    try recheck(); return false
                } catch Failure.installation { return true }
                catch { return false }
            }
            #endif
            func validate(_ app: NSRunningApplication, owner: uid_t) throws {
                guard Installation.companionRoleMatches(bundle: app.bundleURL?.path, executable: app.executableURL?.path, identifier: app.bundleIdentifier, terminated: app.isTerminated) else { throw Failure.identity }
                let before = try Identity.read(app.processIdentifier, path: executable, owner: owner)
                try recheck(); try verifyStatic()
                var code: SecCode?, staticCode: SecStaticCode?
                let attributes = [kSecGuestAttributePid as String: NSNumber(value: before.pid)] as CFDictionary
                guard SecCodeCopyGuestWithAttributes(nil, attributes, [], &code) == errSecSuccess, let code,
                      SecCodeCheckValidity(code, [], requirement) == errSecSuccess,
                      SecCodeCopyStaticCode(code, [], &staticCode) == errSecSuccess, let staticCode,
                      MacOriginalSignaturePolicy.signedMetadataMatches(staticCode, companion: true) else { throw Failure.signature }
                try recheck()
                guard try Identity.read(app.processIdentifier, path: executable, owner: owner) == before,
                      Installation.companionRoleMatches(bundle: app.bundleURL?.path, executable: app.executableURL?.path, identifier: app.bundleIdentifier, terminated: app.isTerminated) else { throw Failure.identity }
                #if MAC_ORIGINAL_COMPANION_DISCOVERY_FIXTURE
                print("verified helper pid=\(before.pid) uid=\(before.uid) ruid=\(before.ruid) birth=\(before.seconds).\(before.micros) path=\(executable); signed TeamIdentifier=5A4RE8SF68 Identifier=wxplayer after static+dynamic validity")
                #endif
            }
        }
        func candidates() -> [NSRunningApplication] {
            NSWorkspace.shared.runningApplications.filter { app in
                guard app.bundleURL?.path == bundle || app.executableURL?.path == executable else { return false }
                guard Self.companionRoleMatches(bundle: app.bundleURL?.path, executable: app.executableURL?.path, identifier: app.bundleIdentifier, terminated: app.isTerminated) else { return true }
                do { try Companion().validate(app, owner: owner); return false }
                catch { return true } // Unknown/invalid companion remains blocking, including when main is absent.
            }
        }
        #if MAC_ORIGINAL_COMPANION_FILE_FIXTURE
        static func fixtureCompanionReplacement() -> Bool {
            do { return try Companion().fixtureReplacementFails() } catch { return false }
        }
        static func fixtureCompanionFailure() -> String {
            do { let target = try Companion(); try target.verifyStatic(); return "accepted" }
            catch Failure.installation { return "installation" }
            catch { return "signature" }
        }
        #endif
    }
    private var installation: Installation?, exact: NSRunningApplication?, identity: Identity?
    private var started = false, cancelled = false, sealed = false, quitAccepted = false
    private var terminateAttempted = false, restoreAttempted = false, originalGone = false, restoreOwed = false
    private var foreignReopened = false, quitOutstanding = false, openOutstanding = false, safeCleanup = false
    private var prepareReply: ((Bool) -> Void)?, timer: Timer?, openTimer: Timer?
    private var quitDeadline: UInt64 = 0
    private(set) var settled = false
    private(set) var failureCode: String?
    var pending: Bool { quitOutstanding || openOutstanding }
    var restorationFailed: Bool { failureCode == "restoreUnconfirmed" || failureCode == "restoreIdentityUnconfirmed" }
    var onReopened: (() -> Void)?, onChange: (() -> Void)?
    init() {}
    #if MAC_ORIGINAL_HANDOVER_FIXTURE
    enum FixtureRestoreDelivery { case actual, nilResult, error, late }
    var fixtureRestoreDelivery: FixtureRestoreDelivery = .actual
    var fixtureTerminateCalls: Int { terminateAttempted ? 1 : 0 }
    var fixtureRestoreCalls: Int { restoreAttempted ? 1 : 0 }
    static func fixtureSameIdentity(expectedBirth: UInt64, observedBirth: UInt64, expectedMicro: UInt64 = 1, observedMicro: UInt64 = 1) -> Bool {
        Identity(pid: 42, uid: 501, ruid: 501, seconds: expectedBirth, micros: expectedMicro) == Identity(pid: 42, uid: 501, ruid: 501, seconds: observedBirth, micros: observedMicro)
    }
    static func fixtureIdentityMatches(pid: pid_t = 42, uid: uid_t = 501, ruid: uid_t = 501, seconds: UInt64 = 1, micros: UInt64 = 1, path: String = "/generated", owner: uid_t = 501) -> Bool {
        Identity.matches(pid: pid, uid: uid, ruid: ruid, seconds: seconds, micros: micros, path: path, owner: owner, executable: "/generated")
    }
    #endif
    #if MAC_ORIGINAL_COMPANION_FILE_FIXTURE
    static func fixtureGeneratedCompanionFailure() -> String { Installation.fixtureCompanionFailure() }
    static func fixtureGeneratedCompanionReplacementFails() -> Bool { Installation.fixtureCompanionReplacement() }
    #endif
    private static func timer(_ seconds: TimeInterval, repeats: Bool, _ block: @escaping @Sendable (Timer) -> Void) -> Timer {
        let t = Timer(timeInterval: seconds, repeats: repeats, block: block); RunLoop.main.add(t, forMode: .common); return t
    }
    func prepare(_ completion: @escaping (Bool) -> Void) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard !started, !cancelled, !sealed else { completion(false); return }; started = true; prepareReply = completion
        do {
            let target = try Installation(); installation = target
            let candidates = target.candidates()
            guard candidates.count <= 1 else { throw Failure.identity }
            guard let app = candidates.first else { replyPrepare(true); startMonitor(); return }
            exact = app; identity = try target.validate(app)
            guard !cancelled, !sealed, !terminateAttempted else { replyPrepare(false); return }
            guard try target.validate(app) == identity else { throw Failure.identity }
            let current = target.candidates()
            guard current.count == 1, current[0].processIdentifier == app.processIdentifier else { throw Failure.identity }
            terminateAttempted = true; quitOutstanding = true
            quitDeadline = DispatchTime.now().uptimeNanoseconds + 8_000_000_000
            quitAccepted = app.terminate() // Sole normal-quit authority. Never an escalation.
            if !quitAccepted { quitOutstanding = false; failureCode = "quitRefused"; replyPrepare(false); onChange?(); return }
            startMonitor(); tick()
        } catch { failureCode = "originalIdentityUnconfirmed"; replyPrepare(false); onChange?() }
    }
    private func replyPrepare(_ value: Bool) { let reply = prepareReply; prepareReply = nil; reply?(value && !cancelled && !sealed) }
    private func startMonitor() { guard !sealed, !settled, timer == nil else { return }; timer = Self.timer(0.15, repeats: true) { [weak self] _ in self?.tick() } }
    private func tick() {
        guard !sealed, let target = installation else { return }
        if quitOutstanding, let exact, let identity {
            if exact.isTerminated && identity.positivelyAbsent {
                quitOutstanding = false; originalGone = true; restoreOwed = quitAccepted; replyPrepare(true); onChange?()
                if safeCleanup { finishAfterProtectedCleanup() }
            } else if DispatchTime.now().uptimeNanoseconds >= quitDeadline {
                failureCode = "normalQuitUnconfirmed"; replyPrepare(false) // Retain late exact-handle observation.
            }
        }
        if originalGone || !terminateAttempted {
            if !target.candidates().isEmpty, !openOutstanding, !settled, !foreignReopened {
                foreignReopened = true; restoreOwed = false; replyPrepare(false); onReopened?(); onChange?()
            }
        }
    }
    func cancel() { cancelled = true; if !terminateAttempted { replyPrepare(false) } }
    func observeBeforeDispatch() -> Bool {
        guard !cancelled, !sealed, let target = installation, !quitOutstanding, failureCode == nil else { return false }
        do { try target.recheck(); guard target.candidates().isEmpty else { foreignReopened = true; restoreOwed = false; onReopened?(); return false }; return true }
        catch { failureCode = "originalIdentityUnconfirmed"; return false }
    }
    func finishUnconfirmedCleanup() {
        guard !settled, !sealed else { return }
        cancelled = true; failureCode = "cleanupUnconfirmed"
        // Cannot discharge restoration or late normal-quit/open observations from missing backend proof.
        if !restoreOwed && !pending { settled = true; timer?.invalidate(); onChange?() }
    }
    func finishAfterProtectedCleanup() {
        dispatchPrecondition(condition: .onQueue(.main)); safeCleanup = true; cancelled = true
        guard !sealed, !settled, !pending else { return }
        guard restoreOwed, !foreignReopened else { settle(); return }
        guard !restoreAttempted, let target = installation else { return }
        do {
            try target.recheck()
            if !target.candidates().isEmpty { foreignReopened = true; restoreOwed = false; settle(); return }
            guard !sealed else { return }
            restoreAttempted = true; openOutstanding = true
            let config = NSWorkspace.OpenConfiguration(); config.createsNewApplicationInstance = false; config.allowsRunningApplicationSubstitution = false
            openTimer = Self.timer(10, repeats: false) { [weak self] _ in
                guard let self, self.openOutstanding else { return }; self.failureCode = "restoreUnconfirmed"; self.onChange?()
                // Timeout does not retract LaunchServices. Retain the owner until its callback arrives.
            }
            openOriginal(target: target, configuration: config) { [self] app, error in
                DispatchQueue.main.async {
                    self.openOutstanding = false; self.openTimer?.invalidate(); self.openTimer = nil
                    if !self.sealed, error == nil, let app, (try? target.validate(app)) != nil, target.candidates().count == 1, self.failureCode != "restoreUnconfirmed" {
                        self.restoreOwed = false
                    } else { self.failureCode = "restoreUnconfirmed" }
                    self.settle()
                }
            }
        } catch { failureCode = "restoreIdentityUnconfirmed"; settle() }
    }
    private func openOriginal(target: Installation, configuration: NSWorkspace.OpenConfiguration,
                              completion: @escaping (NSRunningApplication?, Error?) -> Void) {
        #if MAC_ORIGINAL_HANDOVER_FIXTURE
        precondition(target.bundle != "/Applications/WeChat.app" && target.identifier != "com.tencent.xinWeChat")
        if fixtureRestoreDelivery == .nilResult { DispatchQueue.main.async { completion(nil, nil) }; return }
        if fixtureRestoreDelivery == .error { DispatchQueue.main.async { completion(nil, Failure.identity) }; return }
        if fixtureRestoreDelivery == .late {
            NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: target.bundle), configuration: configuration) { app, error in
                DispatchQueue.main.asyncAfter(deadline: .now() + 11) { completion(app, error) }
            }
            return
        }
        #endif
        NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: target.bundle), configuration: configuration, completionHandler: completion)
    }
    private func settle() { guard !pending else { return }; settled = true; timer?.invalidate(); timer = nil; onChange?() }
    func sealForApplicationExit() { precondition(!pending); sealed = true; cancelled = true; timer?.invalidate(); openTimer?.invalidate() }
}
