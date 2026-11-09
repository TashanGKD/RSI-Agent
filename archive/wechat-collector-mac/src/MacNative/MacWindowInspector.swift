import AppKit
import CoreFoundation

// No AppKit objects are needed to verify that closing/replacing a diagnostic
// invalidates an outstanding picker/capture callback before it can show a window.
struct InspectorSelectedPreviewLifetime {
    private var active: UUID?
    mutating func begin() -> UUID { let value = UUID(); active = value; return value }
    func accepts(_ value: UUID) -> Bool { active == value }
    mutating func finish(_ value: UUID) -> Bool { guard accepts(value) else { return false }; active = nil; return true }
    mutating func invalidate() { active = nil }
}
private struct InspectorPreviewIdentity {
    let id: Int, pid: Int, x: Double, y: Double, width: Double, height: Double
}
// Validation stays independent of NSApplication, windows, capture and permissions.
private struct InspectorWindow: Equatable {
    let id: Int, pid: Int, x: Double, y: Double, width: Double, height: Double, layer: Int
    let onScreen: Bool, mainTitleMatches: Bool
    let sharingState: Int?, alpha: Double?
    var previewIdentity: InspectorPreviewIdentity { InspectorPreviewIdentity(id: id, pid: pid, x: x, y: y, width: width, height: height) }
    var diagnosticLine: String {
        let position = String(format: "(%.0f, %.0f)", x, y)
        let sharing = sharingState.map(String.init) ?? "未知"
        let opacity = alpha.map { String(format: "%.0f%%", $0 * 100) } ?? "未知"
        return "\(position) · 共享\(sharing) · α\(opacity)"
    }
}
private enum InspectorValidation {
    static let maximumPngBytes = 4 * 1024 * 1024
    static let maximumBase64Bytes = ((maximumPngBytes + 2) / 3) * 4
    static func number(_ value: Any?) -> Double? {
        guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return nil }
        return value.doubleValue
    }
    static func integer(_ value: Any?, minimum: Int, maximum: Int) -> Int? {
        guard let value = number(value), value.rounded(.towardZero) == value, value >= Double(minimum), value <= Double(maximum) else { return nil }
        return Int(value)
    }
    static func boolean(_ value: Any?) -> Bool? {
        guard let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }
    static func fraction(_ value: Any?) -> Double? {
        guard let value = number(value), (0...1).contains(value) else { return nil }
        return value
    }
    static func supplied(_ value: Any?) -> Bool { value != nil && !(value is NSNull) }
    static func visualStats(_ value: Any?) -> String {
        guard let value = value as? [String: Any] else { return "" }
        var parts: [String] = []
        if let nonzero = fraction(value["sampledAlphaNonzeroFraction"]) {
            // Wire value counts alpha > 0; the displayed transparent fraction is
            // its complement. Both statistics use all sampled points as divisor.
            parts.append(String(format: "透明采样%.1f%%", (1 - nonzero) * 100))
        }
        if let white = fraction(value["nearWhiteFraction"]) { parts.append(String(format: "近白%.1f%%", white * 100)) }
        return parts.joined(separator: " / ")
    }
    static func bounds(_ value: Any?) -> (Double, Double, Double, Double)? {
        guard let value = value as? [String: Any], let x = number(value["x"]), let y = number(value["y"]),
              let width = number(value["width"]), let height = number(value["height"]),
              width > 0, height > 0, width <= 32768, height <= 32768,
              (x + width).isFinite, (y + height).isFinite else { return nil }
        return (x, y, width, height)
    }
    static func candidates(_ values: [[String: Any]]) -> [InspectorWindow]? {
        guard values.count <= 64 else { return nil }
        var result: [InspectorWindow] = []; var seen = Set<Int>()
        for value in values {
            guard let id = integer(value["id"], minimum: 1, maximum: Int(UInt32.max)), seen.insert(id).inserted,
                  let pid = integer(value["pid"], minimum: 1, maximum: Int(Int32.max)), let rect = bounds(value["pointBounds"]),
                  let layer = integer(value["layer"], minimum: Int(Int32.min), maximum: Int(Int32.max)),
                  let onScreen = boolean(value["onScreen"]), let main = boolean(value["mainTitleMatches"]) else { return nil }
            let sharing = integer(value["sharingState"], minimum: 0, maximum: Int(Int32.max))
            let alpha = fraction(value["alpha"])
            guard !supplied(value["sharingState"]) || sharing != nil, !supplied(value["alpha"]) || alpha != nil else { return nil }
            result.append(InspectorWindow(id: id, pid: pid, x: rect.0, y: rect.1, width: rect.2, height: rect.3, layer: layer, onScreen: onScreen, mainTitleMatches: main, sharingState: sharing, alpha: alpha))
        }
        return result
    }
    static func selectedWindow(_ value: Any?) -> InspectorPreviewIdentity? {
        guard let value = value as? [String: Any], value["ownerBundleId"] as? String == "com.tencent.xinWeChat",
              let id = integer(value["id"], minimum: 1, maximum: Int(UInt32.max)), let pid = integer(value["pid"], minimum: 1, maximum: Int(Int32.max)),
              let launch = number(value["processLaunchTime"]), launch > 0, let rect = bounds(value["pointBounds"]) else { return nil }
        return InspectorPreviewIdentity(id: id, pid: pid, x: rect.0, y: rect.1, width: rect.2, height: rect.3)
    }
    static func matches(_ value: Any?, expected: InspectorPreviewIdentity) -> Bool {
        guard let value = value as? [String: Any], integer(value["id"], minimum: 1, maximum: Int(UInt32.max)) == expected.id,
              integer(value["pid"], minimum: 1, maximum: Int(Int32.max)) == expected.pid, let rect = bounds(value["pointBounds"]) else { return false }
        return rect.0 == expected.x && rect.1 == expected.y && rect.2 == expected.width && rect.3 == expected.height
    }
    static func preview(_ response: [String: Any], expected: InspectorWindow) -> NSBitmapImageRep? { preview(response, expected: expected.previewIdentity) }
    static func preview(_ response: [String: Any], expected: InspectorPreviewIdentity) -> NSBitmapImageRep? {
        guard integer(response["schemaVersion"], minimum: 1, maximum: 1) == 1,
              let status = response["status"] as? String, ["ocr_ready", "ocr_empty"].contains(status),
              matches(response["window"], expected: expected), let image = response["image"] as? [String: Any],
              let width = integer(image["width"], minimum: 1, maximum: 8192), let height = integer(image["height"], minimum: 1, maximum: 8192),
              width * height <= 16_777_216, let encoded = response["previewPngBase64"] as? String,
              encoded.utf8.count <= maximumBase64Bytes, let data = Data(base64Encoded: encoded),
              data.count >= 33, data.count <= maximumPngBytes,
              Array(data.prefix(8)) == [137, 80, 78, 71, 13, 10, 26, 10],
              Array(data[8..<16]) == [0, 0, 0, 13, 73, 72, 68, 82] else { return nil }
        let headerWidth = data[16..<20].reduce(0) { ($0 << 8) | Int($1) }
        let headerHeight = data[20..<24].reduce(0) { ($0 << 8) | Int($1) }
        // IHDR limits precede any decompression, including metadata mismatches.
        guard headerWidth == width, headerHeight == height,
              let bitmap = NSBitmapImageRep(data: data), bitmap.pixelsWide == width, bitmap.pixelsHigh == height else { return nil }
        return bitmap
    }
}

