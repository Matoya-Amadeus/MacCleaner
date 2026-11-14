import SwiftUI

/// 系统页专用图形组件。
///
/// 为什么单独一个文件：系统页原来把诊断写成 6 张纯文字卡 + 两个长列表 + 一整屏说明，
/// 页面被撑到「其他工作无法展开」。这里把每个数字都换成可扫视的图形：
/// 分组标题（格式塔的接近性 / 封闭性）、计数胶囊、时间条、屏幕形状、紧凑进程行。
/// 全部沿用 Theme 的颜色与 CardBackground，保证和其他页同貌（相似性）。

/// 区块标题：图标 + 标题 + 一句口径说明，右侧细线把这一组「框」起来。
struct SystemSectionHeader: View {
    let icon: String
    let title: String
    var note: String? = nil

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.accent)
                .frame(width: 16)
            Text(title).font(.subheadline.weight(.semibold))
            if let note {
                Text(note)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            Rectangle()
                .fill(Color.secondary.opacity(0.14))
                .frame(height: 1)
        }
        .accessibilityElement(children: .combine)
    }
}

/// 计数胶囊：一个数字 + 一个图标 + 一个标签，替代 "launchctl 12 · RunAtLoad 11 · 周期 2" 这类长串。
struct SystemCountChip: View {
    let icon: String
    let value: String
    let label: String
    var tint: Color = Theme.accent

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(tint)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(.system(size: 15, weight: .semibold).monospacedDigit())
                    .lineLimit(1)
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(padding: 0)
        .accessibilityElement(children: .combine)
    }
}

/// 开机耗时条：以 120 秒为参考刻度，中间细线是 60 秒。
struct SystemTimeBar: View {
    let seconds: Int

    private var ratio: Double { min(max(Double(seconds) / 120, 0), 1) }
    private var tint: Color {
        seconds >= 90 ? Theme.warn : Theme.accent
    }

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.secondary.opacity(0.14))
                Capsule()
                    .fill(tint.gradient)
                    .frame(width: max(proxy.size.width * ratio, 2))
                Rectangle()
                    .fill(Color.secondary.opacity(0.4))
                    .frame(width: 1, height: 10)
                    .offset(x: proxy.size.width * 0.5)
            }
        }
        .frame(height: 6)
        .accessibilityLabel("\(seconds) 秒，参考刻度 120 秒")
    }
}

/// 显示器形状：主屏更大更亮，外接屏小一号；数量即图形数量。
struct SystemScreenGlyph: View {
    let count: Int

    var body: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(0..<min(max(count, 0), 3), id: \.self) { index in
                RoundedRectangle(cornerRadius: 2)
                    .fill(index == 0 ? Theme.accent.opacity(0.75) : Theme.accent.opacity(0.32))
                    .overlay(
                        RoundedRectangle(cornerRadius: 2)
                            .strokeBorder(Theme.accent.opacity(0.55), lineWidth: 0.8)
                    )
                    .frame(width: index == 0 ? 22 : 16, height: index == 0 ? 14 : 11)
            }
        }
        .accessibilityLabel("\(count) 块屏")
    }
}

/// 紧凑进程行：名字 + 迷你条 + 百分比，一行 20pt，不再每行铺 Divider。
struct SystemProcessRow: View {
    let name: String
    let percent: Double
    let ratio: Double
    var secondary: String? = nil
    var tint: Color = Theme.accent

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "bolt.horizontal")
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
                .frame(width: 14)
            Text(name)
                .font(.system(size: 12))
                .lineLimit(1)
            Spacer(minLength: 8)
            if let secondary {
                Text(secondary)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .monospacedDigit()
            }
            MiniBar(ratio: ratio, tint: tint, width: 54)
            Text(String(format: "%.1f%%", percent))
                .font(.system(size: 12).monospacedDigit())
                .frame(width: 52, alignment: .trailing)
        }
        .padding(.vertical, 3)
        .accessibilityElement(children: .combine)
    }
}
