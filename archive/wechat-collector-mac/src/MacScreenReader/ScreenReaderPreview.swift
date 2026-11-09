import Foundation
import CoreGraphics
import ImageIO

struct ScreenPreviewVisualStats:Encodable {
    let sampledAlphaNonzeroFraction:Double,nearWhiteFraction:Double
}
enum ScreenPreview {
    static let maxPngBytes=4*1024*1024
    static func visualStats(_ image:CGImage)->ScreenPreviewVisualStats? {
        guard (try? ScreenReaderLimits.validateImage(width:image.width,height:image.height)) != nil else { return nil }
        let width=min(image.width,64),height=min(image.height,64)
        let format=CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue
        guard let context=CGContext(data:nil,width:width,height:height,bitsPerComponent:8,bytesPerRow:width*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:format),let bytes=context.data else { return nil }
        context.interpolationQuality = .none;context.setBlendMode(.copy)
        context.clear(CGRect(x:0,y:0,width:width,height:height));context.draw(image,in:CGRect(x:0,y:0,width:width,height:height))
        return withExtendedLifetime(context) {
            let pixels=bytes.assumingMemoryBound(to:UInt8.self);var nonzero=0,nearWhite=0
            for index in 0..<(width*height) {
                let alpha=Int(pixels[index*4+3]);guard alpha>0 else { continue };nonzero+=1
                // Channels are premultiplied. Compare unpremultiplied RGB to
                // 250/255 without rounding; transparent pixels are never white.
                if (0..<3).allSatisfy({Int(pixels[index*4+$0])*255>=250*alpha}) { nearWhite+=1 }
            }
            let total=Double(width*height)
            return ScreenPreviewVisualStats(sampledAlphaNonzeroFraction:Double(nonzero)/total,nearWhiteFraction:Double(nearWhite)/total)
        }
    }
    static func pngBase64(_ image:CGImage) throws -> String {
        try ScreenReaderLimits.validateImage(width:image.width,height:image.height)
        let bytes=NSMutableData()
        guard let destination=CGImageDestinationCreateWithData(bytes,"public.png" as CFString,1,nil) else { throw ScreenReaderFailure.captureFailed }
        CGImageDestinationAddImage(destination,image,nil)
        guard CGImageDestinationFinalize(destination) else { throw ScreenReaderFailure.captureFailed }
        guard bytes.length<=maxPngBytes else { throw ScreenReaderFailure.previewLimit }
        return (bytes as Data).base64EncodedString()
    }
}
