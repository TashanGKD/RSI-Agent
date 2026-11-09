import Darwin

// Kernel start time shared with the Host's process identity source. No fallback
// to NSRunningApplication.launchDate or wall-clock estimates is permitted.
struct ScreenProcessStart:Equatable {
    let pid:UInt32,seconds:UInt64,microseconds:UInt64
    var unixTime:Double { Double(seconds)+Double(microseconds)/1_000_000 }
    static func read(pid:Int32) throws -> ScreenProcessStart {
        guard pid>1,MemoryLayout<proc_bsdinfo>.size==136,
              MemoryLayout<proc_bsdinfo>.offset(of:\.pbi_pid)==12,
              MemoryLayout<proc_bsdinfo>.offset(of:\.pbi_start_tvsec)==120,
              MemoryLayout<proc_bsdinfo>.offset(of:\.pbi_start_tvusec)==128 else { throw ScreenReaderFailure.targetChanged }
        var info=proc_bsdinfo()
        let count=withUnsafeMutablePointer(to:&info) { pointer in
            proc_pidinfo(pid,PROC_PIDTBSDINFO,0,pointer,Int32(MemoryLayout<proc_bsdinfo>.size))
        }
        guard count==Int32(MemoryLayout<proc_bsdinfo>.size),info.pbi_pid==UInt32(pid),
              info.pbi_start_tvsec>0,info.pbi_start_tvusec<1_000_000 else { throw ScreenReaderFailure.targetChanged }
        return ScreenProcessStart(pid:info.pbi_pid,seconds:info.pbi_start_tvsec,microseconds:info.pbi_start_tvusec)
    }
}
