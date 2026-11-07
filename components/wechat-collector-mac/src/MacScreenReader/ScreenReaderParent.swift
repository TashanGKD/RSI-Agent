import Foundation
import AppKit
import Security
import Darwin

// A stdio helper has no public socket. In addition to a private launch nonce,
// require the currently signed/identified native app to remain its direct parent.
// Local ad-hoc signatures do not establish a publisher identity; production may
// pin a Developer-ID team via ScreenReaderHostTeamIdentifier in the helper plist.
struct ScreenReaderParent {
    let pid:Int32
    let launchTime:TimeInterval
    static let expectedIdentifier="local.wechat.collector.mac"
    static func establish() throws -> ScreenReaderParent {
        let pid=getppid()
        guard pid>1,let running=NSRunningApplication(processIdentifier:pid),!running.isTerminated,
              running.bundleIdentifier==expectedIdentifier,let bundle=running.bundleURL,let executable=running.executableURL,
              executable.standardizedFileURL.resolvingSymlinksInPath()==bundle.appendingPathComponent("Contents/MacOS/WechatCollectorMac").standardizedFileURL.resolvingSymlinksInPath(),
              let launched=running.launchDate else { throw ScreenReaderFailure.untrustedParent }
        var dynamic:SecCode?
        guard SecCodeCopyGuestWithAttributes(nil,[kSecGuestAttributePid as String:pid] as CFDictionary,SecCSFlags(rawValue:0),&dynamic)==errSecSuccess,let dynamic=dynamic,
              SecCodeCheckValidity(dynamic,SecCSFlags(rawValue:0),nil)==errSecSuccess else { throw ScreenReaderFailure.untrustedParent }
        var code:SecStaticCode?,information:CFDictionary?
        guard SecCodeCopyStaticCode(dynamic,SecCSFlags(rawValue:0),&code)==errSecSuccess,let code=code,
              SecCodeCopySigningInformation(code,SecCSFlags(rawValue:kSecCSSigningInformation),&information)==errSecSuccess,
              let fields=information as? [String:Any],fields[kSecCodeInfoIdentifier as String] as? String==expectedIdentifier else { throw ScreenReaderFailure.untrustedParent }
        if let requiredTeam=Bundle.main.object(forInfoDictionaryKey:"ScreenReaderHostTeamIdentifier") as? String,!requiredTeam.isEmpty {
            guard fields[kSecCodeInfoTeamIdentifier as String] as? String==requiredTeam else { throw ScreenReaderFailure.untrustedParent }
        }
        return ScreenReaderParent(pid:pid,launchTime:launched.timeIntervalSince1970)
    }
    func revalidate() throws {
        let current=try Self.establish()
        guard current.pid==pid,current.launchTime==launchTime else { throw ScreenReaderFailure.untrustedParent }
    }
}
