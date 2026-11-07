import AppKit
import CoreFoundation

private struct SavedArticlePayload {
    let requestID: String, title: String, content: String, author: String?, publishedAt: String?, bodyPath: String?
    let found: Bool, available: Bool, truncated: Bool, canOpen: Bool
    static func boolean(_ value: Any?) -> Bool? {
        guard let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }
    static func parse(_ value: [String: Any]) -> SavedArticlePayload? {
        guard let request = value["requestId"] as? String, request.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil,
              let title = value["title"] as? String, title.utf16.count <= 16000,
              let found = boolean(value["found"]), let available = boolean(value["bodyAvailable"]),
              let truncated = boolean(value["contentTruncated"]), let canOpen = boolean(value["canOpenFile"]),
              !available || found, !canOpen || available else { return nil }
        let content = value["content"] as? String ?? ""
        guard content.utf16.count <= 16000 else { return nil }
        let path = value["bodyPath"] as? String
        if canOpen { guard let path = path, validPathShape(path) else { return nil } }
        return SavedArticlePayload(requestID: request, title: title, content: content, author: value["author"] as? String,
            publishedAt: value["publishedAt"] as? String, bodyPath: path, found: found, available: available, truncated: truncated, canOpen: canOpen)
    }
    static func validPathShape(_ path: String) -> Bool {
        (path as NSString).isAbsolutePath && path.utf8.count <= 16384 && (path as NSString).pathExtension.lowercased() == "md"
            && !path.contains("\0") && !path.contains("//") && !path.hasSuffix("/")
            && !path.split(separator: "/").contains(where: { $0 == "." || $0 == ".." })
    }
    func callback(_ operation: String) -> [String: Any]? {
        guard operation == "close" || operation == "open" && canOpen || operation == "collect" && !available else { return nil }
        return ["action": "savedArticleAction", "requestId": requestID, "operation": operation]
    }
    func mayOpen(_ path: String) -> Bool {
        guard canOpen, path == bodyPath, Self.validPathShape(path) else { return false }
        var current = path
        while true {
            guard let attributes = try? FileManager.default.attributesOfItem(atPath: current) else { return false }
            let type = (attributes[.type] as? FileAttributeType)?.rawValue ?? attributes[.type] as? String
            guard type != nil, type != FileAttributeType.typeSymbolicLink.rawValue else { return false }
            if current == path {
                guard type == FileAttributeType.typeRegular.rawValue, let links = attributes[.referenceCount] as? NSNumber, links.intValue == 1 else { return false }
            }
            let parent = (current as NSString).deletingLastPathComponent
            if parent == current || parent.isEmpty { break }
            current = parent
        }
        return true
    }
}

