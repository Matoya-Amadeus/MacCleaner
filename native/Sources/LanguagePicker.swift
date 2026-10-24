import SwiftUI

/// 左下角的语言切换：图标 + 语言名，**悬停即展开菜单**（用户 2026-10-24 要求）。
/// 选完立即生效——文案都走 `L10n`，切语言等于换一个字符串源。
struct LanguagePicker: View {
    @AppStorage("appLanguage") private var language = AppLanguage.zh.rawValue
    @Environment(\.appLanguage) private var current
    @State private var hovering = false
    @State private var showMenu = false
    @State private var closeWorkItem: DispatchWorkItem?

    private var label: String { L10n.t("nav.language", current) }
    private var endonym: String {
        (AppLanguage(rawValue: language) ?? .zh).endonym
    }

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "globe")
                .font(.system(size: 12, weight: .medium))
            Text(label).font(.system(size: 12))
            Spacer(minLength: 4)
            Text(endonym)
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)
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
            closeWorkItem?.cancel()
            if inside {
                showMenu = true
            } else {
                // 移出后略等一会儿再关，避免鼠标划过的瞬间闪烁。
                let work = DispatchWorkItem { showMenu = false }
                closeWorkItem = work
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35, execute: work)
            }
        }
        .onTapGesture { showMenu.toggle() }
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
        .accessibilityLabel(label)
    }
}
