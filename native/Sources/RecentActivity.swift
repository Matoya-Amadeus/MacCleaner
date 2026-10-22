import Foundation

/// 最近一次操作的摘要（菜单栏里显示一行）。
///
/// 存 `UserDefaults` 而不是内存：App 退出后菜单栏图标也会消失，
/// 但下次打开时"上次做了什么"仍有价值（例如你关掉窗口只想看结果）。
enum RecentActivity {
    static let key = "lastOperationSummary"

    static func record(_ text: String) {
        let stamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .short)
        UserDefaults.standard.set("\(stamp) · \(text)", forKey: key)
    }
}
