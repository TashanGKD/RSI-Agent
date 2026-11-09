import Foundation
import CoreGraphics

// Optional observations only. Sharing state never chooses a capture mechanism
// or grants permission; absent/ambiguous context stays unknown.
struct ScreenWindowSharingMetadata {
    let sharingState:Int?,alpha:Double?
    static func parse(_ entries:[[String:Any]]?,windowID:UInt32,pid:Int32)->ScreenWindowSharingMetadata? {
        guard windowID>0,pid>1,let entries=entries else { return nil }
        let matching=entries.filter{integer($0[kCGWindowNumber as String])==Int(windowID) && integer($0[kCGWindowOwnerPID as String])==Int(pid)}
        guard matching.count==1,let entry=matching.first else { return nil }
        let state=integer(entry[kCGWindowSharingState as String]).flatMap{Int32(exactly:$0)}.map{Int($0)}
        var alpha:Double?
        if let number=number(entry[kCGWindowAlpha as String]),number.doubleValue.isFinite,(0...1).contains(number.doubleValue) { alpha=number.doubleValue }
        guard state != nil || alpha != nil else { return nil }
        return ScreenWindowSharingMetadata(sharingState:state,alpha:alpha)
    }
    private static func number(_ value:Any?)->NSNumber? {
        guard let value=value as? NSNumber,CFGetTypeID(value) != CFBooleanGetTypeID() else { return nil };return value
    }
    private static func integer(_ value:Any?)->Int? {
        guard let value=number(value) else { return nil };return Int(exactly:value.doubleValue)
    }
}
