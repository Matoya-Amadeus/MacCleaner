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

    /// 探针必须读一个**只有 FDA 才能读**的位置：没授权时返回的是 EPERM 而不是 EACCES。
    ///
    /// 以前读 `~/Library/Application Support/com.apple.TCC/TCC.db`——macOS 14 起用户级
    /// TCC 数据库已经不存在了，于是 `probe()` 恒为 false：界面永远认为没权限、
    /// 清理时也不会跳过 Apple 应用的数据目录，最后撞上 TCC 变成一条报错
    /// （2026-11-03 排查用户 `com.apple.Safari` 清理失败时发现）。
    static func probe() -> Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        // 任一可读即可证明有 FDA；都不存在时只能保守地当作"没有"。
        for relative in ["Library/Safari", "Library/Mail", "Library/Messages",
                         "Library/Application Support/com.apple.TCC"] {
            let url = home.appendingPathComponent(relative)
            guard FileManager.default.fileExists(atPath: url.path) else { continue }
            if canRead(url.path) { return true }
        }
        return false
    }

    static func canRead(_ path: String) -> Bool {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory) else { return false }
        if isDirectory.boolValue {
            // 目录不能交给 FileHandle（open 目录再 read 会失败），列一次就够。
            return (try? FileManager.default.contentsOfDirectory(atPath: path)) != nil
        }
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

    /// 复查授权状态。
    ///
    /// **值没变就不要赋值**：`@Published` 每次赋值都会通知整棵视图树重算，
    /// 而本方法挂在 `didBecomeActive` 上（每次切回 App 都跑）。之前无条件赋值，
    /// 于是"切出去看一眼再切回来"也会触发一轮刷新（用户 2026-11-03 反馈）。
    func refresh() {
        let fullDisk = Self.probe()
        if fullDisk != hasFullDiskAccess { hasFullDiskAccess = fullDisk }

        let alive = grantedFolders.filter { Self.canRead($0) }
        if alive != grantedFolders {
            grantedFolders = alive
            UserDefaults.standard.set(Array(alive), forKey: Self.grantedKey)
        }
    }

    func openSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(url)
        }
    }

    /// 打开「完全磁盘访问权限」面板。
    ///
    /// **不在这里标记重启**：以前一打开设置就写 `needsRestartAfterPermission`，
    /// 用户只是切出去看一眼、什么都没勾就切回来，App 也会整个重启一次
    /// （勾选状态与扫描结果全丢，表现成"莫名其妙又在扫描"，2026-11-03 反馈）。
    /// 现在由 `App.swift` 的 `didBecomeActive` 对比授权前后值：真的拿到权限才动作，
    /// 而且只重启 core 子进程，不重启界面。
    func openFullDiskAccessSettings() {
        openSettings()
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

            // 完全磁盘访问：清理 Safari / 邮件 / 信息这类 Apple 应用数据的前提。
            // 放在最上面，因为它是"清理点了没反应"最常见的原因（2026-11-03 用户反馈）。
            if !store.hasFullDiskAccess {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "externaldrive.badge.exclamationmark")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("清理 Safari 等 Apple 应用缓存需要「完全磁盘访问权限」")
                            .font(.callout.weight(.medium))
                        Text("没有它，这些目录会被跳过——macOS 不允许任何 App 读取。授权后 App 会自动重启。")
                            .font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 6)
                    Button("打开设置") { store.openFullDiskAccessSettings() }
                        .controlSize(.small)
                }
                .padding(10)
                .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
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
                Button("打开系统设置（完整权限）") { store.openFullDiskAccessSettings() }
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
