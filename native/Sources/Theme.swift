import SwiftUI

/// 设计系统：颜色、间距、卡片、页面骨架。
///
/// 为什么单独立一个文件：之前每页各写一套 `.background(Color.secondary.opacity(0.07))`
/// 和各自的 padding，结果是"同一层级的卡片长得不一样"——格式塔里最不该犯的错（破坏相似性）。
/// 现在所有页面只从这几个 token 取值。
enum Theme {

    // MARK: - 颜色

    /// 主色取图标那支青绿（#2ED8B3），让 App 内外一致。
    static let accent = Color(red: 0.180, green: 0.847, blue: 0.702)
    static let accentDeep = Color(red: 0.043, green: 0.639, blue: 0.529)

    static let warn = Color(red: 1.0, green: 0.62, blue: 0.24)
    static let danger = Color(red: 1.0, green: 0.36, blue: 0.36)

    /// 卡片底：比页面底亮一档（图底关系）。**亮色模式必须换成深色低透明度**——
    /// 白 4.5% 铺在浅底上等于没画，卡片会"消失"。
    static func cardFill(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.045) : Color.black.opacity(0.035)
    }

    static func cardStroke(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.075) : Color.black.opacity(0.07)
    }

    /// 选中项的文字色：亮色底上 #2ED8B3 太浅，用深青才够对比。
    static func accentText(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? accent : accentDeep
    }

    /// 选中项的底色：亮色下要略重一点，否则"选中"几乎看不出来。
    static func accentFill(_ scheme: ColorScheme) -> Color {
        accent.opacity(scheme == .dark ? 0.16 : 0.22)
    }
    static let pageTop = Color(red: 0.086, green: 0.090, blue: 0.102)
    static let pageBottom = Color(red: 0.052, green: 0.055, blue: 0.063)

    // MARK: - 尺度

    enum Space {
        static let xs: CGFloat = 4
        static let s: CGFloat = 8
        static let m: CGFloat = 12
        static let l: CGFloat = 16
        static let xl: CGFloat = 24
        static let page: CGFloat = 22
    }

    enum Radius {
        static let card: CGFloat = 12
        static let chip: CGFloat = 8
        static let bar: CGFloat = 3
    }
}

// MARK: - 页面背景

/// 深色底 + 左上角一层极淡的青绿辉光（呼应图标，也给深色界面一点"光感"）。
/// 明暗主题都可用：亮色模式下辉光降到 4%，不会脏。
struct PageBackground: View {
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ZStack {
            if scheme == .dark {
                LinearGradient(
                    colors: [Theme.pageTop, Theme.pageBottom],
                    startPoint: .top,
                    endPoint: .bottom
                )
                RadialGradient(
                    colors: [Theme.accent.opacity(0.10), .clear],
                    center: UnitPoint(x: 0.12, y: -0.05),
                    startRadius: 0,
                    endRadius: 620
                )
            } else {
                Color(nsColor: .windowBackgroundColor)
            }
        }
        .ignoresSafeArea()
    }
}

// MARK: - 卡片

struct CardBackground: ViewModifier {
    var padding: CGFloat = Theme.Space.l
    @Environment(\.colorScheme) private var scheme

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(Theme.cardFill(scheme), in: RoundedRectangle(cornerRadius: Theme.Radius.card))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .strokeBorder(Theme.cardStroke(scheme), lineWidth: 1)
            )
    }
}

extension View {
    /// 统一的卡片外观（所有卡片都走这里，保证"同级同貌"）。
    func card(padding: CGFloat = Theme.Space.l) -> some View {
        modifier(CardBackground(padding: padding))
    }
}

// MARK: - 页面骨架

/// 每页顶部：标题 + 一句说明 + 右侧信息（时间戳/操作）。
/// 一致的位置让用户"永远知道自己在哪一页、这页是干什么的"。
struct PageHeader<Trailing: View>: View {
    let title: String
    let subtitle: String
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 20, weight: .semibold))
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: Theme.Space.m)
            trailing()
        }
        .padding(.horizontal, Theme.Space.page)
        .padding(.top, Theme.Space.l)
        .padding(.bottom, Theme.Space.m)
    }
}

extension PageHeader where Trailing == EmptyView {
    init(title: String, subtitle: String) {
        self.init(title: title, subtitle: subtitle) { EmptyView() }
    }
}

// MARK: - 分段 → 芯片

/// 用芯片替代系统分段控件：分段看起来像"换页"，芯片明确是"筛这一屏"。
struct ChipPicker<Value: Hashable>: View {
    let options: [(value: Value, label: String)]
    @Binding var selection: Value
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: Theme.Space.s) {
            ForEach(options, id: \.value) { option in
                let isOn = option.value == selection
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { selection = option.value }
                } label: {
                    Text(option.label)
                        .font(.system(size: 12.5, weight: isOn ? .semibold : .regular))
                        .foregroundStyle(isOn ? Theme.accentText(scheme) : Color.secondary)
                        .padding(.horizontal, 11)
                        .padding(.vertical, 5)
                        .background(
                            isOn ? Theme.accentFill(scheme) : Theme.cardFill(scheme),
                            in: RoundedRectangle(cornerRadius: Theme.Radius.chip)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.Radius.chip)
                                .strokeBorder(isOn ? Theme.accent.opacity(0.45) : Color.clear, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, Theme.Space.page)
    }
}
