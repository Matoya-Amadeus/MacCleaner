import LocalAuthentication

/// 破坏性操作前的生物识别确认。
///
/// 设计：**不拦死**。
/// - 机器没有 Touch ID / 未设置密码 → `canEvaluatePolicy` 失败 → 返回 `true`（不拦），
///   否则等于在这类机器上禁用功能；
/// - 用户点了取消 / 指纹不匹配 → 返回 `false`（这次不做）；
/// - 过程中出错（比如被系统锁）→ 返回 `false`，宁可让用户再点一次。
enum BiometricGate {
    static func confirm(reason: String) async -> Bool {
        // 开发/验收钩子：无人值守的自动化里没法按指纹，用它跳过（默认关闭）。
        if ProcessInfo.processInfo.environment["MACCLEANER_DEV_NO_BIO"] != nil {
            return true
        }
        let context = LAContext()
        context.localizedCancelTitle = "取消"
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            return true  // 没有可用认证方式：不拦
        }
        do {
            return try await context.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: reason
            )
        } catch let error as LAError {
            // 只有"用户自己的选择/失败"才算拒绝；
            // 其它（系统无效上下文、签名问题等）放行——否则等于在这个环境里禁用功能。
            switch error.code {
            case .userCancel, .userFallback, .authenticationFailed, .biometryLockout:
                return false
            default:
                return true
            }
        } catch {
            return true
        }
    }
}
