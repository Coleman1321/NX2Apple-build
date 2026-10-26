// The app icon: "nx" in the wordmark's face (SF Pro Bold, tight) and the launcher's cream on black, with the
// selection bar the collection uses under it. Renders a 1024 px master on the macOS icon grid.
// Usage: swift frontend/make_icon.swift <out.png>   (frontend/make_icon.sh makes AppIcon.icns from it)
import AppKit

let size: CGFloat = 1024
let cream = NSColor(red: 1, green: 0.94, blue: 0.84, alpha: 1)
let amber = NSColor(red: 1, green: 0.80, blue: 0.56, alpha: 1)

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let cg = NSGraphicsContext.current!.cgContext

// The tile: 824 px on the 1024 grid, with the system's soft drop shadow
let tile = NSRect(x: 100, y: 100, width: 824, height: 824)
let shape = NSBezierPath(roundedRect: tile, xRadius: 185, yRadius: 185)
cg.saveGState()
cg.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: NSColor.black.withAlphaComponent(0.45).cgColor)
NSColor.black.setFill(); shape.fill()
cg.restoreGState()

cg.saveGState()
shape.addClip()
NSGradient(starting: NSColor(white: 0.115, alpha: 1), ending: NSColor(white: 0.03, alpha: 1))!.draw(in: tile, angle: -90)
// A warm glow behind the letters
let glow = NSGradient(colors: [amber.withAlphaComponent(0.15), amber.withAlphaComponent(0.04), .clear], atLocations: [0, 0.55, 1], colorSpace: .deviceRGB)!
glow.draw(fromCenter: NSPoint(x: 512, y: 470), radius: 0, toCenter: NSPoint(x: 512, y: 470), radius: 470, options: [])

// "nx": its outline, centred on its own glyph bounds, filled with a cream-to-amber gradient
let font = NSFont.systemFont(ofSize: 470, weight: .bold)
let text = NSAttributedString(string: "nx", attributes: [.font: font, .kern: -16])
let line = CTLineCreateWithAttributedString(text)
let glyphs = CGMutablePath()
for run in CTLineGetGlyphRuns(line) as! [CTRun] {
    let count = CTRunGetGlyphCount(run)
    var ids = [CGGlyph](repeating: 0, count: count), positions = [CGPoint](repeating: .zero, count: count)
    CTRunGetGlyphs(run, CFRange(location: 0, length: count), &ids)
    CTRunGetPositions(run, CFRange(location: 0, length: count), &positions)
    let runFont = (CTRunGetAttributes(run) as Dictionary)[kCTFontAttributeName] as! CTFont
    for (glyph, position) in zip(ids, positions) {
        if let path = CTFontCreatePathForGlyph(runFont, glyph, nil) {
            glyphs.addPath(path, transform: CGAffineTransform(translationX: position.x, y: position.y))
        }
    }
}
let box = glyphs.boundingBoxOfPath
let barGap: CGFloat = 58, barHeight: CGFloat = 26
let block = box.height + barGap + barHeight   // letters and bar, centred together
let origin = CGPoint(x: 512 - box.midX, y: 512 - block / 2 + barGap + barHeight - box.minY + 6)
var place = CGAffineTransform(translationX: origin.x, y: origin.y)
let placed = glyphs.copy(using: &place)!
cg.saveGState()
cg.setShadow(offset: CGSize(width: 0, height: -6), blur: 26, color: amber.withAlphaComponent(0.2).cgColor)
cg.addPath(placed); cg.setFillColor(cream.cgColor); cg.fillPath()
cg.restoreGState()
cg.saveGState()
cg.addPath(placed); cg.clip()
NSGradient(starting: cream, ending: amber)!.draw(in: placed.boundingBoxOfPath, angle: -90)
cg.restoreGState()

// The selection bar under the letters
let barWidth = box.width * 0.34
let bar = NSRect(x: 512 - barWidth / 2, y: origin.y + box.minY - barGap - barHeight, width: barWidth, height: barHeight)
cream.setFill(); NSBezierPath(roundedRect: bar, xRadius: barHeight / 2, yRadius: barHeight / 2).fill()

// A hairline on the tile's edge, brighter at the top
cg.restoreGState()
let rim = CGPath(roundedRect: tile.insetBy(dx: 1.5, dy: 1.5), cornerWidth: 183.5, cornerHeight: 183.5, transform: nil)
cg.saveGState()
cg.addPath(rim); cg.setLineWidth(3); cg.replacePathWithStrokedPath(); cg.clip()
NSGradient(starting: NSColor.white.withAlphaComponent(0.22), ending: NSColor.white.withAlphaComponent(0.03))!.draw(in: tile, angle: -90)
cg.restoreGState()

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
