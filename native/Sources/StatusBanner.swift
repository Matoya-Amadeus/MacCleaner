import SwiftUI

/// 页面反馈的**唯一**位置：列表上方一条。
///
/// 之前错误是红色 Label、提示是灰色小字、权限是橙色块，散在三处，用户得挨个找。
/// 现在统一成一个组件，只靠颜色/图标区分语义。
enum StatusLevel {
    case info
    case warn
    case error

    var symbol: String {
        switch self {
        case .info: return "info.circle"
        case .warn: return "exclamationmark.triangle"
        case .error: return "xmark.octagon"
        }
    }

    var tint: Color {
        switch self {
        case .info: return .secondary
        case .warn: return .orange
        case .error: return .red
        }
    }
}

struct StatusBanner: View {
    let level: StatusLevel
    let text: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: level.symbol)
                .foregroundStyle(level.tint)
            Text(text)
                .font(.callout)
                .foregroundStyle(level == .info ? .secondary : .primary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .controlSize(.small)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(level.tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(level == .error ? "错误" : level == .warn ? "警告" : "提示")：\(text)")
    }
}
