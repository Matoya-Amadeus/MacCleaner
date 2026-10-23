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
    CGColor(red: 0.10, green: 0.85, blue: 0.70, alpha: 0.20),
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
    ctx.setShadow(offset: .zero, blur: s * 0.11, color: CGColor(red: 0.08, green: 0.80, blue: 0.66, alpha: 0.35))
    draw()
    ctx.restoreGState()
    // 内层：紧贴笔画的亮光
    ctx.saveGState()
    ctx.setShadow(offset: .zero, blur: s * 0.045, color: CGColor(red: 0.35, green: 0.95, blue: 0.80, alpha: 0.55))
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

/// 拟人版：五官长在盘体上（眼睛＝圆形接口，嘴＝带描边的散热槽），
/// 右下伸出一只小手握扫帚。构图刻意留白：脸在左中，扫帚收在右下，互不抢。
func drawBuddy() {
    let body = CGRect(x: rect.minX + rect.width * 0.105,
                      y: rect.minY + rect.height * 0.320,
                      width: rect.width * 0.615,
                      height: rect.height * 0.385)

    // ── 盘体 ──
    let outline = CGMutablePath()
    outline.move(to: CGPoint(x: body.minX + rect.width * 0.045, y: body.minY))
    outline.addLine(to: CGPoint(x: body.maxX - rect.width * 0.045, y: body.minY))
    outline.addQuadCurve(to: CGPoint(x: body.maxX, y: body.minY + rect.height * 0.060),
                         control: CGPoint(x: body.maxX, y: body.minY))
    outline.addLine(to: CGPoint(x: body.maxX, y: body.maxY - rect.height * 0.165))
    outline.addQuadCurve(to: CGPoint(x: body.maxX - rect.width * 0.120, y: body.maxY),
                         control: CGPoint(x: body.maxX, y: body.maxY - rect.height * 0.050))
    outline.addLine(to: CGPoint(x: body.minX + rect.width * 0.120, y: body.maxY))
    outline.addQuadCurve(to: CGPoint(x: body.minX, y: body.maxY - rect.height * 0.165),
                         control: CGPoint(x: body.minX, y: body.maxY - rect.height * 0.050))
    outline.addLine(to: CGPoint(x: body.minX, y: body.minY + rect.height * 0.060))
    outline.addQuadCurve(to: CGPoint(x: body.minX + rect.width * 0.045, y: body.minY),
                         control: CGPoint(x: body.minX, y: body.minY))

    ctx.saveGState()
    ctx.addPath(outline)
    ctx.setFillColor(CGColor(red: 0.114, green: 0.804, blue: 0.663, alpha: 0.10))
    ctx.fillPath()
    ctx.restoreGState()

    let save = strokeWidthValue
    strokeWidthValue = s * 0.045
    withGlow { strokeGradient(outline) }
    strokeWidthValue = save

    // ── 表情：一只闭眼（wink）+ 一只圆形接口，不画嘴 ──
    // 左眼：闭眼的弧线（读作"眨眼"，比画笑脸克制得多）
    let winkY = body.minY + body.height * 0.650
    let wink = CGMutablePath()
    wink.move(to: CGPoint(x: body.minX + body.width * 0.245, y: winkY))
    wink.addQuadCurve(to: CGPoint(x: body.minX + body.width * 0.365, y: winkY),
                      control: CGPoint(x: body.minX + body.width * 0.305, y: winkY + rect.height * 0.040))
    ctx.saveGState()
    ctx.addPath(wink)
    ctx.setLineWidth(s * 0.023)
    ctx.setLineCap(.round)
    ctx.setStrokeColor(blueTop)
    ctx.strokePath()
    ctx.restoreGState()

    // 右眼：圆形接口（外环 + 挖空 + 中心灯）
    let eyeCenter = CGPoint(x: body.minX + body.width * 0.585, y: winkY + rect.height * 0.004)
    let outer = rect.width * 0.050

    ctx.saveGState()
    ctx.addEllipse(in: CGRect(x: eyeCenter.x - outer, y: eyeCenter.y - outer,
                              width: outer * 2, height: outer * 2))
    ctx.setLineWidth(s * 0.021)
    ctx.setStrokeColor(blueMid)
    ctx.strokePath()
    ctx.restoreGState()

    ctx.saveGState()
    let inner = outer - s * 0.015
    ctx.addEllipse(in: CGRect(x: eyeCenter.x - inner, y: eyeCenter.y - inner,
                              width: inner * 2, height: inner * 2))
    ctx.setFillColor(CGColor(red: 0.050, green: 0.165, blue: 0.145, alpha: 1))
    ctx.fillPath()
    ctx.restoreGState()

    ctx.saveGState()
    let pupil = outer * 0.42
    ctx.setShadow(offset: .zero, blur: s * 0.020,
                  color: CGColor(red: 0.35, green: 0.95, blue: 0.80, alpha: 0.75))
    ctx.addEllipse(in: CGRect(x: eyeCenter.x - pupil, y: eyeCenter.y - pupil,
                              width: pupil * 2, height: pupil * 2))
    ctx.setFillColor(blueTop)
    ctx.fillPath()
    ctx.restoreGState()

    // ── 指示灯：右下五条 ──
    for index in 0..<5 {
        let bar = CGRect(x: body.minX + body.width * (0.470 + CGFloat(index) * 0.062),
                         y: body.minY + body.height * 0.150,
                         width: rect.width * 0.013, height: rect.height * 0.062)
        ctx.saveGState()
        ctx.addPath(CGPath(roundedRect: bar, cornerWidth: rect.width * 0.0065,
                           cornerHeight: rect.width * 0.0065, transform: nil))
        ctx.setFillColor(blueTop)
        ctx.fillPath()
        ctx.restoreGState()
    }

    // ── 小手 + 扫帚（收在右下，不越过盘顶）──
    let handCenter = CGPoint(x: body.maxX + rect.width * 0.058,
                             y: body.minY + body.height * 0.470)
    let handRadius = rect.width * 0.040

    // 手臂：从盘体侧壁连到手
    let arm = CGMutablePath()
    arm.move(to: CGPoint(x: body.maxX - rect.width * 0.030, y: body.minY + body.height * 0.415))
    arm.addLine(to: handCenter)
    ctx.saveGState()
    ctx.addPath(arm)
    ctx.setLineWidth(s * 0.040)
    ctx.setLineCap(.round)
    ctx.setStrokeColor(blueMid)
    ctx.strokePath()
    ctx.restoreGState()

    // 扫帚柄：穿过手掌，向下右延伸
    let handleTop = CGPoint(x: handCenter.x + rect.width * 0.010, y: handCenter.y + rect.height * 0.170)
    let handleBottom = CGPoint(x: handCenter.x + rect.width * 0.075, y: handCenter.y - rect.height * 0.175)
    ctx.saveGState()
    let handle = CGMutablePath()
    handle.move(to: handleTop)
    handle.addLine(to: handleBottom)
    ctx.addPath(handle)
    ctx.setLineWidth(s * 0.016)
    ctx.setLineCap(.round)
    ctx.setStrokeColor(blueTop)
    ctx.strokePath()
    ctx.restoreGState()

    // 刷毛：从柄下端散开（朝右下扫）
    for index in 0..<5 {
        let t = CGFloat(index) / 4
        let angle = CGFloat.pi * (-0.58 + 0.62 * t)          // 右下扇面（扫地方向）
        let length = rect.width * (0.105 + 0.020 * (1 - abs(t - 0.5) * 2))
        let tip = CGPoint(x: handleBottom.x + cos(angle) * length * 0.55 - rect.width * 0.020,
                          y: handleBottom.y + sin(angle) * length)
        let hair = CGMutablePath()
        hair.move(to: handleBottom)
        hair.addLine(to: tip)
        ctx.saveGState()
        ctx.addPath(hair)
        ctx.setLineWidth(s * 0.021)
        ctx.setLineCap(.round)
        ctx.setStrokeColor(blueTop)
        ctx.strokePath()
        ctx.restoreGState()
    }

    // 刷箍：刷毛根部一小段横向短条
    ctx.saveGState()
    ctx.addPath(CGPath(roundedRect: CGRect(x: handleBottom.x - rect.width * 0.022,
                                           y: handleBottom.y - rect.height * 0.012,
                                           width: rect.width * 0.044,
                                           height: rect.height * 0.030),
                       cornerWidth: rect.width * 0.014, cornerHeight: rect.width * 0.014,
                       transform: nil))
    ctx.setFillColor(blueMid)
    ctx.fillPath()
    ctx.restoreGState()

    // 手掌：连指手套（圆角矩形 + 拇指），盖在柄上，才有"握住"的层次
    ctx.saveGState()
    let glove = CGRect(x: handCenter.x - handRadius * 0.95,
                       y: handCenter.y - handRadius * 1.25,
                       width: handRadius * 1.75,
                       height: handRadius * 2.30)
    let glovePath = CGPath(roundedRect: glove,
                           cornerWidth: glove.width * 0.46,
                           cornerHeight: glove.width * 0.46,
                           transform: nil)
    ctx.addPath(glovePath)
    ctx.setFillColor(blueMid)
    ctx.fillPath()
    ctx.restoreGState()

    // 拇指：贴在手套左上侧，指向盘体
    ctx.saveGState()
    let thumb = CGRect(x: glove.minX - handRadius * 0.42,
                       y: glove.maxY - handRadius * 0.86,
                       width: handRadius * 0.86,
                       height: handRadius * 0.66)
    ctx.addPath(CGPath(roundedRect: thumb,
                       cornerWidth: thumb.height * 0.5,
                       cornerHeight: thumb.height * 0.5,
                       transform: nil))
    ctx.setFillColor(blueMid)
    ctx.fillPath()
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

var sparkleCenter = pt(0.845, 0.815)
var sparkleRadius = s * 0.042
if variant == "drive" || variant == "disk" { sparkleCenter = pt(0.845, 0.815); sparkleRadius = s * 0.042 }
if variant == "broom" { sparkleCenter = pt(0.74, 0.22); sparkleRadius = s * 0.05 }
ctx.saveGState()
ctx.setShadow(offset: .zero, blur: s * 0.05, color: CGColor(red: 0.35, green: 0.95, blue: 0.80, alpha: 0.8))
drawSparkle(center: sparkleCenter, radius: sparkleRadius)
ctx.restoreGState()

guard let image = ctx.makeImage() else { exit(1) }
let rep = NSBitmapImageRep(cgImage: image)
guard let data = rep.representation(using: .png, properties: [:]) else { exit(1) }
try data.write(to: URL(fileURLWithPath: outPath))
print("wrote \(outPath)")
