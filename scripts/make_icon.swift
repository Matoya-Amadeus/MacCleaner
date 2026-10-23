import AppKit
import CoreGraphics

// 生成 Mac Cleaner 图标：暗色 squircle + 发光蓝色笔画（对齐 App Store 图标的美术语言）。
// 用法：make_icon <variant: m|broom|drive> <out.png> [size]

let args = CommandLine.arguments
guard args.count >= 3 else { print("usage: make_icon <m|broom|drive> <out.png> [size]"); exit(2) }
let variant = args[1]
let outPath = args[2]
let size = CGFloat(Double(args.count > 3 ? args[3] : "1024") ?? 1024)

let colorSpace = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: Int(size), height: Int(size),
                          bitsPerComponent: 8, bytesPerRow: 0, space: colorSpace,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
    exit(1)
}

let s = size
// macOS 图标留白：四周约 8%
let inset = s * 0.085
let rect = CGRect(x: inset, y: inset, width: s - inset * 2, height: s - inset * 2)
// squircle：圆角约 22.5%（Big Sur 之后的比例）
let radius = rect.width * 0.225

let squircle = CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius, transform: nil)

// ① 深色底：上浅下深
ctx.saveGState()
ctx.addPath(squircle)
ctx.clip()
let bg = CGGradient(colorsSpace: colorSpace, colors: [
    CGColor(red: 0.176, green: 0.176, blue: 0.196, alpha: 1),
    CGColor(red: 0.043, green: 0.043, blue: 0.051, alpha: 1),
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: rect.maxY), end: CGPoint(x: 0, y: rect.minY), options: [])

// 顶部一道极淡的高光，营造"玻璃壳"质感
let sheen = CGGradient(colorsSpace: colorSpace, colors: [
    CGColor(red: 1, green: 1, blue: 1, alpha: 0.10),
    CGColor(red: 1, green: 1, blue: 1, alpha: 0.0),
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(sheen,
                       start: CGPoint(x: 0, y: rect.maxY),
                       end: CGPoint(x: 0, y: rect.midY + rect.height * 0.15),
                       options: [])
ctx.restoreGState()

// ② 内描边（1px 亮边，图标边缘不"糊"）
ctx.saveGState()
ctx.addPath(CGPath(roundedRect: rect.insetBy(dx: s * 0.0015, dy: s * 0.0015),
                   cornerWidth: radius, cornerHeight: radius, transform: nil))
ctx.setStrokeColor(CGColor(red: 1, green: 1, blue: 1, alpha: 0.10))
ctx.setLineWidth(s * 0.0025)
ctx.strokePath()
ctx.restoreGState()

// ②.5 环境辉光：笔画背后一团很淡的蓝（参考图里那层 bloom）
ctx.saveGState()
ctx.addPath(squircle)
ctx.clip()
let bloom = CGGradient(colorsSpace: colorSpace, colors: [
    CGColor(red: 0.16, green: 0.47, blue: 1.0, alpha: 0.22),
    CGColor(red: 0.16, green: 0.47, blue: 1.0, alpha: 0.0),
] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(bloom,
                       startCenter: CGPoint(x: rect.midX, y: rect.midY + rect.height * 0.05), startRadius: 0,
                       endCenter: CGPoint(x: rect.midX, y: rect.midY + rect.height * 0.05), endRadius: rect.width * 0.52,
                       options: [])
ctx.restoreGState()

// ③ 笔画样式：渐变蓝 + 外发光
let strokeWidth = s * 0.074
let blueTop = CGColor(red: 0.478, green: 0.741, blue: 1.0, alpha: 1)
let blueMid = CGColor(red: 0.259, green: 0.557, blue: 1.0, alpha: 1)
let blueDeep = CGColor(red: 0.086, green: 0.361, blue: 0.949, alpha: 1)

func withGlow(_ draw: () -> Void) {
    // 外层：大范围、很淡
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: s * 0.11, color: CGColor(red: 0.12, green: 0.42, blue: 1, alpha: 0.35))
    draw()
    ctx.restoreGState()
    // 内层：紧贴笔画的亮光
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: s * 0.045, color: CGColor(red: 0.35, green: 0.62, blue: 1, alpha: 0.55))
    draw()
    ctx.restoreGState()
    draw()
}

func strokeGradient(_ path: CGPath) {
    ctx.saveGState()
    ctx.addPath(path)
    ctx.setLineWidth(strokeWidth)
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)
    ctx.replacePathWithStrokedPath()
    ctx.clip()
    let g = CGGradient(colorsSpace: colorSpace, colors: [blueTop, blueMid, blueDeep] as CFArray,
                       locations: [0, 0.55, 1])!
    ctx.drawLinearGradient(g,
                           start: CGPoint(x: rect.minX, y: rect.maxY),
                           end: CGPoint(x: rect.maxX, y: rect.minY),
                           options: [])
    ctx.restoreGState()
}

