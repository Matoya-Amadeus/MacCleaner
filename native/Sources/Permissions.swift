import AppKit
import Combine
import SwiftUI

/// 「完全磁盘访问权限」的**唯一**判断点与**唯一**提示入口。
///
/// 为什么不按页面各弹一条：macOS 会对 `~/Downloads`、`~/Desktop`、`~/Documents`
/// **分别**弹一次授权框，用户点得很累（2026-10-23 反馈）。
/// 所以：
/// 1. 没授权时，清理页传 `skip_protected` 给内核——**根本不去碰**那些目录，不弹框；
/// 2. 全 App 只在顶部显示**一条**提示，说明"授权一次就全读到"。
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

/// 全 App 共用的一条权限提示。
struct PermissionNotice: View {
    @ObservedObject var store: PermissionStore

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "lock.shield")
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("读不到「下载 / 桌面 / 文稿」等受保护目录")
                    .font(.callout.weight(.medium))
                Text("macOS 会为每个文件夹各弹一次授权；这里只在顶部提示一条——授权「完全磁盘访问权限」**一次**即可全部读到（已为你跳过这些目录，不会反复弹框）。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 10)
            Button("打开设置") { store.openSettings() }
                .controlSize(.small)
            Button("已授权，重新检查") {
                store.refresh()
            }
            .controlSize(.small)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("缺少完全磁盘访问权限：读不到下载、桌面、文稿等目录。可打开系统设置授权，或点重新检查。")
    }
}
