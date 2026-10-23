import AppKit
import SwiftUI

extension Notification.Name {
    /// ⌘R：当前页重新读取（由各页自己监听，RootView 只负责发）。
    static let mcReload = Notification.Name("mc.reload")
    /// ⌘1–4：切换侧栏入口（菜单项发，RootView 收）。
    static let mcSelectSection = Notification.Name("mc.selectSection")
}

/// 侧边栏 4 个入口（2026-10-22 合并，原 8 个）：
/// 清理 / 软件 / 磁盘 / 系统。技能列表移到右上角按钮——它不属于"日常清理"这件事。
enum SidebarItem: String, CaseIterable, Identifiable {
    case clean, software, disk, system, ai

    var id: String { rawValue }

    var title: String {
        switch self {
        case .clean: return "清理"
        case .software: return "软件"
        case .disk: return "磁盘"
        case .system: return "系统"
        case .ai: return "AI"
        }
    }

    var symbol: String {
        switch self {
        case .clean: return "sparkles"
        case .software: return "shippingbox"
        case .disk: return "internaldrive"
        case .system: return "gauge.with.dots.needle.50percent"
        case .ai: return "wand.and.stars"
        }
    }
}

enum MainWindow {
    /// 从菜单栏叫回主窗口：先激活 App，再把主窗口提到最前。
    /// 不用 `WindowGroup` 的 `openWindow`（那会新开一个窗口，用户看到两个一样的窗口更困惑）。
    static func show() {
        NSApp.activate(ignoringOtherApps: true)
        for window in NSApp.windows where window.canBecomeMain {
            window.makeKeyAndOrderFront(nil)
            return
        }
    }
}

private func post(_ item: SidebarItem) {
    NotificationCenter.default.post(name: .mcSelectSection, object: item.rawValue)
}

@main
struct MacCleanerApp: App {
    var body: some Scene {
        WindowGroup("Mac Cleaner") {
            RootView()
                .frame(minWidth: 760, minHeight: 520)
                .tint(Theme.accent)
                // 只做深色：这套视觉（青绿辉光、半透明卡片）是按深色底设计的，
                // 亮色下即使调过对比度也不如深色成立，索性固定（用户 2026-10-23 决定）。
                .preferredColorScheme(.dark)   // 1080×729 这类小屏上 920 宽会顶出屏幕
        }
        .windowToolbarStyle(.unified)


        .commands {
            // 原生菜单：这是 WebView 版永远给不了的那一层的一部分。
            CommandGroup(replacing: .newItem) {}
            CommandMenu("前往") {
                Button("清理") { post(.clean) }.keyboardShortcut("1", modifiers: .command)
                Button("软件") { post(.software) }.keyboardShortcut("2", modifiers: .command)
                Button("磁盘") { post(.disk) }.keyboardShortcut("3", modifiers: .command)
                Button("系统") { post(.system) }.keyboardShortcut("4", modifiers: .command)
                Button("AI 可调用") { post(.ai) }.keyboardShortcut("5", modifiers: .command)
                Divider()
                Button("重新读取本页") {
                    NotificationCenter.default.post(name: .mcReload, object: nil)
                }
                .keyboardShortcut("r", modifiers: .command)
            }
        }
    }
}

struct RootView: View {
    // 记住上次停在哪个入口：原生 App 的默认期待（重开还在这儿）。
    @AppStorage("selectedSection") private var storedSection: String = SidebarItem.disk.rawValue
    @State private var selection: SidebarItem? = .disk
    @StateObject private var permissions = PermissionStore.shared
    @State private var showPermissions = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        NavigationSplitView {
            // 自绘侧栏：系统侧栏的选中色跟随「系统强调色」（这台机器是蓝色），
            // 与我们的青绿主色不一致。自绘能保证"品牌色只出现在选中项上"，
            // 代价是要自己写键盘/无障碍——两点都已补。
            VStack(spacing: 2) {
                ForEach(SidebarItem.allCases, id: \.self) { item in
                    Button {
                        selection = item
                    } label: {
                        HStack(spacing: 9) {
                            Image(systemName: item.symbol)
                                .frame(width: 18)
                                .foregroundStyle(selection == item ? Theme.accentText(scheme) : .secondary)
                            Text(item.title)
                                .font(.system(size: 13, weight: selection == item ? .semibold : .regular))
                                .foregroundStyle(selection == item ? Theme.accentText(scheme) : .primary)
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 6)
                        .padding(.horizontal, 9)
                        .background(
                            selection == item ? Theme.accentFill(scheme) : Color.clear,
                            in: RoundedRectangle(cornerRadius: 7)
                        )
                        .contentShape(RoundedRectangle(cornerRadius: 7))
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(selection == item ? [.isSelected] : [])
                    .accessibilityLabel(item.title)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 8)
            .padding(.top, 10)
            .navigationSplitViewColumnWidth(min: 168, ideal: 186, max: 240)
            .onAppear {
                StatusItemController.shared.sync()
                permissions.refresh()
                // 授权**统一收到启动时的一次弹窗**里（用户 2026-10-23 要求）：
                // 不授权也照常能用——我们只是跳过受保护目录，不在清理过程中反复弹系统框。
                // 只**首次**弹一次：每次都弹等于骚扰（用户反馈过授权框太多）。
                // 之后想授权，点工具栏那个盾牌即可。
                if !permissions.canScanProtected,
                   !UserDefaults.standard.bool(forKey: "permissionAsked") {
                    UserDefaults.standard.set(true, forKey: "permissionAsked")
                    showPermissions = true
                }
                // 开发钩子：MACCLEANER_DEV_PERM=1 强制弹出（截图/验收用）。
                if ProcessInfo.processInfo.environment["MACCLEANER_DEV_PERM"] != nil {
                    showPermissions = true
                }
                // 开发钩子（MACCLEANER_DEV_PLAN）要落到「软件」页，否则截图得手点一次。
                if let path = ProcessInfo.processInfo.environment["MACCLEANER_DEV_PLAN"], !path.isEmpty {
                    selection = .software
                    return
                }
                if let restored = SidebarItem(rawValue: storedSection) { selection = restored }
            }
            .onChange(of: selection) { _, newValue in
                if let newValue { storedSection = newValue.rawValue }
            }
            .sheet(isPresented: $showPermissions) {
                PermissionSheet(store: permissions) { showPermissions = false }
            }
            .onReceive(NotificationCenter.default.publisher(for: .mcSelectSection)) { note in
                if let raw = note.object as? String, let item = SidebarItem(rawValue: raw) {
                    selection = item
                }
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 240)
            .listStyle(.sidebar)
        } detail: {
            Group {
                switch selection ?? .disk {
                case .clean: CleanView()
                case .software: SoftwareView()
                case .disk: DiskView()
                case .system: SystemView()
                case .ai: ToolsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(PageBackground())
            .toolbar {
                if !permissions.canScanProtected {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            showPermissions = true
                        } label: {
                            Label("权限", systemImage: "lock.shield")
                        }
                        .help("有几个受保护目录读不到；点这里可以一次勾选授权")
                    }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        StatusItemController.shared.toggle()
                    } label: {
                        Label("菜单栏图标", systemImage: "menubar.rectangle")
                    }
                    .help("在菜单栏显示 Mac Cleaner 图标（菜单栏挤的话可以关掉）")
                }
            }
        }
    }
}

struct PlaceholderView: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "hammer.fill").font(.system(size: 28)).foregroundStyle(.tertiary)
            Text(title).font(.title3.weight(.semibold))
            Text(detail).font(.callout).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
