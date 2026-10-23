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

    /// 有没有在筛选（用于高亮图标）
    private var isFiltering: Bool { status != .all || category != nil }

    var body: some View {
        HStack(spacing: 6) {
            Menu {
                Section("状态") {
                    ForEach(SelectionFilter.allCases) { option in
                        Button {
                            status = option
                        } label: {
                            if status == option { Label(option.title, systemImage: "checkmark") }
                            else { Text(option.title) }
                        }
                    }
                }
                Section("分类") {
                    Button {
                        category = nil
                    } label: {
                        if category == nil { Label("全部分类", systemImage: "checkmark") }
                        else { Text("全部分类") }
                    }
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
                }
                if isFiltering {
                    Divider()
                    Button("清除筛选") {
                        status = .all
                        category = nil
                    }
                }
            } label: {
                Label(currentLabel, systemImage: SelectionFilter.allCases.contains(status) ? status.symbol : "line.3.horizontal.decrease.circle")
                    .font(.callout)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .help("按状态或分类筛选")
        }
    }

    private var currentLabel: String {
        if let category { return "\(category) · \(status.title)" }
        return status == .all ? "筛选" : status.title
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
