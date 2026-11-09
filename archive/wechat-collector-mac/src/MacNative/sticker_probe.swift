import Foundation
import CoreGraphics
import ImageIO
import Darwin

enum StickerProbeFailure:Error {case invalidImage,limit}
struct StickerProbeResult:Encodable {
    let status="ready"
    let mime:String,width:Int,height:Int,frames:Int,thumbnailPngBase64:String
}
enum StickerProbe {
    static let maxBytes=8*1024*1024,maxFramePixels=16_000_000,maxTotalPixels=64_000_000,maxFrames=300
    static func validate(_ sizes:[CGSize]) throws {
        guard !sizes.isEmpty,sizes.count<=maxFrames else {throw StickerProbeFailure.limit}
        var total=0
        for size in sizes {
            guard size.width.isFinite,size.height.isFinite,size.width>=1,size.height>=1,
                  size.width.rounded(.down)==size.width,size.height.rounded(.down)==size.height,
                  size.width<=Double(maxFramePixels),size.height<=Double(maxFramePixels) else {throw StickerProbeFailure.limit}
            let width=Int(size.width),height=Int(size.height)
            guard width<=maxFramePixels/height else {throw StickerProbeFailure.limit}
            let pixels=width*height
            guard total<=maxTotalPixels-pixels else {throw StickerProbeFailure.limit};total+=pixels
        }
        // Preserve the original GIF canvas * frame-count memory budget too.
        let first=sizes[0]
        guard Int(first.width)*Int(first.height)<=maxTotalPixels/sizes.count else {throw StickerProbeFailure.limit}
    }
    static func inspect(_ bytes:Data) throws -> StickerProbeResult {
        guard !bytes.isEmpty,bytes.count<=maxBytes else {throw StickerProbeFailure.limit}
        let mime:String
        if bytes.starts(with:[137,80,78,71,13,10,26,10]) {mime="image/png"}
        else if bytes.starts(with:[255,216,255]) {mime="image/jpeg"}
        else if bytes.starts(with:Data("GIF8".utf8)) {mime="image/gif"}
        else if bytes.count>=12,bytes.prefix(4)==Data("RIFF".utf8),bytes[8..<12]==Data("WEBP".utf8) {mime="image/webp"}
        else {throw StickerProbeFailure.invalidImage}
        let options=[kCGImageSourceShouldCache:false] as CFDictionary
        guard let source=CGImageSourceCreateWithData(bytes as CFData,options),CGImageSourceGetStatus(source) == .statusComplete else {throw StickerProbeFailure.invalidImage}
        let count=CGImageSourceGetCount(source)
        guard count>0,count<=maxFrames else {throw StickerProbeFailure.limit}
        var sizes:[CGSize]=[]
        for index in 0..<count {
            guard let properties=CGImageSourceCopyPropertiesAtIndex(source,index,options) as? [CFString:Any],
                  let width=properties[kCGImagePropertyPixelWidth] as? NSNumber,CFGetTypeID(width) != CFBooleanGetTypeID(),
                  let height=properties[kCGImagePropertyPixelHeight] as? NSNumber,CFGetTypeID(height) != CFBooleanGetTypeID() else {throw StickerProbeFailure.invalidImage}
            sizes.append(CGSize(width:width.doubleValue,height:height.doubleValue))
        }
        try validate(sizes)
        let thumbnailOptions=[kCGImageSourceCreateThumbnailFromImageAlways:true,kCGImageSourceThumbnailMaxPixelSize:160,kCGImageSourceCreateThumbnailWithTransform:true,kCGImageSourceShouldCacheImmediately:true] as CFDictionary
        guard let image=CGImageSourceCreateThumbnailAtIndex(source,0,thumbnailOptions),image.width>0,image.height>0,max(image.width,image.height)<=160 else {throw StickerProbeFailure.invalidImage}
        let data=NSMutableData()
        guard let destination=CGImageDestinationCreateWithData(data,"public.png" as CFString,1,nil) else {throw StickerProbeFailure.invalidImage}
        CGImageDestinationAddImage(destination,image,nil)
        guard CGImageDestinationFinalize(destination),data.length<=1024*1024 else {throw StickerProbeFailure.limit}
        return StickerProbeResult(mime:mime,width:Int(sizes[0].width),height:Int(sizes[0].height),frames:count,thumbnailPngBase64:(data as Data).base64EncodedString())
    }
}

