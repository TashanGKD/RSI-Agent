import Foundation
import Darwin

enum PipeIO {
    // FileHandle.read(upToCount:) may wait to fill its buffer on a live pipe.
    // One POSIX read returns the currently available chunk; callers retain
    // ownership of the handle and assemble/bound their own JSONL records.
    static func readChunk(from handle:FileHandle,maxBytes:Int=4096) throws -> Data {
        guard maxBytes>0,maxBytes<=1_048_576 else { throw POSIXError(.EINVAL) }
        var bytes=Data(count:maxBytes)
        while true {
            let (count,errorCode)=bytes.withUnsafeMutableBytes { buffer -> (Int,Int32) in
                let count=Darwin.read(handle.fileDescriptor,buffer.baseAddress,maxBytes)
                return (count,count<0 ? errno : 0)
            }
            if count>=0 { bytes.count=count;return bytes } // EOF is empty Data.
            if errorCode==EINTR { continue }
            throw POSIXError(POSIXErrorCode(rawValue:errorCode) ?? .EIO)
        }
    }
}
