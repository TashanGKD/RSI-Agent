import Foundation
import AppKit
import ScreenCaptureKit

enum ScreenPickerStage:String,Codable {
    case pickerStart="picker_start",filterShape="filter_shape",filterIdentity="filter_identity",postSelection="post_selection",ready
}
struct ScreenPickerDiagnostics:Encodable {
    let stage:ScreenPickerStage
    private(set) var osErrorDomain:String?
    private(set) var osErrorCode:Int?
    init(stage:ScreenPickerStage) {self.stage=stage}
    static func startFailure(domain:String,code:Int)->ScreenPickerDiagnostics {
        var result=ScreenPickerDiagnostics(stage:.pickerStart)
        // Descriptions and userInfo are never read. Malformed OS domains are
        // omitted rather than displayed; code presence marks a real callback.
        if domain.utf8.count<=128,domain.range(of:#"\A[A-Za-z0-9_.-]{1,128}\z"#,options:.regularExpression) != nil {result.osErrorDomain=domain}
        result.osErrorCode=code;return result
    }
}
enum ScreenPickerPolicy {
    static func excludedBundleIDs(_ identifiers:[String?])->[String] {
        Array(Set(identifiers.compactMap{$0}.filter{!$0.isEmpty && $0 != ScreenWindow.applicationBundleID})).sorted()
    }
    static func validate(windows:[ScreenWindow],includedDisplayCount:Int,includedApplicationCount:Int,windowStyle:Bool,displays:[CGRect]?) throws -> ScreenWindow {
        guard windowStyle,includedDisplayCount==0,includedApplicationCount==0,windows.count==1 else { throw ScreenReaderFailure.pickerRejected }
        let window=try ScreenTargetPolicy.select(windows,windowID:windows[0].windowID)
        try ScreenDisplayPolicy.validate(window.frame,displays:displays)
        return window
    }
}

// Testable exactly-once lifecycle. The production adapter owns all OS/UI access;
// synthetic tests use ordinary values and closures, never a real picker.
@MainActor final class ScreenPickerWait<Value> {
    private var continuation:CheckedContinuation<Value,Error>?
    private var timeout:Task<Void,Never>?
    private var cleanup:(()->Void)?
    private var started=false
    func wait(timeoutNanoseconds:UInt64=120_000_000_000,start:(@escaping (Result<Value,ScreenReaderFailure>)->Void)->Void,cleanup:@escaping ()->Void) async throws -> Value {
        guard !started else { throw ScreenReaderFailure.pickerRejected };started=true
        return try await withTaskCancellationHandler(operation:{
            try await withCheckedThrowingContinuation { continuation in
                self.continuation=continuation;self.cleanup=cleanup
                if Task.isCancelled { finish(.failure(.pickerCancelled));return }
                timeout=Task { @MainActor [weak self] in
                    do { try await Task.sleep(nanoseconds:timeoutNanoseconds) } catch { return }
                    self?.finish(.failure(.pickerTimeout))
                }
                start { [weak self] result in self?.finish(result) }
            }
        },onCancel:{ Task { @MainActor in self.finish(.failure(.pickerCancelled)) } })
    }
    func finish(_ result:Result<Value,ScreenReaderFailure>) {
        guard let pending=continuation else { return };continuation=nil
        timeout?.cancel();timeout=nil
        let release=cleanup;cleanup=nil;release?()
        switch result { case .success(let value):pending.resume(returning:value);case .failure(let error):pending.resume(throwing:error) }
    }
}
@MainActor enum ScreenChooseBudget {
    static func run<Value>(timeoutNanoseconds:UInt64,operation:@escaping @MainActor () async throws -> Value) async throws -> Value {
        let waiter=ScreenPickerWait<Value>();var pending:Task<Void,Never>?
        return try await waiter.wait(timeoutNanoseconds:timeoutNanoseconds,start:{complete in
            pending=Task { @MainActor in
                do {try Task.checkCancellation();let value=try await operation();try Task.checkCancellation();complete(.success(value))}
                catch let error as ScreenReaderFailure {complete(.failure(error))}
                catch is CancellationError {complete(.failure(.pickerCancelled))}
                catch {complete(.failure(.captureFailed))}
            }
        },cleanup:{pending?.cancel();pending=nil})
    }
}

@available(macOS 15.2,*) @MainActor final class ScreenSystemWindowPicker:NSObject,SCContentSharingPickerObserver {
    private let waiter=ScreenPickerWait<SCContentFilter>()
    private var result:((Result<SCContentFilter,ScreenReaderFailure>)->Void)?
    private var eventPump:Task<Void,Never>?
    private var selected=false
    private static var appPrepared=false
    private static var activeOwner:UUID?
    private let identity=UUID()
    private let onStartFailure:(ScreenPickerDiagnostics)->Void
    init(onStartFailure:@escaping (ScreenPickerDiagnostics)->Void={_ in}) {
        self.onStartFailure=onStartFailure;super.init()
    }
    func choose() async throws -> SCContentFilter {
        try Task.checkCancellation()
        // This method is reached only after authenticated explicit native-menu
        // intent. No default/probe/capture path initializes NSApplication.
        let app=NSApplication.shared
        if !Self.appPrepared { app.setActivationPolicy(.accessory);app.finishLaunching();Self.appPrepared=true }
        let picker=SCContentSharingPicker.shared
        return try await waiter.wait(start:{ completion in
            self.result=completion
            Self.activeOwner=self.identity
            var configuration=SCContentSharingPickerConfiguration()
            configuration.allowedPickerModes=[.singleWindow]
            configuration.allowsChangingSelectedContent=false
            configuration.excludedBundleIDs=ScreenPickerPolicy.excludedBundleIDs(NSWorkspace.shared.runningApplications.map{$0.bundleIdentifier})
            picker.defaultConfiguration=configuration;picker.maximumStreamCount=1
            picker.add(self);picker.isActive=true
            self.eventPump=Task { @MainActor [weak self] in
                while !Task.isCancelled,self?.result != nil {
                    // Share one future deadline across the whole batch so
                    // AppKit can service run-loop sources while waiting. This
                    // is a bounded run-loop hypothesis pending live UI proof.
                    let batchDeadline=Date().addingTimeInterval(0.01)
                    for _ in 0..<32 {
                        guard let event=app.nextEvent(matching:.any,until:batchDeadline,inMode:.default,dequeue:true) else { break }
                        app.sendEvent(event)
                    }
                    app.updateWindows()
                    do { try await Task.sleep(nanoseconds:10_000_000) } catch { return }
                }
            }
            app.activate(ignoringOtherApps:true)
            picker.present(using:.window)
        },cleanup:{
            self.result=nil;self.eventPump?.cancel();self.eventPump=nil
            picker.remove(self)
            if !self.selected { self.releaseSelection() }
        })
    }
    func cancel() { waiter.finish(.failure(.pickerCancelled)) }
    func releaseSelection() {
        guard Self.activeOwner==identity else { return }
        Self.activeOwner=nil;SCContentSharingPicker.shared.isActive=false
    }
    nonisolated func contentSharingPicker(_ picker:SCContentSharingPicker,didCancelFor stream:SCStream?) {
        Task { @MainActor [weak self] in self?.result?(.failure(.pickerCancelled)) }
    }
    nonisolated func contentSharingPicker(_ picker:SCContentSharingPicker,didUpdateWith filter:SCContentFilter,for stream:SCStream?) {
        Task { @MainActor [weak self] in
            guard stream==nil else { self?.result?(.failure(.pickerRejected));return }
            self?.selected=true
            self?.result?(.success(filter))
        }
    }
    nonisolated func contentSharingPickerStartDidFailWithError(_ error:Error) {
        let osError=error as NSError
        let diagnostic=ScreenPickerDiagnostics.startFailure(domain:osError.domain,code:osError.code)
        Task { @MainActor [weak self] in
            guard let self=self,let complete=self.result else {return}
            self.onStartFailure(diagnostic);complete(.failure(.pickerRejected))
        }
    }
}
