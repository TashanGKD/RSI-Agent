import Foundation
import Darwin

// AppKit initialization is restricted to explicit chooseWindow. There is no
// automatic permission request, network listener or image persistence.
private struct BoundedLineReader {
    private var pending=Data()
    private var ended=false
    mutating func next() throws -> Data? {
        var line=Data(),overflow=false
        while true {
            if let newline=pending.firstIndex(of:10) {
                let part=pending[..<newline]
                if !overflow && line.count+part.count<=8192 { line.append(part) } else { overflow=true }
                pending.removeSubrange(...newline)
                if overflow { throw ScreenReaderFailure.requestTooLarge };return line
            }
            if !pending.isEmpty {
                if !overflow && line.count+pending.count<=8192 { line.append(pending) } else { overflow=true }
                pending.removeAll(keepingCapacity:true)
                if overflow { throw ScreenReaderFailure.requestTooLarge }
            }
            if ended { if overflow { throw ScreenReaderFailure.requestTooLarge };return line.isEmpty ? nil : line }
            let chunk=try PipeIO.readChunk(from:FileHandle.standardInput)
            if chunk.isEmpty { ended=true } else { pending=chunk }
        }
    }
}
private actor ScreenRequestInput {
    private var reader=BoundedLineReader()
    func next() throws -> Data? { try reader.next() }
}
@main struct ScreenReaderHelper {
    @MainActor private static var parentExitWatch:ScreenReaderParentExitWatch?
    @MainActor static func main() async {
        signal(SIGPIPE,SIG_IGN)
        var coreLimit=rlimit(rlim_cur:0,rlim_max:0);_ = setrlimit(RLIMIT_CORE,&coreLimit)
        guard CommandLine.arguments.dropFirst().elementsEqual(["--serve"]) else {
            try? emit(["schemaVersion":1,"status":"usage","helperBundleId":"local.wechat.collector.screen-reader","usage":"Launch the signed helper app as the native app's private --serve child; no screen is read by default.","permissionRequests":"explicit_native_action_only","inputActions":"unavailable"] as [String:Any]);return
        }
        let startupInstance=UUID().uuidString
        guard let auth=ProcessInfo.processInfo.environment["WECHAT_SCREEN_READER_AUTH"],auth.range(of:#"\A[a-f0-9]{64}\z"#,options:.regularExpression) != nil else {
            try? emit(ScreenResponse.failure(.unauthorized,instance:startupInstance));return
        }
        guard Bundle.main.bundleIdentifier=="local.wechat.collector.screen-reader" else { try? emit(ScreenResponse.failure(.untrustedParent,instance:startupInstance));return }
        let parent:ScreenReaderParent
        do {
            parent=try ScreenReaderParent.establish()
            parentExitWatch=try ScreenReaderParentExitWatch(validatedParentPID:parent.pid)
            try parent.revalidate() // Close the establishment/registration race.
        } catch { try? emit(ScreenResponse.failure(.untrustedParent,instance:startupInstance));return }
        guard #available(macOS 14.2,*) else { try? emit(ScreenResponse.failure(.unsupportedOS,instance:startupInstance));return }
        let engine=ScreenReaderEngine(auth:auth,source:AppleWindowImageSource())
        let input=ScreenRequestInput()
        while true {
            do {
                guard let data=try await input.next() else { return }
                try parent.revalidate()
                let response=await engine.handle(data)
                try parent.revalidate()
                try emit(response)
                if response.fatal { return }
            } catch let error as ScreenReaderFailure {
                engine.invalidateProbe()
                let response=ScreenResponse.failure(error,instance:engine.instance)
                try? emit(response)
                if response.fatal { return }
            } catch { return } // EOF/broken private pipe, never dump OS/user data.
        }
    }
    static func emit(_ response:ScreenResponse) throws {
        let data=try JSONEncoder().encode(response)
        guard data.count<=ScreenResponse.maxEncodedBytes else { try emit(ScreenResponse.failure(.ocrLimit,instance:response.helperInstance,requestId:response.requestId));return }
        try FileHandle.standardOutput.write(contentsOf:data+Data([10]))
    }
    static func emit(_ value:[String:Any]) throws {
        let data=try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]);try FileHandle.standardOutput.write(contentsOf:data+Data([10]))
    }
}
