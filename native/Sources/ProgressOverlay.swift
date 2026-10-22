import SwiftUI

/// 长操作的计时器：**纯客户端**，不依赖内核推送。
///
/// 为什么还要计时（协议里已经有 `started` 事件）：事件只告诉你"开始了"，
/// 用户想知道的是"多久了、是不是卡住了"。0.3 秒没有回声就会被当成"点了没反应"
/// —— 这个教训在旧界面上踩过三次（侧栏首次点击、点卸载、进度页计时归零）。
@MainActor
final class ElapsedTimer: ObservableObject {
    @Published private(set) var seconds = 0
    private var task: Task<Void, Never>?

    func start() {
        stop()
        seconds = 0
        task = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                guard !Task.isCancelled, let self else { return }
                self.seconds += 1
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    deinit { task?.cancel() }
}

/// 遮罩式进度：把整块区域盖住，明确告诉用户"正在做，别重复点"。
struct ProgressOverlay: View {
    let title: String
    let detail: String?
    /// 只有**真的支持取消**的操作才传（内核每项开始前检查一次标志）。
    /// 不支持的操作用户按了也停不下来——那是骗人。
    var onCancel: (() -> Void)?
    @ObservedObject var timer: ElapsedTimer

    var body: some View {
        ZStack {
            Color.black.opacity(0.08).ignoresSafeArea()
            VStack(spacing: 10) {
                ProgressView().controlSize(.large)
                Text(title).font(.callout.weight(.medium))
                if let detail {
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                }
                Text("已用 \(timer.seconds) 秒")
                    .font(.caption2).monospacedDigit().foregroundStyle(.tertiary)
                if let onCancel {
                    Button("取消", action: onCancel)
                        .controlSize(.small)
                        .padding(.top, 2)
                }
            }
            .padding(22)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
            .shadow(radius: 12, y: 4)
        }
        .transition(.opacity)
    }
}

extension View {
    /// `busy` 时盖上进度层；`title` 写清"正在做什么"，别只写"处理中"。
    func progressOverlay(
        _ busy: Bool,
        title: String,
        detail: String? = nil,
        onCancel: (() -> Void)? = nil,
        timer: ElapsedTimer
    ) -> some View {
        overlay {
            if busy {
                ProgressOverlay(title: title, detail: detail, onCancel: onCancel, timer: timer)
            }
        }
        .disabled(busy)
    }
}
