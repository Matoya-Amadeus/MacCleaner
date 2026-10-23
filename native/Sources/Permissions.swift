import AppKit
import Combine
import SwiftUI

/// 「受保护文件夹」的授权状态。
///
/// 背景（2026-10-23）：macOS 对 `~/Downloads`、`~/Desktop`、`~/Documents` 是**分别**弹框的，
/// 没有 API 能把它们合成一个系统对话框。所以做了两件事：
/// 1. **没授权就完全不去碰**（内核 `skip_protected`），用户不会被反复弹框；
/// 2. 想扫全的人，在**一个**面板里勾选要授权的文件夹，点一次 → 系统只弹**一次**选择窗口
///    （多选目录），用户 ⌘ 选中即可。用户意图（user intent）会覆盖后续的自动弹框。
@MainActor
final class PermissionStore: ObservableObject {
    static let shared = PermissionStore()

    static let folderNames = ["Downloads", "Desktop", "Documents"]
    static let grantedKey = "grantedProtectedFolders"

    @Published private(set) var hasFullDiskAccess = false
    @Published private(set) var grantedFolders: Set<String> = []

    private init() {
        hasFullDiskAccess = Self.probe()
        grantedFolders = Set(UserDefaults.standard.stringArray(forKey: Self.grantedKey) ?? [])
        // 记住的路径要还在，否则等于没授权
        grantedFolders = grantedFolders.filter { Self.canRead($0) }
    }

    /// 能不能扫受保护目录：要么有 FDA，要么用户明确选过这些文件夹。
    var canScanProtected: Bool {
        hasFullDiskAccess || !grantedFolders.isEmpty
    }

    static func probe() -> Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let db = home.appendingPathComponent("Library/Application Support/com.apple.TCC/TCC.db")
        guard let handle = try? FileHandle(forReadingFrom: db) else { return false }
        defer { try? handle.close() }
        _ = try? handle.read(upToCount: 1)
        return true
    }

    static func canRead(_ path: String) -> Bool {
        guard let handle = try? FileHandle(forReadingFrom: URL(fileURLWithPath: path)) else { return false }
        defer { try? handle.close() }
        _ = try? handle.read(upToCount: 1)
        return true
    }

    func folderPath(_ name: String) -> String {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(name).path
    }

    /// 打开**一次**系统选择窗口，让用户把勾选的文件夹一起授权。
    func requestAccess(for names: [String]) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = true
        panel.prompt = "授权"
        panel.message = "按住 ⌘ 选中要授权的文件夹（下载 / 桌面 / 文稿），只需这一次。"
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser
        panel.begin { response in
            guard response == .OK else { return }
            let chosen = panel.urls.map(\.path)
            Task { @MainActor in
                var granted = self.grantedFolders
                for path in chosen where Self.canRead(path) {
                    granted.insert(path)
                }
                self.grantedFolders = granted
                UserDefaults.standard.set(Array(granted), forKey: Self.grantedKey)
                self.hasFullDiskAccess = Self.probe()
            }
        }
    }

    func refresh() {
        hasFullDiskAccess = Self.probe()
        grantedFolders = grantedFolders.filter { Self.canRead($0) }
        UserDefaults.standard.set(Array(grantedFolders), forKey: Self.grantedKey)
    }

    func openSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(url)
        }
    }
}

/// 一个面板、三个勾选框、一次确认。
struct PermissionSheet: View {
    @ObservedObject var store: PermissionStore
    var onClose: () -> Void

    @State private var checked: Set<String> = Set(PermissionStore.folderNames)

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Image(systemName: "lock.shield").foregroundStyle(.orange)
                Text("授权读取几个文件夹").font(.headline)
            }

            Text("「下载 / 桌面 / 文稿」属于 macOS 的受保护目录。系统本来会为**每个**文件夹各弹一次框——那样要点三次。")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 6) {
                ForEach(PermissionStore.folderNames, id: \.self) { name in
                    Toggle(isOn: Binding(
                        get: { checked.contains(name) },
                        set: { isOn in
                            if isOn { checked.insert(name) } else { checked.remove(name) }
                        }
                    )) {
                        Text("~/\(name)").font(.system(.body, design: .monospaced))
                    }
                    .toggleStyle(.checkbox)
                }
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))

            Text("点【授权】后只会弹出**一次**系统窗口：按住 ⌘ 把它们一起选中即可。")
                .font(.caption)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)

            if store.hasFullDiskAccess {
                Label("已拥有「完全磁盘访问权限」，无需再选。", systemImage: "checkmark.seal")
                    .font(.caption).foregroundStyle(.green)
            }

            HStack {
                Button("打开系统设置（完整权限）") { store.openSettings() }
                    .controlSize(.small)
                Spacer()
                Button("以后再说", action: onClose).keyboardShortcut(.cancelAction)
                Button("授权") {
                    store.requestAccess(for: Array(checked))
                    onClose()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(checked.isEmpty)
            }
        }
        .padding(20)
        .frame(width: 460)
    }
}
