import AppKit
import CoreFoundation

private struct FileLocationPayload {
    struct Row { let index: Int; let name: String; let directory: String; let path: String; let summary: String; let details: String }
    let request: String, token: String, title: String, status: String
    let busy: Bool
    let rows: [Row]
    static func capability(_ value: String) -> Bool { value.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil }
    static func boolean(_ value: Any?) -> Bool? { guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }; return n.boolValue }
    static func integer(_ value: Any?) -> Int? { guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue == Double(n.intValue) else { return nil }; return n.intValue }
    static func pathShape(_ path: String) -> Bool { (path as NSString).isAbsolutePath && path.utf8.count <= 16384 && !path.contains("\0") && !path.contains("//") && !path.split(separator: "/").contains(where: { $0 == "." || $0 == ".." }) }
    static func parse(request: String, value: [String: Any]) -> FileLocationPayload? {
        guard capability(request), let token = value["token"] as? String, capability(token),
            let title = value["title"] as? String, title.utf16.count <= 1024,
            let status = value["status"] as? String, status.utf16.count <= 16384,
            let busy = boolean(value["busy"]), let items = value["items"] as? [[String: Any]], items.count <= 20 else { return nil }
        var rows: [Row] = []
        for item in items {
            guard let index = integer(item["index"]), index == rows.count,
                let name = item["name"] as? String, name.utf16.count <= 1024,
                let path = item["path"] as? String, pathShape(path),
                let directory = item["directory"] as? String, directory == (path as NSString).deletingLastPathComponent,
                let summary = item["summary"] as? String, summary.utf16.count <= 1024,
                let details = item["details"] as? String, details.utf16.count <= 20000 else { return nil }
            rows.append(Row(index: index, name: name, directory: directory, path: path, summary: summary, details: details))
        }
        return FileLocationPayload(request: request, token: token, title: title, status: status, busy: busy, rows: rows)
    }
    func command(_ operation: String, index: Int? = nil) -> [String: Any]? {
        guard operation == "close" || !busy && (operation == "retry" || operation == "reveal" && index.map({ $0 >= 0 && $0 < rows.count }) == true) else { return nil }
        var result: [String: Any] = ["action": "fileLocationAction", "requestId": request, "operation": operation, "candidateToken": token]
        if let index = index { result["candidateIndex"] = index }; return result
    }
    func mayReveal(token: String, index: Int, path: String) -> Bool {
        guard busy, token == self.token, index >= 0, index < rows.count, path == rows[index].path, Self.pathShape(path) else { return false }
        var current = path
        while true {
            guard let attributes = try? FileManager.default.attributesOfItem(atPath: current), let kind = attributes[.type] as? FileAttributeType,
                kind != .typeSymbolicLink, current != path || kind == .typeRegular else { return false }
            let parent = (current as NSString).deletingLastPathComponent
            if parent == current || parent.isEmpty { break }; current = parent
        }; return true
    }
}

