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
    /// 修掉"分栏尺寸过期"导致的布局错乱。
    ///
    /// SwiftUI 会把 `NavigationSplitView` 两个子视图的 frame 存进 UserDefaults，
    /// 键名里带**视图类型的签名**。我们每次改界面（加 .tint / .preferredColorScheme / 换侧栏）
    /// 签名就变，旧键留在磁盘上；一旦窗口 frame 与某个旧键的高度对不上，
    /// 分栏就会按旧高度排版、被窗口裁掉上半截——表现是侧栏文字顶到红绿灯、
    /// 详情页从标题栏后面开始（2026-10-23 用户截图）。
    static func healSplitFramesIfNeeded() {
        guard let window = NSApp.windows.first(where: { $0.canBecomeMain }) else { return }
        let contentHeight = window.contentLayoutRect.height
        guard contentHeight > 100 else { return }

        let defaults = UserDefaults.standard
        let all = defaults.dictionaryRepresentation()
        var staleKeys: [String] = []
        var sawMismatch = false

        for (key, value) in all where key.contains("NSSplitView Subview Frames") {
            // 形如 "0.000000, 0.000000, 186.000000, 893.000000, NO, NO"
            let numbers = "\(value)".split(separator: ",").compactMap {
                Double($0.trimmingCharacters(in: .whitespaces))
            }
            if numbers.count >= 4, abs(numbers[3] - Double(contentHeight)) > 8 {
                sawMismatch = true
                staleKeys.append(key)
            }
        }

        guard sawMismatch else { return }
        for key in staleKeys { defaults.removeObject(forKey: key) }
        // 强制一次布局重算：分栏会按当前窗口高度重新分配。
        var frame = window.frame
        frame.size.height -= 1
        window.setFrame(frame, display: true)
        frame.size.height += 1
        window.setFrame(frame, display: true)
    }

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

    var body: some View {
        NavigationSplitView {
            // 侧栏用 List：只有 List/ScrollView 会**自动避开标题栏**。
            // 之前用纯 VStack 自绘，内容会顶到红绿灯底下（2026-10-23 用户截图抓到）。
            // 选中色仍由我们自己画（系统侧栏会跟随系统强调色，是蓝色），
            // 所以不绑 List 的 selection，避免再叠一层系统高亮。
            List {
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
                        .padding(.vertical, 5)
                        .padding(.horizontal, 8)
                        .contentShape(RoundedRectangle(cornerRadius: 7))
                    }
                    .buttonStyle(.plain)
                    .listRowInsets(EdgeInsets(top: 1, leading: 6, bottom: 1, trailing: 6))
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
            .navigationSplitViewColumnWidth(min: 168, ideal: 186, max: 240)
            .onAppear {
                // 试过"启动时预热内核"（并行 spawn 21 MB 的 PyInstaller 包）：
                // 实测反而更慢（684–734 ms → 962–1572 ms），因为进程启动与首屏渲染抢 CPU。
                // 已回退；详见 docs/acceptance-2026-10-23.md。
                MainWindow.healSplitFramesIfNeeded()
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
