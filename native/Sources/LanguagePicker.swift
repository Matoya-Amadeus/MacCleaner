import SwiftUI

/// 左下角的语言切换入口：图标 + 当前语言名。
///
/// **为什么不用 `popover`**（2026-10-24 验收结论）：
/// 控件挂在侧栏的 `safeAreaInset(edge: .bottom)` 里，`popover` 在这个位置**从不渲染**——
/// 用 AX 证明过落点确实命中控件（`element-at` → `AXStaticText '语言'`），`showMenu` 也置了 true，
/// 但屏幕上没有任何浮层，且找不到浮层窗口。
/// 所以改成**自己画浮层**：菜单由 `RootView` 用 `.overlay` 渲染在最上层，
/// 位置固定在语言栏上方；外观与原来一致。
struct LanguagePicker: View {
    /// 由 `RootView` 持有：菜单渲染在窗口顶层，才能既不被侧栏裁切、又能盖住列表。
    @Binding var isOpen: Bool
    @Environment(\.appLanguage) private var current
    @State private var hovering = false

    private var label: String { L10n.t("nav.language", current) }
    private var endonym: String {
        (AppLanguage(rawValue: current) ?? .zh).endonym
    }

    var body: some View {
        // 与上方侧栏项**同一套排版**（2026-10-24 用户要求：照 AI 那行的 icon 与文本调）：
        // 图标列宽 17、字号 13、间距 9、左对齐；箭头贴右但用 tertiary 弱化，不抢视觉。
        HStack(spacing: 9) {
            Image(systemName: "globe")
                .frame(width: 17)
                .font(.system(size: 12, weight: .medium))
            Text(endonym).font(.system(size: 13))
            Spacer(minLength: 0)
            Image(systemName: "chevron.up.chevron.down")
                .font(.system(size: 8, weight: .semibold))
                .foregroundStyle(.quaternary)
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(
            hovering || isOpen ? Theme.accentFill(.dark) : Color.clear,
            in: RoundedRectangle(cornerRadius: 7)
        )
        .contentShape(RoundedRectangle(cornerRadius: 7))
        .onHover { inside in
            hovering = inside
            // 悬停即展开（用户要求）；关闭交给"点条目"或"点外部"。
            if inside, !isOpen {
                isOpen = true
            }
        }
        .onTapGesture { isOpen = true }
        .help(label)
        .accessibilityLabel(label)
        .accessibilityAddTraits(.isButton)
    }
}

/// 语言菜单本体（由 `RootView` 放在顶层 overlay 里）。
struct LanguageMenu: View {
    @AppStorage("appLanguage") private var language = AppLanguage.zh.rawValue
    @Environment(\.appLanguage) private var current
    let onClose: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(AppLanguage.allCases) { item in
                Button {
                    language = item.rawValue
                    onClose()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: language == item.rawValue ? "checkmark" : "circle")
                            .font(.system(size: 10))
                            .opacity(language == item.rawValue ? 1 : 0)
                        Text(item.endonym).font(.callout)
                        Spacer(minLength: 12)
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(6)
        .frame(width: 150)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(.white.opacity(0.09), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.35), radius: 12, y: 4)
        .accessibilityLabel(L10n.t("nav.language", current))
    }
}