// AppKit counterpart of FileLocationWindow; candidate data is plain text.
final class MacFileLocationView: NSObject, NSWindowDelegate {
    private final class FileWindow: NSWindow { var escape: (() -> Void)?; override func cancelOperation(_ sender: Any?) { escape?() } }
    private final class Entry: NSObject, NSTableViewDataSource, NSTableViewDelegate {
        let window: FileWindow, table = NSTableView(), status = NSTextField(wrappingLabelWithString: ""), details = NSTextField(wrappingLabelWithString: "")
        let retry = NSButton(title: "重新查找", target: nil, action: nil), reveal = NSButton(title: "打开所在文件夹", target: nil, action: nil)
        let disclosure = NSButton(checkboxWithTitle: "文件详情", target: nil, action: nil)
        var state: FileLocationPayload, send: ([String: Any]) -> Void, lastReveal = ""
        init(state: FileLocationPayload, send: @escaping ([String: Any]) -> Void) {
            self.state = state; self.send = send
            window = FileWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 440), styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
            super.init()
            window.minSize = NSSize(width: 460, height: 280); window.isReleasedWhenClosed = false
            let content = NSView(), stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 12
            window.contentView = content; content.addSubview(stack); stack.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24), stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24), stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 24), stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -24)])
            status.textColor = .secondaryLabelColor; status.maximumNumberOfLines = 3; stack.addArrangedSubview(status); status.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
            let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = false; scroll.borderType = .noBorder
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("candidate")); table.addTableColumn(column); table.headerView = nil; table.rowHeight = 65
            table.dataSource = self; table.delegate = self; table.columnAutoresizingStyle = .uniformColumnAutoresizingStyle; table.allowsMultipleSelection = false
            scroll.documentView = table; stack.addArrangedSubview(scroll); scroll.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true; scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 40).isActive = true
            disclosure.target = self; disclosure.action = #selector(toggleDetails); stack.addArrangedSubview(disclosure)
            details.isSelectable = true; details.maximumNumberOfLines = 5; details.lineBreakMode = .byTruncatingMiddle; stack.addArrangedSubview(details); details.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
            let buttons = NSStackView(views: [retry, reveal]); buttons.spacing = 12; stack.addArrangedSubview(buttons); buttons.trailingAnchor.constraint(equalTo: stack.trailingAnchor).isActive = true
            retry.target = self; retry.action = #selector(retryAction); reveal.target = self; reveal.action = #selector(revealAction)
            window.escape = { [weak self] in self?.window.close() }; update(state)
        }
        func update(_ next: FileLocationPayload) {
            let selected = state.token == next.token ? table.selectedRow : -1
            state = next; window.title = next.title; status.stringValue = next.status; table.reloadData()
            if selected >= 0 && selected < next.rows.count { table.selectRowIndexes(IndexSet(integer: selected), byExtendingSelection: false) }
            else if next.rows.count == 1 { table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false) }
            else { table.deselectAll(nil) }
            table.isEnabled = !next.busy; retry.isEnabled = !next.busy; selectedChanged()
        }
        func numberOfRows(in tableView: NSTableView) -> Int { state.rows.count }
        func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
            let candidate = state.rows[row], label = NSTextField(wrappingLabelWithString: candidate.name + "\n" + candidate.directory + "\n" + candidate.summary)
            label.font = .systemFont(ofSize: 12); label.maximumNumberOfLines = 3; label.lineBreakMode = .byTruncatingMiddle; label.toolTip = candidate.path; return label
        }
        func tableViewSelectionDidChange(_ notification: Notification) { selectedChanged() }
        func selectedChanged() { let selected = table.selectedRow; let valid = selected >= 0 && selected < state.rows.count; reveal.isEnabled = valid && !state.busy; disclosure.isHidden = !valid; details.isHidden = !valid || disclosure.state != .on; details.stringValue = valid ? state.rows[selected].details : "" }
        @objc func toggleDetails() { selectedChanged() }
        @objc func retryAction() { if let command = state.command("retry") { retry.isEnabled = false; reveal.isEnabled = false; send(command) } }
        @objc func revealAction() { if let command = state.command("reveal", index: table.selectedRow) { retry.isEnabled = false; reveal.isEnabled = false; send(command) } }
    }
    private var entries: [String: Entry] = [:], closed: [String] = []
    func show(request: String, state: [String: Any], owner: NSWindow?, send: @escaping ([String: Any]) -> Void) {
        guard Thread.isMainThread, let payload = FileLocationPayload.parse(request: request, value: state), !closed.contains(request) else { return }
        if let entry = entries[request] { entry.update(payload); return }
        guard entries.count < 16 else { return }
        let entry = Entry(state: payload, send: send); entries[request] = entry; entry.window.delegate = self
        if let owner = owner { entry.window.setFrameOrigin(NSPoint(x: owner.frame.midX - 380, y: owner.frame.midY - 220)) } else { entry.window.center() }
        entry.window.makeKeyAndOrderFront(nil)
    }
    func reveal(request: String, token: String, index: Int, revealToken: String, path: String) {
        guard Thread.isMainThread, let entry = entries[request], FileLocationPayload.capability(revealToken), entry.lastReveal != revealToken else { return }
        entry.lastReveal = revealToken
        let allowed = entry.state.mayReveal(token: token, index: index, path: path)
        let succeeded = allowed && NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
        entry.send(["action": "fileLocationAction", "requestId": request, "candidateToken": token, "operation": "revealResult", "revealToken": revealToken, "succeeded": succeeded])
    }
    private func remember(_ request: String) { closed.append(request); if closed.count > 64 { closed.removeFirst(closed.count - 64) } }
    func dismiss(request: String) { guard let entry = entries.removeValue(forKey: request) else { return }; remember(request); entry.window.close() }
    func windowWillClose(_ notification: Notification) { guard let window = notification.object as? NSWindow, let pair = entries.first(where: { $0.value.window === window }) else { return }; entries.removeValue(forKey: pair.key); remember(pair.key); if let command = pair.value.state.command("close") { pair.value.send(command) } }
}

#if FILE_LOCATION_SYNTHETIC
@main private enum FileLocationSynthetic {
    static func main() throws {
        func check(_ value: Bool, _ reason: String) { if !value { fatalError(reason) } }
        let request = String(repeating: "a", count: 32), token = String(repeating: "b", count: 32)
        let root = "/private/tmp/file-location-native-" + UUID().uuidString; try FileManager.default.createDirectory(atPath: root, withIntermediateDirectories: true); defer { try? FileManager.default.removeItem(atPath: root) }
        let path = root + "/report (3).txt"; try "fixture".write(toFile: path, atomically: true, encoding: .utf8)
        let value: [String: Any] = ["token": token, "title": "report.txt", "status": "正在核对…", "busy": true, "items": [["index": 0, "name": "report (3).txt", "directory": root, "path": path, "summary": "7 B · 大小一致", "details": path]]]
        guard let state = FileLocationPayload.parse(request: request, value: value) else { fatalError("valid state rejected") }
        check(!state.mayReveal(token: "forged", index: 0, path: path), "forged token accepted"); check(!state.mayReveal(token: token, index: 1, path: path), "forged index accepted"); check(!state.mayReveal(token: token, index: 0, path: "/etc/passwd"), "arbitrary path accepted")
        check(state.mayReveal(token: token, index: 0, path: path), "exact regular candidate rejected"); check(state.command("reveal", index: 0) == nil, "busy state allows double action")
        var ready = value; ready["busy"] = false; let callback = FileLocationPayload.parse(request: request, value: ready)!.command("reveal", index: 0)!
        check(callback["path"] == nil && callback["candidateIndex"] as? Int == 0, "callback grants path authority")
        var bad = value; bad["busy"] = 1; check(FileLocationPayload.parse(request: request, value: bad) == nil, "numeric boolean accepted")
        bad = value; bad["items"] = Array(repeating: (value["items"] as! [[String: Any]])[0], count: 21); check(FileLocationPayload.parse(request: request, value: bad) == nil, "unbounded candidates accepted")
        try FileManager.default.removeItem(atPath: path); try FileManager.default.createSymbolicLink(atPath: path, withDestinationPath: "/etc/passwd"); check(!state.mayReveal(token: token, index: 0, path: path), "symlink replacement accepted")
        print("PASS native file payload and exact selection authority; forged token/index/path, numeric boolean, oversized list, symlink rejected. No AppKit/Finder/UI launched.")
    }
}
#endif
