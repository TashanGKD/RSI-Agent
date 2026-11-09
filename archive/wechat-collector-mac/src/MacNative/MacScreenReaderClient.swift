import Foundation

final class ScreenReaderTermination {
    private let condition = NSCondition()
    private var completed: (Int, MacScreenReaderClient.HelperTerminationReason)?
    private static func reason(_ value: Process.TerminationReason) -> MacScreenReaderClient.HelperTerminationReason {
        switch value { case .exit: return .exit; case .uncaughtSignal: return .signal; @unknown default: return .unknown }
    }
    func record(_ child: Process) {
        condition.lock(); completed = (Int(child.terminationStatus), Self.reason(child.terminationReason)); condition.broadcast(); condition.unlock()
    }
    func errorAfterEOF(child: Process?) -> MacScreenReaderClient.ReaderError {
        // EOF can precede Foundation's terminationHandler delivery. Give only
        // that metadata 250 ms to settle; never waitForExit on a live helper.
        let limit = Date().addingTimeInterval(0.25)
        condition.lock()
        while completed == nil && Date() < limit { _ = condition.wait(until: limit) }
        let result = completed; condition.unlock()
        if let result = result { return .helperExited(exitStatus: result.0, terminationReason: result.1) }
        if let child = child, !child.isRunning { return .helperExited(exitStatus: Int(child.terminationStatus), terminationReason: Self.reason(child.terminationReason)) }
        return .aliveEOF
    }
}

