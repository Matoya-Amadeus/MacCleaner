import AppKit
import UserNotifications

/// 完成通知：只在**App 不在前台**时发。
///
/// 为什么不无条件发：用户正盯着结果页看，再弹一条系统横幅是噪音。
/// 授权被拒 / 系统不支持时全部静默降级——通知是锦上添花，不该影响主流程。
enum Notifier {
    private static var authorized = false
    private static var requested = false

    static func requestIfNeeded() async {
        guard !requested else { return }
        requested = true
        do {
            authorized = try await UNUserNotificationCenter.current()
                .requestAuthorization(options: [.alert, .sound])
        } catch {
            authorized = false
        }
    }

    static func post(title: String, body: String) async {
        guard !NSApp.isActive else { return }   // 前台自己看得到，不打扰
        await requestIfNeeded()
        guard authorized else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )
        try? await UNUserNotificationCenter.current().add(request)
    }
}
