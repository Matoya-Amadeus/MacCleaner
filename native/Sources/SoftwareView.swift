import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// 软件页：卸载 / 更新 / 残留（原来是三个侧栏入口，2026-10-22 合并）。
struct SoftwareView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case uninstall, updates, orphans
        var id: String { rawValue }
        var titleKey: String {
            switch self {
            case .uninstall: return "tab.uninstall"
            case .updates: return "tab.updates"
            case .orphans: return "tab.orphans"
            }
        }

        var title: String {
            switch self {
            case .uninstall: return L10n.t("tab.uninstall", UserDefaults.standard.string(forKey: "appLanguage") ?? "zh")
            case .updates: return L10n.t("tab.updates", UserDefaults.standard.string(forKey: "appLanguage") ?? "zh")
            case .orphans: return L10n.t("tab.orphans", UserDefaults.standard.string(forKey: "appLanguage") ?? "zh")
            }
        }
    }

    @Environment(\.appLanguage) private var language

    @State private var tab: Tab = .uninstall

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(title: L10n.t("software.title", language), subtitle: L10n.t("software.subtitle", language))

            ChipPicker(options: Tab.allCases.map { ($0, L10n.t($0.titleKey, language)) }, selection: $tab)
                .padding(.bottom, 10)

            switch tab {
            case .uninstall:
                UninstallListView()
            case .updates:
                UpdatesListView()
            case .orphans:
                OrphansListView()
            }
        }
        .onAppear {
            // 开发钩子：MACCLEANER_DEV_TAB=updates|orphans 直接落到对应分段（截图/验收用）。
            if let raw = ProcessInfo.processInfo.environment["MACCLEANER_DEV_TAB"],
               let target = Tab(rawValue: raw) {
                tab = target
            }
        }
    }
}

// MARK: - 卸载（列表 → 残留 → 执行 → 结果）

// MARK: - 更新

struct UpdatesListView: View {
    @State private var groups: [Group] = []
    @State private var sparkle: [Sparkle] = []
    @State private var sparkleRest: [SparkleRest] = []
    @State private var electronUpdates: [ElectronApp] = []
    @State private var undetectable: [Undetectable] = []
    @State private var checked: Set<String> = []
    @State private var loading = false
    @State private var applying = false
    @State private var error: String?
    @State private var notice: String?
    @State private var result: OperationResult?
    @State private var pendingSparkle: [String: String] = [:]   // path → 打开时的版本
    @State private var checkedAt: Date?
    @State private var filter: SelectionFilter = .all
    @State private var category: String?
    @State private var knownVersions: [String: String] = [:]    // path → 当前版本（含"已是最新"的）
    @StateObject private var timer = ElapsedTimer()

    struct Item: Identifiable {
        let id: String          // 内核给的稳定键 manager|kind|name
        let name: String
        let installed: String
        let available: String
    }

    struct Group: Identifiable {
        var id: String { label }
        let label: String
        let items: [Item]
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    struct Sparkle: Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let version: String
        let latest: String
    }