// Explicit local debug UI only. It has no capture, input, permission, file-save,
// network or OCR-text publishing path; the caller supplies one-window responses.
final class MacWindowInspector: NSObject, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate {
    private var window: NSWindow?
    private let table = NSTableView(), imageView = NSImageView(), imageScroll = NSScrollView()
    private let status = NSTextField(labelWithString: "请选择一个窗口后查看预览。")
    private let previewButton = NSButton(title: "查看所选窗口", target: nil, action: nil)
    private let fitButton = NSButton(title: "适应窗口", target: nil, action: nil)
    private var candidates: [InspectorWindow] = []
    private var onPreview: ((Int) -> Void)?
    private var pending: InspectorWindow?
    private var selectedPreview: InspectorPreviewIdentity?
    private var selectedLifetime = InspectorSelectedPreviewLifetime()
    private var imageSize = NSSize.zero

    func show(candidates values: [[String: Any]], onPreview: @escaping (Int) -> Void) {
        guard Thread.isMainThread else { return }
        makeWindow()
        self.onPreview = onPreview; pending = nil; selectedPreview = nil; selectedLifetime.invalidate(); clearImage()
        if let validated = InspectorValidation.candidates(values) {
            candidates = validated
            status.stringValue = validated.isEmpty ? "未找到可预览的微信窗口。" : "请选择一个窗口后查看预览。窗口列表不包含聊天标题。"
        } else { candidates = []; status.stringValue = "窗口列表无效，请重新打开诊断窗口。" }
        table.reloadData(); table.deselectAll(nil); updateButtons()
        window?.makeKeyAndOrderFront(nil)
    }
    func renderPreview(response: [String: Any]) {
        guard Thread.isMainThread, let request = pending else { return }
        // A new show/list or a changed selection never consumes an old preview.
        if let value = response["window"], !InspectorValidation.matches(value, expected: request.previewIdentity) {
            pending = nil; clearImage(); status.stringValue = "窗口身份或位置已变化，请重新选择窗口。"; updateButtons(); return
        }
        pending = nil
        guard candidates.indices.contains(table.selectedRow), candidates[table.selectedRow] == request,
              let bitmap = InspectorValidation.preview(response, expected: request) else {
            clearImage(); status.stringValue = "预览未通过窗口或图像校验，请重新选择窗口。"; updateButtons(); return
        }
        display(bitmap: bitmap, response: response, windowID: request.id)
    }
    // Only the explicit native menu/button workflow calls these methods. Starting
    // a picker does not create or reopen this diagnostic window.
    func beginSelectedPreview() -> UUID {
        pending = nil; clearImage(); updateButtons()
        return selectedLifetime.begin()
    }
    func isSelectedPreviewPending(_ requestID: UUID) -> Bool { selectedLifetime.accepts(requestID) }
    func cancelSelectedPreview(_ requestID: UUID? = nil) {
        if let requestID = requestID, !selectedLifetime.accepts(requestID) { return }
        selectedLifetime.invalidate()
    }
    @discardableResult func showSelectedPreview(response: [String: Any], requestID: UUID) -> Bool {
        guard Thread.isMainThread, selectedLifetime.accepts(requestID) else { return false }
        guard let selected = InspectorValidation.selectedWindow(response["window"]),
              let bitmap = InspectorValidation.preview(response, expected: selected) else {
            selectedLifetime.invalidate(); status.stringValue = "系统所选窗口预览未通过图像或身份校验。"; return false
        }
        guard selectedLifetime.finish(requestID) else { return false }
        makeWindow(); pending = nil; onPreview = nil; candidates = []; selectedPreview = selected
        table.reloadData(); table.deselectAll(nil)
        display(bitmap: bitmap, response: response, windowID: selected.id)
        window?.makeKeyAndOrderFront(nil)
        return true
    }
    private func display(bitmap: NSBitmapImageRep, response: [String: Any], windowID: Int) {
        imageSize = NSSize(width: bitmap.pixelsWide, height: bitmap.pixelsHigh)
        let image = NSImage(size: imageSize); image.addRepresentation(bitmap)
        imageView.image = image; imageView.frame = NSRect(origin: .zero, size: imageSize)
        let occlusion = response["occlusionStatus"] as? String
        let observation = occlusion == "clear" ? "未检测到遮挡" : (occlusion == "obscured" ? "检测到遮挡" : "遮挡状态未知")
        status.stringValue = "窗口 \(windowID) · \(bitmap.pixelsWide) × \(bitmap.pixelsHigh) 像素 · \(observation) · 仅在内存预览"
        let stats = InspectorValidation.visualStats(response["previewVisualStats"])
        if !stats.isEmpty { status.stringValue += " · " + stats }
        window?.contentView?.layoutSubtreeIfNeeded(); fitImage(nil); updateButtons()
    }
    private func makeWindow() {
        guard window == nil else { return }
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 700), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        panel.title = "微信窗口诊断"; panel.minSize = NSSize(width: 760, height: 500); panel.isReleasedWhenClosed = false; panel.delegate = self; panel.center(); window = panel
        let root = NSView(); panel.contentView = root
        let heading = NSTextField(labelWithString: "选择一个微信窗口，检查该窗口当前渲染。预览不会保存或上传。")
        heading.font = .systemFont(ofSize: 13); heading.textColor = .secondaryLabelColor
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier("window")); column.title = "微信窗口"; column.width = 280; table.addTableColumn(column)
        table.delegate = self; table.dataSource = self; table.headerView = nil; table.rowHeight = 64; table.allowsMultipleSelection = false; table.allowsEmptySelection = true
        let list = NSScrollView(); list.documentView = table; list.hasVerticalScroller = true; list.borderType = .bezelBorder
        imageView.imageScaling = .scaleProportionallyUpOrDown; imageView.imageAlignment = .alignCenter; imageView.isEditable = false
        imageScroll.documentView = imageView; imageScroll.hasVerticalScroller = true; imageScroll.hasHorizontalScroller = true
        imageScroll.borderType = .bezelBorder; imageScroll.allowsMagnification = true; imageScroll.minMagnification = 0.01; imageScroll.maxMagnification = 8
        previewButton.target = self; previewButton.action = #selector(requestPreview(_:)); previewButton.bezelStyle = .rounded
        fitButton.target = self; fitButton.action = #selector(fitImage(_:)); fitButton.bezelStyle = .rounded
        status.font = .systemFont(ofSize: 12); status.textColor = .secondaryLabelColor; status.lineBreakMode = .byWordWrapping
        status.maximumNumberOfLines = 2; status.cell?.wraps = true; status.cell?.isScrollable = false
        for view in [heading, list, imageScroll, previewButton, fitButton, status] { root.addSubview(view); view.translatesAutoresizingMaskIntoConstraints = false }
        NSLayoutConstraint.activate([
            heading.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16), heading.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16), heading.topAnchor.constraint(equalTo: root.topAnchor, constant: 16),
            list.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16), list.topAnchor.constraint(equalTo: heading.bottomAnchor, constant: 12), list.widthAnchor.constraint(equalToConstant: 280), list.bottomAnchor.constraint(equalTo: previewButton.topAnchor, constant: -12),
            imageScroll.leadingAnchor.constraint(equalTo: list.trailingAnchor, constant: 12), imageScroll.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16), imageScroll.topAnchor.constraint(equalTo: list.topAnchor), imageScroll.bottomAnchor.constraint(equalTo: list.bottomAnchor),
            previewButton.leadingAnchor.constraint(equalTo: list.leadingAnchor), previewButton.bottomAnchor.constraint(equalTo: status.topAnchor, constant: -8),
            fitButton.trailingAnchor.constraint(equalTo: imageScroll.trailingAnchor), fitButton.centerYAnchor.constraint(equalTo: previewButton.centerYAnchor),
            status.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: 16), status.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -16), status.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -12)
        ])
    }
    private func clearImage() { imageView.image = nil; imageSize = .zero; imageView.frame = .zero }
    private func updateButtons() { previewButton.isEnabled = pending == nil && candidates.indices.contains(table.selectedRow); fitButton.isEnabled = imageView.image != nil }
    @objc private func requestPreview(_ sender: Any?) {
        guard pending == nil, candidates.indices.contains(table.selectedRow) else { return }
        selectedLifetime.invalidate()
        let selected = candidates[table.selectedRow]; pending = selected; clearImage(); status.stringValue = "正在获取所选窗口预览…"; updateButtons(); onPreview?(selected.id)
    }
    @objc private func fitImage(_ sender: Any?) {
        guard imageSize.width > 0, imageSize.height > 0 else { return }
        let size = imageScroll.contentView.bounds.size
        let scale = min(size.width / imageSize.width, size.height / imageSize.height)
        imageScroll.setMagnification(max(0.01, min(8, scale)), centeredAt: NSPoint(x: imageSize.width / 2, y: imageSize.height / 2))
    }
    func numberOfRows(in tableView: NSTableView) -> Int { selectedPreview == nil ? candidates.count : 1 }
    func selectionShouldChange(in tableView: NSTableView) -> Bool { selectedPreview == nil }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        if let selected = selectedPreview, row == 0 {
            let dimensions = String(format: "%.0f × %.0f 点", selected.width, selected.height)
            let position = String(format: "(%.0f, %.0f)", selected.x, selected.y)
            let text = NSTextField(wrappingLabelWithString: "窗口 \(selected.id) · \(dimensions)\n系统明确选择\n位置 \(position)")
            text.font = .systemFont(ofSize: 12); text.maximumNumberOfLines = 3; return text
        }
        guard candidates.indices.contains(row) else { return nil }
        let value = candidates[row]
        let dimensions = String(format: "%.0f × %.0f 点", value.width, value.height)
        let position = value.onScreen ? "屏幕内" : "未显示"
        let main = value.mainTitleMatches ? "主窗候选" : "其他微信窗口"
        let text = NSTextField(wrappingLabelWithString: "窗口 \(value.id) · \(dimensions)\n\(position) · \(main) · 层 \(value.layer)\n\(value.diagnosticLine)")
        text.font = .systemFont(ofSize: 12); text.maximumNumberOfLines = 3
        return text
    }
    func tableViewSelectionDidChange(_ notification: Notification) { clearImage(); if pending == nil { status.stringValue = "点击查看所选窗口；可使用触控板缩放预览。" }; updateButtons() }
    func windowWillClose(_ notification: Notification) { pending = nil; selectedLifetime.invalidate(); selectedPreview = nil; clearImage(); candidates = []; onPreview = nil; table.reloadData() }
}

