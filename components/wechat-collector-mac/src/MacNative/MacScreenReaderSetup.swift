import AppKit

extension CollectorDelegate {
    @objc func showScreenReader() {
        if screenReaderWindow == nil {
            let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 340), styleMask: [.titled, .closable], backing: .buffered, defer: false)
            panel.title = "微信窗口读取（本机）"; panel.isReleasedWhenClosed = false; panel.delegate = self
            let heading = NSTextField(wrappingLabelWithString: "仅识别本机微信窗口，用于核对会话和历史读取位置。识别结果不会作为原始聊天消息导入，也不会上传。")
            let status = NSTextField(wrappingLabelWithString: "只需在首次使用时完成系统屏幕读取授权。已有权限会直接复用；检测结果在这里更新，不会反复弹窗。")
            screenReaderStatus = status
            let grant = NSButton(title: "授权屏幕读取…", target: self, action: #selector(requestScreenPermission))
            screenReaderPermissionButton = grant
            let probe = NSButton(title: "检查权限和窗口", target: self, action: #selector(probeScreenReader))
            let capture = NSButton(title: "读取当前微信窗口", target: self, action: #selector(captureScreenReader))
            let choose = NSButton(title: "选择微信窗口（系统）…", target: self, action: #selector(chooseWechatWindow))
            choose.isEnabled = !screenReaderChoosing; screenReaderChooseButton = choose
            let actions = NSStackView(views: [grant, probe, capture, choose]); actions.orientation = .vertical; actions.alignment = .leading; actions.spacing = 8
            let stack = NSStackView(views: [heading, status, actions]); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 18
            let content = NSView(); content.addSubview(stack); stack.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24), stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24), stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 24)])
            panel.contentView = content; panel.center(); screenReaderWindow = panel
        }
        updateScreenPermission(CGPreflightScreenCaptureAccess())
        screenReaderWindow?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    @objc func requestScreenPermission() {
        screenReaderStatus?.stringValue = "正在请求独立助手的屏幕读取权限，请在系统提示中确认。"
        screenReaderClient.request("requestScreenPermission") { result in self.showScreenReaderResult(result) }
    }
    @objc func probeScreenReader() {
        setScreenReaderStatus("正在检查；没有读取屏幕图像。")
        screenReaderClient.request("probe") { result in self.showScreenReaderResult(result) }
    }
    @objc func captureScreenReader() {
        setScreenReaderStatus("正在确认微信窗口并进行本地识别…")
        self.screenReaderClient.request("probe") { result in
                guard case let .success(probe) = result, probe["status"] as? String == "ready" else { self.showScreenReaderResult(result); return }
                self.screenReaderClient.request("capture") { captured in
                    guard case let .success(snapshot) = captured, ["ocr_ready", "ocr_empty"].contains(snapshot["status"] as? String ?? "") else { self.showScreenReaderResult(captured); return }
                    self.checkVisionAccount(snapshot)
                }
        }
    }
    @objc func showWindowInspector() {
        setScreenReaderStatus("正在查询原微信窗口…")
        screenReaderClient.request("listWindows") { result in
            guard case let .success(response) = result, response["status"] as? String == "windows_ready", let candidates = response["windowCandidates"] as? [[String: Any]] else { self.showScreenReaderResult(result); return }
            self.windowInspector.show(candidates: candidates) { windowID in self.previewWechatWindow(windowID) }
        }
    }
    // This selector is wired only to the explicit native menu and settings
    // button. Startup, normal probe/capture and web messages never invoke it.
    @objc func chooseWechatWindow() {
        guard !screenReaderChoosing else { setScreenReaderStatus("系统窗口选择仍在进行，请完成或取消后重试。"); return }
        screenReaderChoosing = true; screenReaderChooseButton?.isEnabled = false
        let requestID = windowInspector.beginSelectedPreview()
        setScreenReaderStatus("请在系统选择器中明确选择原微信的一个窗口。")
        screenReaderClient.request("chooseWindow") { result in
            guard self.windowInspector.isSelectedPreviewPending(requestID) else { self.finishWindowChoice(); return }
            guard case let .success(ready) = result, ready["status"] as? String == "ready", let token = ready["targetToken"] as? String else {
                self.windowInspector.cancelSelectedPreview(requestID); self.finishWindowChoice()
                if case let .success(response) = result, response["code"] as? String == "picker_cancelled" { self.setScreenReaderStatus("已取消系统窗口选择。"); }
                else if case let .success(response) = result {
                    var parts: [String] = []
                    if let code = response["code"] as? String, code.range(of: #"\A[a-z_]{1,64}\z"#, options: .regularExpression) != nil { parts.append(code) }
                    if let diagnostic = response["pickerDiagnostics"] as? [String: Any] {
                        if let stage = diagnostic["stage"] as? String, ["picker_start", "filter_shape", "filter_identity", "post_selection", "ready"].contains(stage) { parts.append(stage) }
                        if let domain = diagnostic["osErrorDomain"] as? String, domain.range(of: #"\A[A-Za-z0-9._-]{1,128}\z"#, options: .regularExpression) != nil { parts.append(domain) }
                        if let code = diagnostic["osErrorCode"] as? Int { parts.append(String(code)) }
                    }
                    self.setScreenReaderStatus("系统选择未完成：" + (parts.isEmpty ? "未返回具体原因" : parts.joined(separator: " · ")))
                } else if case let .failure(error) = result {
                    let reason: String
                    switch error {
                    case MacScreenReaderClient.ReaderError.stopped: reason = "助手已退出"
                    case MacScreenReaderClient.ReaderError.missingHelper: reason = "缺少读取助手"
                    case MacScreenReaderClient.ReaderError.probeRequired: reason = "窗口验证已过期"
                    case MacScreenReaderClient.ReaderError.protocolFailure: reason = "助手回包未通过校验"
                    default: reason = MacScreenReaderClient.lifecycleReason(error) ?? "私有连接未完成"
                    }
                    self.setScreenReaderStatus("系统选择未完成：" + reason)
                }
                return
            }
            self.screenReaderClient.request("capturePreview", expectedToken: token) { captured in
                defer { self.finishWindowChoice() }
                guard self.windowInspector.isSelectedPreviewPending(requestID) else { return }
                guard case let .success(snapshot) = captured, ["ocr_ready", "ocr_empty"].contains(snapshot["status"] as? String ?? "") else {
                    self.windowInspector.cancelSelectedPreview(requestID)
                    if case let .failure(error) = captured, let reason = MacScreenReaderClient.lifecycleReason(error) { self.setScreenReaderStatus("所选窗口预览未完成：" + reason) }
                    else { self.setScreenReaderStatus("所选微信窗口未能预览，可稍后重新选择。") }
                    return
                }
                guard self.windowInspector.showSelectedPreview(response: snapshot, requestID: requestID) else {
                    self.setScreenReaderStatus("所选窗口预览未通过图像或身份校验。"); return
                }
                self.checkVisionAccount(snapshot) // The existing boundary removes PNG before sending to Host.
            }
        }
    }
    private func finishWindowChoice() { screenReaderChoosing = false; screenReaderChooseButton?.isEnabled = true }
    private func previewWechatWindow(_ windowID: Int) {
        setScreenReaderStatus("正在预览已选中的原微信窗口…")
        screenReaderClient.request("probe", windowID: windowID) { result in
            guard case let .success(response) = result, response["status"] as? String == "ready" else { self.windowInspector.renderPreview(response: [:]); self.showScreenReaderResult(result); return }
            self.screenReaderClient.request("capturePreview") { captured in
                guard case let .success(snapshot) = captured, ["ocr_ready", "ocr_empty"].contains(snapshot["status"] as? String ?? "") else { self.windowInspector.renderPreview(response: [:]); self.showScreenReaderResult(captured); return }
                self.windowInspector.renderPreview(response: snapshot)
                self.setScreenReaderStatus("窗口预览处理完成，请查看诊断窗口。")
            }
        }
    }
    private func updateScreenPermission(_ granted: Bool) {
        screenReaderPermissionButton?.isEnabled = !granted
        screenReaderPermissionButton?.title = granted ? "屏幕读取已授权" : "授权屏幕读取…"
    }
    private func setScreenReaderStatus(_ text: String) {
        screenReaderStatus?.stringValue = text
        for status in screenReaderMenuStatuses { status.title = "窗口读取：" + String(text.prefix(32)) }
    }
    private func showScreenReaderResult(_ result: Result<[String: Any], Error>) {
        switch result {
        case let .success(value):
            if let permission = value["permission"] as? [String: Any], let granted = permission["screenCapture"] as? Bool { updateScreenPermission(granted) }
            if value["status"] as? String == "ready" { setScreenReaderStatus("窗口检查通过；可继续读取当前微信窗口。") }
            else if let permission = value["permission"] as? [String: Any], permission["screenCapture"] as? Bool == true, (value["status"] as? String ?? "").hasPrefix("permission_") { setScreenReaderStatus("屏幕读取已授权，后续直接复用。"); screenReaderWindow?.orderOut(nil) }
            else {
                var text = value["message"] as? String ?? "请完成系统屏幕读取授权后重新检查。"
                if value["code"] as? String == "target_not_found", let diagnostics = value["diagnostics"] as? [String: Any], let displays = diagnostics["displayCount"] as? Int, let candidates = diagnostics["candidateCount"] as? Int, let visible = diagnostics["onScreenCount"] as? Int {
                    text = "屏幕\(displays)块，微信窗口\(candidates)个、可见\(visible)个；未找到唯一可读窗口。"
                }
                setScreenReaderStatus(text)
            }
        case let .failure(error): setScreenReaderStatus(MacScreenReaderClient.lifecycleReason(error) ?? "独立读取助手未连接或已超时。请重新检查。")
        }
    }
    private func checkVisionAccount(_ snapshot: [String: Any]) {
        var metadata = snapshot; metadata.removeValue(forKey: "previewPngBase64")
        guard let identity = backendIdentity, let body = try? JSONSerialization.data(withJSONObject: metadata) else { showScreenReaderResult(.failure(MacScreenReaderClient.ReaderError.protocolFailure)); return }
        var request = URLRequest(url: identity.baseURL.appendingPathComponent("native/vision")); request.httpMethod = "POST"; request.httpBody = body; request.timeoutInterval = 12
        request.setValue("Bearer " + secret, forHTTPHeaderField: "Authorization"); request.setValue(launchInstance, forHTTPHeaderField: "X-Collector-Instance"); request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let session = URLSession(configuration: .ephemeral, delegate: NoBackendRedirects(), delegateQueue: nil)
        session.dataTask(with: request) { data, response, _ in
            session.finishTasksAndInvalidate()
            DispatchQueue.main.async {
                guard response?.url == request.url, (response as? HTTPURLResponse)?.statusCode == 200, let data = data, let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { self.showScreenReaderResult(.failure(MacScreenReaderClient.ReaderError.protocolFailure)); return }
                self.setScreenReaderStatus(value["message"] as? String ?? "读取结果尚未确认。")
            }
        }.resume()
    }
}
