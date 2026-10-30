import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count > 1 else {
    fputs("usage: read-plan-text image\n", stderr)
    exit(2)
}

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let data = try? Data(contentsOf: url),
      let image = NSImage(data: data) else {
    fputs("could not open image\n", stderr)
    exit(1)
}

var proposed = NSRect(origin: .zero, size: image.size)
guard let cg = image.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else {
    fputs("could not read pixels\n", stderr)
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("vision: \(error)\n", stderr)
    exit(1)
}

var rows: [[String: Any]] = []
for observation in request.results ?? [] {
    guard let best = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    rows.append([
        "text": best.string,
        "x": box.origin.x,
        "y": box.origin.y,
        "w": box.size.width,
        "h": box.size.height,
        "confidence": best.confidence,
    ])
}

let output = try JSONSerialization.data(withJSONObject: rows, options: [])
FileHandle.standardOutput.write(output)
