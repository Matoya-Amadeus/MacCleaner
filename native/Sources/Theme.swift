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
                // 顶部辉光往下铺得更长一点，页面顶部不至于"一刀切"到纯黑
                // （2026-10-24 用户要求：绿色背景底再往下拉）。
                // 绿色只在**头部区域**：顶部最亮，筛选栏下方再延伸一小段后自然渐隐。
                // 之前用 endRadius 820 的径向渐变，等于整页都泛绿（用户："我没让你都变成纯绿底"）。
                // 现在用竖直分段：0% 亮 → 14% → 32%（约 224pt）收干。
                LinearGradient(
                    stops: [
                        .init(color: Theme.accent.opacity(0.13), location: 0.00),
                        .init(color: Theme.accent.opacity(0.09), location: 0.13),
                        .init(color: Theme.accent.opacity(0.03), location: 0.24),
                        .init(color: .clear, location: 0.34),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                // 左上角保留一小片柔光，避免顶部看起来是"一条平涂"。
                RadialGradient(
                    colors: [Theme.accent.opacity(0.10), .clear],
                    center: UnitPoint(x: 0.10, y: -0.02),
                    startRadius: 0,
                    endRadius: 420
                )
            } else {
                Color(nsColor: .windowBackgroundColor)
            }
        }
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

extension View {
    /// 在 `List` 里把任意视图当"分组表头"用：不吸顶、不画分隔线、留出上间距。
    ///
    /// 存在的理由：macOS 的 `Section` 表头默认吸顶，自定义的多行表头会盖住第一行。
    func listSectionHeaderRow() -> some View {
        self
            .listRowSeparator(.hidden)
            .listRowBackground(Color.clear)
            // 格式塔·接近性：组**之间**要明显松于组内（原来 14 与行距 42 太接近，
            // 视觉上分不清"换组"），所以上间距 14 → 26。
            // 标题要**贴近自己的子项**、远离上一组：上间距 34、下间距 0。
            // 之前上下都留白且接近，两组之间的空隙和"标题→首行"几乎一样，
            // 视觉上分不清标题属于哪一组（用户 2026-10-24 截图）。
            // 标题到自己的子项距离**减半**（用户 2026-10-24：除个 2）。
            // 负 bottom inset 会把标题行压向首行；-16 太多，第一组标题被顶出可视区，
            // 收敛到 -8（实测仍比原来近一半，且首组标题可见）。
            .listRowInsets(EdgeInsets(top: 34, leading: 12, bottom: -8, trailing: 12))
    }
}

/// 列表行的统一样式：**组内不画分隔线**（同组是一整块），用悬停高亮补回边界感。
///
/// 为什么做成 modifier：清理 / 卸载 / 更新 / 残留 / AI 五个列表都要这一套，
/// 各写一遍必然漂移（2026-10-24 只有清理页做了，用户一眼看出不一致）。
struct RowHoverModifier: ViewModifier {
    let rowID: String
    @Binding var hoveringID: String?

    func body(content: Content) -> some View {
        content
            .listRowSeparator(.hidden)
            .listRowBackground(
                RoundedRectangle(cornerRadius: 6)
                    .fill(hoveringID == rowID ? Color.white.opacity(0.045) : Color.clear)
                    .padding(.horizontal, 6)
            )
            .onHover { inside in
                hoveringID = inside ? rowID : nil
            }
    }
}

extension View {
    func rowHover(_ id: String, hoveringID: Binding<String?>) -> some View {
        modifier(RowHoverModifier(rowID: id, hoveringID: hoveringID))
    }
}
