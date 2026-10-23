import SwiftUI

/// 列表筛选：**状态**（全部 / 已选 / 未选）+ **分类**（分组名）。
///
/// 放在「全选」右边——用户先决定"整体勾不勾"，再决定"看的这批是哪些"。
/// 分类项来自数据本身（内核给的分组），不在界面里硬编码。
enum SelectionFilter: String, CaseIterable, Identifiable {
    case all, selected, unselected

    var id: String { rawValue }
    var title: String {
        switch self {
        case .all: return "全部"
        case .selected: return "已选"
        case .unselected: return "未选"
        }
    }
    var symbol: String {
        switch self {
        case .all: return "line.3.horizontal.decrease.circle"
        case .selected: return "checkmark.circle"
        case .unselected: return "circle"
        }
    }
}

struct FilterBar: View {
    @Binding var status: SelectionFilter
    @Binding var category: String?          // nil = 全部分类
    let categories: [(label: String, count: Int)]
    /// AI 页没有勾选概念，只需要分类——那时不显示"状态"这一维。
    var showsStatus: Bool = true
    @Environment(\.colorScheme) private var colorScheme

    /// 有没有在筛选（用于高亮图标）
    private var isFiltering: Bool { status != .all || category != nil }

    var body: some View {
        // 拆成**两个**独立下拉：状态 / 分类，各自都有"全部"，结果是两者的**交集**。
        // 之前塞在一个菜单里（两段标题），选完一个得重新打开才能选另一个，
        // 而且看不出"这两个条件是并列的"（用户 2026-10-23 要求拆开）。
        HStack(spacing: 8) {
            if showsStatus {
                Menu {
                    ForEach(SelectionFilter.allCases) { option in
                        Button {
                            status = option
                        } label: {
                            if status == option { Label(option.title, systemImage: "checkmark") }
                            else { Text(option.title) }
                        }
                    }
                } label: {
                    chip(
                        title: status == .all ? "全部状态" : status.title,
                        symbol: status.symbol,
                        active: status != .all
                    )
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .help("按勾选状态筛选")
            }

            Menu {
                Button {
                    category = nil
                } label: {
                    if category == nil { Label("全部分类", systemImage: "checkmark") }
                    else { Text("全部分类") }
                }
                Divider()
                ForEach(categories, id: \.label) { item in
                    Button {
                        category = item.label
                    } label: {
                        if category == item.label {
                            Label("\(item.label) · \(item.count)", systemImage: "checkmark")
                        } else {
                            Text("\(item.label) · \(item.count)")
                        }
                    }
                }
            } label: {
                chip(
                    title: category ?? "全部分类",
                    symbol: "square.grid.2x2",
                    active: category != nil
                )
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("按分组筛选")

            if isFiltering {
                Button {
                    status = .all
                    category = nil
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help("清除筛选（状态与分类一起清）")
            }
        }
    }

    /// 下拉按钮的样子：有筛选时用主色，一眼看出"这一维被限定了"。
    private func chip(title: String, symbol: String, active: Bool) -> some View {
        HStack(spacing: 5) {
            Image(systemName: symbol).font(.system(size: 11, weight: .medium))
            Text(title).font(.callout)
            Image(systemName: "chevron.down").font(.system(size: 9, weight: .semibold))
        }
        .foregroundStyle(active ? Theme.accentText(colorScheme) : Color.secondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 4)
        .background(
            active ? Theme.accentFill(colorScheme) : Color.clear,
            in: RoundedRectangle(cornerRadius: 7)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 7)
                .strokeBorder(active ? Theme.accent.opacity(0.35) : Theme.cardStroke(colorScheme), lineWidth: 1)
        )
    }
}

/// 「全选」勾选框：**统一放在筛选左边**（用户 2026-10-23 要求：先决定整体勾不勾，再看这批是哪几条）。
/// 只勾"当前可见"的项——筛选成"未选"时点全选，不该把看不见的也勾上。
struct SelectAllToggle: View {
    let isOn: Bool
    /// 已选 / 总数：部分选中时（比如 7/8）在标签里显示出来，
    /// 否则空心的勾选框会让人以为"一个都没选"。
    var count: (selected: Int, total: Int)?
    let action: (Bool) -> Void

    private var label: String {
        if let count, count.selected > 0, count.selected < count.total {
            return "全选（\(count.selected)/\(count.total)）"
        }
        return "全选"
    }

    var body: some View {
        Toggle(isOn: Binding(get: { isOn }, set: { action($0) })) {
            Text(label).font(.callout).monospacedDigit()
        }
        .toggleStyle(.checkbox)
        .accessibilityLabel(label)
    }
}