    /// Electron 应用（读包内 app-update.yml，走 latest-mac.yml / GitHub Releases）。
    struct ElectronApp: Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let version: String
        let latest: String
    }

    /// 装了、但没有任何公开更新源（Steam / Adobe / JetBrains…）：只标注，不猜版本。
    struct Undetectable: Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let reason: String
    }

    /// 检查过但没有更新的 Sparkle 应用（含"没有更新源""更新源不可达"）。
    /// 单独展示的理由：整段消失会让人以为"这个功能没做"，而不是"查过了，确实没有"。
    struct SparkleRest: Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let version: String
        let reason: String
    }

    private var allItems: [Item] { groups.flatMap(\.items) }

    var body: some View {
        VStack(spacing: 0) {
            if let error {
                StatusBanner(level: .error, text: error)
            } else if let notice {
                StatusBanner(level: .info, text: notice)
            }

            if loading {
                ProgressView("检查更新…（brew outdated 可能要几秒）")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if groups.isEmpty && sparkle.isEmpty && sparkleRest.isEmpty
                        && electronUpdates.isEmpty && undetectable.isEmpty {
                Text("全部是最新的").foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                HStack(spacing: 12) {
                    SelectAllToggle(
                        isOn: !filteredGroups.isEmpty
                            && filteredGroups.flatMap { $0.items.map(\.id) }.allSatisfy(checked.contains),
                        count: (
                            selected: filteredGroups.flatMap { $0.items.map(\.id) }.filter(checked.contains).count,
                            total: filteredGroups.flatMap { $0.items.map(\.id) }.count
                        )
                    ) { on in
                        let ids = filteredGroups.flatMap { $0.items.map(\.id) }
                        if on { checked.formUnion(ids) } else { checked.subtract(ids) }
                    }
                    FilterBar(status: $filter, category: $category, categories: categories)
                    Spacer()
                }
                .padding(.horizontal, 20)
                .padding(.top, 6)

                List {
                    if !sparkle.isEmpty {
                                                Text("自带更新（Sparkle）· 确认有更新的").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                                                ForEach(sparkle) { app in
                                                    HStack(spacing: 10) {
                                                        Image(systemName: "arrow.triangle.2.circlepath")
                                                            .frame(width: 20).foregroundStyle(.secondary)
                                                        VStack(alignment: .leading, spacing: 1) {
                                                            Text(app.name)
                                                            Text("\(app.version) → \(app.latest)")
                                                                .font(.caption2).foregroundStyle(.secondary)
                                                        }
                                                        Spacer(minLength: 8)
                                                        Button("在应用内更新") { Task { await open(app) } }
                                                            .controlSize(.small)
                                                    }
                                                }
                                            

                    }
                    // 开发钩子：MACCLEANER_DEV_EXTRA_ONLY=1 时只显示 Electron / 无法检测两组，
                    // 方便一屏内验收（brew 那 79 行会把它们顶到屏幕外）。
                    if ProcessInfo.processInfo.environment["MACCLEANER_DEV_EXTRA_ONLY"] == nil {
                    ForEach(filteredGroups) { group in
                                                Text("\(group.label) · \(group.items.count)").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                                                ForEach(group.items) { item in
                                                    Toggle(isOn: Binding(
                                                        get: { checked.contains(item.id) },
                                                        set: { isOn in
                                                            if isOn { checked.insert(item.id) } else { checked.remove(item.id) }
                                                        }
                                                    )) {
                                                        HStack(spacing: 10) {
                                                            Image(systemName: "shippingbox").frame(width: 20).foregroundStyle(.secondary)
                                                            Text(item.name).lineLimit(1)
                                                            Spacer(minLength: 8)
                                                            Text("\(item.installed) → \(item.available)")
                                                                .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                                                        }
                                                    }
                                                    .toggleStyle(.checkbox)
                                                    // App Store 项只能去商店点更新，勾选等于骗人。
                                                    .disabled(item.id.hasPrefix("mas|"))
                                                }
                                            

                    }

                    }

                    if !sparkleRest.isEmpty, category == nil || category == "App 更新检查" {
                        Text("App 更新检查 · \(sparkleRest.count)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                        ForEach(sparkleRest) { item in
                            HStack(spacing: 10) {
                                Image(systemName: "checkmark.seal")
                                    .frame(width: 20)
                                    .foregroundStyle(.secondary)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(item.name).lineLimit(1)
                                    Text("\(item.version) · \(item.reason)")
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                        .lineLimit(1)
                                }
                                Spacer(minLength: 8)
                            }
                        }
                    }
                    if !electronUpdates.isEmpty, category == nil || category == "Electron 应用" {
                        Text("Electron 应用 · \(electronUpdates.count)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                        ForEach(electronUpdates) { item in
                            HStack(spacing: 10) {
                                Image(systemName: "bolt.horizontal.circle")
                                    .frame(width: 20)
                                    .foregroundStyle(Theme.accent)
                                Text(item.name).lineLimit(1)
                                Spacer(minLength: 8)
                                Text("\(item.version) → \(item.latest)")
                                    .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                            }
                        }
                    }

                    if !undetectable.isEmpty, category == nil || category == "无法自动检测" {
                        Text("无法自动检测 · \(undetectable.count)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                        Text("这些应用由自身更新（Steam、Adobe、JetBrains 等），没有公开更新源；不猜版本。")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                            .padding(.vertical, 2)
                        ForEach(undetectable) { item in
                            HStack(spacing: 10) {
                                Image(systemName: "minus.circle")
                                    .frame(width: 20)
                                    .foregroundStyle(.tertiary)
                                Text(item.name).lineLimit(1)
                                Spacer(minLength: 8)
                                Text(item.reason).font(.caption2).foregroundStyle(.tertiary)
                                // 查不到版本不等于帮不上忙：这些应用都自带更新器，
                                // 打开它就能触发"检查更新"（AppSweep / Greypaint 的做法）。
                                Button("打开") { Task { await openSelfUpdating(item) } }
                                    .controlSize(.small)
                            }
                        }
                    }
                }
                .listStyle(.inset)
            }

            Divider()
            HStack {
                // 79 项里混着 App Store 项（我们只能打开商店，不能替你点"更新"）。
                // 单独说出来，避免"说 79 项可更新、其实有 1 项做不到"（2026-10-23 反馈）。
                let autoItems = allItems.filter { !$0.id.hasPrefix("mas|") }
                let manualCount = allItems.count - autoItems.count
                let autoChecked = checked.filter { id in autoItems.contains { $0.id == id } }.count
                Text("已选 \(autoChecked) / \(autoItems.count) 项可自动更新"
                     + (manualCount > 0 ? " · 另有 \(manualCount) 项需在 App Store 更新" : "")
                     + (checkedAt.map { " · 检查于 \(Self.clock.string(from: $0))" } ?? ""))
                    .font(.callout.weight(.medium)).monospacedDigit()
                Spacer()
                Button {
                    Task { await apply() }
                } label: {
                    if applying { ProgressView().controlSize(.small) }
                    else { Text(checked.isEmpty ? "更新" : "更新 \(checked.count) 项") }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(checked.isEmpty || applying)
            }
            .padding(16)
        }
        .task { if groups.isEmpty && sparkle.isEmpty { await load() } }
        .progressOverlay(applying, title: "正在更新…", detail: "在当前这条命令跑完后停下（不打断 brew）",
                         onCancel: { Task { await CoreClient.shared.cancelCurrent() } }, timer: timer)
        .sheet(item: $result) { sheet in
            ResultSheet(result: sheet) { result = nil }
        }
    }

    private var filteredGroups: [Group] {
        groups.compactMap { group -> Group? in
            if let category, group.label != category { return nil }
            let items = group.items.filter { item in
                switch filter {
                case .all: return true
                case .selected: return checked.contains(item.id)
                case .unselected: return !checked.contains(item.id)
                }
            }
            return items.isEmpty ? nil : Group(label: group.label, items: items)
        }
    }

    private var categories: [(label: String, count: Int)] {
        var out = groups.map { (label: $0.label, count: $0.items.count) }
        // 新加的三组也要能被筛选——否则选"Homebrew formula"时它们仍留在列表里，
        // 用户会以为筛选没生效（2026-10-23 反馈）。
        if !sparkleRest.isEmpty { out.append((label: "App 更新检查", count: sparkleRest.count)) }
        if !electronUpdates.isEmpty { out.append((label: "Electron 应用", count: electronUpdates.count)) }
        if !undetectable.isEmpty { out.append((label: "无法自动检测", count: undetectable.count)) }
        return out
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request("updates.list")
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let label = group["label"]?.stringValue else { return nil }
                let items = (group["items"]?.arrayValue ?? []).compactMap { raw -> Item? in
                    guard let id = raw["id"]?.stringValue, let name = raw["name"]?.stringValue else { return nil }
                    return Item(id: id, name: name,
                                installed: raw["installed"]?.stringValue ?? "",
                                available: raw["available"]?.stringValue ?? "")
                }
                return items.isEmpty ? nil : Group(label: label, items: items)
            }
            sparkle = (data["sparkle_updates"]?.arrayValue ?? []).compactMap { raw in
                guard let path = raw["path"]?.stringValue, let name = raw["name"]?.stringValue else { return nil }
                return Sparkle(name: name, path: path,
                               version: raw["version"]?.stringValue ?? "",
                               latest: raw["latest"]?.stringValue ?? "")
            }

            // 直接用内核分好的 electron_updates（已经筛过 update_available），
            // 界面不重复判断布尔——之前这里判空导致整组不显示。
            electronUpdates = (data["electron_updates"]?.arrayValue ?? []).compactMap { raw in
                guard let name = raw["name"]?.stringValue,
                      let path = raw["path"]?.stringValue else { return nil }
                return ElectronApp(
                    name: name, path: path,
                    version: raw["version"]?.stringValue ?? "",
                    latest: raw["latest"]?.stringValue ?? ""
                )
            }
            undetectable = (data["undetectable"]?.arrayValue ?? []).compactMap { raw in
                guard let name = raw["name"]?.stringValue, let path = raw["path"]?.stringValue else { return nil }
                return Undetectable(name: name, path: path,
                                    reason: raw["reason"]?.stringValue ?? "由应用自身更新")
            }

            sparkleRest = (data["sparkle_rest"]?.arrayValue ?? []).compactMap { raw in
                guard let path = raw["path"]?.stringValue,
                      let name = raw["name"]?.stringValue else { return nil }
                return SparkleRest(
                    name: name,
                    path: path,
                    version: raw["version"]?.stringValue ?? "",
                    reason: raw["reason"]?.stringValue ?? "已是最新"
                )
            }

            // 版本表要包含**全部** Sparkle 应用（含"已是最新"的）：
            // 用户刚在应用内更新完，这个应用就已经从"有更新"挪到"已是最新"那一组了。
            var versions: [String: String] = [:]
            for key in ["sparkle_updates", "sparkle_rest", "sparkle"] {
                for raw in data[key]?.arrayValue ?? [] {
                    guard let path = raw["path"]?.stringValue else { continue }
                    versions[path] = raw["version"]?.stringValue ?? ""
                }
            }
            knownVersions = versions
            checkedAt = Date()

            // 核对：点过"在应用内更新"的应用，版本变了吗？
            for (path, oldVersion) in pendingSparkle {
                guard let now = versions[path], !now.isEmpty else { continue }
                if now != oldVersion {
                    let name = (data["sparkle_updates"]?.arrayValue ?? []).first {
                        $0["path"]?.stringValue == path
                    }?["name"]?.stringValue ?? URL(fileURLWithPath: path).lastPathComponent
                    notice = "\(name) 已更新：\(oldVersion) → \(now)"
                    pendingSparkle.removeValue(forKey: path)
                }
            }
            // 默认全选，但**排除 App Store 项**：它们只能去商店点更新，
            // 勾上会让底部按钮显示一个做不到的数量（2026-10-23 反馈）。
            checked = Set(groups.flatMap(\.items).filter { !$0.id.hasPrefix("mas|") }.map(\.id))
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func apply() async {
        applying = true
        timer.start()
        defer {
            applying = false
            timer.stop()
        }
        do {
            let result = try await CoreClient.shared.request(
                "updates.apply", args: ["ids": .array(checked.sorted().map { .string($0) })]
            )
            if result["status"]?.stringValue == "refused" {
                notice = "没有勾选任何项，什么都没升级"
            } else if let outcome = OperationResult.from(result["result"], canOpenTrash: false) {
                self.result = outcome
            } else {
                let ok = (result["results"]?.arrayValue ?? []).filter { $0["ok"]?.boolValue == true }.count
                let total = (result["results"]?.arrayValue ?? []).count
                notice = "已完成 \(ok)/\(total) 项；失败的项在终端里能看到输出"
            }
            checked = []
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// 打开"自己做更新"的应用：它是唯一能安全升级自己的主体。
    private func openSelfUpdating(_ item: Undetectable) async {
        do {
            _ = try await CoreClient.shared.request("app.open", args: ["path": .string(item.path)])
            notice = "已打开 \(item.name)；在它的菜单里点“检查更新”即可（这类应用由自己管理更新）"
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func open(_ app: Sparkle) async {
        do {
            _ = try await CoreClient.shared.request("app.open", args: ["path": .string(app.path)])
            // 记下打开时的版本；它更新完再回到这一页（或按 ⌘R）就会自动核对并报告。
            pendingSparkle[app.path] = knownVersions[app.path] ?? app.version
            notice = "已打开 \(app.name)（当前 \(app.version)）；在它里面更新完，回来按 ⌘R 我会核对版本"
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - 残留

struct OrphansListView: View {
    @State private var groups: [Group] = []
    @State private var checked: Set<String> = []
    @State private var loading = false
    @State private var applying = false
    @State private var error: String?
    @State private var notice: String?
    @State private var result: OperationResult?
    @State private var scannedAt: Date?
    @State private var filter: SelectionFilter = .all
    @State private var category: String?
    @StateObject private var timer = ElapsedTimer()

    struct Item: Identifiable {
        var id: String { path }
        let path: String
        let name: String
        let bytes: Int64
    }

    struct Group: Identifiable {
        var id: String { label }
        let label: String
        let items: [Item]
    }

    private var allItems: [Item] { groups.flatMap(\.items) }
    private var checkedBytes: Int64 {
        allItems.filter { checked.contains($0.id) }.reduce(0) { $0 + $1.bytes }
    }

    var body: some View {
        VStack(spacing: 0) {
            if let error {
                StatusBanner(level: .error, text: error)
            } else if let notice {
                StatusBanner(level: .info, text: notice)
            }

            if loading {
                ProgressView("扫描残留…（会读 LaunchServices，可能要几秒）")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if groups.isEmpty {
                Text("没有发现残留").foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                HStack(spacing: 12) {
                    SelectAllToggle(
                        isOn: !filteredGroups.isEmpty
                            && filteredGroups.flatMap { $0.items.map(\.id) }.allSatisfy(checked.contains),
                        count: (
                            selected: filteredGroups.flatMap { $0.items.map(\.id) }.filter(checked.contains).count,
                            total: filteredGroups.flatMap { $0.items.map(\.id) }.count
                        )
                    ) { on in
                        let ids = filteredGroups.flatMap { $0.items.map(\.id) }
                        if on { checked.formUnion(ids) } else { checked.subtract(ids) }
                    }
                    FilterBar(status: $filter, category: $category, categories: categories)
                    Spacer()
                }
                .padding(.horizontal, 20)
                .padding(.top, 6)

                List {
                    ForEach(filteredGroups) { group in
                                                Text("\(group.label) · \(group.items.count)").font(.caption.weight(.medium)).foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                                                ForEach(group.items) { item in
                                                    Toggle(isOn: Binding(
                                                        get: { checked.contains(item.id) },
                                                        set: { isOn in
                                                            if isOn { checked.insert(item.id) } else { checked.remove(item.id) }
                                                        }
                                                    )) {
                                                        HStack(spacing: 10) {
                                                            Image(systemName: "questionmark.folder").frame(width: 20).foregroundStyle(.secondary)
                                                            VStack(alignment: .leading, spacing: 1) {
                                                                Text(item.name).lineLimit(1)
                                                                Text(displayPath(item.path))
                                                                    .font(.caption2).foregroundStyle(.tertiary)
                                                                    .lineLimit(1).truncationMode(.middle)
                                                            }
                                                            Spacer(minLength: 8)
                                                            Text(ByteText.format(item.bytes)).monospacedDigit().foregroundStyle(.secondary)
                                                        }
                                                    }
                                                    .toggleStyle(.checkbox)
                                                }
                                            

                    }
                }
                .listStyle(.inset)
            }

            Divider()
            HStack {
                Text("已选 \(checked.count) 项 · \(ByteText.format(checkedBytes))"
                     + (scannedAt.map { " · 读取于 \(Self.clock.string(from: $0))" } ?? ""))
                    .font(.callout.weight(.medium)).monospacedDigit()
                Spacer()
                Button {
                    Task { await apply() }
                } label: {
                    if applying { ProgressView().controlSize(.small) }
                    else { Text(checked.isEmpty ? "移入废纸篓" : "移入废纸篓 \(checked.count) 项") }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(checked.isEmpty || applying)
            }
            .padding(16)
        }
        .task {
            if groups.isEmpty { await load() }
            // 开发钩子：MACCLEANER_DEV_RESULT=1 弹一张样例结果页（截图/验收用）。
            if ProcessInfo.processInfo.environment["MACCLEANER_DEV_RESULT"] != nil, result == nil {
                result = OperationResult(
                    title: "残留清理完成", count: 18, bytes: 42_000_000,
                    failures: [(path: "/Users/x/Library/Caches/com.demo/locked.db", reason: "permission denied")],
                    cancelled: false, canOpenTrash: true
                )
            }
        }
        .progressOverlay(applying, title: "正在移入废纸篓…", detail: "每项开始前会检查一次取消",
                         onCancel: { Task { await CoreClient.shared.cancelCurrent() } }, timer: timer)
        .sheet(item: $result) { sheet in
            ResultSheet(result: sheet) { result = nil }
        }
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private func displayPath(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix(home) ? "~" + path.dropFirst(home.count) : path
    }

    private var filteredGroups: [Group] {
        groups.compactMap { group -> Group? in
            if let category, group.label != category { return nil }
            let items = group.items.filter { item in
                switch filter {
                case .all: return true
                case .selected: return checked.contains(item.path)
                case .unselected: return !checked.contains(item.path)
                }
            }
            return items.isEmpty ? nil : Group(label: group.label, items: items)
        }
    }

    private var categories: [(label: String, count: Int)] {
        groups.map { (label: $0.label, count: $0.items.count) }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request("orphans.list")
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let label = group["label"]?.stringValue else { return nil }
                let items = (group["items"]?.arrayValue ?? []).compactMap { raw -> Item? in
                    guard let path = raw["path"]?.stringValue else { return nil }
                    return Item(path: path,
                                name: raw["name"]?.stringValue ?? URL(fileURLWithPath: path).lastPathComponent,
                                bytes: raw["bytes"]?.intValue ?? 0)
                }
                return items.isEmpty ? nil : Group(label: label, items: items)
            }
            checked = Set(groups.first(where: { $0.label == "Caches" })?.items.map(\.path) ?? [])
            scannedAt = Date()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func apply() async {
        guard await BiometricGate.confirm(reason: "确认移走 \(checked.count) 项残留") else { return }
        applying = true
        timer.start()
        defer {
            applying = false
            timer.stop()
        }
        do {
            let result = try await CoreClient.shared.request(
                "orphans.apply", args: ["paths": .array(checked.sorted().map { .string($0) })]
            )
            if let outcome = OperationResult.from(result["result"], canOpenTrash: true) {
                self.result = outcome
            } else {
                let moved = (result["moved"]?.arrayValue ?? []).count
                notice = "已把 \(moved) 项移入废纸篓"
            }
            RecentActivity.record("清理残留 \(checked.count) 项")
            await Notifier.post(title: "残留清理完成", body: "已移走 \(checked.count) 项到废纸篓")
            checked = []
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
