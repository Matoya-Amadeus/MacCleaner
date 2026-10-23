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
    CGColor(red: 0.10, green: 0.85, blue: 0.70, alpha: 0.09),
    CGColor(red: 0.10, green: 0.85, blue: 0.70, alpha: 0.0),
] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(bloom,
                       startCenter: CGPoint(x: rect.midX, y: rect.midY + rect.height * 0.05), startRadius: 0,
                       endCenter: CGPoint(x: rect.midX, y: rect.midY + rect.height * 0.05), endRadius: rect.width * 0.52,
                       options: [])
ctx.restoreGState()

// ③ 笔画样式：渐变蓝 + 外发光
var strokeWidthValue = s * 0.074
let strokeWidth = strokeWidthValue
// 青绿：亮青 → 主青 → 深青（用户指定 2026-10-23）
let blueTop = CGColor(red: 0.706, green: 1.000, blue: 0.925, alpha: 1)   // 亮青（高光侧）
let blueMid = CGColor(red: 0.114, green: 0.804, blue: 0.663, alpha: 1)   // 主青
let blueDeep = CGColor(red: 0.024, green: 0.522, blue: 0.427, alpha: 1)  // 深青（暗部）

func withGlow(_ draw: () -> Void) {
    // 外层：大范围、很淡
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: s * 0.11, color: CGColor(red: 0.08, green: 0.80, blue: 0.66, alpha: 0.16))
    draw()
    ctx.restoreGState()
    // 内层：紧贴笔画的亮光
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: s * 0.045, color: CGColor(red: 0.35, green: 0.95, blue: 0.80, alpha: 0.26))
    draw()
    ctx.restoreGState()
    draw()
}

