import SwiftUI

/// 左下角的语言切换：图标 + 语言名，**悬停即展开菜单**（用户 2026-10-24 要求）。
/// 选完立即生效——文案都走 `L10n`，切语言等于换一个字符串源。
struct LanguagePicker: View {
    @AppStorage("appLanguage") private var language = AppLanguage.zh.rawValue
    @Environment(\.appLanguage) private var current
    @State private var hovering = false
    @State private var showMenu = false

    private var label: String { L10n.t("nav.language", current) }
    private var endonym: String {
        (AppLanguage(rawValue: language) ?? .zh).endonym
    }

    var body: some View {
        // 侧栏只有 158pt：塞「Language  English」会折行（实测 "Langua/ge"）。
        // 图标本身已经表达"语言"，只留当前语言名；完整说明放 tooltip。
        HStack(spacing: 6) {
            Image(systemName: "globe")
                .font(.system(size: 12, weight: .medium))
            Text(endonym).font(.system(size: 12))
            Spacer(minLength: 0)
            Image(systemName: "chevron.up.chevron.down")
                .font(.system(size: 8, weight: .semibold))
                .foregroundStyle(.quaternary)
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 6)
        .background(
            hovering ? Theme.accentFill(.dark) : Color.clear,
            in: RoundedRectangle(cornerRadius: 7)
        )
        .contentShape(RoundedRectangle(cornerRadius: 7))
        .onHover { inside in
            hovering = inside
            // 只在"进入"时展开；**不做移出自动关闭**——
            // 鼠标从触发区移到 popover 里的瞬间会先触发 exit，0.35s 后把菜单关掉，
            // 点击就落空了（2026-10-24 用户报"切不回中文"）。
            // 关闭交给 popover 自己：点条目或点外部。
            if inside, !showMenu {
                showMenu = true
            }
        }
        // 只"开"不"toggle"：hover 已经把菜单打开了，再 toggle 会把它关掉——
        // 表现为"点语言没反应/切不回中文"（2026-10-24 验收抓到）。
        // 关闭交给 popover 自己（选中条目或点外部）。
        // 延迟一点再开：popover 若在 mouseDown 当帧打开，紧接着的 mouseUp 会被
        // 判定为"点在菜单外"，于是打开即关闭（2026-10-24 验收：点语言没反应）。
        .onTapGesture {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { showMenu = true }
        }
        .popover(isPresented: $showMenu, arrowEdge: .top) {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(AppLanguage.allCases) { item in
                    Button {
                        language = item.rawValue
                        showMenu = false
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
        }
        .help(label)
        .accessibilityLabel(label)
    }
}