// Native translation of SavedArticleWindow. The original plain text and actions
// are retained; article text is never HTML, a web view, a script or a URL action.
final class MacSavedArticleView: NSObject, NSWindowDelegate {
    private final class ActionButton: NSButton { var requestID = ""; var operation = "" }
    private final class DocumentView: NSView { override var isFlipped: Bool { true } }
    private struct Entry { let window: NSWindow; let state: SavedArticlePayload; let send: ([String: Any]) -> Void; let openButton: NSButton? }
    private var entries: [String: Entry] = [:]
    private var closed: [String] = []
    func show(state value: [String: Any], owner: NSWindow?, send: @escaping ([String: Any]) -> Void) {
        guard Thread.isMainThread, let state = SavedArticlePayload.parse(value), !closed.contains(state.requestID) else { return }
        if let existing = entries[state.requestID] { existing.window.makeKeyAndOrderFront(nil); return }
        guard entries.count < 16 else { return }
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 700), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        panel.title = state.title; panel.minSize = NSSize(width: 500, height: 350); panel.isReleasedWhenClosed = false; panel.delegate = self
        if let owner = owner { panel.setFrameOrigin(NSPoint(x: owner.frame.midX - 450, y: owner.frame.midY - 350)) } else { panel.center() }
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = false; scroll.autohidesScrollers = true
        let document = DocumentView(), stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 0
        document.translatesAutoresizingMaskIntoConstraints = false; stack.translatesAutoresizingMaskIntoConstraints = false
        document.addSubview(stack); scroll.documentView = document; panel.contentView = scroll
        func text(_ value: String, size: CGFloat = 12, weight: NSFont.Weight = .regular) -> NSTextField {
            let label = NSTextField(wrappingLabelWithString: value); label.font = .systemFont(ofSize: size, weight: weight)
            label.isSelectable = true; label.isEditable = false; label.maximumNumberOfLines = 0; label.lineBreakMode = .byWordWrapping
            stack.addArrangedSubview(label); label.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
            return label
        }
        func spacer(_ height: CGFloat) { let view = NSView(); view.heightAnchor.constraint(equalToConstant: height).isActive = true; stack.addArrangedSubview(view) }
        _ = text(state.title, size: 22, weight: .semibold); spacer(8)
        let summary = state.available ? [state.author, state.publishedAt].compactMap { $0 }.filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }.joined(separator: " · ")
            : (state.found ? "已找到这篇文章，但正文尚未保存或本地文件缺失。请在公众号页采集正文。" : "未找到身份一致的已保存文章。请在公众号页解析此链接并采集正文，不会按标题猜测。")
        _ = text(summary); spacer(12)
        if state.available {
            _ = text(state.content)
            if state.truncated { _ = text("这里显示前 16,000 字，完整内容可打开本地 Markdown 文件查看。") }
        }
        var openButton: NSButton?
        if state.canOpen || !state.available {
            spacer(12)
            let button = ActionButton(title: state.canOpen ? "打开本地正文文件" : "前往公众号页准备采集", target: self, action: #selector(performAction(_:)))
            button.requestID = state.requestID; button.operation = state.canOpen ? "open" : "collect"; button.bezelStyle = .rounded
            stack.addArrangedSubview(button); if state.canOpen { openButton = button }
        }
        let width = stack.widthAnchor.constraint(equalTo: document.widthAnchor, constant: -56); width.priority = .defaultHigh
        NSLayoutConstraint.activate([
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            stack.topAnchor.constraint(equalTo: document.topAnchor, constant: 24), stack.bottomAnchor.constraint(equalTo: document.bottomAnchor, constant: -24),
            stack.centerXAnchor.constraint(equalTo: document.centerXAnchor), stack.leadingAnchor.constraint(greaterThanOrEqualTo: document.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: document.trailingAnchor, constant: -28), stack.widthAnchor.constraint(lessThanOrEqualToConstant: 820), width
        ])
        entries[state.requestID] = Entry(window: panel, state: state, send: send, openButton: openButton)
        panel.makeKeyAndOrderFront(nil)
    }
    @objc private func performAction(_ button: ActionButton) {
        guard let entry = entries[button.requestID], let command = entry.state.callback(button.operation) else { return }
        entry.send(command)
    }
    func openFile(requestID: String, path: String) {
        guard Thread.isMainThread, let entry = entries[requestID] else { return }
        guard entry.state.mayOpen(path), NSWorkspace.shared.open(URL(fileURLWithPath: path)) else { entry.openButton?.title = "无法打开文件，请检查关联程序"; return }
    }
    private func rememberClosed(_ requestID: String) { closed.append(requestID); if closed.count > 64 { closed.removeFirst(closed.count - 64) } }
    func dismiss(requestID: String) {
        guard let entry = entries.removeValue(forKey: requestID) else { return }
        rememberClosed(requestID); entry.window.close()
    }
    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow, let pair = entries.first(where: { $0.value.window === window }) else { return }
        entries.removeValue(forKey: pair.key); rememberClosed(pair.key)
        if let command = pair.value.state.callback("close") { pair.value.send(command) }
    }
}

#if SAVED_ARTICLE_SYNTHETIC
@main private enum SavedArticleSynthetic {
    static func main() throws {
        func check(_ value: Bool, _ message: String) { if !value { print("FAIL: " + message); exit(1) } }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("saved-article-native-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        // Match Host's SourcePathProtection spelling for Apple's /var alias.
        // Foundation URL resolution may shorten /private/var back to /var.
        let rawRoot = root.path
        let canonicalRoot = rawRoot.hasPrefix("/var/") ? "/private" + rawRoot : rawRoot
        let file = canonicalRoot + "/fixture.md", other = canonicalRoot + "/other.md"
        try "<script>literal text</script>".write(toFile: file, atomically: true, encoding: .utf8)
        try "other fixture".write(toFile: other, atomically: true, encoding: .utf8)
        let value: [String: Any] = ["requestId": String(repeating: "a", count: 32), "title": "Fixture article", "found": true, "bodyAvailable": true,
            "contentTruncated": false, "canOpenFile": true, "content": "<script>literal text</script>", "bodyPath": file]
        guard let state = SavedArticlePayload.parse(value) else { print("FAIL: valid canonical Markdown state rejected"); exit(1) }
        check(state.content == "<script>literal text</script>", "plain text was transformed or interpreted")
        check(state.callback("open")?.keys.sorted() == ["action", "operation", "requestId"], "callback carries a path or URL")
        check(state.callback("collect") == nil, "saved body wrongly allows collect callback")
        check(!state.mayOpen(other), "file authority allows another Markdown")
        check(state.mayOpen(file), "file authority rejects its regular fixture Markdown")
        var invalid = value; invalid["requestId"] = "forged"; check(SavedArticlePayload.parse(invalid) == nil, "invalid window capability accepted")
        invalid = value; invalid["content"] = String(repeating: "x", count: 16001); check(SavedArticlePayload.parse(invalid) == nil, "unbounded body accepted")
        invalid = value; invalid["bodyAvailable"] = 1; check(SavedArticlePayload.parse(invalid) == nil, "numeric availability accepted")
        try FileManager.default.removeItem(atPath: file); try FileManager.default.createSymbolicLink(atPath: file, withDestinationPath: other)
        check(!state.mayOpen(file), "replacement symlink accepted")
        try FileManager.default.removeItem(atPath: file); try FileManager.default.linkItem(atPath: other, toPath: file)
        check(!state.mayOpen(file), "hardlinked Markdown accepted")
        print("PASS: bound Markdown callback, literal/limited plain text, strict capability and link recheck; no AppKit window/workspace/UI opened")
    }
}
#endif
