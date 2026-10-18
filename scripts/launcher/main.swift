// MacCleaner 原生外壳（2026-10-18）。
//
// 为什么需要它：`maccleaner ui` 起的是本机 loopback 服务，用 `webbrowser.open()` 会**跳到浏览器**——
// 用户双击图标期待的是一个 app 窗口，不是一堆浏览器标签。这里用 WKWebView 开一个真窗口，
// 页面仍然来自同一个 loopback 服务（安全模型不变：只听 127.0.0.1、一次性 bootstrap、CSRF 双凭据）。
//
// 生命周期：窗口关闭 → 终止后端子进程；后端意外退出 → 窗口显示"后端已退出"。
import Cocoa
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
            let reason = backendErrorText()
            presentError(
                reason.isEmpty
                    ? "无法启动本地服务。\n请先在终端运行：\n  cd \(repo) && ./bin/maccleaner ui --no-open"
                    : "后端没有起来：\n\(reason)"
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
        process.arguments = ["python3", "-m", "maccleaner", "ui", "--no-open"]
        process.currentDirectoryURL = URL(fileURLWithPath: repo)

        var environment = ProcessInfo.processInfo.environment
        let srcPath = repo + "/src"
        environment["PYTHONPATH"] = environment["PYTHONPATH"].map { srcPath + ":" + $0 } ?? srcPath
        environment["no_proxy"] = "*"
        environment["NO_PROXY"] = "*"
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

        // 读到第一行 http:// 为止；15 秒还没出来就认为失败（不让 UI 无限等）。
        let deadline = Date().addingTimeInterval(15)
        var buffer = Data()
        while Date() < deadline {
            let chunk = pipe.fileHandleForReading.availableData
            if chunk.isEmpty { break }
            buffer.append(chunk)
            if let text = String(data: buffer, encoding: .utf8),
               let line = text.split(separator: "\n").first(where: { $0.hasPrefix("http://") }) {
                return URL(string: String(line))
            }
        }
        return nil
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

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript("document.documentElement.dataset.stage || '(none)'") { value, error in
            if let error = error {
                self.log("loaded but eval failed: \(error.localizedDescription)")
            } else {
                self.log("loaded stage=\(value ?? "nil")")
            }
        }
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
