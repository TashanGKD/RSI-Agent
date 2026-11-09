import AppKit

// AppKit translation of the original ForwardedRecordWindow: its 720-point
// window, selectable row text, nested/back position and action labels are kept.
final class MacForwardView: NSObject, NSWindowDelegate {
    private final class ActionButton: NSButton {
        var payload: [String: Any] = [:]
    }
    private var window: NSWindow?
    private var send: (([String: Any]) -> Void)?
    private var current: [String: Any] = [:]
    private var suppressClose = false
    private var statusLabel: NSTextField?
    private var closedSession: String?
    private let files = MacForwardFileView()

    func show(state: [String: Any], send: @escaping ([String: Any]) -> Void) {
        guard let session = state["session"] as? String, !session.isEmpty,
              let revision = state["revision"] as? Int, revision > 0,
              let items = state["items"] as? [[String: Any]], items.count <= 500 else { return }
        guard closedSession != session else { return }
        let sameDocument = current["session"] as? String == session && current["revision"] as? Int == revision
        self.send = send; current = state
        if let fileState = state["fileCandidates"] as? [String: Any] { files.show(state: fileState, parent: state, send: send) }
        else { files.dismiss() }
        if sameDocument, window?.isVisible == true {
            statusLabel?.stringValue = state["status"] as? String ?? ""
            return // Status updates preserve reading position and the active image window.
        }
        if window == nil {
            let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 720), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            panel.title = "聊天记录"; panel.minSize = NSSize(width: 460, height: 360)
            panel.isReleasedWhenClosed = false; panel.delegate = self; panel.center(); window = panel
        }
        guard let window = window else { return }
        let root = NSView(); window.contentView = root
        let title = label(state["title"] as? String ?? "聊天记录", size: 17, weight: .semibold)
        title.lineBreakMode = .byTruncatingTail; title.maximumNumberOfLines = 1
        let back = button("返回上一层", operation: "back", state: state)
        back.isHidden = !(state["canBack"] as? Bool ?? false)
        let heading = NSStackView(views: [title, back]); heading.orientation = .horizontal; heading.spacing = 12
        title.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let summary = label(state["summary"] as? String ?? "", size: 13, color: .secondaryLabelColor)
        let header = NSStackView(views: [heading, summary]); header.orientation = .vertical; header.alignment = .leading; header.spacing = 8
        let status = label(state["status"] as? String ?? "", size: 12, color: .secondaryLabelColor); statusLabel = status
        let copy = button("复制聊天记录", operation: "copy", state: state)
        let footer = NSStackView(views: [status, copy]); footer.orientation = .horizontal; footer.spacing = 12
        status.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true; scroll.drawsBackground = false
        let rows = NSStackView(); rows.orientation = .vertical; rows.alignment = .leading; rows.spacing = 12; rows.translatesAutoresizingMaskIntoConstraints = false
        scroll.documentView = rows
        var rowViews: [NSView] = []
        for item in items {
            let box = NSBox(); box.boxType = .custom; box.borderWidth = 0; box.fillColor = .controlBackgroundColor; box.cornerRadius = 8
            box.contentViewMargins = NSSize(width: 0, height: 0)
            let content = NSStackView(); content.orientation = .vertical; content.alignment = .leading; content.spacing = 6; content.translatesAutoresizingMaskIntoConstraints = false
            content.addArrangedSubview(label(item["heading"] as? String ?? "", size: 12, color: .secondaryLabelColor))
            content.addArrangedSubview(label(item["text"] as? String ?? "", size: 14))
            if let quote = item["quote"] as? String, !quote.isEmpty { content.addArrangedSubview(label(quote, size: 12, color: .secondaryLabelColor)) }
            if let detail = item["detail"] as? String, !detail.isEmpty { content.addArrangedSubview(label(detail, size: 12, color: .secondaryLabelColor)) }
            if item["hasAction"] as? Bool == true, let index = item["index"] as? Int {
                let action = button(item["action"] as? String ?? "查看", operation: "item", state: state)
                action.payload["item"] = index; content.addArrangedSubview(action)
            }
            for view in content.arrangedSubviews where view is NSTextField {
                view.widthAnchor.constraint(equalTo: content.widthAnchor).isActive = true
            }
            guard let surface = box.contentView else { continue }
            surface.addSubview(content)
            NSLayoutConstraint.activate([content.leadingAnchor.constraint(equalTo: surface.leadingAnchor, constant: 16), content.trailingAnchor.constraint(equalTo: surface.trailingAnchor, constant: -16), content.topAnchor.constraint(equalTo: surface.topAnchor, constant: 12), content.bottomAnchor.constraint(equalTo: surface.bottomAnchor, constant: -12)])
            rows.addArrangedSubview(box); box.translatesAutoresizingMaskIntoConstraints = false
            box.widthAnchor.constraint(equalTo: rows.widthAnchor).isActive = true
            rowViews.append(box)
        }
        for view in [header, scroll, footer] { root.addSubview(view); view.translatesAutoresizingMaskIntoConstraints = false }
        NSLayoutConstraint.activate([
            header.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24), header.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), header.topAnchor.constraint(equalTo: root.topAnchor, constant: 24),
            heading.widthAnchor.constraint(equalTo: header.widthAnchor), summary.widthAnchor.constraint(equalTo: header.widthAnchor),
            footer.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24), footer.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), footer.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -24),
            scroll.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 12), scroll.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24), scroll.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), scroll.bottomAnchor.constraint(equalTo: footer.topAnchor, constant: -12),
            rows.leadingAnchor.constraint(equalTo: scroll.contentView.leadingAnchor), rows.trailingAnchor.constraint(equalTo: scroll.contentView.trailingAnchor), rows.topAnchor.constraint(equalTo: scroll.contentView.topAnchor), rows.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor)
        ])
        root.layoutSubtreeIfNeeded()
        let selected = state["scrollIndex"] as? Int ?? 0
        if rowViews.indices.contains(selected) { rows.scrollToVisible(rowViews[selected].frame) }
        window.makeKeyAndOrderFront(nil)
    }
    private func label(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = .labelColor) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: text)
        field.font = .systemFont(ofSize: size, weight: weight); field.textColor = color
        field.isSelectable = true; field.maximumNumberOfLines = 0; field.lineBreakMode = .byWordWrapping
        return field
    }
    private func button(_ title: String, operation: String, state: [String: Any]) -> ActionButton {
        let control = ActionButton(title: title, target: self, action: #selector(performAction(_:)))
        control.bezelStyle = .rounded
        control.payload = ["action": "forwardedAction", "operation": operation, "session": state["session"] as? String ?? "", "revision": state["revision"] as? Int ?? -1]
        return control
    }
    @objc private func performAction(_ sender: ActionButton) { send?(sender.payload) }
    func dismiss() { files.dismiss(); closedSession = current["session"] as? String; suppressClose = true; window?.close(); suppressClose = false; current = [:] }
    func windowWillClose(_ notification: Notification) {
        guard !suppressClose, let session = current["session"] as? String, let revision = current["revision"] as? Int else { return }
        closedSession = session
        send?(["action": "forwardedAction", "operation": "close", "session": session, "revision": revision])
    }
}