// Pure request construction, shared by the pipe and synthetic protocol tests.
enum ScreenReaderRequestProtocol {
    static func supports(_ action: String) -> Bool { ["probe", "capture", "capturePreview", "listWindows", "requestScreenPermission", "chooseWindow"].contains(action) }
    static func payload(action: String, windowID: Int? = nil, expectedToken: String? = nil, availableToken: String? = nil, auth: String, requestID: String) throws -> [String: Any] {
        guard supports(action) else { throw MacScreenReaderClient.ReaderError.protocolFailure }
        var value: [String: Any] = ["schemaVersion": 1, "requestId": requestID, "action": action, "auth": auth]
        if action == "requestScreenPermission" || action == "chooseWindow" { value["authorizationIntent"] = "user_clicked_native_menu" }
        if let windowID = windowID {
            guard action == "probe", windowID > 0, windowID <= Int(UInt32.max) else { throw MacScreenReaderClient.ReaderError.protocolFailure }
            value["windowId"] = windowID
        }
        if action == "capture" || action == "capturePreview" {
            guard let token = availableToken, validToken(token), expectedToken == nil || expectedToken == token else { throw MacScreenReaderClient.ReaderError.probeRequired }
            value["targetToken"] = token
        } else if expectedToken != nil { throw MacScreenReaderClient.ReaderError.protocolFailure }
        return value
    }
    static func validToken(_ value: String) -> Bool { value.range(of: #"\A[A-Za-z0-9-]{1,128}\z"#, options: .regularExpression) != nil }
    static func deadline(_ action: String) -> TimeInterval { action == "chooseWindow" ? 125 : (action == "requestScreenPermission" ? 120 : 30) }
    static func nextToken(action: String, response: [String: Any]) -> String? {
        guard ["probe", "chooseWindow"].contains(action), response["status"] as? String == "ready", let token = response["targetToken"] as? String, validToken(token) else { return nil }
        return token
    }
}

private final class ScreenReaderDeadline {
    private let lock = NSLock()
    private var active = true
    func expire(_ child: Process) { lock.lock(); defer { lock.unlock() }; if active && child.isRunning { child.terminate() } }
    func finish() { lock.lock(); active = false; lock.unlock() }
}

// One private child and serialized pipe, with no socket, image persistence or OCR logging.
final class MacScreenReaderClient {
    private let queue = DispatchQueue(label: "local.wechat.collector.screen-reader.pipe")
    private var process: Process?
    private var termination: ScreenReaderTermination?
    private var input: FileHandle?
    private var output: FileHandle?
    private var pending = Data()
    private var auth = ""
    private var targetToken: String?
    private var instance: String?
    private var stopping = false
    private let stateLock = NSLock()

    func request(_ action: String, windowID: Int? = nil, expectedToken: String? = nil, completion: @escaping (Result<[String: Any], Error>) -> Void) {
        guard ScreenReaderRequestProtocol.supports(action) else { DispatchQueue.main.async { completion(.failure(ReaderError.protocolFailure)) }; return }
        queue.async {
            do {
                self.stateLock.lock(); let stopped = self.stopping; self.stateLock.unlock()
                guard !stopped else { throw ReaderError.stopped }
                try self.start()
                let requestId = UUID().uuidString
                if action != "capture" && action != "capturePreview" { self.targetToken = nil }
                let payload = try ScreenReaderRequestProtocol.payload(action: action, windowID: windowID, expectedToken: expectedToken, availableToken: self.targetToken, auth: self.auth, requestID: requestId)
                if action == "capture" || action == "capturePreview" {
                    self.targetToken = nil
                }
                guard let child = self.process else { throw ReaderError.stopped }
                let deadline = ScreenReaderDeadline()
                let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))
                timer.schedule(deadline: .now() + ScreenReaderRequestProtocol.deadline(action))
                timer.setEventHandler { deadline.expire(child) }; timer.resume()
                defer { deadline.finish(); timer.cancel() }
                try self.input?.write(contentsOf: JSONSerialization.data(withJSONObject: payload) + Data([10]))
                let line = try self.readLine()
                guard let result = try JSONSerialization.jsonObject(with: line) as? [String: Any], result["schemaVersion"] as? Int == 1 else { throw ReaderError.protocolFailure }
                let startupFailure = result["requestId"] == nil && result["fatal"] as? Bool == true && result["status"] as? String == "blocked" && ["untrusted_parent", "unauthorized", "unsupported_os"].contains(result["code"] as? String ?? "")
                guard result["requestId"] as? String == requestId || startupFailure, let instance = result["helperInstance"] as? String,
                      self.instance == nil || self.instance == instance else { throw ReaderError.protocolFailure }
                self.instance = instance
                self.targetToken = ScreenReaderRequestProtocol.nextToken(action: action, response: result)
                if result["fatal"] as? Bool == true || startupFailure { self.reset() }
                DispatchQueue.main.async { completion(.success(result)) }
            } catch {
                self.reset()
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }
    private func start() throws {
        if process?.isRunning == true { return }
        reset()
        guard let executable = Bundle.main.resourceURL?.appendingPathComponent("helpers/微信窗口读取.app/Contents/MacOS/WechatScreenReader"), FileManager.default.isExecutableFile(atPath: executable.path) else { throw ReaderError.missingHelper }
        let child = Process(), source = Pipe(), destination = Pipe()
        auth = (UUID().uuidString + UUID().uuidString).replacingOccurrences(of: "-", with: "").lowercased()
        child.executableURL = executable; child.arguments = ["--serve"]
        var environment: [String: String] = ["WECHAT_SCREEN_READER_AUTH": auth]
        for key in ["HOME", "TMPDIR", "LANG", "LC_CTYPE"] { if let value = ProcessInfo.processInfo.environment[key] { environment[key] = value } }
        child.environment = environment
        child.standardInput = source; child.standardOutput = destination; child.standardError = FileHandle.nullDevice
        let observed = ScreenReaderTermination(); child.terminationHandler = { observed.record($0) }
        try child.run()
        stateLock.lock(); let stopped = stopping; if !stopped { process = child }; stateLock.unlock()
        if stopped { if child.isRunning { child.terminate() }; throw ReaderError.stopped }
        input = source.fileHandleForWriting; output = destination.fileHandleForReading; termination = observed
    }
    private func readLine() throws -> Data {
        while true {
            if let newline = pending.firstIndex(of: 10) {
                let result = Data(pending[..<newline]); pending.removeSubrange(...newline)
                guard result.count <= 6 * 1_048_576 else { throw ReaderError.protocolFailure }; return result
            }
            guard pending.count <= 6 * 1_048_576, let output = output else { throw ReaderError.protocolFailure }
            let chunk = try PipeIO.readChunk(from: output)
            guard !chunk.isEmpty else { throw termination?.errorAfterEOF(child: process) ?? ReaderError.aliveEOF }
            pending.append(chunk)
        }
    }
    private func reset() {
        stateLock.lock(); let child = process; process = nil; stateLock.unlock()
        if child?.isRunning == true { child?.terminate() }
        try? input?.close(); try? output?.close()
        input = nil; output = nil; termination = nil; pending = Data(); targetToken = nil; instance = nil; auth = ""
    }
    func stop() {
        stateLock.lock(); stopping = true; let child = process; stateLock.unlock()
        if child?.isRunning == true { child?.terminate() }
        queue.async { self.reset() }
    }
    enum HelperTerminationReason: String { case exit, signal, unknown }
    enum ReaderError: Error { case stopped, missingHelper, probeRequired, protocolFailure, helperExited(exitStatus: Int, terminationReason: HelperTerminationReason), aliveEOF }
    static func lifecycleReason(_ error: Error) -> String? {
        switch error {
        case let ReaderError.helperExited(status, reason): return "助手已退出（\(reason.rawValue)，退出码 \(status)）"
        case ReaderError.aliveEOF: return "助手仍在运行，但输出连接已关闭"
        default: return nil
        }
    }
}
