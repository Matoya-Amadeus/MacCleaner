import AppKit
import Combine
import SwiftUI

/// 「完全磁盘访问权限」的**唯一**判断点与**唯一**提示入口。
///
/// 为什么不按页面各弹一条：macOS 会对 `~/Downloads`、`~/Desktop`、`~/Documents`
/// **分别**弹一次授权框，用户点得很累（2026-10-23 反馈）。
/// 所以：
/// 1. 没授权时，清理页传 `skip_protected` 给内核——**根本不去碰**那些目录，不弹框；
/// 2. 全 App 只在工具栏放**一个**盾牌图标，点开才展开说明。
///
/// 为什么不做成横幅：横幅要占宽度，`NavigationSplitView` 会被它挤到最小列宽
/// （侧栏退化成图标条、分段控件被顶出可视区）——2026-10-23 实际踩过。
@MainActor
final class PermissionStore: ObservableObject {
    static let shared = PermissionStore()

    @Published private(set) var hasFullDiskAccess = false

    private init() {
        hasFullDiskAccess = Self.probe()
    }

    /// 读 TCC 数据库是最可靠的探针：没有权限必然失败。
    static func probe() -> Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let db = home.appendingPathComponent("Library/Application Support/com.apple.TCC/TCC.db")
        guard let handle = try? FileHandle(forReadingFrom: db) else { return false }
        defer { try? handle.close() }
        _ = try? handle.read(upToCount: 1)
        return true
    }

    func refresh() {
        hasFullDiskAccess = Self.probe()
    }

    func openSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(url)
        }
    }
}

/// 点盾牌图标后弹出的说明（竖向排，不参与主窗口布局）。
struct PermissionPopover: View {
    @ObservedObject var store: PermissionStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("读不到几个受保护目录", systemImage: "lock.shield")
                .font(.callout.weight(.semibold))
            Text("「下载 / 桌面 / 文稿」属于 macOS 的受保护目录。系统会为每个文件夹各弹一次授权——所以本工具**已经跳过它们**，不会反复打扰你。")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Text("想扫得更全，授权「完全磁盘访问权限」**一次**即可全部读到。")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack {
                Button("打开设置") { store.openSettings() }
                    .controlSize(.small)
                Button("已授权，重新检查") { store.refresh() }
                    .controlSize(.small)
            }
        }
        .padding(14)
        .frame(width: 300)
    }
}