// Original FileLocationWindow semantics: list same-name candidates, show size and
// uncertainty, and require a separate selection/reveal action. No UI path input.
private final class MacForwardFileView: NSObject, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate {
    private var window: NSWindow?
    private var table = NSTableView()
    private var status = NSTextField(wrappingLabelWithString: "")
    private var details = NSTextField(wrappingLabelWithString: "")
    private var reveal = NSButton()
    private var retry = NSButton()
    private var state: [String: Any] = [:]
    private var parent: [String: Any] = [:]
    private var rows: [[String: Any]] = []
    private var send: (([String: Any]) -> Void)?
    private var closedToken: String?
    private var suppressClose = false
    func show(state: [String: Any], parent: [String: Any], send: @escaping ([String: Any]) -> Void) {
        guard let token = state["token"] as? String, token != closedToken,
              let items = state["items"] as? [[String: Any]], items.count <= 20 else { return }
        let changed = self.state["token"] as? String != token || rows.count != items.count
        self.state = state; self.parent = parent; self.send = send; rows = items
        if window == nil { build() }
        status.stringValue = state["status"] as? String ?? ""
        window?.title = state["title"] as? String ?? "本地文件"
        let busy = state["busy"] as? Bool ?? false
        table.isEnabled = !busy; retry.isEnabled = !busy
        if changed { table.reloadData(); table.deselectAll(nil); if rows.count == 1 { table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false) } }
        selectionChanged()
        if window?.isVisible != true { window?.makeKeyAndOrderFront(nil) }
    }
    private func build() {
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 440), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        panel.minSize = NSSize(width: 460, height: 280); panel.isReleasedWhenClosed = false; panel.delegate = self; panel.center(); window = panel
        status.font = .systemFont(ofSize: 13); status.textColor = .secondaryLabelColor; status.isSelectable = true
        details.font = .systemFont(ofSize: 12); details.textColor = .secondaryLabelColor; details.isSelectable = true
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("file")); column.resizingMask = .autoresizingMask; table.addTableColumn(column)
        table.headerView = nil; table.rowHeight = 58; table.delegate = self; table.dataSource = self; table.columnAutoresizingStyle = .uniformColumnAutoresizingStyle
        let scroll = NSScrollView(); scroll.documentView = table; scroll.hasVerticalScroller = true
        reveal = NSButton(title: "打开所在文件夹", target: self, action: #selector(revealSelected))
        retry = NSButton(title: "重新查找", target: self, action: #selector(retrySearch))
        let buttons = NSStackView(views: [retry, reveal]); buttons.orientation = .horizontal; buttons.spacing = 12
        let root = NSView(); panel.contentView = root
        for view in [status, scroll, details, buttons] { root.addSubview(view); view.translatesAutoresizingMaskIntoConstraints = false }
        NSLayoutConstraint.activate([
            status.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24), status.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), status.topAnchor.constraint(equalTo: root.topAnchor, constant: 24),
            buttons.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), buttons.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -24),
            details.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24), details.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), details.bottomAnchor.constraint(equalTo: buttons.topAnchor, constant: -12),
            scroll.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 24), scroll.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -24), scroll.topAnchor.constraint(equalTo: status.bottomAnchor, constant: 12), scroll.bottomAnchor.constraint(equalTo: details.topAnchor, constant: -12), scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 60)
        ])
    }
    func numberOfRows(in tableView: NSTableView) -> Int { rows.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        guard rows.indices.contains(row) else { return nil }
        let cell = NSTableCellView()
        let path = NSTextField(labelWithString: rows[row]["directory"] as? String ?? ""); path.lineBreakMode = .byTruncatingMiddle
        let summary = NSTextField(labelWithString: rows[row]["summary"] as? String ?? ""); summary.font = .systemFont(ofSize: 12); summary.textColor = .secondaryLabelColor
        for field in [path, summary] { cell.addSubview(field); field.translatesAutoresizingMaskIntoConstraints = false }
        NSLayoutConstraint.activate([path.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 4), path.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -4), path.topAnchor.constraint(equalTo: cell.topAnchor, constant: 6), summary.leadingAnchor.constraint(equalTo: path.leadingAnchor), summary.trailingAnchor.constraint(equalTo: path.trailingAnchor), summary.topAnchor.constraint(equalTo: path.bottomAnchor, constant: 4)])
        return cell
    }
    func tableViewSelectionDidChange(_ notification: Notification) { selectionChanged() }
    private func selectionChanged() {
        let selected = table.selectedRow
        reveal.isEnabled = !(state["busy"] as? Bool ?? false) && rows.indices.contains(selected)
        details.stringValue = rows.indices.contains(selected) ? rows[selected]["details"] as? String ?? "" : "请选择文件候选。"
    }
    private func payload(_ operation: String) -> [String: Any] {
        ["action": "forwardedAction", "operation": operation, "session": parent["session"] as? String ?? "", "revision": parent["revision"] as? Int ?? -1, "candidateToken": state["token"] as? String ?? ""]
    }
    @objc private func revealSelected() {
        guard rows.indices.contains(table.selectedRow) else { return }
        var value = payload("fileReveal"); value["candidateIndex"] = rows[table.selectedRow]["index"] as? Int ?? -1; send?(value)
    }
    @objc private func retrySearch() { send?(payload("fileRetry")) }
    func dismiss() { closedToken = state["token"] as? String; suppressClose = true; window?.close(); suppressClose = false; state = [:]; rows = [] }
    func windowWillClose(_ notification: Notification) { if !suppressClose { closedToken = state["token"] as? String; send?(payload("fileClose")) } }
}