func strokeGradient(_ path: CGPath) {
    ctx.saveGState()
    ctx.addPath(path)
    ctx.setLineWidth(strokeWidthValue)
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

/// 磁盘（照参考图轮廓）：上圆下宽的身形 + 底部指示灯带。轮廓描边、指示条填色。
func drawDisk(withFace: Bool = false) {
    let outline = CGMutablePath()

    // 身形：底边平、两肩圆角、顶边略窄
    outline.move(to: pt(0.200, 0.290))
    outline.addLine(to: pt(0.800, 0.290))
    outline.addQuadCurve(to: pt(0.850, 0.350), control: pt(0.850, 0.290))
    outline.addLine(to: pt(0.850, 0.560))
    outline.addQuadCurve(to: pt(0.715, 0.745), control: pt(0.850, 0.700))
    outline.addLine(to: pt(0.285, 0.745))
    outline.addQuadCurve(to: pt(0.150, 0.560), control: pt(0.150, 0.700))
    outline.addLine(to: pt(0.150, 0.350))
    outline.addQuadCurve(to: pt(0.200, 0.290), control: pt(0.150, 0.290))
    outline.closeSubpath()

    // 指示灯带的分隔线
    outline.move(to: pt(0.160, 0.420))
    outline.addLine(to: pt(0.840, 0.420))

    // 盘身内部：一层很淡的青（8%），让实体感出来，但不抢线稿
    ctx.saveGState()
    ctx.addPath(outline)
    ctx.setFillColor(CGColor(red: 0.114, green: 0.804, blue: 0.663, alpha: 0.09))
    ctx.fillPath()
    ctx.restoreGState()

    let save = strokeWidthValue
    strokeWidthValue = s * 0.045
    withGlow { strokeGradient(outline) }
    strokeWidthValue = save

    // 盘身顶部内阴影：光从上面来，内部上沿压暗一点点
    ctx.saveGState()
    ctx.addPath(outline)
    ctx.clip()
    let innerShadow = CGGradient(colorsSpace: colorSpace, colors: [
        CGColor(red: 0, green: 0, blue: 0, alpha: 0.22),
        CGColor(red: 0, green: 0, blue: 0, alpha: 0.0),
    ] as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(innerShadow,
                           start: CGPoint(x: 0, y: rect.minY + rect.height * 0.93),
                           end: CGPoint(x: 0, y: rect.minY + rect.height * 0.66),
                           options: [])
    ctx.restoreGState()

    // 指示灯：八个小竖条（**填色**，不描边——描边会把它们糊成一块）
    for index in 0..<8 {
        let x = 0.500 + Double(index) * 0.037
        let bar = CGRect(x: rect.minX + rect.width * x,
                         y: rect.minY + rect.height * 0.305,
                         width: rect.width * 0.013,
                         height: rect.height * 0.062)
        let barPath = CGPath(roundedRect: bar, cornerWidth: rect.width * 0.007,
                             cornerHeight: rect.width * 0.007, transform: nil)
        ctx.saveGState()
        ctx.addPath(barPath)
        ctx.setFillColor(blueTop)
        ctx.fillPath()
        ctx.restoreGState()
    }

    guard withFace else { return }

    // 两只圆眼（带一点上高光）
    for centerX in [0.405, 0.595] {
        let radius = rect.width * 0.036
        let center = pt(CGFloat(centerX), 0.590)
        ctx.saveGState()
        ctx.setShadow(offset: .zero, blur: s * 0.02,
                      color: CGColor(red: 0.35, green: 0.95, blue: 0.80, alpha: 0.65))
        ctx.setFillColor(blueTop)
        ctx.fillEllipse(in: CGRect(x: center.x - radius, y: center.y - radius,
                                   width: radius * 2, height: radius * 2))
        ctx.restoreGState()

        // 瞳孔上方一点深色，眼睛才有"看的方向"
        ctx.saveGState()
        ctx.setFillColor(CGColor(red: 0.04, green: 0.30, blue: 0.26, alpha: 0.55))
        ctx.fillEllipse(in: CGRect(x: center.x - radius * 0.42,
                                   y: center.y - radius * 0.30,
                                   width: radius * 0.84, height: radius * 0.84))
        ctx.restoreGState()
    }

    // 小笑弧：从左眼下方轻轻荡到右眼下方
    let smile = CGMutablePath()
    smile.move(to: pt(0.452, 0.512))
    smile.addQuadCurve(to: pt(0.548, 0.512), control: pt(0.500, 0.462))
    ctx.saveGState()
    ctx.addPath(smile)
    ctx.setLineWidth(s * 0.026)
    ctx.setLineCap(.round)
    ctx.setStrokeColor(blueTop)
    ctx.strokePath()
    ctx.restoreGState()
}

/// 磁盘（照参考图轮廓）：上圆下宽的身形 + 底部指示灯带。轮廓描边、指示条填色。

/// v5：整体居中、左右留白；扫帚斜压在磁盘**前面**，中间留一圈空隙（描边挖空）。
/// 扫帚照 emoji 🧹 复刻：细长柄 + 刷箍 + 上窄下宽的毛束。
func drawBuddy() {
    // ── 磁盘（居中偏左一点，给扫帚留视觉重量）──
    let body = CGRect(x: rect.minX + rect.width * 0.245,
                      y: rect.minY + rect.height * 0.435,
                      width: rect.width * 0.450,
                      height: rect.height * 0.270)

    let outline = CGMutablePath()
    outline.move(to: CGPoint(x: body.minX + rect.width * 0.040, y: body.minY))
    outline.addLine(to: CGPoint(x: body.maxX - rect.width * 0.040, y: body.minY))
    outline.addQuadCurve(to: CGPoint(x: body.maxX, y: body.minY + rect.height * 0.048),
                         control: CGPoint(x: body.maxX, y: body.minY))
    outline.addLine(to: CGPoint(x: body.maxX, y: body.maxY - rect.height * 0.120))
    outline.addQuadCurve(to: CGPoint(x: body.maxX - rect.width * 0.090, y: body.maxY),
                         control: CGPoint(x: body.maxX, y: body.maxY - rect.height * 0.040))
    outline.addLine(to: CGPoint(x: body.minX + rect.width * 0.090, y: body.maxY))
    outline.addQuadCurve(to: CGPoint(x: body.minX, y: body.maxY - rect.height * 0.120),
                         control: CGPoint(x: body.minX, y: body.maxY - rect.height * 0.040))
    outline.addLine(to: CGPoint(x: body.minX, y: body.minY + rect.height * 0.048))
    outline.addQuadCurve(to: CGPoint(x: body.minX + rect.width * 0.040, y: body.minY),
                         control: CGPoint(x: body.minX, y: body.minY))

    ctx.saveGState()
    ctx.addPath(outline)
    ctx.setFillColor(CGColor(red: 0.114, green: 0.804, blue: 0.663, alpha: 0.10))
    ctx.fillPath()
    ctx.restoreGState()

    strokeWidthValue = s * 0.040
    withGlow { strokeGradient(outline) }

    // ── 眼睛 "> <"（居中在盘面上）──
    let eyeY = body.midY + rect.height * 0.012
    let eyeW = body.width * 0.100
    let eyeH = body.height * 0.150

    let leftEye = CGMutablePath()
    leftEye.move(to: CGPoint(x: body.minX + body.width * 0.250, y: eyeY + eyeH))
    leftEye.addLine(to: CGPoint(x: body.minX + body.width * 0.250 + eyeW, y: eyeY))
    leftEye.addLine(to: CGPoint(x: body.minX + body.width * 0.250, y: eyeY - eyeH))

    let rightEyeX = body.minX + body.width * 0.640
    let rightEye = CGMutablePath()
    rightEye.move(to: CGPoint(x: rightEyeX, y: eyeY + eyeH))
    rightEye.addLine(to: CGPoint(x: rightEyeX - eyeW, y: eyeY))
    rightEye.addLine(to: CGPoint(x: rightEyeX, y: eyeY - eyeH))

    ctx.saveGState()
    for eye in [leftEye, rightEye] { ctx.addPath(eye) }
    ctx.setLineWidth(s * 0.034)
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)
    ctx.setStrokeColor(blueTop)
    ctx.strokePath()
    ctx.restoreGState()

    // ── 扫帚（emoji 姿态：柄在右上，毛束在左下）──
    let bristleTip = CGPoint(x: rect.minX + rect.width * 0.270, y: rect.minY + rect.height * 0.250)
    let handleTop = CGPoint(x: rect.minX + rect.width * 0.735, y: rect.minY + rect.height * 0.640)
    let angle = atan2(handleTop.y - bristleTip.y, handleTop.x - bristleTip.x)
    let length = hypot(handleTop.x - bristleTip.x, handleTop.y - bristleTip.y)

    // 在"沿柄方向"的局部坐标里画：x 轴朝柄顶
    ctx.saveGState()
    ctx.translateBy(x: bristleTip.x, y: bristleTip.y)
    ctx.rotate(by: angle)

    let w = rect.width                  // 便于按比例写尺寸
    let h = rect.height
    let gap = s * 0.010                 // 与磁盘之间的空隙（细一圈，别像描黑边）

    // 毛束轮廓（局部坐标：x 从 0 向柄方向延伸）
    let bristle = CGMutablePath()
    bristle.move(to: CGPoint(x: w * 0.120, y: -w * 0.032))
    bristle.addLine(to: CGPoint(x: w * 0.120, y: w * 0.032))
    bristle.addLine(to: CGPoint(x: -w * 0.020, y: w * 0.070))
    bristle.addQuadCurve(to: CGPoint(x: -w * 0.020, y: -w * 0.070),
                         control: CGPoint(x: -w * 0.052, y: 0))
    bristle.closeSubpath()

    // 刷箍
    let ferrule = CGRect(x: w * 0.100, y: -w * 0.034, width: w * 0.052, height: w * 0.068)

    // ① 先描一圈背景色，制造"压在磁盘上但留缝"的效果
    ctx.saveGState()
    ctx.addPath(bristle)
    ctx.setLineWidth(gap * 2)
    ctx.setLineJoin(.round)
    ctx.setStrokeColor(CGColor(red: 0.086, green: 0.086, blue: 0.098, alpha: 1))
    ctx.strokePath()
    ctx.addPath(CGPath(roundedRect: ferrule.insetBy(dx: -gap, dy: -gap),
                       cornerWidth: ferrule.height * 0.3, cornerHeight: ferrule.height * 0.3,
                       transform: nil))
    ctx.setFillColor(CGColor(red: 0.086, green: 0.086, blue: 0.098, alpha: 1))
    ctx.fillPath()
    // 柄的缝隙
    let handleGap = CGMutablePath()
    handleGap.move(to: CGPoint(x: w * 0.150, y: 0))
    handleGap.addLine(to: CGPoint(x: length, y: 0))
    ctx.addPath(handleGap)
    ctx.setLineWidth(s * 0.020 + gap * 2)
    ctx.setLineCap(.round)
    ctx.setStrokeColor(CGColor(red: 0.086, green: 0.086, blue: 0.098, alpha: 1))
    ctx.strokePath()
    ctx.restoreGState()

    // ② 柄
    ctx.saveGState()
    let handle = CGMutablePath()
    handle.move(to: CGPoint(x: w * 0.140, y: 0))
    handle.addLine(to: CGPoint(x: length, y: 0))
    ctx.addPath(handle)
    ctx.setLineWidth(s * 0.026)
    ctx.setLineCap(.round)
    ctx.setStrokeColor(blueTop)
    ctx.strokePath()
    ctx.restoreGState()

    // ③ 毛束
    ctx.saveGState()
    ctx.addPath(bristle)
    ctx.setFillColor(blueMid)
    ctx.fillPath()
    ctx.restoreGState()

    // ④ 毛束纹理（三道细线，沿柄方向）
    for offset in [-0.026, 0.0, 0.026] {
        let hair = CGMutablePath()
        hair.move(to: CGPoint(x: w * 0.010, y: CGFloat(offset) * w))
        hair.addLine(to: CGPoint(x: w * 0.100, y: CGFloat(offset) * w * 1.25))
        ctx.saveGState()
        ctx.addPath(hair)
        ctx.setLineWidth(s * 0.009)
        ctx.setLineCap(.round)
        ctx.setStrokeColor(CGColor(red: 0.05, green: 0.26, blue: 0.22, alpha: 0.5))
        ctx.strokePath()
        ctx.restoreGState()
    }

    // ⑤ 刷箍
    ctx.saveGState()
    ctx.addPath(CGPath(roundedRect: ferrule,
                       cornerWidth: ferrule.height * 0.35, cornerHeight: ferrule.height * 0.35,
                       transform: nil))
    ctx.setFillColor(blueTop)
    ctx.fillPath()
    ctx.restoreGState()

    ctx.restoreGState()
}

func drawMark() {
    let path = CGMutablePath()
    if variant == "buddy" { drawBuddy(); return }

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
        drawDisk(withFace: false)
        return
    }
    withGlow { strokeGradient(path) }

    // 细高光：沿笔画内侧描一道很淡的白，制造"玻璃管"的立体感
    ctx.saveGState()
    ctx.addPath(path)
    ctx.setLineWidth(strokeWidthValue * 0.34)
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
    ctx.setFillColor(CGColor(red: 0.80, green: 1.0, blue: 0.94, alpha: alpha))
    ctx.fillPath()
    ctx.restoreGState()
}

var sparkleCenter = pt(0.225, 0.795)
var sparkleRadius = s * 0.030
if variant == "drive" || variant == "disk" { sparkleCenter = pt(0.845, 0.815); sparkleRadius = s * 0.042 }
if variant == "broom" { sparkleCenter = pt(0.74, 0.22); sparkleRadius = s * 0.05 }
ctx.saveGState()
ctx.setShadow(offset: .zero, blur: s * 0.05, color: CGColor(red: 0.35, green: 0.95, blue: 0.80, alpha: 0.35))
drawSparkle(center: sparkleCenter, radius: sparkleRadius)
ctx.restoreGState()

guard let image = ctx.makeImage() else { exit(1) }
let rep = NSBitmapImageRep(cgImage: image)
guard let data = rep.representation(using: .png, properties: [:]) else { exit(1) }
try data.write(to: URL(fileURLWithPath: outPath))
print("wrote \(outPath)")
