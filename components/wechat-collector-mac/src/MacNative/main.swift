import AppKit
import WebKit
import AVKit

final class CollectorDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate, NSMenuItemValidation {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var item: NSStatusItem!
    var secret = ""
    var launchInstance = ""
    var backendIdentity: BackendIdentity?
    var startupDirectory: URL?
    var connectionCancelItems: [NSMenuItem] = []
    var terminationPending = false
    lazy var connectionSession = MacConnectionSession(send: { [weak self] command, completion in
        self?.sendConnection(command, completion: completion)
    })
    var mediaWindows: [NSWindow] = []
    var players: [AVPlayer] = []
    let forwardedView = MacForwardView()
    let savedArticleView = MacSavedArticleView()
    let fileLocationView = MacFileLocationView()
    let screenReaderClient = MacScreenReaderClient()
    var screenReaderWindow: NSWindow?
    var screenReaderStatus: NSTextField?
    var screenReaderPermissionButton: NSButton?
    var screenReaderChooseButton: NSButton?
    var screenReaderChoosing = false
    var screenReaderMenuStatuses: [NSMenuItem] = []
    let windowInspector = MacWindowInspector()
    var imageWindow: NSWindow?
    var imageWeb: WKWebView?
    var activeMediaWindow: NSWindow?
    var mediaPlayback: MacLocalMediaPlayback?
    var mediaTimer: Timer?
    var mediaStatus: NSTextField?
    lazy var playbackActivitySender = MacPlaybackActivitySender(send: { [weak self] active, completion in
        guard let self = self else { completion(false); return }
        self.sendPlaybackActivity(active, completion: completion)
    }, onFailure: { [weak self] in self?.notice("操作回传失败，请重试或重新打开应用。") })

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let application = NSMenuItem(); let menu = NSMenu()
        menu.addItem(withTitle: "显示微信记录", action: #selector(showWindow), keyEquivalent: "0")
        menu.addItem(withTitle: "微信窗口读取（本机）…", action: #selector(showScreenReader), keyEquivalent: "")
        menu.addItem(withTitle: "直接读取微信窗口", action: #selector(captureScreenReader), keyEquivalent: "")
        menu.addItem(withTitle: "诊断微信窗口…", action: #selector(showWindowInspector), keyEquivalent: "")
        menu.addItem(withTitle: "选择微信窗口（系统）…", action: #selector(chooseWechatWindow), keyEquivalent: "")
        let readStatus = NSMenuItem(title: "屏幕读取：尚未检测", action: nil, keyEquivalent: ""); readStatus.isEnabled = false; readStatus.identifier = NSUserInterfaceItemIdentifier("screenReadStatus"); menu.addItem(readStatus); screenReaderMenuStatuses = [readStatus]
        let connectionCancel = NSMenuItem(title: "取消当前本机连接", action: #selector(cancelConnection), keyEquivalent: "")
        connectionCancel.isEnabled = false; connectionCancel.identifier = NSUserInterfaceItemIdentifier("connectionCancel")
        menu.addItem(connectionCancel); connectionCancelItems = [connectionCancel]
        menu.addItem(NSMenuItem.separator())
        menu.addItem(withTitle: "退出微信记录", action: #selector(quit), keyEquivalent: "q")
        application.submenu = menu
        let mainMenu = NSMenu(); mainMenu.addItem(application)
        let edit = NSMenuItem(title: "编辑", action: nil, keyEquivalent: ""); edit.submenu = NSMenu(title: "编辑")
        edit.submenu?.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.submenu?.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.submenu?.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        mainMenu.addItem(edit); NSApp.mainMenu = mainMenu
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "bubble.left.and.bubble.right", accessibilityDescription: "微信记录")
        item.menu = menu.copy() as? NSMenu
        if let status = item.menu?.items.first(where: { $0.identifier?.rawValue == "screenReadStatus" }) { screenReaderMenuStatuses.append(status) }
        if let cancel = item.menu?.items.first(where: { $0.identifier?.rawValue == "connectionCancel" }) { connectionCancelItems.append(cancel) }
        connectionSession.onActiveChange = { [weak self] active in self?.connectionCancelItems.forEach { $0.isEnabled = active } }
        connectionSession.onStatus = { [weak self] status in self?.window?.subtitle = status }
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(self, name: "collector")
        web = WKWebView(frame: .zero, configuration: config); web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "微信记录"; window.minSize = NSSize(width: 820, height: 580)
        window.isReleasedWhenClosed = false; window.delegate = self; window.contentView = web; window.center()
        if let icon = Bundle.main.resourceURL?.appendingPathComponent("Project/reference-web/assets/applogo.png") { NSApp.applicationIconImage = NSImage(contentsOf: icon) }
        showWindow(); if startBackend() { connect(attempt: 0) }
    }
    @discardableResult func startBackend() -> Bool {
        guard let resources = Bundle.main.resourceURL else { return false }
        let executable = resources.appendingPathComponent("backend/WechatCollector.MacHost")
        let process = Process(); process.executableURL = executable
        // Each launch owns its secret, readiness directory and backend child. Never
        // discover a backend through shared Application Support files or a fixed port.
        launchInstance = UUID().uuidString
        secret = UUID().uuidString.replacingOccurrences(of: "-", with: "") + UUID().uuidString.replacingOccurrences(of: "-", with: "")
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("wechat-collector-" + launchInstance, isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            startupDirectory = directory
            var environment = ProcessInfo.processInfo.environment
            environment["WECHAT_COLLECTOR_PROJECT"] = resources.appendingPathComponent("Project").path
            environment["WECHAT_COLLECTOR_BRIDGE_SECRET"] = secret
            environment["WECHAT_COLLECTOR_INSTANCE"] = launchInstance
            environment["WECHAT_COLLECTOR_READY_FILE"] = directory.appendingPathComponent("ready.json").path
            environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
            process.environment = environment
            process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
            process.terminationHandler = { [weak self] _ in DispatchQueue.main.async { self?.connectionSession.cancel() } }
            try process.run(); backend = process
            return true
        } catch { cleanupReadiness(); notice("本地服务未能启动，请重新打开应用。"); return false }
    }
    func cleanupReadiness() {
        if let directory = startupDirectory { try? FileManager.default.removeItem(at: directory) }
        startupDirectory = nil
    }
    func connect(attempt: Int) {
        guard let process = backend, process.isRunning else {
            cleanupReadiness(); notice("本次本地服务已停止，请重新打开应用。"); return
        }
        guard attempt < 120 else {
            process.terminate(); cleanupReadiness(); notice("本地记录连接未完成，请查看诊断后重试。"); return
        }
        func retry() { DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.connect(attempt: attempt + 1) } }
        guard let directory = startupDirectory,
              let data = try? Data(contentsOf: directory.appendingPathComponent("ready.json")),
              let identity = BackendIdentity.parse(data, expectedInstance: launchInstance, expectedPID: process.processIdentifier) else { retry(); return }
        var request = URLRequest(url: identity.baseURL.appendingPathComponent("session")); request.httpMethod = "POST"; request.timeoutInterval = 2
        request.setValue("Bearer " + secret, forHTTPHeaderField: "Authorization")
        request.setValue(launchInstance, forHTTPHeaderField: "X-Collector-Instance")
        // Refuse redirects: neither the launch secret nor its session may leave the
        // exact endpoint advertised by our child.
        let session = URLSession(configuration: .ephemeral, delegate: NoBackendRedirects(), delegateQueue: nil)
        session.dataTask(with: request) { data, response, _ in
            session.finishTasksAndInvalidate()
            DispatchQueue.main.async {
                guard process.isRunning, let data = data,
                      (response as? HTTPURLResponse)?.statusCode == 200,
                      response?.url == request.url, identity.matchesSession(data) else { retry(); return }
                self.backendIdentity = identity; self.cleanupReadiness()
                var load = URLRequest(url: identity.baseURL)
                load.setValue("Bearer " + self.secret, forHTTPHeaderField: "Authorization"); self.web.load(load)
            }
        }.resume()
    }
    @objc func showWindow() { window?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { if !flag { showWindow() }; return true }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        menuItem.action == #selector(cancelConnection) ? connectionSession.active : true
    }
    @objc func cancelConnection() { connectionSession.cancel() }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminationPending { return .terminateLater }
        guard connectionSession.active else { connectionSession.sealForApplicationExit(); return .terminateNow }
        terminationPending = true
        connectionSession.requestTermination { outcome in
            // Native cleanup uncertainty is separate from C8's authenticated root-capture terminal.
            let cleaned = outcome == .cleaned
            if !cleaned {
                self.window?.subtitle = "连接尚未确认结束，本次退出已取消；正在保留清理状态。"
            }
            DispatchQueue.main.async {
                NSApp.reply(toApplicationShouldTerminate: cleaned)
                if !cleaned { self.terminationPending = false }
            }
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) { screenReaderClient.stop(); mediaPlayback?.close(); mediaTimer?.invalidate(); backend?.terminate(); cleanupReadiness() }
    func windowWillClose(_ notification: Notification) {
        if let closing = notification.object as? NSWindow, closing === window { connectionSession.cancel() }
        if let closing = notification.object as? NSWindow, closing === window || closing === screenReaderWindow { windowInspector.cancelSelectedPreview() }
        if let closing = notification.object as? NSWindow, closing === activeMediaWindow {
            mediaPlayback?.close(); mediaPlayback = nil; mediaTimer?.invalidate(); mediaTimer = nil; activeMediaWindow = nil
            playbackActivitySender.update(false)
        }
    }
    @objc func playMedia() { mediaPlayback?.play() }
    @objc func pauseMedia() { mediaPlayback?.pause() }
    func notice(_ text: String) { let alert = NSAlert(); alert.messageText = "微信记录"; alert.informativeText = text; alert.addButton(withTitle: "好"); alert.runModal() }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let identity = backendIdentity, message.frameInfo.securityOrigin.protocol == "http",
              message.frameInfo.securityOrigin.host == "127.0.0.1", message.frameInfo.securityOrigin.port == identity.port,
              let value = message.body as? [String: Any], value["type"] as? String == "macNative", let command = value["command"] as? String else { return }
        switch command {
        case "connectAccount":
            if Set(value.keys) == Set(["type", "command", "requestId"]), let request = value["requestId"] as? String { connectionSession.begin(requestId: request) }
        case "forwarded":
            if let state = value["state"] as? [String: Any] { forwardedView.show(state: state) { self.reply(page: "chat", command: $0) } }
        case "closeForwarded": forwardedView.dismiss()
        case "fileLocation":
            if let request = value["requestId"] as? String, let state = value["state"] as? [String: Any] { fileLocationView.show(request: request, state: state, owner: window) { self.reply(page: "chat", command: $0) } }
        case "fileLocationReveal":
            if let request = value["requestId"] as? String, let token = value["candidateToken"] as? String, let index = value["candidateIndex"] as? Int, let revealToken = value["revealToken"] as? String, let path = value["path"] as? String { fileLocationView.reveal(request: request, token: token, index: index, revealToken: revealToken, path: path) }
        case "closeFileLocation": fileLocationView.dismiss(request: value["requestId"] as? String ?? "")
        case "savedArticle":
            if let state = value["state"] as? [String: Any] { savedArticleView.show(state: state, owner: window) { self.reply(page: "chat", command: $0) } }
        case "savedArticleOpen": savedArticleView.openFile(requestID: value["requestId"] as? String ?? "", path: value["path"] as? String ?? "")
        case "closeSavedArticle": savedArticleView.dismiss(requestID: value["requestId"] as? String ?? "")
        case "clipboard":
            if let text = value["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string) }
        case "notice": notice(value["text"] as? String ?? "操作未完成。")
        case "reveal": if let path = value["path"] as? String { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)]) }
        case "openFolder": if let path = value["path"] as? String { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
        case "openLicenses": if let url = Bundle.main.resourceURL?.appendingPathComponent("Project/reference-licenses") { NSWorkspace.shared.open(url) }
        case "openUrl": if let link = value["url"] as? String, let url = URL(string: link), ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        case "theme":
            let mode = value["mode"] as? String ?? "system"
            NSApp.appearance = mode == "system" ? nil : NSAppearance(named: mode == "dark" ? .darkAqua : .aqua)
        case "selectFolder":
            let setupFolder = value["page"] as? String == "chat" && value["callbackAction"] as? String == "selectedSetupFolder"
            if setupFolder {
                guard let request = value["requestId"] as? String, request.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil,
                      let field = value["field"] as? String, ["setupSource", "setupDirectory"].contains(field) else { return }
            }
            let panel = NSOpenPanel(); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.allowsMultipleSelection = false
            panel.beginSheetModal(for: window) { response in
                var command: [String: Any] = ["action": setupFolder ? "selectedSetupFolder" : "selectedFolder", "field": value["field"] as? String ?? "", "path": response == .OK ? panel.url?.path ?? "" : ""]
                if setupFolder { command["requestId"] = value["requestId"] as? String ?? "" }
                self.reply(page: setupFolder ? "chat" : "settings", command: command)
            }
        case "saveDocument":
            let panel = NSSavePanel(); panel.title = value["title"] as? String ?? "导出文件"; panel.nameFieldStringValue = value["filename"] as? String ?? "导出文件.txt"
            panel.beginSheetModal(for: window) { response in
                self.reply(page: value["page"] as? String ?? "chat", command: ["action": "saveDocument", "requestId": value["requestId"] as? String ?? "", "path": response == .OK ? panel.url?.path ?? "" : ""])
            }
        case "media":
            if let path = value["path"] as? String {
                activeMediaWindow?.close()
                let voice = value["voice"] as? Bool ?? false
                let playback = MacLocalMediaPlayback(url: URL(fileURLWithPath: path)); mediaPlayback = playback
                let player = playback.player
                let view = AVPlayerView(); view.player = player; view.controlsStyle = .none
                let preview = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 800, height: voice ? 180 : 560), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
                let play = NSButton(title: "播放", target: self, action: #selector(playMedia)); let pause = NSButton(title: "暂停", target: self, action: #selector(pauseMedia))
                let status = NSTextField(labelWithString: "就绪"); mediaStatus = status
                let controls = NSStackView(views: [play,pause,status]); controls.orientation = .horizontal; controls.spacing = 8
                let content = NSView(); content.addSubview(controls); controls.translatesAutoresizingMaskIntoConstraints = false
                NSLayoutConstraint.activate([controls.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 16), controls.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -16)])
                if !voice { content.addSubview(view); view.translatesAutoresizingMaskIntoConstraints = false; NSLayoutConstraint.activate([view.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 16), view.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -16), view.topAnchor.constraint(equalTo: content.topAnchor, constant: 16), view.bottomAnchor.constraint(equalTo: controls.topAnchor, constant: -8)]) }
                preview.title = voice ? "语音" : "视频"; preview.contentView = content; preview.delegate = self; preview.isReleasedWhenClosed = false; preview.center(); preview.makeKeyAndOrderFront(nil); activeMediaWindow = preview
                playback.onChange = { [weak self] state in
                    self?.mediaStatus?.stringValue = state.text
                    self?.playbackActivitySender.update(state.active)
                }
                mediaTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
                    guard let self = self, let playback = self.mediaPlayback else { return }
                    let state = playback.display
                    self.mediaStatus?.stringValue = state.text
                    self.playbackActivitySender.update(state.active)
                }
                playMedia()
            }
        case "image":
            if let path = value["path"] as? String, let image = NSImage(contentsOfFile: path) {
                let view = NSImageView(); view.image = image; view.imageScaling = .scaleProportionallyUpOrDown
                let preview = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 760), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
                preview.title = "图片"; preview.contentView = view; preview.isReleasedWhenClosed = false; preview.center(); preview.makeKeyAndOrderFront(nil); mediaWindows.append(preview)
            }
        case "imagePage":
            let sticker = value["kind"] as? String == "sticker"
            if imageWindow == nil {
                let configuration = WKWebViewConfiguration(); configuration.websiteDataStore = web.configuration.websiteDataStore; configuration.userContentController.add(self, name: "collector")
                imageWeb = WKWebView(frame: .zero, configuration: configuration); imageWeb?.navigationDelegate = self
                let preview = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 760), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
                preview.title = "图片"; preview.minSize = NSSize(width: 600, height: 400); preview.contentView = imageWeb; preview.isReleasedWhenClosed = false; preview.center(); imageWindow = preview
            }
            imageWindow?.title = sticker ? "表情" : "图片"
            imageWindow?.setContentSize(NSSize(width: sticker ? 680 : 1000, height: sticker ? 620 : 760))
            imageWeb?.load(URLRequest(url: identity.baseURL.appendingPathComponent("Common/image.html"))); imageWindow?.makeKeyAndOrderFront(nil)
        case "closeImage": imageWindow?.orderOut(nil)
        case "copyImage":
            if let path = value["path"] as? String, let image = NSImage(contentsOfFile: path) { NSPasteboard.general.clearContents(); NSPasteboard.general.writeObjects([image]) }
        case "copyFile":
            if let path = value["path"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.writeObjects([URL(fileURLWithPath: path) as NSURL]) }
        case "saveImage":
            let panel = NSSavePanel(); panel.nameFieldStringValue = value["filename"] as? String ?? "微信图片.png"
            panel.beginSheetModal(for: imageWindow ?? window) { response in
                self.reply(page: "image", command: ["action": "saveImage", "version": value["version"] as? Int ?? -1, "path": response == .OK ? panel.url?.path ?? "" : ""])
            }
        case "importVoiceModel":
            let panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
            panel.beginSheetModal(for: window) { response in
                self.reply(page: "chat", command: ["action": "importVoiceModel", "path": response == .OK ? panel.url?.path ?? "" : ""])
            }
        case "saveExport":
            let panel = NSSavePanel(); panel.nameFieldStringValue = value["filename"] as? String ?? "微信聊天记录.jsonl"
            panel.beginSheetModal(for: window) { response in
                self.reply(page: value["page"] as? String ?? "export", command: ["action": "saveExport", "requestId": value["requestId"] as? String ?? "", "path": response == .OK ? panel.url?.path ?? "" : ""])
            }
        default: notice("此功能的 Mac 适配尚未完成，未执行操作。")
        }
    }
    func sendConnection(_ command: [String: Any], completion: @escaping ([String: Any]?) -> Void) {
        guard let identity = backendIdentity, backend?.isRunning == true,
              let data = try? JSONSerialization.data(withJSONObject: command), data.count <= 4096 else { completion(nil); return }
        var request = URLRequest(url: identity.baseURL.appendingPathComponent("native/connection"))
        request.httpMethod = "POST"; request.httpBody = data; request.timeoutInterval = 2
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + secret, forHTTPHeaderField: "Authorization")
        request.setValue(launchInstance, forHTTPHeaderField: "X-Collector-Instance")
        let session = URLSession(configuration: .ephemeral, delegate: NoBackendRedirects(), delegateQueue: nil)
        session.dataTask(with: request) { data, response, _ in
            session.finishTasksAndInvalidate()
            let value: [String: Any]?
            if (response as? HTTPURLResponse)?.statusCode == 200, response?.url == request.url,
               let data, data.count <= 4096, let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { value = object }
            else { value = nil }
            DispatchQueue.main.async { completion(value) }
        }.resume()
    }
    func sendPlaybackActivity(_ active: Bool, completion: @escaping (Bool) -> Void) {
        guard let identity = backendIdentity,
              let data = try? JSONSerialization.data(withJSONObject: ["action": "playback", "active": active]) else { completion(false); return }
        var request = URLRequest(url: identity.baseURL.appendingPathComponent("bridge/chat"))
        request.httpMethod = "POST"; request.httpBody = data; request.timeoutInterval = 5
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer " + secret, forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { _, response, error in
            DispatchQueue.main.async { completion(error == nil && (response as? HTTPURLResponse)?.statusCode == 200) }
        }.resume()
    }
    func reply(page: String, command: [String: Any]) {
        guard ["export", "chat", "settings", "official", "image"].contains(page),
              let identity = backendIdentity, let data = try? JSONSerialization.data(withJSONObject: command) else { return }
        var request = URLRequest(url: identity.baseURL.appendingPathComponent("bridge/" + page))
        request.httpMethod = "POST"; request.httpBody = data; request.setValue("application/json", forHTTPHeaderField: "Content-Type"); request.setValue("Bearer " + secret, forHTTPHeaderField: "Authorization")
        // Dialog completions enqueue events server-side. The page's sole /events
        // consumer delivers them in order; a POST must never drain or inject events.
        URLSession.shared.dataTask(with: request) { _, response, error in
            if error != nil || (response as? HTTPURLResponse)?.statusCode != 200 {
                DispatchQueue.main.async { self.notice("操作回传失败，请重试或重新打开应用。") }
            }
        }.resume()
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if let identity = backendIdentity, url.scheme == "http", url.host == "127.0.0.1", url.port == identity.port { decisionHandler(.allow) }
        else { decisionHandler(.cancel); if ["https", "http"].contains(url.scheme ?? ""), navigationAction.navigationType == .linkActivated { NSWorkspace.shared.open(url) } }
    }
}
final class NoBackendRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
let delegate = CollectorDelegate()
NSApplication.shared.delegate = delegate
NSApplication.shared.run()
