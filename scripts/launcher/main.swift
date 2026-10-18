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

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        guard let url = startBackend() else {
            presentError("无法启动本地服务。\n请先在终端运行：\n  cd \(repo) && ./bin/maccleaner ui --no-open")
            return
        }
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
        process.standardError = FileHandle.nullDevice

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
        webView.setValue(false, forKey: "drawsBackground")
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
