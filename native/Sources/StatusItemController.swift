import AppKit

/// 菜单栏图标（可选）。
///
/// 为什么不用 SwiftUI 的 `MenuBarExtra`：它一旦写进 `Scene` 就没法开关，
/// 而这台机器的菜单栏已经很挤——图标会落进系统的隐藏区，用户找不到还以为没做。
/// 用 `NSStatusItem` 手动管理，就能给一个"显示/隐藏"的开关。
@MainActor
final class StatusItemController: NSObject {
    static let shared = StatusItemController()
    static let visibilityKey = "showMenuBarIcon"

    private var item: NSStatusItem?

    var isEnabled: Bool {
        UserDefaults.standard.object(forKey: Self.visibilityKey) as? Bool ?? true
    }

    func sync() {
        if isEnabled { install() } else { remove() }
    }

    func toggle() {
        UserDefaults.standard.set(!isEnabled, forKey: Self.visibilityKey)
        sync()
    }

    private func install() {
        guard item == nil else { return }
        let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        status.button?.image = NSImage(
            systemSymbolName: "internaldrive",
            accessibilityDescription: "Mac Cleaner"
        )
        status.button?.toolTip = "Mac Cleaner"
        status.menu = buildMenu()
        item = status
    }

    private func remove() {
        if let item {
            NSStatusBar.system.removeStatusItem(item)
        }
        item = nil
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()
        menu.addItem(withTitle: "打开 Mac Cleaner", action: #selector(openMain), keyEquivalent: "o")
            .target = self
        menu.addItem(.separator())

        let summary = UserDefaults.standard.string(forKey: RecentActivity.key) ?? ""
        let label = NSMenuItem(
            title: summary.isEmpty ? "还没有操作记录" : summary,
            action: nil,
            keyEquivalent: ""
        )
        label.isEnabled = false
        menu.addItem(label)

        menu.addItem(.separator())
        menu.addItem(withTitle: "退出", action: #selector(quit), keyEquivalent: "q").target = self
        return menu
    }

    @objc private func openMain() {
        MainWindow.show()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}
