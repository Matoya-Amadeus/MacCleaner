import AppKit
import Combine
import SwiftUI

/// 磁盘：容量 + 目录清单 + 系统级目录（只读，需授权才有准确数字）。
///
/// 沿用旧界面的产品结论：**这一页是展示页，不下钻**；一条整机容量条，其余都是文字数字。
struct DiskView: View {
    @State private var report: Report?
    @State private var system: SystemBlock?
    @State private var error: String?
    @State private var measuring = false
    @State private var loading = false
    @State private var needsPermission = false
    @State private var loadedAt: Date?

    struct Entry: Identifiable {
        let id = UUID()
        let name: String
        let path: String
        let bytes: Int64
    }

    struct SystemBlock {
        let admin: Bool
        let cached: Bool
        let sizes: [(path: String, bytes: Int64)]
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    struct Report {
        let total: Int64
        let used: Int64
        let free: Int64
        let percent: Double
        let sections: [Entry]
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }

                if needsPermission {
                    permissionBanner
                }

                if let report {
                    header(report)
                    directoryList(report.sections)
                } else if loading {
                    ProgressView("读取磁盘…").frame(maxWidth: .infinity, alignment: .center).padding(.top, 60)
                }

                systemSection
            }
            .padding(28)
            .frame(maxWidth: 880, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task { await load() }
        .onReceive(NotificationCenter.default.publisher(for: .mcReload)) { _ in
            Task { await load() }
        }
        // 回到前台时重读一次：磁盘占用变化慢，但"切走再回来还是旧数字"会让人怀疑。
        // 只在这一页做（系统状态页按决定保持"进页面读一次"）。
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            guard !measuring else { return }
            Task { await load() }
        }
    }

    /// 探测「完全磁盘访问权限」：读 TCC 数据库是最可靠的探针（无权限必然失败）。
    nonisolated static func hasFullDiskAccess() -> Bool {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let probe = home.appendingPathComponent("Library/Application Support/com.apple.TCC/TCC.db")
        guard let handle = try? FileHandle(forReadingFrom: probe) else { return false }
        defer { try? handle.close() }
        _ = try? handle.read(upToCount: 1)
        return true
    }

    private var permissionBanner: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "lock.trianglebadge.exclamationmark")
                .font(.title3)
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 6) {
                Text("读不到目录体积：需要「完全磁盘访问权限」").font(.callout.weight(.semibold))
                Text("系统会保护 macOS 与「个人文件夹」里的内容。授权一次即可，随时可在系统设置里撤销。")
                    .font(.caption).foregroundStyle(.secondary)
                Button("打开「完全磁盘访问权限」设置") {
                    if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
                        NSWorkspace.shared.open(url)
                    }
                }
                .controlSize(.small)
                .padding(.top, 2)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 10))
    }

    // MARK: - 区块

    private func header(_ report: Report) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("\(Int(report.percent.rounded()))%")
                .font(.system(size: 44, weight: .semibold, design: .rounded))
                .monospacedDigit()
            HStack(spacing: 10) {
                Text("已用 \(ByteText.format(report.used))，可用 \(ByteText.format(report.free))（共 \(ByteText.format(report.total))）")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                if let loadedAt {
                    // 不加【刷新】按钮（前面已删），改成把"什么时候读的"写出来：
                    // 数字看起来不再像实时监控，用户自己决定要不要切走再回来。
                    Text("读取于 \(Self.clock.string(from: loadedAt))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            // 只有这一条条：整机占比。目录行不再画条（同一根条两种基准会被误读）。
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.15))
                    Capsule()
                        .fill(Color.accentColor)
                        .frame(width: max(4, geometry.size.width * min(1, report.percent / 100)))
                }
            }
            .frame(height: 8)
            .padding(.top, 2)
        }
    }

    private func directoryList(_ sections: [Entry]) -> some View {
        VStack(spacing: 0) {
            ForEach(sections) { entry in
                HStack(spacing: 10) {
                    Image(systemName: Symbol.folder(for: entry.name))
                        .frame(width: 20)
                        .foregroundStyle(.secondary)
                    Text(entry.name).lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 12)
                    Text(ByteText.format(entry.bytes))
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 9)
                .padding(.horizontal, 4)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(entry.name)，\(ByteText.format(entry.bytes))")
                if entry.id != sections.last?.id { Divider().opacity(0.5) }
            }
        }
    }

    @ViewBuilder
    private var systemSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "lock.shield").foregroundStyle(.secondary)
                Text("系统级目录").font(.headline)
                Text(system?.admin == true ? "一次性授权" : "只读")
                    .font(.caption)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Color.secondary.opacity(0.12), in: Capsule())
                    .foregroundStyle(.secondary)
            }

            if let system, !system.sizes.isEmpty {
                VStack(spacing: 0) {
                    ForEach(system.sizes, id: \.path) { item in
                        HStack {
                            Text(item.path).lineLimit(1).truncationMode(.middle)
                            Spacer(minLength: 12)
                            Text(ByteText.format(item.bytes)).monospacedDigit().foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 7)
                        Divider().opacity(0.4)
                    }
                }
            } else {
                Text("未测量。授权后可以读到准确体积（只读，不会删除任何东西）。")
                    .font(.callout).foregroundStyle(.secondary)
            }

            Button {
                Task { await measure() }
            } label: {
                if measuring {
                    HStack(spacing: 8) { ProgressView().controlSize(.small); Text("正在测量…") }
                } else {
                    Text(system?.admin == true ? "重新测量（需授权）" : "用管理员授权测量一次（只读）")
                }
            }
            .disabled(measuring)
        }
        .padding(16)
        .background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12).strokeBorder(Color.secondary.opacity(0.18), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
        )
    }

    // MARK: - 数据

    private func load() async {
        loading = true
        defer { loading = false }

        // ① 容量：statfs，毫秒级。哪怕没有权限，首屏也一定有东西看。
        do {
            let summary = try await CoreClient.shared.request("disk.summary")
            report = Report(
                total: summary["total"]?.intValue ?? 0,
                used: summary["used"]?.intValue ?? 0,
                free: summary["free"]?.intValue ?? 0,
                percent: summary["percent"]?.doubleValue ?? 0,
                sections: []
            )
            // 只有 statfs：即使没有完全磁盘访问权限，容量也是真实的，时间戳照样要有。
            loadedAt = Date()
        } catch {
            self.error = error.localizedDescription
            return
        }

        // ② 目录体积：没有「完全磁盘访问权限」就先不读——
        //    否则 macOS 会对每个受保护目录弹一次授权框，界面还会卡住（真机撞到）。
        let isDevRoot = ProcessInfo.processInfo.environment["MACCLEANER_CORE_HOME"] != nil
        guard isDevRoot || Self.hasFullDiskAccess() else {
            needsPermission = true
            return
        }

        do {
            let data = try await CoreClient.shared.request("disk")
            report = Report(
                total: data["total"]?.intValue ?? 0,
                used: data["used"]?.intValue ?? 0,
                free: data["free"]?.intValue ?? 0,
                percent: data["percent"]?.doubleValue ?? 0,
                sections: (data["sections"]?.arrayValue ?? []).compactMap { item in
                    guard let name = item["name"]?.stringValue else { return nil }
                    return Entry(name: name, path: item["path"]?.stringValue ?? "", bytes: item["bytes"]?.intValue ?? 0)
                }.sorted { left, right in
                    left.bytes == right.bytes ? left.name < right.name : left.bytes > right.bytes
                }
            )
            system = parseSystem(data["system"])
            loadedAt = Date()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func measure() async {
        measuring = true
        defer { measuring = false }
        do {
            let data = try await CoreClient.shared.request("system.measure")
            system = parseSystem(data)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func parseSystem(_ value: JSONValue?) -> SystemBlock? {
        guard let value, let object = value.objectValue else { return nil }
        let sizes = (object["sizes"]?.objectValue ?? [:]).compactMap { key, raw -> (path: String, bytes: Int64)? in
            guard let bytes = raw.intValue else { return nil }
            return (key, bytes)
        }.sorted { $0.path < $1.path }
        return SystemBlock(
            admin: object["admin"]?.boolValue ?? false,
            cached: object["cached"]?.boolValue ?? false,
            sizes: sizes
        )
    }
}

enum Symbol {
    /// 常用目录配 SF Symbol：比通用文件夹更容易一眼认出（与旧界面同一套判断）。
    static func folder(for name: String) -> String {
        switch name.lowercased() {
        case "pictures", "photos": return "photo.on.rectangle"
        case "downloads": return "arrow.down.circle"
        case "music": return "music.note"
        case "movies": return "film"
        case "documents": return "doc.text"
        case "desktop": return "display"
        case "applications": return "square.grid.2x2"
        default: return "folder"
        }
    }
}
