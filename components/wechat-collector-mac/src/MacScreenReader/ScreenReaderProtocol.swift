import Foundation

// Private one-request/one-response JSON lines. No caller-selected process, path,
// display, rectangle or input event is part of this protocol. Permission requests
// require their own explicit native-menu intent and never accompany probe/capture.
enum ScreenReaderFailure: String, Error, Codable {
    case invalidRequest = "invalid_request", requestTooLarge = "request_too_large", unsupportedAction = "unsupported_action"
    case unauthorized, untrustedParent = "untrusted_parent", permissionRequired = "permission_required"
    case wrongApplication = "wrong_application", targetNotFound = "target_not_found", ambiguousTarget = "ambiguous_target", targetChanged = "target_changed"
    case probeRequired = "probe_required", staleProbe = "stale_probe", imageLimit = "image_limit", ocrLimit = "ocr_limit", invalidObservation = "invalid_observation"
    case targetObscured = "target_obscured"
    case windowLimit = "window_limit",previewLimit = "preview_limit"
    case offDisplay = "off_display",displayContextUnavailable = "display_context_unavailable"
    case pickerCancelled = "picker_cancelled",pickerTimeout = "picker_timeout",pickerRejected = "picker_rejected",unsupportedPickerOS = "unsupported_picker_os"
    case captureFailed = "capture_failed", ocrUnavailable = "ocr_unavailable", platformTimeout = "platform_timeout", unsupportedOS = "unsupported_os"
    var message: String {
        switch self {
        case .permissionRequired: return "尚无屏幕读取权限；请由用户在系统设置中授权独立助手后重新检测。"
        case .ambiguousTarget: return "发现多个微信目标窗口；请只保留要读取的一个可见窗口。"
        case .targetObscured: return "微信窗口上方有重叠窗口或遮挡证据不明，请保持目标独立可见。"
        case .targetNotFound: return "未找到唯一可见的微信窗口。"
        case .offDisplay: return "目标窗口不与当前显示器范围相交，已停止读取；请将该窗口移到显示器内后重新检测。"
        case .displayContextUnavailable: return "无法可靠确认显示器范围，已停止读取；请重新检测。"
        case .pickerCancelled: return "已取消系统窗口选择，未读取窗口。"
        case .pickerTimeout: return "系统窗口选择已超时，本助手将退出。"
        case .pickerRejected: return "系统选择结果不是指定微信的单个窗口，已拒绝读取。"
        case .unsupportedPickerOS: return "验证系统单窗口选择需要 macOS 15.2 或以上版本。"
        case .targetChanged, .staleProbe, .probeRequired: return "目标窗口已改变或检测已过期，请重新检测。"
        case .wrongApplication: return "目标不属于指定位置的微信应用，已拒绝读取。"
        case .unauthorized, .untrustedParent: return "只接受本次主应用私有会话请求。"
        case .imageLimit, .ocrLimit, .invalidObservation, .windowLimit, .previewLimit: return "图像、窗口或识别结果超出可信边界，未返回部分结果。"
        case .ocrUnavailable: return "本机文字识别未完成，未导入任何消息。"
        case .platformTimeout: return "系统读取超时；本助手会退出，由主应用重新启动。"
        case .unsupportedOS: return "独立窗口读取需要 macOS 14.2 或以上版本。"
        default: return "请求无法执行；未读取其他窗口或执行输入操作。"
        }
    }
}
enum ScreenReadAction: String { case probe, capture, capturePreview, listWindows, requestScreenPermission, chooseWindow }
struct ScreenRequest {
    let requestId: String
    let action: ScreenReadAction
    let auth: String
    let targetToken: String?
    let authorizationIntent: String?
    let windowId: UInt32?
    static func decode(_ data: Data) throws -> ScreenRequest {
        guard data.count <= 8192 else { throw ScreenReaderFailure.requestTooLarge }
        let values = try FlatRequestJSON(data).parse()
        guard Set(values.keys).isSubset(of: ["schemaVersion", "requestId", "action", "auth", "targetToken", "authorizationIntent", "windowId"]),
              values["schemaVersion"] == .integer(1), case let .string(requestId)? = values["requestId"],
              requestId.range(of: #"\A[A-Za-z0-9_.-]{1,128}\z"#, options:.regularExpression) != nil,
              case let .string(rawAction)? = values["action"], case let .string(auth)? = values["auth"],
              auth.range(of: #"\A[a-f0-9]{64}\z"#, options:.regularExpression) != nil else { throw ScreenReaderFailure.invalidRequest }
        guard let action = ScreenReadAction(rawValue:rawAction) else { throw ScreenReaderFailure.unsupportedAction }
        var targetToken: String?
        if case let .string(token)? = values["targetToken"] { targetToken = token }
        if action == .capture || action == .capturePreview {
            guard let token = targetToken, token.range(of:#"\A[A-Za-z0-9-]{1,128}\z"#,options:.regularExpression) != nil else { throw ScreenReaderFailure.invalidRequest }
        } else if values["targetToken"] != nil { throw ScreenReaderFailure.invalidRequest }
        var intent:String?
        if case let .string(value)? = values["authorizationIntent"] { intent=value }
        if action == .requestScreenPermission || action == .chooseWindow {
            guard intent=="user_clicked_native_menu",values["targetToken"]==nil else { throw ScreenReaderFailure.invalidRequest }
        } else if values["authorizationIntent"] != nil { throw ScreenReaderFailure.invalidRequest }
        var windowId:UInt32?
        if let raw=values["windowId"] {
            guard action == .probe,case let .integer(value)=raw,value>0,value<=Int(UInt32.max) else { throw ScreenReaderFailure.invalidRequest }
            windowId=UInt32(value)
        }
        return ScreenRequest(requestId:requestId,action:action,auth:auth,targetToken:targetToken,authorizationIntent:intent,windowId:windowId)
    }
    func authenticate(_ expected: String) throws {
        let a=Array(auth.utf8),b=Array(expected.utf8)
        guard a.count==64,b.count==64 else { throw ScreenReaderFailure.unauthorized }
        var difference:UInt8=0;for index in 0..<64 { difference |= a[index] ^ b[index] }
        guard difference==0 else { throw ScreenReaderFailure.unauthorized }
    }
}
// A flat lexer rejects duplicate/unknown keys and nested or malformed JSON before
// allocating any images or invoking an OS provider. No recursive JSON descent.
private struct FlatRequestJSON {
    enum Scalar: Equatable { case string(String), integer(Int) }
    let bytes:[UInt8]
    init(_ data:Data) { bytes=Array(data) }
    func parse() throws -> [String:Scalar] { var copy=self;return try copy.object() }
    private var end:Int { bytes.count }
    private var index:Int { get { cursor } set { cursor=newValue } }
    private mutating func object() throws -> [String:Scalar] {
        skip();try take(123);skip();var result:[String:Scalar]=[:]
        if peek(125) { index+=1;skip();guard index==end else { throw ScreenReaderFailure.invalidRequest };return result }
        while true {
            let key=try string();guard result[key]==nil else { throw ScreenReaderFailure.invalidRequest }
            skip();try take(58);skip()
            if peek(34) { result[key] = .string(try string()) }
            else { result[key] = .integer(try integer()) }
            skip();if peek(125) { index+=1;break };try take(44);skip()
        }
        skip();guard index==end else { throw ScreenReaderFailure.invalidRequest };return result
    }
    private var cursor:Int = 0
    private mutating func skip() { while index<end && [9,10,13,32].contains(bytes[index]) { index+=1 } }
    private func peek(_ byte:UInt8)->Bool { index<end && bytes[index]==byte }
    private mutating func take(_ byte:UInt8) throws { guard peek(byte) else { throw ScreenReaderFailure.invalidRequest };index+=1 }
    private mutating func string() throws -> String {
        let start=index;try take(34)
        while index<end {
            let byte=bytes[index];index+=1
            if byte==92 { guard index<end else { throw ScreenReaderFailure.invalidRequest };index+=1 }
            else if byte==34 {
                guard let value=try? JSONDecoder().decode(String.self,from:Data(bytes[start..<index])) else { throw ScreenReaderFailure.invalidRequest };return value
            }
        }
        throw ScreenReaderFailure.invalidRequest
    }
    private mutating func integer() throws -> Int {
        let start=index;if peek(45) { index+=1 }
        guard index<end,(48...57).contains(bytes[index]) else { throw ScreenReaderFailure.invalidRequest }
        if peek(48) { index+=1 } else { while index<end && (48...57).contains(bytes[index]) { index+=1 } }
        guard let value=Int(String(decoding:bytes[start..<index],as:UTF8.self)) else { throw ScreenReaderFailure.invalidRequest };return value
    }
}