#if STICKER_PROBE_SYNTHETIC
@main enum StickerProbeSynthetic {
    static func main() throws {
        func check(_ value:Bool,_ reason:String){if !value{fatalError(reason)}}
        func refused(_ body:() throws->Void){do{try body();fatalError("Expected sticker rejection")}catch{}}
        func generatedGIF(_ count:Int)->Data {
            let context=CGContext(data:nil,width:320,height:64,bitsPerComponent:8,bytesPerRow:320*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
            context.setFillColor(CGColor(gray:0.5,alpha:1));context.fill(CGRect(x:0,y:0,width:320,height:64))
            let bytes=NSMutableData(),destination=CGImageDestinationCreateWithData(bytes,"com.compuserve.gif" as CFString,count,nil)!
            for _ in 0..<count {CGImageDestinationAddImage(destination,context.makeImage()!,[kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:0.1]] as CFDictionary)}
            check(CGImageDestinationFinalize(destination),"Synthetic GIF generation failed");return bytes as Data
        }
        let gif=generatedGIF(2),result=try StickerProbe.inspect(gif)
        check(result.frames==2&&result.mime=="image/gif"&&result.width==320&&result.height==64,"Animated source metadata changed")
        let thumbnail=Data(base64Encoded:result.thumbnailPngBase64)!,source=CGImageSourceCreateWithData(thumbnail as CFData,nil)!,image=CGImageSourceCreateImageAtIndex(source,0,nil)!
        check(image.width==160&&image.height==32,"Inline thumbnail does not preserve 160px longest edge")
        _ = try StickerProbe.inspect(generatedGIF(300))
        refused{_ = try StickerProbe.inspect(generatedGIF(301))}
        try StickerProbe.validate([CGSize(width:4000,height:4000)])
        try StickerProbe.validate(Array(repeating:CGSize(width:4000,height:4000),count:4))
        refused{try StickerProbe.validate([CGSize(width:4001,height:4000)])}
        refused{try StickerProbe.validate(Array(repeating:CGSize(width:4000,height:4000),count:5))}
        refused{try StickerProbe.validate([])}
        refused{try StickerProbe.validate([CGSize(width:Double.nan,height:1)])}
        refused{_ = try StickerProbe.inspect(Data("not an image".utf8))}
        refused{_ = try StickerProbe.inspect(gif.prefix(10))}
        refused{_ = try StickerProbe.inspect(Data(repeating:0,count:StickerProbe.maxBytes+1))}
        print("PASS: generated sticker GIF frames, 160px thumbnail, 300/16M/64M limits, malformed and byte budgets; no UI or network")
    }
}
#else
@main enum StickerProbeMain {
    static func main() {
        signal(SIGPIPE,SIG_IGN)
        var limit=rlimit(rlim_cur:0,rlim_max:0);_ = setrlimit(RLIMIT_CORE,&limit)
        guard CommandLine.arguments.dropFirst().elementsEqual(["--inspect"]) else {emit(["status":"usage","usage":"--inspect: bounded image bytes on private stdin; no file/UI/network access"]);return}
        do {
            var bytes=Data(),buffer=[UInt8](repeating:0,count:16384)
            while true {
                let count=Darwin.read(STDIN_FILENO,&buffer,buffer.count)
                if count<0 {if errno==EINTR{continue};throw StickerProbeFailure.invalidImage}
                if count==0 {break}
                guard bytes.count<=StickerProbe.maxBytes-count else {throw StickerProbeFailure.limit}
                bytes.append(contentsOf:buffer.prefix(count))
            }
            let data=try JSONEncoder().encode(StickerProbe.inspect(bytes));try FileHandle.standardOutput.write(contentsOf:data+Data([10]))
        } catch {emit(["status":"missing","code":"invalid_or_oversized_sticker"])}
    }
    static func emit(_ value:[String:String]){if let data=try? JSONSerialization.data(withJSONObject:value){try? FileHandle.standardOutput.write(contentsOf:data+Data([10]))}}
}
#endif
