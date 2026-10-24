import SwiftUI

/// 支持的语言。新增语言：加一个 case + 在 `L10n.strings` 里补一列即可。
enum AppLanguage: String, CaseIterable, Identifiable {
    case zh
    case en

    var id: String { rawValue }
    /// 语言自己的名字（不翻译，永远认得出）。
    var endonym: String {
        switch self {
        case .zh: return "中文"
        case .en: return "English"
        }
    }
}

/// 极简本地化。
///
/// 为什么不用 `.strings` 资源包：这套 UI 全是代码里的字符串常量，
/// 走 Bundle 本地化要先把每一处改成 `NSLocalizedString`，改动面一样大，
/// 却把文案拆到了看不见的资源文件里。用一个字典，改文案就在代码旁边。
enum L10n {
    /// key → (中文, English)
    static let strings: [String: (zh: String, en: String)] = [
        // 侧栏
        "nav.clean": ("清理", "Clean"),
        "nav.software": ("软件", "Apps"),
        "nav.disk": ("磁盘", "Disk"),
        "nav.system": ("系统", "System"),
        "nav.ai": ("AI", "AI"),
        "nav.language": ("语言", "Language"),

        // 页头
        "clean.title": ("清理", "Clean"),
        "clean.subtitle": ("缓存、日志与开发工具；只读扫描，删除前会确认",
                           "Caches, logs and dev tools. Read-only scan; nothing is removed before you confirm."),
        "software.title": ("软件", "Apps"),
        "software.subtitle": ("卸载残留、检查更新、清理孤儿文件",
                              "Uninstall leftovers, check updates, clean orphan files."),
        "disk.title": ("磁盘", "Disk"),
        "disk.subtitle": ("整机容量、目录构成与系统级占用",
                          "Capacity, folder breakdown and system-level usage."),
        "system.title": ("系统", "System"),
        "system.subtitle": ("负载、内存、电池与进程",
                            "Load, memory, battery and processes."),
        "ai.title": ("AI 能力", "AI Access"),
        "ai.subtitle": ("agent 可直接调用的工具：MCP 与 stdio 命令",
                        "Tools agents can call directly: MCP and stdio commands."),

        // 分段 / 芯片
        "tab.recommended": ("推荐清理", "Recommended"),
        "tab.large": ("大文件", "Large files"),
        "tab.uninstall": ("卸载", "Uninstall"),
        "tab.updates": ("更新", "Updates"),
        "tab.orphans": ("残留", "Leftovers"),
        "tab.catalog": ("可调用", "Callable"),
        "tab.skills": ("软件 Skill", "App skills"),

        // 常用控件
        "common.selectAll": ("全选", "Select all"),
        "common.allStatus": ("全部状态", "All states"),
        "common.allCategory": ("全部分类", "All categories"),
        "common.clearFilter": ("清除筛选（状态与分类一起清）", "Clear filters (state and category)"),
        "common.status": ("已选", "Selected"),
        "common.updated": ("读取于", "Read at"),
        "common.sampled": ("采样于", "Sampled at"),
        "common.checkedAt": ("检查于", "Checked at"),

        // 动作按钮
        "action.clean": ("清理", "Clean"),
        "action.uninstall": ("卸载", "Uninstall"),
        "action.update": ("更新", "Update"),
        "action.trash": ("移入废纸篓", "Move to Trash"),
        "action.open": ("打开", "Open"),
        "action.openSettings": ("打开设置", "Open Settings"),
        "action.retry": ("重试", "Retry"),
        "action.cancel": ("取消", "Cancel"),
        "action.close": ("关闭", "Close"),
    ]

    /// 取文案；缺 key 时返回 key 本身（便于发现遗漏，而不是显示空白）。
    static func t(_ key: String, _ language: String) -> String {
        guard let entry = strings[key] else { return key }
        return language == "en" ? entry.en : entry.zh
    }
}

// MARK: - 让任意视图通过环境读语言

private struct AppLanguageKey: EnvironmentKey {
    static let defaultValue = AppLanguage.zh.rawValue
}

extension EnvironmentValues {
    var appLanguage: String {
        get { self[AppLanguageKey.self] }
        set { self[AppLanguageKey.self] = newValue }
    }
}

/// 视图里的简写：`Text(L("nav.clean"))`。
struct L: View {
    let key: String
    @Environment(\.appLanguage) private var language

    init(_ key: String) { self.key = key }

    var body: some View {
        Text(L10n.t(key, language))
    }
}

extension View {
    /// 读语言后直接拿字符串（用于 Label / 按钮标题等非 Text 场景）。
    func localized(_ key: String, language: String) -> String {
        L10n.t(key, language)
    }
}