#if WINDOW_INSPECTOR_SYNTHETIC
@main private enum InspectorSynthetic {
    static func main() {
        func check(_ condition: Bool, _ message: String) { if !condition { print("FAIL: " + message); exit(1) } }
        let valid: [String: Any] = ["id": 123, "pid": 456, "pointBounds": ["x": -1600, "y": -700, "width": 800, "height": 600], "layer": 0, "onScreen": true, "mainTitleMatches": false]
        var bad = valid; bad["id"] = true
        check(InspectorValidation.candidates([bad]) == nil, "Boolean window id accepted")
        bad = valid; bad["pointBounds"] = ["x": Double.nan, "y": 0, "width": 800, "height": 600]
        check(InspectorValidation.candidates([bad]) == nil, "nonfinite frame accepted")
        check(InspectorValidation.candidates(Array(repeating: valid, count: 65)) == nil, "window count overflow accepted")
        check(InspectorValidation.candidates([valid, valid]) == nil, "duplicate window id accepted")
        bad = valid; bad["sharingState"] = true
        check(InspectorValidation.candidates([bad]) == nil, "Boolean sharing state accepted")
        for alpha in [Double.nan, Double.infinity, -0.1, 1.1] {
            bad = valid; bad["alpha"] = alpha
            check(InspectorValidation.candidates([bad]) == nil, "invalid optional alpha accepted")
        }
        bad = valid; bad["sharingState"] = 2; bad["alpha"] = 0.5
        let decorated = InspectorValidation.candidates([bad])?.first
        check(decorated?.sharingState == 2 && decorated?.alpha == 0.5, "optional diagnostic fields were discarded")
        check(decorated?.diagnosticLine == "(-1600, -700) · 共享2 · α50%", "diagnostic metadata formatting changed")
        bad = valid; bad["sharingState"] = NSNull(); bad["alpha"] = NSNull()
        check(InspectorValidation.candidates([bad])?.first?.diagnosticLine.contains("共享未知") == true, "unknown optional fields were not retained as unknown")
        check(InspectorValidation.visualStats(["sampledAlphaNonzeroFraction": 1, "nearWhiteFraction": 1]) == "透明采样0.0% / 近白100.0%", "nontransparent white was mislabeled transparent")
        check(InspectorValidation.visualStats(["sampledAlphaNonzeroFraction": 0, "nearWhiteFraction": 0]) == "透明采样100.0% / 近白0.0%", "transparent sampling complement is incorrect")
        for invalidStats in [Double.nan, Double.infinity, -0.1, 1.1] {
            check(InspectorValidation.visualStats(["sampledAlphaNonzeroFraction": invalidStats, "nearWhiteFraction": invalidStats]).isEmpty, "invalid optional stats displayed")
        }
        check(InspectorValidation.visualStats(nil).isEmpty && InspectorValidation.visualStats(["sampledAlphaNonzeroFraction": true]).isEmpty, "missing or Boolean stats were displayed as measured numbers")
        check(InspectorValidation.candidates([valid])?.first?.x == -1600, "valid extended-screen metadata rejected")
        let expected = InspectorValidation.candidates([valid])!.first!
        var selectedWindow = valid; selectedWindow.removeValue(forKey: "layer"); selectedWindow.removeValue(forKey: "onScreen"); selectedWindow.removeValue(forKey: "mainTitleMatches")
        selectedWindow["ownerBundleId"] = "com.tencent.xinWeChat"; selectedWindow["processLaunchTime"] = 1767225600.0
        check(InspectorValidation.selectedWindow(selectedWindow)?.id == 123, "selected mode demanded fabricated candidate metadata")
        var foreignWindow = selectedWindow; foreignWindow["ownerBundleId"] = "another.bundle"
        check(InspectorValidation.selectedWindow(foreignWindow) == nil, "selected preview accepted another app")
        foreignWindow = selectedWindow; foreignWindow["processLaunchTime"] = true
        check(InspectorValidation.selectedWindow(foreignWindow) == nil, "selected preview accepted invalid process lifetime")
        var lifetime = InspectorSelectedPreviewLifetime()
        let oldRequest = lifetime.begin(); let newRequest = lifetime.begin()
        check(!lifetime.accepts(oldRequest) && lifetime.accepts(newRequest), "replacement did not reject old picker callback")
        lifetime.invalidate(); check(!lifetime.finish(newRequest), "closed inspector allowed old callback to reopen")
        let once = lifetime.begin(); check(lifetime.finish(once) && !lifetime.finish(once), "selected preview callback was not single-use")
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 8, bitsPerPixel: 32)!
        let png = bitmap.representation(using: .png, properties: [:])!
        let response: [String: Any] = ["schemaVersion": 1, "status": "ocr_empty", "window": valid, "image": ["width": 2, "height": 2], "previewPngBase64": png.base64EncodedString()]
        check(InspectorValidation.preview(response, expected: expected) != nil, "valid in-memory synthetic PNG rejected")
        var selectedResponse = response; selectedResponse["window"] = selectedWindow
        check(InspectorValidation.preview(selectedResponse, expected: InspectorValidation.selectedWindow(selectedWindow)!) != nil, "selected preview PNG validation failed without layer/onScreen metadata")
        var invalid = response; invalid["previewPngBase64"] = "not base64"
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "invalid base64 accepted")
        invalid = response; invalid["previewPngBase64"] = String(repeating: "A", count: InspectorValidation.maximumBase64Bytes + 4)
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "oversized encoded payload accepted")
        invalid = response; invalid["image"] = ["width": 8192, "height": 8192]
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "oversized pixel allocation accepted")
        invalid = response; invalid["image"] = ["width": 3, "height": 2]
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "IHDR metadata mismatch accepted")
        var poisoned = png; poisoned[16] = 127
        invalid = response; invalid["previewPngBase64"] = poisoned.base64EncodedString()
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "poisoned huge IHDR accepted before decoding")
        invalid = response; var stale = valid; stale["pid"] = 457; invalid["window"] = stale
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "stale process identity accepted")
        invalid = response; stale = valid; stale["pointBounds"] = ["x": -1600, "y": -699, "width": 800, "height": 600]; invalid["window"] = stale
        check(InspectorValidation.preview(invalid, expected: expected) == nil, "changed window frame accepted")
        print("PASS: synthetic optional sharing/alpha/stat diagnostics, metadata, bounds, identity, count, base64 and predecode PNG limits; no window/capture/input/permission access")
    }
}
#endif