// 单位坐标（0…1）→ 画布坐标
func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
    CGPoint(x: rect.minX + rect.width * x, y: rect.minY + rect.height * y)
}

func drawMark() {
    let path = CGMutablePath()
    switch variant {
    case "m":
        // 字母 M：两竖 + 中间 V（与 App Store 的 A 同一套"粗笔画 + 圆头"语言）
        path.move(to: pt(0.20, 0.20))
        path.addLine(to: pt(0.20, 0.80))
        path.move(to: pt(0.20, 0.80))
        path.addLine(to: pt(0.50, 0.42))
        path.addLine(to: pt(0.80, 0.80))
        path.move(to: pt(0.80, 0.80))
        path.addLine(to: pt(0.80, 0.20))
    case "broom":
        // 扫帚：斜柄 + 扇形刷头（清理语义，不依赖首字母）
        path.move(to: pt(0.72, 0.24))
        path.addLine(to: pt(0.40, 0.58))
        path.move(to: pt(0.22, 0.62))
        path.addLine(to: pt(0.58, 0.62))
        path.move(to: pt(0.26, 0.62))
        path.addLine(to: pt(0.30, 0.82))
        path.move(to: pt(0.40, 0.62))
        path.addLine(to: pt(0.42, 0.82))
        path.move(to: pt(0.54, 0.62))
        path.addLine(to: pt(0.54, 0.82))
    default:
        // 磁盘 + 星光：一横一竖的储物盘轮廓 + 右上角四角星
        path.move(to: pt(0.26, 0.34))
        path.addLine(to: pt(0.74, 0.34))
        path.move(to: pt(0.26, 0.34))
        path.addLine(to: pt(0.26, 0.72))
        path.move(to: pt(0.74, 0.34))
        path.addLine(to: pt(0.74, 0.72))
        path.move(to: pt(0.26, 0.72))
        path.addLine(to: pt(0.74, 0.72))
        // 内部横线（盘片）
        path.move(to: pt(0.26, 0.56))
        path.addLine(to: pt(0.74, 0.56))
    }
    withGlow { strokeGradient(path) }

    // 细高光：沿笔画内侧描一道很淡的白，制造"玻璃管"的立体感
    ctx.saveGState()
    ctx.addPath(path)
    ctx.setLineWidth(strokeWidth * 0.34)
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)
    ctx.setStrokeColor(CGColor(red: 1, green: 1, blue: 1, alpha: 0.16))
    ctx.strokePath()
    ctx.restoreGState()
}

// 让笔画居中一点（参考图里标记略偏右下）
ctx.saveGState()
drawMark()
ctx.restoreGState()

// ④ 星光（三种方案都加一颗，呼应"清理后发亮"）
func drawSparkle(center c: CGPoint, radius r: CGFloat, alpha: CGFloat = 0.95) {
    let p = CGMutablePath()
    p.move(to: CGPoint(x: c.x, y: c.y + r))
    p.addQuadCurve(to: CGPoint(x: c.x + r, y: c.y), control: CGPoint(x: c.x + r * 0.18, y: c.y + r * 0.18))
    p.addQuadCurve(to: CGPoint(x: c.x, y: c.y - r), control: CGPoint(x: c.x + r * 0.18, y: c.y - r * 0.18))
    p.addQuadCurve(to: CGPoint(x: c.x - r, y: c.y), control: CGPoint(x: c.x - r * 0.18, y: c.y - r * 0.18))
    p.addQuadCurve(to: CGPoint(x: c.x, y: c.y + r), control: CGPoint(x: c.x - r * 0.18, y: c.y + r * 0.18))
    ctx.saveGState()
    ctx.addPath(p)
    ctx.setFillColor(CGColor(red: 0.72, green: 0.88, blue: 1.0, alpha: alpha))
    ctx.fillPath()
    ctx.restoreGState()
}

var sparkleCenter = pt(0.845, 0.815)
var sparkleRadius = s * 0.042
if variant == "drive" { sparkleCenter = pt(0.80, 0.20); sparkleRadius = s * 0.058 }
if variant == "broom" { sparkleCenter = pt(0.74, 0.22); sparkleRadius = s * 0.05 }
ctx.saveGState()
ctx.setShadow(offset: .zero, blur: s * 0.05, color: CGColor(red: 0.4, green: 0.7, blue: 1, alpha: 0.8))
drawSparkle(center: sparkleCenter, radius: sparkleRadius)
ctx.restoreGState()

guard let image = ctx.makeImage() else { exit(1) }
let rep = NSBitmapImageRep(cgImage: image)
guard let data = rep.representation(using: .png, properties: [:]) else { exit(1) }
try data.write(to: URL(fileURLWithPath: outPath))
print("wrote \(outPath)")
