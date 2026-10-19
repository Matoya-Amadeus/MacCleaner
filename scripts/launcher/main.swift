// MacCleaner 原生外壳（2026-10-18）。
//
// 为什么需要它：`maccleaner ui` 起的是本机 loopback 服务，用 `webbrowser.open()` 会**跳到浏览器**——
// 用户双击图标期待的是一个 app 窗口，不是一堆浏览器标签。这里用 WKWebView 开一个真窗口，
// 页面仍然来自同一个 loopback 服务（安全模型不变：只听 127.0.0.1、一次性 bootstrap、CSRF 双凭据）。
//
// 生命周期：窗口关闭 → 终止后端子进程；后端意外退出 → 窗口显示"后端已退出"。
import Cocoa
import Darwin
import WebKit

let app = NSApplication.shared
app.setActivationPolicy(.regular)

let repoKey = "MacCleanerRepo"
let repoPath = (Bundle.main.object(forInfoDictionaryKey: repoKey) as? String) ?? ""
let fallbackRepo = "/Users/you/Workspace/Github/MacCleaner"

final class Delegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, NSWindowDelegate {
    var window: NSWindow?
    var webView: WKWebView?
    var backend: Process?
    var errorPipe: Pipe?
    var smokeStarted = false
    var snapshotTaken = false

