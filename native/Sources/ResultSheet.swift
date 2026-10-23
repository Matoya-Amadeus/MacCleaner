import SwiftUI

/// 卸载 / 更新 / 残留 三处的“结果页”。
///
/// 三种内核返回的形状不同（`moved/count`、`results[].ok`、`plan_items[].status`），
/// 归一化在 `view_models.result_view()` 里做了；这里只管显示。
struct OperationResult: Identifiable {
    let id = UUID()
    let title: String
    let count: Int
    let bytes: Int64
    let failures: [(path: String, reason: String)]
    let cancelled: Bool
    let canOpenTrash: Bool

    /// 从内核的 `{"result": {...}}` 里解出来；形状不对就返回 nil（界面回落到一行提示）。
    static func from(_ value: JSONValue?, canOpenTrash: Bool) -> OperationResult? {
        guard let value, let object = value.objectValue else { return nil }
        let failures = (object["failures"]?.arrayValue ?? []).compactMap { item -> (String, String)? in
            guard let path = item["path"]?.stringValue else { return nil }
            return (path, item["reason"]?.stringValue ?? "")
        }
        return OperationResult(
            title: object["title"]?.stringValue ?? "完成",
            count: Int(object["count"]?.intValue ?? 0),
            bytes: object["bytes"]?.intValue ?? 0,
            failures: failures.map { (path: $0.0, reason: $0.1) },
            cancelled: object["cancelled"]?.boolValue ?? false,
            canOpenTrash: canOpenTrash
        )
    }
}

struct ResultSheet: View {
    let result: OperationResult
    let onClose: () -> Void

    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: result.cancelled ? "pause.circle.fill" : "checkmark.seal.fill")
                    .font(.title2)
                    .foregroundStyle(result.cancelled ? .orange : .green)
                Text(result.cancelled ? "已取消（部分完成）" : result.title)
                    .font(.title3.weight(.semibold))
            }

            HStack(alignment: .top, spacing: 14) {
                stat("完成", "\(result.count) 项", nil)
                if result.bytes > 0 {
                    stat("体积", ByteText.format(result.bytes), "移入废纸篓可恢复")
                }
                if !result.failures.isEmpty {
                    stat("失败", "\(result.failures.count) 项", "详见下方")
                }
            }

            if !result.failures.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("未完成的项").font(.callout.weight(.medium))
                    ForEach(result.failures.prefix(5), id: \.path) { item in
                        HStack(spacing: 6) {
                            Image(systemName: "xmark.circle").foregroundStyle(.red)
                            Text(displayPath(item.path)).font(.caption).lineLimit(1).truncationMode(.middle)
                            Spacer(minLength: 6)
                            Text(item.reason).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                        }
                    }
                    if result.failures.count > 5 {
                        Text("另有 \(result.failures.count - 5) 项…").font(.caption2).foregroundStyle(.tertiary)
                    }
                    // 权限类失败只报"Permission denied"没法行动——直接给一个入口。
                    if result.failures.contains(where: {
                        $0.reason.contains("App 管理") || $0.reason.contains("Permission")
                            || $0.reason.contains("not permitted")
                    }) {
                        HStack(spacing: 8) {
                            Image(systemName: "lock.shield").foregroundStyle(.orange)
                            Text("修改其它 App 需要「App 管理」权限，授权后再试一次。")
                                .font(.caption2).foregroundStyle(.secondary)
                            Spacer(minLength: 4)
                            Button("打开设置") {
                                // 勾选完回到 App 时自动重启（见 App.swift 的 didBecomeActive）
                                UserDefaults.standard.set(true, forKey: "needsRestartAfterPermission")
                                if let url = URL(string:
                                    "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AppBundles") {
                                    NSWorkspace.shared.open(url)
                                }
                            }
                            .controlSize(.small)
                        }
                        .padding(.top, 4)
                    }
                }
            }

            if let error {
                Text(error).font(.caption).foregroundStyle(.red)
            }

            HStack {
                if result.canOpenTrash {
                    Button("在 Finder 中打开废纸篓") {
                        Task {
                            do {
                                _ = try await CoreClient.shared.request("trash.open")
                            } catch {
                                self.error = error.localizedDescription
                            }
                        }
                    }
                }
                Spacer()
                Button("完成", action: onClose).keyboardShortcut(.defaultAction)
            }
        }
        .padding(22)
        .frame(width: 520)
    }

    private func stat(_ title: String, _ value: String, _ footnote: String?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.weight(.semibold)).monospacedDigit()
            if let footnote {
                Text(footnote).font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.secondary.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
    }

    private func displayPath(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix(home) ? "~" + path.dropFirst(home.count) : path
    }
}
