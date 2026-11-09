import Foundation
import CoreGraphics
import Vision
import CryptoKit

enum LocalWindowOCR {
    static func pixelBounds(_ r:CGRect,width:Int,height:Int) throws -> ScreenBounds {
        try ScreenReaderLimits.validateImage(width:width,height:height)
        guard [r.minX,r.minY,r.width,r.height].allSatisfy({$0.isFinite}),r.width>0,r.height>0,r.minX>=0,r.minY>=0,r.maxX<=1.000001,r.maxY<=1.000001 else { throw ScreenReaderFailure.invalidObservation }
        let left=Double(r.minX)*Double(width),top=max(0,1-Double(r.maxY))*Double(height)
        let right=min(1,Double(r.maxX))*Double(width),bottom=(1-Double(r.minY))*Double(height)
        return ScreenBounds(x:left,y:top,width:right-left,height:bottom-top)
    }
    static func normalize(_ candidates:[OCRCandidate],width:Int,height:Int) throws -> [ScreenWord] {
        try ScreenReaderLimits.validateImage(width:width,height:height)
        guard candidates.count<=ScreenReaderLimits.maxWords else { throw ScreenReaderFailure.ocrLimit }
        var words:[ScreenWord]=[],total=0
        for candidate in candidates {
            guard candidate.confidence.isFinite,(0...1).contains(candidate.confidence) else { throw ScreenReaderFailure.invalidObservation }
            let box=try pixelBounds(candidate.bounds,width:width,height:height)
            guard candidate.confidence>=ScreenReaderLimits.minimumConfidence else { continue }
            let text=candidate.text.trimmingCharacters(in:.whitespacesAndNewlines)
            guard !text.isEmpty else { continue };total+=text.utf8.count
            guard text.utf8.count<=ScreenReaderLimits.maxWordBytes,total<=ScreenReaderLimits.maxTextBytes else { throw ScreenReaderFailure.ocrLimit }
            words.append(ScreenWord(text:text,confidence:candidate.confidence,bounds:box))
        }
        return words.sorted { $0.bounds.y == $1.bounds.y ? $0.bounds.x<$1.bounds.x : $0.bounds.y<$1.bounds.y }
    }
    static func uncertainRegions(_ candidates:[OCRCandidate],width:Int,height:Int) throws -> [ScreenRegion] {
        guard candidates.count<=ScreenReaderLimits.maxWords else { throw ScreenReaderFailure.ocrLimit }
        return try candidates.compactMap { candidate in
            guard candidate.confidence.isFinite,(0...1).contains(candidate.confidence) else { throw ScreenReaderFailure.invalidObservation }
            guard candidate.confidence<ScreenReaderLimits.minimumConfidence || candidate.text.isEmpty else { return nil }
            return ScreenRegion(confidence:candidate.confidence,bounds:try pixelBounds(candidate.bounds,width:width,height:height),reason:candidate.text.isEmpty ? "no_candidate" : "low_confidence")
        }
    }
    static func analyze(_ image:CGImage) throws -> ScreenOCRResult {
        try ScreenReaderLimits.validateImage(width:image.width,height:image.height)
        let request=VNRecognizeTextRequest();request.recognitionLevel = .accurate;request.usesLanguageCorrection=false
        let supported=try request.supportedRecognitionLanguages()
        let languages=["zh-Hans","en-US"].filter{supported.contains($0)}
        guard !languages.isEmpty else { throw ScreenReaderFailure.ocrUnavailable }
        request.recognitionLanguages=languages;request.minimumTextHeight=0.005
        let rectangles=VNDetectRectanglesRequest();rectangles.minimumAspectRatio=0.02;rectangles.maximumAspectRatio=1;rectangles.minimumSize=0.02;rectangles.minimumConfidence=0;rectangles.maximumObservations=65;rectangles.quadratureTolerance=8
        let deadline=DispatchWorkItem{request.cancel();rectangles.cancel()};DispatchQueue.global().asyncAfter(deadline:.now()+8,execute:deadline);defer{deadline.cancel()}
        do { try VNImageRequestHandler(cgImage:image,orientation:.up,options:[:]).perform([request,rectangles]) }
        catch { throw ScreenReaderFailure.ocrUnavailable }
        var candidates:[OCRCandidate]=[],uncertain:[OCRCandidate]=[]
        let observations=request.results ?? []
        guard observations.count<=ScreenReaderLimits.maxWords else { throw ScreenReaderFailure.ocrLimit }
        for observation in observations {
            guard let line=observation.topCandidates(1).first else { uncertain.append(OCRCandidate(text:"",confidence:0,bounds:observation.boundingBox));continue }
            if line.confidence<ScreenReaderLimits.minimumConfidence || line.string.isEmpty {
                // Preserve the uncertain region without disclosing its unreliable text.
                uncertain.append(OCRCandidate(text:line.string.isEmpty ? "" : "uncertain",confidence:line.confidence,bounds:observation.boundingBox));continue
            }
            guard line.string.utf8.count<=ScreenReaderLimits.maxTextBytes else { throw ScreenReaderFailure.ocrLimit }
            var ranges:[Range<String.Index>]=[]
            line.string.enumerateSubstrings(in:line.string.startIndex..<line.string.endIndex,options:.byWords){_,range,_,_ in ranges.append(range)}
            if ranges.isEmpty && !line.string.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty { ranges=[line.string.startIndex..<line.string.endIndex] }
            for range in ranges {
                guard candidates.count<ScreenReaderLimits.maxWords else { throw ScreenReaderFailure.ocrLimit }
                guard let rectangle=try? line.boundingBox(for:range) else { throw ScreenReaderFailure.invalidObservation }
                candidates.append(OCRCandidate(text:String(line.string[range]),confidence:line.confidence,bounds:rectangle.boundingBox))
            }
        }
        let detected=rectangles.results ?? [];guard detected.count<=64 else { throw ScreenReaderFailure.ocrLimit }
        let boxes=try detected.map { observation -> ScreenRectangle in
            guard observation.confidence.isFinite,(0...1).contains(observation.confidence) else { throw ScreenReaderFailure.invalidObservation }
            return ScreenRectangle(confidence:observation.confidence,bounds:try pixelBounds(observation.boundingBox,width:image.width,height:image.height))
        }
        return ScreenOCRResult(words:try normalize(candidates,width:image.width,height:image.height),uncertainRegions:try uncertainRegions(uncertain,width:image.width,height:image.height),rectangles:boxes,fingerprint:try fingerprint(image),pixelWidth:image.width,pixelHeight:image.height)
    }
    static func fingerprint(_ image:CGImage) throws -> String {
        try ScreenReaderLimits.validateImage(width:image.width,height:image.height)
        guard let context=CGContext(data:nil,width:image.width,height:image.height,bitsPerComponent:8,bytesPerRow:image.width*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue),let pixels=context.data else { throw ScreenReaderFailure.imageLimit }
        context.setFillColor(CGColor(gray:1,alpha:1));context.fill(CGRect(x:0,y:0,width:image.width,height:image.height));context.draw(image,in:CGRect(x:0,y:0,width:image.width,height:image.height))
        return withExtendedLifetime(context) {
            // Bind dimensions as well as canonical RGBA bytes. Equal-area blank
            // images with different aspect ratios must not share an identity.
            var hash=SHA256()
            hash.update(data:Data("window-rgba-v1:\(image.width)x\(image.height):".utf8))
            hash.update(data:Data(bytesNoCopy:pixels,count:image.width*image.height*4,deallocator:.none))
            return hash.finalize().map{String(format:"%02x",$0)}.joined()
        }
    }
}
