import Foundation
import CoreGraphics

struct ScreenWindow: Equatable {
    static let applicationPath="/Applications/WeChat.app"
    static let applicationBundleID="com.tencent.xinWeChat"
    let windowID:UInt32
    let pid:Int32
    let bundleID:String
    let bundlePath:String
    let launchTime:Double
    let frame:CGRect
    let layer:Int
    let onScreen:Bool
    var appVersion:String? = nil
    var mainTitleMatches=false
}
enum ScreenTargetPolicy {
    static func isMainWindowCandidate(_ window:ScreenWindow)->Bool {
        window.layer==0 && window.mainTitleMatches &&
        [window.frame.minX,window.frame.minY,window.frame.width,window.frame.height].allSatisfy{$0.isFinite} &&
        window.frame.width>=200 && window.frame.height>=120
    }
    static func select(_ windows:[ScreenWindow],windowID:UInt32?=nil) throws -> ScreenWindow {
        if let id=windowID {
            let matches=windows.filter{$0.windowID==id}
            guard !matches.isEmpty else { throw ScreenReaderFailure.targetNotFound }
            guard matches.count==1 else { throw ScreenReaderFailure.ambiguousTarget }
            return try validateTarget(matches[0])
        }
        let claimed=windows.filter{$0.bundleID==ScreenWindow.applicationBundleID || $0.bundlePath==ScreenWindow.applicationPath}
        for window in claimed {
            guard window.bundleID==ScreenWindow.applicationBundleID,window.bundlePath==ScreenWindow.applicationPath,window.pid>1,window.windowID>0,window.launchTime.isFinite,window.launchTime>0 else { throw ScreenReaderFailure.wrongApplication }
            if window.onScreen && window.layer==0 {
                guard [window.frame.minX,window.frame.minY,window.frame.width,window.frame.height].allSatisfy({$0.isFinite}),window.frame.width>0,window.frame.height>0 else { throw ScreenReaderFailure.targetChanged }
            }
        }
        let visible=claimed.filter{$0.onScreen && $0.layer==0 && $0.frame.width>0 && $0.frame.height>0}
        // The background fallback is only a read target: exact main-title match,
        // unique ordinary window, never a largest-window or arbitrary-title guess.
        let candidates=visible.isEmpty ? claimed.filter{isMainWindowCandidate($0)} : visible
        guard !candidates.isEmpty else { throw ScreenReaderFailure.targetNotFound }
        guard candidates.count==1 else { throw ScreenReaderFailure.ambiguousTarget }
        return try validateTarget(candidates[0])
    }
    private static func validateTarget(_ target:ScreenWindow) throws -> ScreenWindow {
        guard target.bundleID==ScreenWindow.applicationBundleID,target.bundlePath==ScreenWindow.applicationPath,target.pid>1,target.windowID>0,target.launchTime.isFinite,target.launchTime>0 else { throw ScreenReaderFailure.wrongApplication }
        guard target.layer==0 else { throw ScreenReaderFailure.targetNotFound }
        guard [target.frame.origin.x,target.frame.origin.y,target.frame.width,target.frame.height].allSatisfy({$0.isFinite}) else { throw ScreenReaderFailure.targetChanged }
        guard target.frame.width>=200,target.frame.height>=120 else { throw ScreenReaderFailure.targetNotFound }
        guard target.frame.width<=CGFloat(ScreenReaderLimits.maxDimension),target.frame.height<=CGFloat(ScreenReaderLimits.maxDimension) else { throw ScreenReaderFailure.imageLimit }
        try ScreenReaderLimits.validateImage(width:Int(ceil(target.frame.width)),height:Int(ceil(target.frame.height)))
        return target
    }
    static func revalidate(_ expected:ScreenWindow,_ actual:ScreenWindow) throws {
        _ = try select([actual],windowID:actual.windowID);guard expected==actual else { throw ScreenReaderFailure.targetChanged }
    }
    static func listing(_ windows:[ScreenWindow]) throws -> [ScreenWindow] {
        let original=windows.filter{$0.bundleID==ScreenWindow.applicationBundleID && $0.bundlePath==ScreenWindow.applicationPath}
        guard original.count<=64 else { throw ScreenReaderFailure.windowLimit }
        guard Set(original.map{$0.windowID}).count==original.count else { throw ScreenReaderFailure.ambiguousTarget }
        for window in original {
            guard window.windowID>0,window.pid>1,window.launchTime.isFinite,window.launchTime>0,
                  [window.frame.minX,window.frame.minY,window.frame.width,window.frame.height].allSatisfy({$0.isFinite}),window.frame.width>=0,window.frame.height>=0 else { throw ScreenReaderFailure.targetChanged }
        }
        return original
    }
}
enum ScreenReaderLimits {
    static let maxPixels=16_777_216,maxDimension=8192,maxWords=4096,maxWordBytes=512,maxTextBytes=65_536
    static let minimumConfidence:Float=0.75
    static func validateImage(width:Int,height:Int) throws {
        guard width>0,height>0,width<=maxDimension,height<=maxDimension,width<=maxPixels/height else { throw ScreenReaderFailure.imageLimit }
    }
}
enum ScreenDisplayPolicy {
    static func validate(_ windowFrame:CGRect,displays:[CGRect]?) throws {
        guard let displays=displays,!displays.isEmpty,
              displays.allSatisfy({ frame in
                  [frame.minX,frame.minY,frame.maxX,frame.maxY,frame.width,frame.height].allSatisfy{$0.isFinite} && frame.width>0 && frame.height>0
              }) else { throw ScreenReaderFailure.displayContextUnavailable }
        guard [windowFrame.minX,windowFrame.minY,windowFrame.maxX,windowFrame.maxY,windowFrame.width,windowFrame.height].allSatisfy({$0.isFinite}),windowFrame.width>0,windowFrame.height>0 else { throw ScreenReaderFailure.targetChanged }
        guard displays.contains(where:{ display in
            let intersection=windowFrame.intersection(display)
            return !intersection.isNull && intersection.width>0 && intersection.height>0
        }) else { throw ScreenReaderFailure.offDisplay }
    }
}
struct ScreenBounds:Codable,Equatable { let x:Double,y:Double,width:Double,height:Double }
struct ScreenWord:Codable { let text:String,confidence:Float,bounds:ScreenBounds }
struct OCRCandidate { let text:String,confidence:Float,bounds:CGRect }
struct ScreenRegion:Codable { let confidence:Float,bounds:ScreenBounds,reason:String }
struct ScreenRectangle:Encodable { let confidence:Float,bounds:ScreenBounds;let source="VNDetectRectangles" }
struct ScreenOCRResult { let words:[ScreenWord],uncertainRegions:[ScreenRegion],rectangles:[ScreenRectangle],fingerprint:String,pixelWidth:Int,pixelHeight:Int }
struct ScreenOccluder { let windowID:UInt32,pid:Int32,layer:Int,alpha:Double,frame:CGRect }
enum ScreenOcclusionStatus:String,Codable {
 case clear,obscured,unknown
 static func combined(_ observations:[ScreenOcclusionStatus])->ScreenOcclusionStatus {
  if observations.contains(.unknown) { return .unknown }
  return observations.contains(.obscured) ? .obscured : .clear
 }
}
struct ScreenEnumerationDiagnostics:Encodable {
 let candidateCount:Int,onScreenCount:Int,layer0Count:Int,mainWindowCount:Int,displayCount:Int?
 init(windows:[ScreenWindow],displayCount:Int?) {
  let original=windows.filter{$0.bundleID==ScreenWindow.applicationBundleID && $0.bundlePath==ScreenWindow.applicationPath}
  candidateCount=original.count;onScreenCount=original.filter{$0.onScreen}.count;layer0Count=original.filter{$0.layer==0}.count;mainWindowCount=original.filter{ScreenTargetPolicy.isMainWindowCandidate($0)}.count;self.displayCount=displayCount
 }
}
enum ScreenOcclusionPolicy {
 static func assess(_ windowsAbove:[ScreenOccluder],target:ScreenWindow)->ScreenOcclusionStatus {
  var obscured=false
  for window in windowsAbove {
   guard window.windowID>0,window.pid>=0,window.alpha.isFinite,(0...1).contains(window.alpha),[window.frame.minX,window.frame.minY,window.frame.width,window.frame.height].allSatisfy({$0.isFinite}),window.frame.width>=0,window.frame.height>=0 else { return .unknown }
   if window.alpha>0,window.frame.width>0,window.frame.height>0,!window.frame.intersection(target.frame).isEmpty { obscured=true }
  }
  return obscured ? .obscured : .clear
 }
 static func validate(_ windowsAbove:[ScreenOccluder],target:ScreenWindow) throws {
  // A future input consumer must additionally obtain fresh evidence. Read-only
  // single-window capture uses assess(), and never promotes this to input trust.
  guard assess(windowsAbove,target:target) == .clear else { throw ScreenReaderFailure.targetObscured }
 }
}
struct WindowProbe {
    let token:String,target:ScreenWindow,expiresAt:Date
    var selectedWindowID:UInt32?=nil
    func validate(token:String,now:Date) throws -> ScreenWindow {
        guard self.token==token else { throw ScreenReaderFailure.probeRequired }
        guard now<=expiresAt else { throw ScreenReaderFailure.staleProbe };return target
    }
}
