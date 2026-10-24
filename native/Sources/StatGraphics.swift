import SwiftUI

/// 数值卡片的三种图形。
///
/// 为什么不用图表库：这几个都是"一个值 + 一个基准"的关系，画成条形/环就够；
/// 引 Charts 会让卡片里塞进坐标轴与图例，反而更难读。

/// 横向计量条：`ratio` 是 0…1 的占比。
struct MeterBar: View {
    let ratio: Double
    var tint: Color = Theme.accent
    var height: CGFloat = 6

    private var clamped: Double { min(max(ratio, 0), 1) }

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.16))
                Capsule()
                    .fill(tint.gradient)
                    .frame(width: max(proxy.size.width * clamped, clamped > 0 ? height : 0))
            }
        }
        .frame(height: height)
        .accessibilityElement()
        .accessibilityLabel("占比 \(Int((clamped * 100).rounded()))%")
    }
}

/// 三根竖条（负载 1/5/15 分钟）：高度按 `scale` 归一，超过 1 的条会填满并变色。
struct LoadBars: View {
    let values: [Double]
    /// 归一化基准（通常是"核数"，即每核 1.0）。
    let scale: Double

    private func ratio(_ value: Double) -> Double {
        guard scale > 0 else { return 0 }
        return min(value / scale, 1)
    }

    private func tint(_ value: Double) -> Color {
        let perCore = scale > 0 ? value / scale : 0
        if perCore >= 1.0 { return .red }
        if perCore >= 0.7 { return .orange }
        return Theme.accent
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 5) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                VStack(spacing: 3) {
                    ZStack(alignment: .bottom) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(Color.secondary.opacity(0.16))
                            .frame(width: 9, height: 26)
                        RoundedRectangle(cornerRadius: 2)
                            .fill(tint(value).gradient)
                            .frame(width: 9, height: max(26 * ratio(value), 2))
                    }
                    Text(String(format: "%.1f", value))
                        .font(.system(size: 8).monospacedDigit())
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            "1 分钟 \(String(format: "%.2f", values.first ?? 0))，"
            + "5 分钟 \(String(format: "%.2f", values.count > 1 ? values[1] : 0))，"
            + "15 分钟 \(String(format: "%.2f", values.count > 2 ? values[2] : 0))"
        )
    }
}

/// 环形计量：中间写百分比。
struct RingGauge: View {
    let percent: Double
    var tint: Color = Theme.accent
    var size: CGFloat = 46
    var caption: String?

    private var clamped: Double { min(max(percent, 0), 100) }

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.secondary.opacity(0.16), lineWidth: 5)
            Circle()
                .trim(from: 0, to: clamped / 100)
                .stroke(tint.gradient, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 0) {
                Text("\(Int(clamped.rounded()))")
                    .font(.system(size: size * 0.30, weight: .semibold).monospacedDigit())
                Text(caption ?? "%")
                    .font(.system(size: size * 0.16))
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(width: size, height: size)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(Int(clamped.rounded())) 百分点")
    }
}

/// 状态胶囊：正常/已触发这类二值状态。
struct StatusPill: View {
    let text: String
    var isGood: Bool = true

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: isGood ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .font(.system(size: 10, weight: .semibold))
            Text(text)
                .font(.system(size: 11, weight: .medium))
        }
        .foregroundStyle(isGood ? Color.green : Color.orange)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background((isGood ? Color.green : Color.orange).opacity(0.12), in: Capsule())
        .accessibilityElement(children: .combine)
    }
}

/// 核心网格：只表示"有多少核"，不假装有用率数据。
struct CoreGrid: View {
    let count: Int
    var columns: Int = 5

    var body: some View {
        let rows = max(Int(ceil(Double(count) / Double(columns))), 1)
        VStack(alignment: .leading, spacing: 3) {
            ForEach(0..<rows, id: \.self) { row in
                HStack(spacing: 3) {
                    ForEach(0..<columns, id: \.self) { column in
                        let index = row * columns + column
                        RoundedRectangle(cornerRadius: 2)
                            .fill(index < count ? Color.accentColor.opacity(0.55) : Color.clear)
                            .frame(width: 9, height: 9)
                    }
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(count) 个核心")
    }
}

/// 列表行下方的迷你占比条（高 3pt，不抢文字）。
/// 用在"目录清单""进程列表"这类**同一基准可比较**的地方；不可比较时不要加。
struct MiniBar: View {
    let ratio: Double
    var tint: Color = Theme.accent
    /// 给定时用固定宽度：横贯整行会像"加载进度"，视觉权重压过内容
    /// （2026-10-24 用户反馈"这个条太丑"）。
    var width: CGFloat? = nil
    var height: CGFloat = 3

    private var clamped: Double { min(max(ratio, 0), 1) }

    var body: some View {
        GeometryReader { proxy in
            let barWidth = width ?? proxy.size.width
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.10))
                Capsule()
                    .fill(tint.opacity(0.55))
                    .frame(width: max(barWidth * clamped, clamped > 0 ? 2 : 0))
            }
            .frame(width: barWidth, alignment: .leading)
        }
        .frame(height: 3)
        .accessibilityHidden(true)   // 行本身已有整句标签，条是纯视觉
    }
}
