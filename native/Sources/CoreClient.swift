import Foundation

/// 内核进程的客户端：起 `maccleaner-core serve --stdio`，按行收发 JSON。
///
/// 为什么不是 HTTP（2026-10-22 决定）：
/// 走 HTTP 就得**整页刷新**才能拿到新内容，那是"点了没反应 / 转圈 / 闪一下"的总根源。
/// stdio 是一问一答 + 事件流，界面用 SwiftUI 状态就地更新，不需要任何刷新。

struct CoreFailure: Error, LocalizedError {
    let code: String
    let message: String
    var errorDescription: String? { "\(message)（\(code)）" }
}

enum CoreEvent: Sendable {
    case started(op: String)
}

actor CoreClient {
    static let shared = CoreClient()

    private var process: Process?
    private var input: FileHandle?
    private var pending: [String: CheckedContinuation<JSONValue, Error>] = [:]
    private var handlers: [String: @Sendable (CoreEvent) -> Void] = [:]
    private var counter = 0
    private var started = false

    // MARK: - 启动 / 关闭

    func startIfNeeded() throws {
        guard !started else { return }
        guard let binary = Self.locateBinary() else {
            throw CoreFailure(code: "no_core", message: "找不到 maccleaner-core（先跑 scripts/build_core.sh）")
        }

        let process = Process()
        process.executableURL = binary
        // 全局参数必须放在子命令**前面**（argparse 在 `serve` 之后只认它自己的选项——
        // 放错位置内核会直接退出，界面表现为"内核进程已退出"）。
        var arguments: [String] = []
        var environment = ProcessInfo.processInfo.environment
        // 开发/自测：把内核指向假家目录，避免动真机、也避开 TCC（2026-10-22 加）。
        if let home = environment["MACCLEANER_CORE_HOME"], !home.isEmpty {
            arguments += ["--home", home,
                          "--root", environment["MACCLEANER_CORE_ROOT"] ?? home,
                          "--state-root", environment["MACCLEANER_CORE_STATE"] ?? home + "/.state"]
        }
        arguments += ["serve", "--stdio"]
        process.arguments = arguments
        // 子进程要能找到 du / brew / mdfind：把当前 PATH 传下去。
        if environment["PATH"] == nil {
            environment["PATH"] = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        }
        process.environment = environment

        let stdinPipe = Pipe()
        let stdoutPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = FileHandle.nullDevice

        try process.run()
        self.process = process
        self.input = stdinPipe.fileHandleForWriting
        self.started = true

        let handle = stdoutPipe.fileHandleForReading
        Task.detached { [weak self] in
            do {
                for try await line in handle.bytes.lines {
                    await self?.consume(line: line)
                }
            } catch {
                await self?.failAll(error)
            }
            // 流自然结束 = 进程没了：不能让界面继续转圈。
            await self?.failAll(CoreFailure(code: "core_exit", message: "内核进程已退出"))
        }
    }

    func shutdown() {
        process?.terminate()
        process = nil
        input = nil
        started = false
    }

    // MARK: - 请求

    /// 发一个命令，等终态。慢命令会先推 `started` 事件，界面据此显示进度。
    func request(
        _ command: String,
        args: [String: JSONValue] = [:],
        onEvent: (@Sendable (CoreEvent) -> Void)? = nil
    ) async throws -> JSONValue {
        try startIfNeeded()
        counter += 1
        let id = "r\(counter)"

        let payload: [String: JSONValue] = [
            "id": .string(id),
            "cmd": .string(command),
            "args": .object(args),
        ]
        let encoded = try JSONEncoder().encode(payload)
        guard let text = String(data: encoded, encoding: .utf8) else {
            throw CoreFailure(code: "encode", message: "请求编码失败")
        }

        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation
            if let onEvent { handlers[id] = onEvent }
            do {
                try write(text + "\n")
            } catch {
                pending.removeValue(forKey: id)
                handlers.removeValue(forKey: id)
                continuation.resume(throwing: error)
            }
        }
    }

    /// 请求取消正在执行的操作。**不等回复**：内核收到后会置标志，执行循环在下一项前退出。
    func cancelCurrent() {
        try? write("{\"id\":\"-\",\"cmd\":\"cancel\"}\n")
    }

    // MARK: - 内部

    private func write(_ text: String) throws {
        guard let input, let data = text.data(using: .utf8) else {
            throw CoreFailure(code: "no_core", message: "内核进程没起来")
        }
        try input.write(contentsOf: data)
    }

    private func consume(line: String) {
        guard let data = line.data(using: .utf8),
              let root = try? JSONDecoder().decode(JSONValue.self, from: data),
              let object = root.objectValue,
              let id = object["id"]?.stringValue
        else { return }

        if let event = object["event"]?.stringValue {
            guard let handler = handlers[id] else { return }
            handler(.started(op: object["op"]?.stringValue ?? event))
            return
        }

        guard let continuation = pending.removeValue(forKey: id) else { return }
        handlers.removeValue(forKey: id)

        if object["ok"]?.boolValue == true {
            continuation.resume(returning: object["data"] ?? .null)
        } else {
            let code = object["error"]?["code"]?.stringValue ?? "error"
            let message = object["error"]?["message"]?.stringValue ?? "内核返回失败"
            continuation.resume(throwing: CoreFailure(code: code, message: message))
        }
    }

    private func failAll(_ error: Error) {
        for (_, continuation) in pending {
            continuation.resume(throwing: error)
        }
        pending.removeAll()
        handlers.removeAll()
        started = false
    }

    /// 找内核二进制：环境变量优先（开发态），其次 App 内嵌资源，最后仓库 dist/。
    nonisolated static func locateBinary() -> URL? {
        let environment = ProcessInfo.processInfo.environment
        if let path = environment["MACCLEANER_CORE_BINARY"], FileManager.default.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        if let resources = Bundle.main.resourceURL {
            let bundled = resources.appendingPathComponent("core/maccleaner-core")
            if FileManager.default.isExecutableFile(atPath: bundled.path) { return bundled }
        }
        let local = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent("dist/maccleaner-core/maccleaner-core")
        if FileManager.default.isExecutableFile(atPath: local.path) { return local }
        return nil
    }
}
