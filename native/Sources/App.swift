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

    /// 本地化 key（文案在 `L10n.strings`）。
    var titleKey: String {
        switch self {
        case .clean: return "nav.clean"
        case .software: return "nav.software"
        case .disk: return "nav.disk"
        case .system: return "nav.system"
        case .ai: return "nav.ai"
        }
    }

    /// 菜单栏等处没有 View 环境，从 UserDefaults 直接读当前语言。
    var title: String {
        let language = UserDefaults.standard.string(forKey: "appLanguage") ?? AppLanguage.zh.rawValue
        return L10n.t(titleKey, language)
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
        .defaultSize(width: 980, height: 700)


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
    @AppStorage("appLanguage") private var language = AppLanguage.zh.rawValue

    var body: some View {
        // 不用 NavigationSplitView：它把两个子视图的 frame 持久化到 UserDefaults
        // （键名带视图类型签名），界面一改签名就留下旧记录，分栏按旧高度排版 →
        // 内容整体上移、顶部被标题栏裁掉（2026-10-23 反复出现，自愈也压不住）。
        // 固定两栏没有这个状态，代价只是自己管宽度与分隔线。
        HStack(spacing: 0) {
            // 宽度约束放在**容器**这一层：`List` 自带最小宽度，直接给它 `.frame(width:)`
            // 会被忽略（实测仍是 ~490pt）。这里从外面卡死 + 裁剪。
            sidebar
                .frame(width: 158)
                .clipped()
            Divider()
            detail
        }
        .environment(\.appLanguage, language)
        .onAppear {
            StatusItemController.shared.sync()
            permissions.refresh()
            // 授权统一收到启动时的一次弹窗里（用户要求）：不授权也照常能用，
            // 只是跳过受保护目录，清理过程中不再反复弹系统框。
            // 只首次弹一次，之后点工具栏盾牌。
            if !permissions.canScanProtected,
               !UserDefaults.standard.bool(forKey: "permissionAsked") {
                UserDefaults.standard.set(true, forKey: "permissionAsked")
                showPermissions = true
            }
            if ProcessInfo.processInfo.environment["MACCLEANER_DEV_PERM"] != nil {
                showPermissions = true
            }
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
        // 去系统设置授权后回到 App：TCC 的变更对**已运行进程**不生效，系统要求重启。
        // 用户不该被要求手动关开——这里自动重启一次（只一次，标记即刻清掉，避免循环）。
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            if UserDefaults.standard.bool(forKey: "needsRestartAfterPermission") {
                UserDefaults.standard.set(false, forKey: "needsRestartAfterPermission")
                AppRelaunch.once()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .mcSelectSection)) { note in
            if let raw = note.object as? String, let item = SidebarItem(rawValue: raw) {
                selection = item
            }
        }
    }

    /// 侧栏：List 自带正确的行高与滚动；选中底色由我们画（系统蓝不跟品牌色）。
    private var sidebar: some View {
        List {
            ForEach(SidebarItem.allCases, id: \.self) { item in
                Button {
                    selection = item
                } label: {
                    HStack(spacing: 9) {
                        Image(systemName: item.symbol)
                            .frame(width: 17)
                            .foregroundStyle(selection == item ? Theme.accentText(scheme) : .secondary)
                        L(item.titleKey)
                            .font(.system(size: 13, weight: selection == item ? .semibold : .regular))
                            .foregroundStyle(selection == item ? Theme.accentText(scheme) : .primary)
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 5)
                    .padding(.horizontal, 8)
                    .contentShape(RoundedRectangle(cornerRadius: 7))
                }
                .buttonStyle(.plain)
                .listRowInsets(EdgeInsets(top: 1, leading: 2, bottom: 1, trailing: 6))
                .listRowBackground(
                    RoundedRectangle(cornerRadius: 7)
                        .fill(selection == item ? Theme.accentFill(scheme) : Color.clear)
                        .padding(.horizontal, 4)
                )
                .listRowSeparator(.hidden)
                .accessibilityAddTraits(selection == item ? [.isSelected] : [])
                .accessibilityLabel(item.title)
            }
        }
        .listStyle(.sidebar)
        .scrollContentBackground(.hidden)
        // 宽度按**最长可见内容**定：`Language  English` 那行约 130pt，加两侧内边距取 158。
        // 原来 186 是为中文标签留的，切到英文后右侧空出 130pt，选中块被拉得很长。
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 0) {
                Divider().opacity(0.4)
                LanguagePicker()
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
            }
            .background(.regularMaterial)
        }
    }

    /// 详情：不套额外容器（历史上套 VStack 会压垮布局）。
    @ViewBuilder
    private var detail: some View {
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

/// 自动重启：授权后 TCC 只在**新进程**里生效。
enum AppRelaunch {
    static func once() {
        let opener = Process()
        opener.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        opener.arguments = ["-n", Bundle.main.bundleURL.path]
        try? opener.run()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            NSApp.terminate(nil)
        }
    }
}
