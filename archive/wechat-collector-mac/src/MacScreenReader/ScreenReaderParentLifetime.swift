import Foundation
import Darwin

final class ScreenReaderParentExitWatch {
    private let source:DispatchSourceProcess
    init(validatedParentPID:Int32,onExit:@escaping ()->Void={_exit(0)}) throws {
        // The caller has already verified signature, executable and launch time.
        // Never turn this primitive into an arbitrary-process observer.
        guard validatedParentPID>1,validatedParentPID==getppid() else { throw ScreenReaderFailure.untrustedParent }
        source=DispatchSource.makeProcessSource(identifier:validatedParentPID,eventMask:.exit,queue:DispatchQueue.global(qos:.utility))
        source.setEventHandler(handler:onExit);source.resume()
    }
    deinit {source.cancel()}
}
