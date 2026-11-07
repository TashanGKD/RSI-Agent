import Cocoa
import CoreImage

// Encodes the server-provided login URL; never downloads or interprets it.
guard CommandLine.arguments.count == 3 else {
    print("Usage: swift qr.swift PRIVATE_LOGIN_JSON OUTPUT_PNG")
    exit(0)
}
let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
guard let obj = try JSONSerialization.jsonObject(with: data) as? [String:Any],
      let body = obj["data"] as? [String:Any],
      let text = body["qrcode_img_content"] as? String, text.utf8.count < 8192,
      let filter = CIFilter(name:"CIQRCodeGenerator") else { exit(2) }
filter.setValue(text.data(using:.utf8), forKey:"inputMessage")
filter.setValue("M",forKey:"inputCorrectionLevel")
guard let qr = filter.outputImage else { exit(2) }
let scaled = qr.transformed(by:CGAffineTransform(scaleX:8,y:8))
let extent = scaled.extent.insetBy(dx:-32,dy:-32)
let white = CIImage(color:CIColor.white).cropped(to:extent)
let composed = scaled.composited(over:white)
guard let cg = CIContext().createCGImage(composed,from:extent),
      let png = NSBitmapImageRep(cgImage:cg).representation(using:.png,properties:[:]) else { exit(2) }
let output = URL(fileURLWithPath:CommandLine.arguments[2])
try png.write(to:output, options:.withoutOverwriting)
try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:output.path)
print(output.path)
