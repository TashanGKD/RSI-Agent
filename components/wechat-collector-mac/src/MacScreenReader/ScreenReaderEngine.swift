import Foundation
import AppKit
import CoreGraphics
import CoreVideo
import ApplicationServices
import ScreenCaptureKit

struct ScreenPermissions:Codable { let screenCapture:Bool,accessibility:Bool,eventPosting:Bool }
struct ScreenWindowInfo:Encodable {
    let id:UInt32,pid:Int32,ownerBundleId:String,pointBounds:ScreenBounds,processLaunchTime:Double,appVersion:String?
    init(_ window:ScreenWindow) {
        id=window.windowID;pid=window.pid;ownerBundleId=window.bundleID;processLaunchTime=window.launchTime;appVersion=window.appVersion
        pointBounds=ScreenBounds(x:window.frame.minX,y:window.frame.minY,width:window.frame.width,height:window.frame.height)
    }
}
struct ScreenImageInfo:Encodable { let width:Int,height:Int,sha256:String }
struct ScreenWindowCandidate:Encodable {
    let id:UInt32,pid:Int32,pointBounds:ScreenBounds,layer:Int,onScreen:Bool,mainTitleMatches:Bool
    let sharingState:Int?,alpha:Double?
    init(_ window:ScreenWindow,sharing:ScreenWindowSharingMetadata?) {
        id=window.windowID;pid=window.pid;pointBounds=ScreenBounds(x:window.frame.minX,y:window.frame.minY,width:window.frame.width,height:window.frame.height)
        layer=window.layer;onScreen=window.onScreen;mainTitleMatches=window.mainTitleMatches
        sharingState=sharing?.sharingState;alpha=sharing?.alpha
    }
}
struct ScreenResponse:Encodable {
    static let maxEncodedBytes=6*1024*1024
    let schemaVersion=1
    let helperInstance:String
    let requestId:String?
    let status:String
    var code:ScreenReaderFailure?
    var message:String?
    var permission:ScreenPermissions?
    var diagnostics:ScreenEnumerationDiagnostics?
    var occlusionStatus:ScreenOcclusionStatus?
    var window:ScreenWindowInfo?
    var windowCandidates:[ScreenWindowCandidate]?
    var previewPngBase64:String?
    var previewVisualStats:ScreenPreviewVisualStats?
    var pickerDiagnostics:ScreenPickerDiagnostics?
    var targetToken:String?
    var targetExpiresAt:String?
    var image:ScreenImageInfo?
    var capturedAt:String?
    var words:[ScreenWord]=[]
    var uncertainRegions:[ScreenRegion]=[]
    var rectangles:[ScreenRectangle]=[]
    let coordinateSpace="window_pixels_top_left"
    let windowCoordinateSpace="screen_points_top_left"
    let confidenceScope="line_candidate"
    let minimumConfidence=ScreenReaderLimits.minimumConfidence
    let ocrCoverage="observed_candidates_only"
    let messageImport="not_performed"
    let inputActions="unavailable"
    let screenshotsPersisted=false
    var fatal=false
    static func failure(_ code:ScreenReaderFailure,instance:String,requestId:String?=nil,permission:ScreenPermissions?=nil)->ScreenResponse {
        var response=ScreenResponse(helperInstance:instance,requestId:requestId,status:"blocked")
        response.code=code;response.message=code.message;response.permission=permission
        response.fatal = [.platformTimeout,.pickerTimeout,.untrustedParent,.unauthorized,.requestTooLarge,.unsupportedOS].contains(code)
        return response
    }
}
@MainActor protocol WindowImageSource {
    func requestScreenPermission()->Bool
    func chooseWindow() async throws -> ScreenWindow
    func invalidateChosenWindow()
    func pickerDiagnostics()->ScreenPickerDiagnostics?
    func permissions()->ScreenPermissions
    func windows() async throws -> [ScreenWindow]
    func displayCount()->Int?
    func displayFrames()->[CGRect]?
    func sharingMetadata(_ window:ScreenWindow)->ScreenWindowSharingMetadata?
    func occlusionStatus(_ window:ScreenWindow) throws -> ScreenOcclusionStatus
    func capture(_ window:ScreenWindow) async throws -> CGImage
}
@MainActor final class ScreenReaderEngine {
    let instance=UUID().uuidString
    private let auth:String
    private let source:WindowImageSource
    private var probe:WindowProbe?
    private var pickerWindow:ScreenWindow?
    private var pickerGeneration:UInt64=0
    private var recentRequestIDs:[String]=[]
    private let chooseTimeoutNanoseconds:UInt64
    init(auth:String,source:WindowImageSource,chooseTimeoutNanoseconds:UInt64=120_000_000_000) { self.auth=auth;self.source=source;self.chooseTimeoutNanoseconds=chooseTimeoutNanoseconds }
    func invalidateProbe() { probe=nil;pickerWindow=nil;pickerGeneration &+= 1;source.invalidateChosenWindow() }
    private func occlusionEvidence(_ window:ScreenWindow) throws -> ScreenOcclusionStatus {
        guard window.onScreen else { return .unknown }
        return try source.occlusionStatus(window)
    }
    private func readTarget(diagnostics:inout ScreenEnumerationDiagnostics?,windowID:UInt32?=nil) async throws -> ScreenWindow {
        let windows=try await source.windows()
        diagnostics=ScreenEnumerationDiagnostics(windows:windows,displayCount:source.displayCount())
        let target=try ScreenTargetPolicy.select(windows,windowID:windowID)
        try ScreenDisplayPolicy.validate(target.frame,displays:source.displayFrames())
        return target
    }
    func handle(_ data:Data) async -> ScreenResponse {
        var request:ScreenRequest?,permission:ScreenPermissions?
        var diagnostics:ScreenEnumerationDiagnostics?
        var pickerStage:ScreenPickerStage?
        do {
            let decoded=try ScreenRequest.decode(data);request=decoded;try decoded.authenticate(auth)
            guard !recentRequestIDs.contains(decoded.requestId) else { throw ScreenReaderFailure.invalidRequest }
            recentRequestIDs.append(decoded.requestId);if recentRequestIDs.count>128 { recentRequestIDs.removeFirst() }
            if decoded.action == .requestScreenPermission {
                invalidateProbe()
                let existing=source.permissions()
                if !existing.screenCapture { _ = source.requestScreenPermission() }
                let current=source.permissions()
                var response=ScreenResponse(helperInstance:instance,requestId:decoded.requestId,status:current.screenCapture ? "permission_granted" : "permission_requested")
                response.permission=current;return response
            }
            let permissions=source.permissions();permission=permissions
            guard permissions.screenCapture else { throw ScreenReaderFailure.permissionRequired }
            switch decoded.action {
            case .requestScreenPermission: throw ScreenReaderFailure.invalidRequest
            case .chooseWindow:
                invalidateProbe()
                pickerStage = .pickerStart
                let generation=pickerGeneration
                let result=try await ScreenChooseBudget.run(timeoutNanoseconds:chooseTimeoutNanoseconds) {
                    let picked=try await self.source.chooseWindow()
                    try Task.checkCancellation();pickerStage = .postSelection
                    var localDiagnostics:ScreenEnumerationDiagnostics?
                    let selected=try await self.readTarget(diagnostics:&localDiagnostics,windowID:picked.windowID)
                    try Task.checkCancellation()
                    guard self.pickerGeneration==generation else {throw ScreenReaderFailure.pickerCancelled}
                    try ScreenTargetPolicy.revalidate(picked,selected)
                    return (selected,localDiagnostics)
                }
                guard pickerGeneration==generation else {throw ScreenReaderFailure.pickerCancelled}
                let selected=result.0;diagnostics=result.1;pickerWindow=selected
                let occlusion=try occlusionEvidence(selected)
                let lock=WindowProbe(token:UUID().uuidString,target:selected,expiresAt:Date().addingTimeInterval(10),selectedWindowID:selected.windowID);probe=lock
                var response=ScreenResponse(helperInstance:instance,requestId:decoded.requestId,status:"ready")
                response.permission=permissions;response.window=ScreenWindowInfo(selected);response.targetToken=lock.token
                response.diagnostics=diagnostics;response.occlusionStatus=occlusion
                response.pickerDiagnostics=ScreenPickerDiagnostics(stage:.ready)
                response.targetExpiresAt=ISO8601DateFormatter().string(from:lock.expiresAt);return response
            case .listWindows:
                probe=nil
                let windows=try await source.windows()
                diagnostics=ScreenEnumerationDiagnostics(windows:windows,displayCount:source.displayCount())
                let candidates=try ScreenTargetPolicy.listing(windows)
                var response=ScreenResponse(helperInstance:instance,requestId:decoded.requestId,status:"windows_ready")
                response.permission=permissions;response.diagnostics=diagnostics;response.windowCandidates=candidates.map{ScreenWindowCandidate($0,sharing:source.sharingMetadata($0))}
                return response
            case .probe:
                probe=nil
                if let chosen=pickerWindow,let explicit=decoded.windowId,explicit != chosen.windowID { invalidateProbe() }
                let selectedID=decoded.windowId ?? pickerWindow?.windowID
                let selected=try await readTarget(diagnostics:&diagnostics,windowID:selectedID)
                if let chosen=pickerWindow { try ScreenTargetPolicy.revalidate(chosen,selected) }
                let occlusion=try occlusionEvidence(selected)
                let lock=WindowProbe(token:UUID().uuidString,target:selected,expiresAt:Date().addingTimeInterval(10),selectedWindowID:selectedID);probe=lock
                var response=ScreenResponse(helperInstance:instance,requestId:decoded.requestId,status:"ready")
                response.permission=permissions;response.window=ScreenWindowInfo(selected);response.targetToken=lock.token
                response.diagnostics=diagnostics;response.occlusionStatus=occlusion
                response.targetExpiresAt=ISO8601DateFormatter().string(from:lock.expiresAt);return response
            case .capture,.capturePreview:
                guard let lock=probe,let token=decoded.targetToken else { throw ScreenReaderFailure.probeRequired }
                probe=nil // One shot, including failed capture attempts.
                let expected=try lock.validate(token:token,now:Date())
                let before=try await readTarget(diagnostics:&diagnostics,windowID:lock.selectedWindowID);try ScreenTargetPolicy.revalidate(expected,before)
                let beforeOcclusion=try occlusionEvidence(before)
                let image=try await source.capture(before);let capturedAt=Date()
                let scaleX=Double(image.width)/Double(before.frame.width),scaleY=Double(image.height)/Double(before.frame.height)
                guard scaleX.isFinite,scaleY.isFinite,(1...4).contains(scaleX),abs(scaleX-scaleY)<0.01 else { throw ScreenReaderFailure.targetChanged }
                guard source.permissions().screenCapture else { throw ScreenReaderFailure.permissionRequired }
                let after=try await readTarget(diagnostics:&diagnostics,windowID:lock.selectedWindowID);try ScreenTargetPolicy.revalidate(before,after)
                let afterOcclusion=try occlusionEvidence(after)
                let recognized=try LocalWindowOCR.analyze(image)
                let preview=decoded.action == .capturePreview ? try ScreenPreview.pngBase64(image) : nil
                let visualStats=decoded.action == .capturePreview ? ScreenPreview.visualStats(image) : nil
                let final=try await readTarget(diagnostics:&diagnostics,windowID:lock.selectedWindowID);try ScreenTargetPolicy.revalidate(after,final)
                let finalOcclusion=try occlusionEvidence(final)
                var response=ScreenResponse(helperInstance:instance,requestId:decoded.requestId,status:recognized.words.isEmpty ? "ocr_empty" : "ocr_ready")
                let finalPermissions=source.permissions();guard finalPermissions.screenCapture else { throw ScreenReaderFailure.permissionRequired }
                response.permission=finalPermissions;response.window=ScreenWindowInfo(final)
                response.diagnostics=diagnostics;response.occlusionStatus = .combined([beforeOcclusion,afterOcclusion,finalOcclusion])
                response.image=ScreenImageInfo(width:recognized.pixelWidth,height:recognized.pixelHeight,sha256:recognized.fingerprint)
                let clock=ISO8601DateFormatter();clock.formatOptions=[.withInternetDateTime,.withFractionalSeconds];response.capturedAt=clock.string(from:capturedAt)
                response.words=recognized.words;response.uncertainRegions=recognized.uncertainRegions;response.rectangles=recognized.rectangles
                response.previewPngBase64=preview
                response.previewVisualStats=visualStats
                return response
            }
        } catch let error as ScreenReaderFailure {
            let pickerDiagnostic=pickerStage.map{stage in stage == .postSelection ? ScreenPickerDiagnostics(stage:stage) : source.pickerDiagnostics() ?? ScreenPickerDiagnostics(stage:stage)}
            invalidateProbe();var response=ScreenResponse.failure(error,instance:instance,requestId:request?.requestId,permission:permission);response.diagnostics=diagnostics;response.pickerDiagnostics=pickerDiagnostic;return response
        } catch {
            let pickerDiagnostic=pickerStage.map{stage in stage == .postSelection ? ScreenPickerDiagnostics(stage:stage) : source.pickerDiagnostics() ?? ScreenPickerDiagnostics(stage:stage)}
            invalidateProbe();var response=ScreenResponse.failure(.captureFailed,instance:instance,requestId:request?.requestId,permission:permission);response.diagnostics=diagnostics;response.pickerDiagnostics=pickerDiagnostic;return response
        }
    }
}
// Exactly-once continuation completion bounds SDK calls. A timeout response is
// fatal for this helper instance: the parent must terminate/relaunch the child.
private final class ScreenCompletion<Value>: @unchecked Sendable {
    private let lock=NSLock()
    private var continuation:CheckedContinuation<Value,Error>?
    init(_ continuation:CheckedContinuation<Value,Error>) { self.continuation=continuation }
    func finish(_ result:Result<Value,Error>) {
        lock.lock();let pending=continuation;continuation=nil;lock.unlock();pending?.resume(with:result)
    }
}
@available(macOS 14.2,*) @MainActor final class AppleWindowImageSource:WindowImageSource {
    private var available:[UInt32:SCWindow]=[:]
    private var enumeratedDisplayCount:Int?
    private var enumeratedDisplayFrames:[CGRect]?
    private var pickerBinding:(window:ScreenWindow,filter:SCContentFilter,session:AnyObject)?
    private var pendingPickerSession:AnyObject?
    private var pickerGeneration=UUID()
    private var latestPickerDiagnostics:ScreenPickerDiagnostics?
    func pickerDiagnostics()->ScreenPickerDiagnostics? {latestPickerDiagnostics}
    func invalidateChosenWindow() {
        let previous=pickerBinding,pending=pendingPickerSession;pickerBinding=nil;pendingPickerSession=nil;pickerGeneration=UUID()
        latestPickerDiagnostics=nil
        if #available(macOS 15.2,*),let session=previous?.session as? ScreenSystemWindowPicker { session.releaseSelection() }
        if #available(macOS 15.2,*),let session=pending as? ScreenSystemWindowPicker {session.cancel();session.releaseSelection()}
    }
    func chooseWindow() async throws -> ScreenWindow {
        try Task.checkCancellation()
        invalidateChosenWindow()
        latestPickerDiagnostics=ScreenPickerDiagnostics(stage:.pickerStart)
        guard #available(macOS 15.2,*) else { throw ScreenReaderFailure.unsupportedPickerOS }
        let generation=pickerGeneration
        let session=ScreenSystemWindowPicker(onStartFailure:{[weak self] diagnostic in
            guard let self=self,self.pickerGeneration==generation else {return};self.latestPickerDiagnostics=diagnostic
        });var accepted=false;pendingPickerSession=session
        defer {if pendingPickerSession === session {pendingPickerSession=nil};if !accepted {session.releaseSelection()}}
        let filter=try await session.choose()
        try Task.checkCancellation()
        latestPickerDiagnostics=ScreenPickerDiagnostics(stage:.filterShape)
        guard filter.style == .window,filter.includedWindows.count==1,filter.includedDisplays.isEmpty,filter.includedApplications.isEmpty else {throw ScreenReaderFailure.pickerRejected}
        latestPickerDiagnostics=ScreenPickerDiagnostics(stage:.filterIdentity)
        let windows=try await self.windows()
        let picked=try ScreenPickerPolicy.validate(windows:try filter.includedWindows.map{try windowMetadata($0)},includedDisplayCount:filter.includedDisplays.count,includedApplicationCount:filter.includedApplications.count,windowStyle:filter.style == .window,displays:enumeratedDisplayFrames)
        let current=try ScreenTargetPolicy.select(windows,windowID:picked.windowID)
        try ScreenTargetPolicy.revalidate(picked,current)
        try Task.checkCancellation()
        guard pickerGeneration==generation else {throw ScreenReaderFailure.pickerCancelled}
        pickerBinding=(current,filter,session);accepted=true;return current
    }
    func displayCount()->Int? { enumeratedDisplayCount }
    func displayFrames()->[CGRect]? { enumeratedDisplayFrames }
    func sharingMetadata(_ window:ScreenWindow)->ScreenWindowSharingMetadata? {
        guard window.bundleID==ScreenWindow.applicationBundleID,window.bundlePath==ScreenWindow.applicationPath,window.pid>1 else { return nil }
        let entries=CGWindowListCopyWindowInfo(.optionIncludingWindow,window.windowID) as? [[String:Any]]
        return ScreenWindowSharingMetadata.parse(entries,windowID:window.windowID,pid:window.pid)
    }
    func requestScreenPermission()->Bool { CGRequestScreenCaptureAccess() }
    func permissions()->ScreenPermissions {
        ScreenPermissions(screenCapture:CGPreflightScreenCaptureAccess(),accessibility:AXIsProcessTrusted(),eventPosting:CGPreflightPostEventAccess())
    }
    func windows() async throws -> [ScreenWindow] {
        guard CGPreflightScreenCaptureAccess() else { throw ScreenReaderFailure.permissionRequired }
        let content:SCShareableContent=try await withCheckedThrowingContinuation { continuation in
            let completion=ScreenCompletion<SCShareableContent>(continuation)
            SCShareableContent.getExcludingDesktopWindows(true,onScreenWindowsOnly:false) { value,_ in
                if let value=value { completion.finish(.success(value)) } else { completion.finish(.failure(ScreenReaderFailure.captureFailed)) }
            }
            DispatchQueue.global().asyncAfter(deadline:.now()+8) { completion.finish(.failure(ScreenReaderFailure.platformTimeout)) }
        }
        available=[:];enumeratedDisplayCount=content.displays.count;enumeratedDisplayFrames=content.displays.map{$0.frame};var result:[ScreenWindow]=[]
        for window in content.windows {
            guard let owner=window.owningApplication,owner.bundleIdentifier==ScreenWindow.applicationBundleID else { continue }
            result.append(try windowMetadata(window));available[window.windowID]=window
        }
        return result
    }
    private func windowMetadata(_ window:SCWindow) throws -> ScreenWindow {
        guard let owner=window.owningApplication,owner.bundleIdentifier==ScreenWindow.applicationBundleID else { throw ScreenReaderFailure.wrongApplication }
        guard let running=NSRunningApplication(processIdentifier:owner.processID),!running.isTerminated,let bundle=running.bundleURL else { throw ScreenReaderFailure.targetChanged }
        let path=bundle.standardizedFileURL.resolvingSymlinksInPath().path
        let version=Bundle(url:bundle)?.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String
        let kernelStart=try ScreenProcessStart.read(pid:owner.processID)
        var metadata=ScreenWindow(windowID:window.windowID,pid:owner.processID,bundleID:running.bundleIdentifier ?? "",bundlePath:path,launchTime:kernelStart.unixTime,frame:window.frame,layer:window.windowLayer,onScreen:window.isOnScreen)
        if path==ScreenWindow.applicationPath && metadata.bundleID==ScreenWindow.applicationBundleID { metadata.mainTitleMatches=window.title=="微信" || window.title=="WeChat" }
        metadata.appVersion=version?.prefix(128).description;return metadata
    }
    func occlusionStatus(_ window:ScreenWindow) throws -> ScreenOcclusionStatus {
        guard window.onScreen else { return .unknown }
        // This API reads only the window server's z-order/bounds. It never creates
        // an image, reads titles, or returns metadata of other apps to the caller.
        guard let above=CGWindowListCopyWindowInfo([.optionOnScreenAboveWindow,.optionIncludingWindow,.excludeDesktopElements],window.windowID) as? [[String:Any]] else { return .unknown }
        var evidence:[ScreenOccluder]=[];var foundTarget=false,unknownEvidence=false
        for entry in above {
            guard let id=entry[kCGWindowNumber as String] as? NSNumber else { unknownEvidence=true;continue }
            let pid=entry[kCGWindowOwnerPID as String] as? NSNumber
            let frame=(entry[kCGWindowBounds as String] as? [String:Any]).flatMap{CGRect(dictionaryRepresentation:$0 as CFDictionary)}
            if id.uint32Value==window.windowID {
                guard pid?.int32Value==window.pid,frame==window.frame else { throw ScreenReaderFailure.targetChanged };foundTarget=true;continue
            }
            guard let pid=pid,let frame=frame,let layer=entry[kCGWindowLayer as String] as? NSNumber,let alpha=entry[kCGWindowAlpha as String] as? NSNumber else { unknownEvidence=true;continue }
            evidence.append(ScreenOccluder(windowID:id.uint32Value,pid:pid.int32Value,layer:layer.intValue,alpha:alpha.doubleValue,frame:frame))
        }
        guard foundTarget else { throw ScreenReaderFailure.targetChanged }
        return unknownEvidence ? .unknown : ScreenOcclusionPolicy.assess(evidence,target:window)
    }
    func capture(_ window:ScreenWindow) async throws -> CGImage {
        guard CGPreflightScreenCaptureAccess(),let target=available[window.windowID],target.owningApplication?.processID==window.pid else { throw ScreenReaderFailure.targetChanged }
        guard target.frame==window.frame else { throw ScreenReaderFailure.targetChanged }
        // SCK can assert inside this initializer for a window outside every
        // display. Validate geometry before entering the nonthrowing OS API.
        try ScreenDisplayPolicy.validate(target.frame,displays:enumeratedDisplayFrames)
        let filter:SCContentFilter
        if let binding=pickerBinding {
            do {
                try ScreenTargetPolicy.revalidate(binding.window,window)
                guard #available(macOS 15.2,*) else { throw ScreenReaderFailure.unsupportedPickerOS }
                let included=try ScreenPickerPolicy.validate(windows:try binding.filter.includedWindows.map{try windowMetadata($0)},includedDisplayCount:binding.filter.includedDisplays.count,includedApplicationCount:binding.filter.includedApplications.count,windowStyle:binding.filter.style == .window,displays:enumeratedDisplayFrames)
                try ScreenTargetPolicy.revalidate(window,included)
                filter=binding.filter
            } catch { invalidateChosenWindow();throw error }
        } else { filter=SCContentFilter(desktopIndependentWindow:target) }
        let scale=Double(filter.pointPixelScale),size=filter.contentRect.size
        guard scale.isFinite,(1...4).contains(scale),size.width.isFinite,size.height.isFinite,abs(size.width-window.frame.width)<=1,abs(size.height-window.frame.height)<=1 else { throw ScreenReaderFailure.targetChanged }
        let width=ceil(Double(size.width)*scale),height=ceil(Double(size.height)*scale)
        guard width>0,height>0,width<=Double(ScreenReaderLimits.maxDimension),height<=Double(ScreenReaderLimits.maxDimension) else { throw ScreenReaderFailure.imageLimit }
        try ScreenReaderLimits.validateImage(width:Int(width),height:Int(height))
        let config=SCStreamConfiguration();config.width=Int(width);config.height=Int(height)
        config.pixelFormat=kCVPixelFormatType_32BGRA;config.colorSpaceName=CGColorSpace.sRGB
        config.showsCursor=false;config.capturesAudio=false;config.ignoreShadowsSingleWindow=true;config.includeChildWindows=false
        let image:CGImage=try await withCheckedThrowingContinuation { continuation in
            let completion=ScreenCompletion<CGImage>(continuation)
            SCScreenshotManager.captureImage(contentFilter:filter,configuration:config) { image,_ in
                if let image=image { completion.finish(.success(image)) } else { completion.finish(.failure(ScreenReaderFailure.captureFailed)) }
            }
            DispatchQueue.global().asyncAfter(deadline:.now()+8) { completion.finish(.failure(ScreenReaderFailure.platformTimeout)) }
        }
        guard image.width==config.width,image.height==config.height else { throw ScreenReaderFailure.targetChanged };return image
    }
}