    /// 读后端失败时的 stderr（最多 400 字符），给提示框用。
    func backendErrorText() -> String {
        guard let pipe = errorPipe else { return "" }
        let data = pipe.fileHandleForReading.availableData
        let text = String(data: data, encoding: .utf8) ?? ""
        return String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(400))
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        guard let url = startBackend() else {
            log("applicationDidFinishLaunching: startBackend returned nil")
            let reason = backendErrorText()
            // 最常见的两种：单会话锁被占（旧窗口/孤儿进程）、后端崩了。两者都要把原因说清。
            presentError(
                reason.isEmpty
                    ? "本地服务没能起来。\n可能已有一个 MacCleaner 窗口在运行；\n也可以先退出它，或重启本应用。"
                    : "本地服务没能起来：\n\(reason)"
            )
            return
        }
        log("backend url=\(url.absoluteString)")
        showWindow(url: url)
    }

    var repo: String {
        repoPath.isEmpty ? fallbackRepo : repoPath
    }

    /// 起后端并同步读取入口 URL（后端第一行就是 URL，见 cli.py 的 `ui` 子命令）。
    func startBackend() -> URL? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        var arguments = ["python3", "-m", "maccleaner", "ui", "--no-open"]
        // 自测用：真实 HOME（这样应用列表/skill 根都是用户真实的）但状态隔离到临时目录，
        // 不污染 ~/.maccleaner、也不会撞上单会话锁。
        if let stateRoot = ProcessInfo.processInfo.environment["MACCLEANER_STATE_ROOT"], !stateRoot.isEmpty {
            arguments += ["--state-root", stateRoot]
        }
        // 自测用：把"扫哪里"指到临时目录，这样点【确认清理】也只动临时文件（真实 HOME 不受影响）。
        if let scanHome = ProcessInfo.processInfo.environment["MACCLEANER_SCAN_HOME"], !scanHome.isEmpty {
            arguments += ["--home", scanHome, "--root", scanHome]
        }
        process.arguments = arguments
        process.currentDirectoryURL = URL(fileURLWithPath: repo)

        var environment = ProcessInfo.processInfo.environment
        let srcPath = repo + "/src"
        environment["PYTHONPATH"] = environment["PYTHONPATH"].map { srcPath + ":" + $0 } ?? srcPath
        environment["no_proxy"] = "*"
        environment["NO_PROXY"] = "*"
        // 父进程被强杀时跑不到 applicationWillTerminate，子进程会留下来占着会话锁；
        // 后端据此监视 ppid，发现被收养就自行退出。
        environment["MACCLEANER_PARENT_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        process.environment = environment

        let pipe = Pipe()
        process.standardOutput = pipe
        // 后端失败时把 stderr 收下来——"已有一个会话在运行"这类原因必须让用户看见，
        // 否则他只会看到一句笼统的"启动失败"。
        let errPipe = Pipe()
        process.standardError = errPipe
        errorPipe = errPipe

        do {
            try process.run()
        } catch {
            return nil
        }
        backend = process
        process.terminationHandler = { finished in
            self.log("backend exited code=\(finished.terminationStatus)")
        }

        // 读到第一行 http:// 为止；15 秒还没出来就认为失败（不让 UI 无限等）。
        let deadline = Date().addingTimeInterval(15)
        var buffer = Data()
        log("startBackend: waiting for url")
        while Date() < deadline {
            let chunk = pipe.fileHandleForReading.availableData
            if chunk.isEmpty {
                log("startBackend: EOF (child likely exited)")
                break
            }
            buffer.append(chunk)
            if let text = String(data: buffer, encoding: .utf8),
               let line = text.split(separator: "\n").first(where: { $0.hasPrefix("http://") }),
               let url = URL(string: String(line)) {
                // 拿到地址还不够：进程可能刚打印就退出了（会话锁冲突就是这种）。
                // 这里等到端口真的能连，才把页面装进窗口——避免"Could not connect"掩盖真实原因。
                if waitForPort(url) {
                    return url
                }
                log("port on \(url.port ?? 0) never opened")
                return nil
            }
        }
        log("startBackend: no url within deadline")
        return nil
    }

    /// 用 POSIX connect 探端口（不用 URLSession：那会被 ATS 拦住，反而误判）。
    func waitForPort(_ url: URL, timeout: TimeInterval = 6) -> Bool {
        guard let port = url.port, let host = url.host else { return false }
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let process = backend, !process.isRunning {
                log("backend died before the port opened")
                return false
            }
            if portIsOpen(host: host, port: UInt16(port)) { return true }
            Thread.sleep(forTimeInterval: 0.2)
        }
        return false
    }

    func portIsOpen(host: String, port: UInt16) -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return false }
        defer { close(descriptor) }
        var address = sockaddr_in()
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        guard inet_pton(AF_INET, host, &address.sin_addr) == 1 else { return false }
        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketPointer in
                connect(descriptor, socketPointer, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    func showWindow(url: URL) {
        let frame = NSRect(x: 0, y: 0, width: 1080, height: 760)
        let window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "MacCleaner"
        window.center()
        window.delegate = self
        window.setFrameAutosaveName("MacCleanerMain")

        let webView = WKWebView(frame: frame)
        webView.navigationDelegate = self
        window.contentView = webView
        webView.load(URLRequest(url: url))

        window.makeKeyAndOrderFront(nil)
        self.window = window
        self.webView = webView
        app.activate(ignoringOtherApps: true)
    }

    func presentError(_ message: String) {
        // 提示文本也写日志：否则"用户看到的到底是什么"永远无法自动核对
        // （2026-10-18：我只知道进程退出了，不知道对话框说了什么）。
        log("alert: " + message.replacingOccurrences(of: "\n", with: " / "))
        let alert = NSAlert()
        alert.messageText = "MacCleaner 启动失败"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
        app.terminate(nil)
    }

    func installMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 MacCleaner", action: nil, keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "退出 MacCleaner", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        app.mainMenu = mainMenu
    }

    // ---- 加载结果自证（2026-10-18：用户遇到黑屏，而我上一轮只验了"进程在跑"）----
    //
    // 教训：进程活着 ≠ 页面渲染了。WKWebView 默认禁止 http://（ATS），失败时**不报错、只是白/黑**。
    // 所以这里把"加载完成"和"加载失败"都写到日志，并用 JS 读一次 data-stage 证明 HTML 真的跑起来了。

    func log(_ message: String) {
        let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        let dir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/MacCleaner", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("launcher.log")
        if let handle = try? FileHandle(forWritingTo: file) {
            handle.seekToEndOfFile()
            handle.write(line.data(using: .utf8) ?? Data())
            try? handle.close()
        } else {
            try? line.write(to: file, atomically: true, encoding: .utf8)
        }
    }


    /// 自测模式（MACCLEANER_SMOKE=1）：在**真实 WKWebView 里**依次点侧栏四个入口，
    /// 每步读一次 `data-stage` 并截图。这是"我自己实际操作一遍"的证据，而不是"看起来能跑"。
    func runSmoke() {
        // (期望 stage, 要点的动作, 额外等待条件)：`updates` 会先出进度页，再出列表——
        // 只等 stage 会截到"正在检查更新"，看不出列表到底有没有渲染出来。
        // 每步除了 stage，还要探一个**内容计数**：只验 stage 会漏掉"页签切了但内容是空的"
        // （2026-10-19 用户指出的正是这一点）。
        let steps: [(String, String, String, String)] = [
            ("idle", "", "", "document.querySelectorAll('.side-item').length"),
            ("updates", "updates-open", "!!document.querySelector('[data-update-id]')",
             "document.querySelectorAll('[data-update-id]').length"),
            ("uninstall-list", "uninstall-list", "",
             "document.querySelectorAll('.row').length"),
            ("skills", "skills-open", "", "document.querySelectorAll('.row').length"),
            // 扫描优化后（26.5s → 0.7s）这一步可以要求**真的到审阅页**，而不只是"有反应"。
            // 审阅页现在是勾选行：按勾选框计数（`.row` 也会匹配到 label，但语义不直接）
            ("review", "start", "", "document.querySelectorAll('[data-target-id]').length"),
            // 后面两步是**破坏性路径**：真点【开始清理】→【确认清理】。自测的 home 是临时目录，
            // 所以真的会移动文件——这正是"验收要自己操作一遍"的意思。
            ("confirming", "approval", "", "document.querySelectorAll('.button').length"),
            ("complete", "confirm", "", "document.querySelectorAll('.stat').length"),
        ]
        var index = 0

        func next() {
            guard index < steps.count else {
                log("smoke done")
                app.terminate(nil)
                return
            }
            let (expected, action, marker, probe) = steps[index]
            index += 1

            func currentStage(_ done: @escaping (String) -> Void) {
                webView?.evaluateJavaScript("document.documentElement.dataset.stage || '(none)'") { value, _ in
                    done(value as? String ?? "nil")
                }
            }

            // 轮询到 stage 真的变了再判定：`updates-open` 会跑真实 `brew outdated`（数秒到十几秒），
            // 固定 sleep 会把"慢"误判成"坏"（2026-10-18 实测过一次）。
            func waitForChange(previous: String, attempt: Int) {
                currentStage { stage in
                    let stageOK = stage == expected || attempt >= 25
                    if stageOK && (!marker.isEmpty) && attempt < 40 {
                        self.webView?.evaluateJavaScript(marker) { value, _ in
                            if (value as? Bool) == true {
                                self.capture(index: index, expected: expected, actual: stage, probe: probe) { next() }
                            } else {
                                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                                    waitForChange(previous: previous, attempt: attempt + 1)
                                }
                            }
                        }
                        return
                    }
                    if stageOK {
                        self.capture(index: index, expected: expected, actual: stage, probe: probe) { next() }
                        return
                    }
                    _ = previous
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                        waitForChange(previous: previous, attempt: attempt + 1)
                    }
                }
            }

            if action.isEmpty {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                    currentStage { self.capture(index: index, expected: expected, actual: $0, probe: probe) { next() } }
                }
                return
            }

            currentStage { before in
                self.webView?.evaluateJavaScript(
                    // 点按钮而不是直接调 API：按钮的点击处理器会收集当前勾选的 id
                    // （清理的批准必须带 approved_ids，直接传 {} 等于"一组都没选"）。
                    "var __b=document.querySelector('[data-bridge-action=\"\(action)\"]')"
    + " || document.querySelector('[data-nav-action=\"\(action)\"]'); if(__b){__b.click();'clicked'}else{'missing'}"
                    ) { value, _ in
                    if let flag = value as? String, flag == "missing" { self.log("smoke click \(action): button not found") }
                    waitForChange(previous: before, attempt: 0)
                }
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { next() }
    }

    func capture(index: Int, expected: String, actual: String, probe: String = "",
                 then next: @escaping () -> Void) {
        if probe.isEmpty {
            log("smoke step \(index): expected=\(expected) actual=\(actual)")
        } else {
            webView?.evaluateJavaScript(probe) { value, _ in
                let count = (value as? NSNumber)?.intValue ?? -1
                self.log("smoke step \(index): expected=\(expected) actual=\(actual) content=\(count)")
                self.snapshot(index: index, actual: actual, then: next)
            }
            return
        }
        snapshot(index: index, actual: actual, then: next)
    }

    func snapshot(index: Int, actual: String, then next: @escaping () -> Void) {
        guard let webView = webView else { next(); return }
        webView.takeSnapshot(with: WKSnapshotConfiguration()) { image, _ in
            if let image = image, let tiff = image.tiffRepresentation,
               let rep = NSBitmapImageRep(data: tiff),
               let png = rep.representation(using: .png, properties: [:]) {
                let dir = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Logs/MacCleaner", isDirectory: true)
                try? png.write(to: dir.appendingPathComponent("smoke-\(index)-\(actual).png"))
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { next() }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript("document.documentElement.dataset.stage || '(none)'") { value, error in
            if let error = error {
                self.log("loaded but eval failed: \(error.localizedDescription)")
            } else {
                self.log("loaded stage=\(value ?? "nil")")
            }
        }
        // 只跑一次：didFinish 会在**每次页面刷新**时触发，不加这个标志自测会被反复启动、互相干扰
        // （2026-10-18 实测：日志里出现几十条重复步骤）。
        if ProcessInfo.processInfo.environment["MACCLEANER_SMOKE"] == "1", !smokeStarted {
            smokeStarted = true
            runSmoke()
            return
        }
        // 只拍一次：进度页会自刷，每刷一次都截图会刷屏（2026-10-19 日志里出现过）。
        if snapshotTaken { return }
        snapshotTaken = true
        // 自证渲染：等一帧后把窗口内容截成 PNG。用户上一轮遇到黑屏，而我当时只看到"进程在跑"。
        // 这张图是"页面真的有内容"的证据，也可用于以后的自动验收。
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            let config = WKSnapshotConfiguration()
            webView.takeSnapshot(with: config) { image, error in
                guard let image = image,
                      let tiff = image.tiffRepresentation,
                      let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    self.log("snapshot failed: \(error?.localizedDescription ?? "unknown")")
                    return
                }
                let dir = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Logs/MacCleaner", isDirectory: true)
                try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let file = dir.appendingPathComponent("launcher-snapshot.png")
                try? png.write(to: file)
                self.log("snapshot ok \(Int(image.size.width))x\(Int(image.size.height)) -> \(file.path)")
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        log("navigation failed: \(error.localizedDescription)")
        presentError("页面加载失败：\(error.localizedDescription)")
    }

    func webView(
        _ webView: WKWebView,
        didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: Error
    ) {
        log("provisional navigation failed: \(error.localizedDescription)")
        presentError("页面加载失败：\(error.localizedDescription)")
    }

    func windowWillClose(_ notification: Notification) {
        app.terminate(nil)
    }

    func applicationWillTerminate(_ notification: Notification) {
        backend?.terminate()
    }
}

let delegate = Delegate()
app.delegate = delegate
app.run()
