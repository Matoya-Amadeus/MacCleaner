import SwiftUI

/// 清理完成页（旧界面那张"释放了多少 / 可恢复多少 / 跳过几项"的收尾屏）。
///
/// 口径全部来自内核 `completion_view()`：
/// - 走废纸篓时 `实际释放 = 0`（空间要清空废纸篓才释放）；
/// - `可恢复` = 真正移进废纸篓的字节；
/// - `跳过` 不含"目标为空"和"用户没勾"两类——那不算异常。
struct CleanCompletion: Identifiable {
    let id = UUID()
    let recoverableBytes: Int64
    let freedBytes: Int64
    let skipped: [(path: String, reason: String)]
    let receiptPath: String
    var cancelled: Bool = false
}

struct CompletionSheet: View {
    let completion: CleanCompletion
    let onClose: () -> Void

    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: completion.cancelled ? "pause.circle.fill" : "checkmark.seal.fill")
                    .font(.title2)
                    .foregroundStyle(completion.cancelled ? .orange : .green)
                Text(completion.cancelled ? "已取消（部分完成）" : "清理完成")
                    .font(.title3.weight(.semibold))
            }

            HStack(alignment: .top, spacing: 14) {
                stat("可恢复", ByteText.format(completion.recoverableBytes), "已移入废纸篓，可恢复")
                stat("已释放", ByteText.format(completion.freedBytes),
                     completion.freedBytes == 0 ? "清空废纸篓后才会释放" : "已经真正腾出")
            }

            if !completion.skipped.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("跳过 \(completion.skipped.count) 项").font(.callout.weight(.medium))
                    ForEach(completion.skipped.prefix(5), id: \.path) { item in
                        HStack(spacing: 6) {
                            Image(systemName: "minus.circle").foregroundStyle(.secondary)
                            Text(displayPath(item.path)).font(.caption).lineLimit(1).truncationMode(.middle)
                            Spacer(minLength: 6)
                            Text(item.reason).font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                    if completion.skipped.count > 5 {
                        Text("另有 \(completion.skipped.count - 5) 项…").font(.caption2).foregroundStyle(.tertiary)
                    }
                }
            }

            // 跳过原因里唯一"用户自己能修"的一种：缺完全磁盘访问。
            // 否则这条会被读成"工具有 bug"，用户还得自己去翻系统设置（2026-11-03 反馈）。
            if permissionSkipped > 0 {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "lock.shield").foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("有 \(permissionSkipped) 项需要「完全磁盘访问权限」")
                            .font(.callout.weight(.medium))
                        Text("Safari / 邮件 / 信息这类 Apple 应用数据被 macOS 保护着，没授权就只能跳过。授权后 App 会自动重启。")
                            .font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 6)
                    Button("去授权") { PermissionStore.shared.openFullDiskAccessSettings() }
                        .controlSize(.small)
                }
                .padding(10)
                .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 8))
            }

            if let error {
                Text(error).font(.caption).foregroundStyle(.red)
            }

            if !completion.receiptPath.isEmpty {
                Text("回执：\(completion.receiptPath)").font(.caption2).foregroundStyle(.tertiary)
                    .lineLimit(1).truncationMode(.middle)
            }

            HStack {
                Button("在 Finder 中打开废纸篓") {
                    Task {
                        do {
                            _ = try await CoreClient.shared.request("trash.open")
                        } catch {
                            self.error = error.localizedDescription
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

    /// 有多少项是被 TCC 挡下的（内核给的原因形如
    /// `permission denied (needs full disk access): ~/Library/Caches/com.apple.Safari`）。
    private var permissionSkipped: Int {
        completion.skipped.filter { item in
            let reason = item.reason.lowercased()
            return reason.contains("full disk access") || reason.contains("not permitted")
        }.count
    }

    private func stat(_ title: String, _ value: String, _ footnote: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title2.weight(.semibold)).monospacedDigit()
            Text(footnote).font(.caption2).foregroundStyle(.tertiary)
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
