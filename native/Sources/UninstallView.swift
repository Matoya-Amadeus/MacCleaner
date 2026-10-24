import AppKit
import SwiftUI

/// 卸载：**勾选式**列表（顶部全选、底部一个统一大按钮）。
///
/// 2026-10-23 改版：之前每行右端一个【卸载】按钮，21 行就有 21 个主操作在抢注意力，
/// 而且要瞄准小按钮。现在整行是勾选框，动作集中在底部一个按钮里。
struct UninstallListView: View {
    @Environment(\.appLanguage) private var language
    @State private var groups: [Category] = []
    @State private var loading = false
    @State private var error: String?
    @State private var search = ""
    @State private var selected: Set<String> = []        // 应用 path
    @State private var filter: SelectionFilter = .all
    @State private var category: String?
    @State private var preparing = false
    @State private var batch: BatchPlan?
    @State private var result: OperationResult?
    @State private var notice: String?
    @State private var loadedAt: Date?
    @StateObject private var timer = ElapsedTimer()

    struct App: Identifiable {
        let id: String          // 用 path 做 id：bundle id 可能缺失
        let name: String
        let bundleID: String
        let path: String
    }

    struct Category: Identifiable {
        var id: String { label }
        let label: String
        let apps: [App]
    }

    struct PlanItem: Identifiable {
        let id: String
        let path: String
        let kind: String
        /// 内核按语言给的显示名（`app-bundle` → 应用本体 / Application）。
        let kindLabel: String
        let bytes: Int64
        let confidence: String
        let requiresAdmin: Bool
    }

    struct AppPlan: Identifiable {
        var id: String { appPath }
        let appName: String
        let appPath: String
        let items: [PlanItem]
    }

    struct BatchPlan: Identifiable {
        let id = UUID()
        let plans: [AppPlan]
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    // MARK: - 派生数据

    private var filtered: [Category] {
        let needle = search.trimmingCharacters(in: .whitespaces).lowercased()
        return groups.compactMap { group -> Category? in
            if let category, group.label != category { return nil }
            let hits = group.apps.filter { app in
                let matchesSearch = needle.isEmpty
                    || app.name.lowercased().contains(needle)
                    || app.bundleID.lowercased().contains(needle)
                let matchesStatus: Bool
                switch filter {
                case .all: matchesStatus = true
                case .selected: matchesStatus = selected.contains(app.id)
                case .unselected: matchesStatus = !selected.contains(app.id)
                }
                return matchesSearch && matchesStatus
            }
            return hits.isEmpty ? nil : Category(label: group.label, apps: hits)
        }
    }

    private var categories: [(label: String, count: Int)] {
        groups.map { (label: $0.label, count: $0.apps.count) }
    }

    private var visibleApps: [App] { filtered.flatMap(\.apps) }
    private var allVisibleSelected: Bool {
        !visibleApps.isEmpty && visibleApps.allSatisfy { selected.contains($0.id) }
    }

    var body: some View {
        VStack(spacing: 0) {
            header

            if let error {
                StatusBanner(level: .error, text: error)
            } else if let notice {
                StatusBanner(level: .info, text: notice)
            }

            if loading && groups.isEmpty {
                ProgressView("读取应用列表…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(filtered) { group in
                        // 表头当普通行：Section 的表头会吸顶，把首组前两行盖住
                        // （2026-10-23 用户截图：浏览器 · 2 下面是空的）。
                        Text("\(group.label) · \(group.apps.count)")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .listSectionHeaderRow()
                        ForEach(group.apps) { app in
                            row(app)
                        }
                    }
                }
                .listStyle(.inset)
            }

            Divider()
            footer
        }
        .task { await load() }
        .progressOverlay(preparing, title: "正在清点残留…", detail: "逐个目录核对，不会删除任何东西", timer: timer)
        .sheet(item: $batch) { plan in
            BatchUninstallSheet(
                batch: plan,
                onDone: { message, outcome in
                    self.batch = nil
                    self.notice = message
                    if let outcome { self.result = outcome }
                    self.selected = []
                    Task { await load() }
                }
            )
        }
        .sheet(item: $result) { sheet in
            ResultSheet(result: sheet) { result = nil }
        }
    }

    // MARK: - 区块

    private var header: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField(L10n.t("search.apps", language), text: $search)
                    .textFieldStyle(.plain)
                if !search.isEmpty {
                    Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).foregroundStyle(.tertiary)
                }
            }
            .padding(8)
            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))

            HStack(spacing: 12) {
                Toggle(isOn: Binding(
                    get: { allVisibleSelected },
                    set: { isOn in
                        if isOn {
                            selected.formUnion(visibleApps.map(\.id))
                        } else {
                            selected.subtract(visibleApps.map(\.id))
                        }
                    }
                )) {
                    Text(search.isEmpty
                         ? L10n.t("common.selectAll", language)
                         : (language == "en"
                            ? "Select all (\(visibleApps.count) results)"
                            : "全选（\(visibleApps.count) 个结果）"))
                        .font(.callout)
                }
                .toggleStyle(.checkbox)

                FilterBar(status: $filter, category: $category, categories: categories)

                Spacer()

                if let loadedAt {
                    Text("\(L10n.t("common.updated", language)) \(Self.clock.string(from: loadedAt))")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 8)
    }

    private var footer: some View {
        HStack {
            Text(language == "en"
                 ? "Selected \(selected.count) of \(groups.flatMap(\.apps).count)"
                 : "已选 \(selected.count) 个 · 共 \(groups.flatMap(\.apps).count) 个")
                .font(.callout.weight(.medium))
                .monospacedDigit()
            Spacer()
            Button {
                Task { await prepare() }
            } label: {
                Text(selected.isEmpty
                          ? L10n.t("action.uninstall", language)
                          : (language == "en" ? "Uninstall \(selected.count)" : "卸载 \(selected.count) 个"))
            }
            .keyboardShortcut(.defaultAction)
            .disabled(selected.isEmpty || preparing)
        }
        .padding(16)
    }

    private func row(_ app: App) -> some View {
        Toggle(isOn: Binding(
            get: { selected.contains(app.id) },
            set: { isOn in
                if isOn { selected.insert(app.id) } else { selected.remove(app.id) }
            }
        )) {
            HStack(spacing: 10) {
                Image(systemName: "shippingbox")
                    .frame(width: 20)
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 1) {
                    Text(app.name).lineLimit(1)
                    Text(app.bundleID.isEmpty ? app.path : app.bundleID)
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer(minLength: 8)
            }
        }
        .toggleStyle(.checkbox)
        .padding(.vertical, 2)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(app.bundleID.isEmpty ? "\(app.name)，\(app.path)" : "\(app.name)，\(app.bundleID)")
        .contextMenu {
            Button("在 Finder 中显示") { Task { await reveal(app.path) } }
            Button("拷贝路径") { copy(app.path) }
            Divider()
            Button("只卸载这个") {
                selected = [app.id]
                Task { await prepare() }
            }
        }
    }

    // MARK: - 数据

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request(
                "apps", args: ["lang": .string(language)]
            )
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let label = group["label"]?.stringValue else { return nil }
                let apps = (group["items"]?.arrayValue ?? []).compactMap { item -> App? in
                    guard let path = item["path"]?.stringValue, let name = item["name"]?.stringValue else { return nil }
                    return App(id: path, name: name, bundleID: item["bundle_id"]?.stringValue ?? "", path: path)
                }
                return apps.isEmpty ? nil : Category(label: label, apps: apps)
            }
            // 已经卸载掉的 path 要从选择里剔掉
            let alive = Set(groups.flatMap(\.apps).map(\.id))
            selected.formIntersection(alive)
            loadedAt = Date()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// 勾了几个就清点几个，合成一张清单给用户一次确认。
    private func prepare() async {
        let apps = groups.flatMap(\.apps).filter { selected.contains($0.id) }
        guard !apps.isEmpty else { return }
        preparing = true
        timer.start()
        defer {
            preparing = false
            timer.stop()
        }
        var plans: [AppPlan] = []
        do {
            for app in apps {
                let data = try await CoreClient.shared.request(
                    "uninstall.plan",
                    args: ["path": .string(app.path), "name": .string(app.name),
                           "bundle_id": .string(app.bundleID), "lang": .string(language)]
                )
                let items = (data["items"]?.arrayValue ?? []).compactMap { item -> PlanItem? in
                    guard let path = item["path"]?.stringValue, let id = item["id"]?.stringValue else { return nil }
                    return PlanItem(
                        id: id,
                        path: path,
                        kind: item["kind"]?.stringValue ?? "",
                        kindLabel: item["kind_label"]?.stringValue ?? (item["kind"]?.stringValue ?? ""),
                        bytes: item["allocated_bytes"]?.intValue ?? 0,
                        confidence: item["confidence"]?.stringValue ?? "exact",
                        requiresAdmin: item["requires_admin"]?.boolValue ?? false
                    )
                }
                plans.append(AppPlan(appName: app.name, appPath: app.path, items: items))
            }
            batch = BatchPlan(plans: plans)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func reveal(_ path: String) async {
        do {
            _ = try await CoreClient.shared.request("files.reveal", args: ["path": .string(path)])
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func copy(_ path: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(path, forType: .string)
    }
}

// MARK: - 批量残留清单（一次确认）

struct BatchUninstallSheet: View {
    @Environment(\.appLanguage) private var language
    let batch: UninstallListView.BatchPlan
    /// (一行提示, 结果页数据)
    let onDone: (String, OperationResult?) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var checked: Set<String> = []
    @State private var applying = false
    @State private var error: String?
    @State private var confirming = false
    @StateObject private var timer = ElapsedTimer()

    private var allItems: [UninstallListView.PlanItem] { batch.plans.flatMap(\.items) }
    /// 计划里有没有"应用本体"这一项（kind == app-bundle）。
    private var hasAppBundle: Bool { allItems.contains { $0.kind == "app-bundle" } }

    private var pickedBytes: Int64 {
        allItems.filter { checked.contains($0.id) }.reduce(0) { $0 + $1.bytes }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("卸载 \(batch.plans.count) 个应用").font(.headline)
                    // 计划里**包含应用本体**，只写"残留 N 项"会让人以为只是清残留，
                    // 于是"卸载完 app 还在"就成了 bug 观感（2026-10-23 反馈）。
                    Text(hasAppBundle
                         ? "含应用本体 + 残留 \(allItems.count) 项 · 共 \(ByteText.format(allItems.reduce(0) { $0 + $1.bytes }))"
                         : "残留 \(allItems.count) 项 · 共 \(ByteText.format(allItems.reduce(0) { $0 + $1.bytes }))")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }
            }
            .padding(16)

            Divider()

            List {
                ForEach(batch.plans) { plan in
                    Section(plan.appName) {
                        let exact = plan.items.filter { $0.confidence != "name-match" && !$0.requiresAdmin }
                        let guessed = plan.items.filter { $0.confidence == "name-match" && !$0.requiresAdmin }
                        let admin = plan.items.filter(\.requiresAdmin)
                        ForEach(exact) { item in toggleRow(item) }
                        ForEach(guessed) { item in toggleRow(item, hint: "按名称匹配 · 默认不勾") }
                        ForEach(admin) { item in
                            HStack {
                                Text(URL(fileURLWithPath: item.path).lastPathComponent).lineLimit(1)
                                Spacer()
                                Text(ByteText.format(item.bytes)).font(.caption).foregroundStyle(.secondary)
                                Text("管理员").font(.caption2)
                                    .padding(.horizontal, 6).padding(.vertical, 2)
                                    .background(Color.secondary.opacity(0.12), in: Capsule())
                            }
                            .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            if let error {
                Text(error).font(.caption).foregroundStyle(.red).padding(.horizontal, 16)
            }

            Divider()
            HStack {
                Text(language == "en"
                     ? "Selected \(checked.count) · \(ByteText.format(pickedBytes))"
                     : "已选 \(checked.count) 项 · \(ByteText.format(pickedBytes))")
                    .font(.callout.weight(.medium)).monospacedDigit()
                Spacer()
                Button {
                    confirming = true
                } label: {
                    if applying { ProgressView().controlSize(.small) }
                    else {
                        Text(checked.isEmpty
                             ? L10n.t("action.trash", language)
                             : (language == "en" ? "Move \(checked.count) to Trash" : "移入废纸篓 \(checked.count) 项"))
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(checked.isEmpty || applying)
            }
            .padding(16)
        }
        .frame(width: 680, height: 580)
        // 这一步可能弹两种系统框：控制访达、管理员密码。文案先说清楚，别让人干等。
        .progressOverlay(
            applying,
            title: "正在移入废纸篓…",
            detail: "若弹出「控制访达」或密码框，请允许 / 输入后继续",
            timer: timer
        )
        .confirmationDialog(
            "确认卸载 \(batch.plans.count) 个应用？",
            isPresented: $confirming
        ) {
            Button("移入废纸篓 \(checked.count) 项", role: .destructive) {
                Task { await apply() }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("将移走 \(checked.count) 项，共 \(ByteText.format(pickedBytes))。移入废纸篓后可恢复。")
        }
        .onAppear {
            // 默认勾"确定项"（路径与 bundle id 对得上），名称匹配的不勾。
            checked = Set(batch.plans.flatMap(\.items)
                .filter { $0.confidence != "name-match" && !$0.requiresAdmin }
                .map(\.id))
        }
    }

    private func toggleRow(_ item: UninstallListView.PlanItem, hint: String? = nil) -> some View {
        Toggle(isOn: Binding(
            get: { checked.contains(item.id) },
            set: { isOn in
                if isOn { checked.insert(item.id) } else { checked.remove(item.id) }
            }
        )) {
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text(URL(fileURLWithPath: item.path).lastPathComponent).lineLimit(1)
                    Text(hint ?? item.kindLabel).font(.caption2).foregroundStyle(.tertiary)
                }
                Spacer()
                Text(ByteText.format(item.bytes)).font(.caption).monospacedDigit().foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.checkbox)
    }

    /// 内核对这类错误无能为力：需要「App 管理」授权，且裸 rename 不会触发授权弹窗。
    private func isPermissionDenied(_ reason: String) -> Bool {
        reason.contains("Permission denied")
            || reason.contains("Operation not permitted")
            || reason.contains("Errno 13")
            || reason.contains("Errno 1 ")
    }

    /// 用 Foundation 的回收站 API 移动；它会走系统授权流程。
    /// 移走一个路径：三条路依次尝试，全部**异步 + 带超时**，绝不阻塞界面。
    ///
    /// 1. `FileManager.trashItem`：App 自己有权限时最快（静默）；
    /// 2. 访达：`osascript` 调 Finder —— 它有全权，但需要「控制访达」自动化授权；
    /// 3. 管理员：`with administrator privileges` 弹一次密码，root 直接移动。
    ///
    /// 为什么不能只用 `NSAppleScript`：它在系统弹窗期间**同步阻塞**，
    /// 曾让「正在移入废纸篓…」卡在 6 秒不动（2026-10-23 截图）。
    private func moveToTrash(_ path: String) async -> (ok: Bool, message: String) {
        var resulting: NSURL?
        if (try? FileManager.default.trashItem(
            at: URL(fileURLWithPath: path),
            resultingItemURL: &resulting
        )) != nil {
            return (true, "")
        }

        let quoted = path.replacingOccurrences(of: "\"", with: "\\\"")
        let finder = """
        tell application "Finder" to delete POSIX file "\(quoted)"
        """
        let viaFinder = await runOsascript(finder, timeout: 12)
        if viaFinder.ok { return (true, "") }

        // 访达没权限（用户点了"不允许"，或从未授权）→ 用管理员权限直接 mv。
        let shellQuoted = path
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        // 注意转义层级：最终交给 AppleScript 的文本必须是
        //   do shell script "mv -f \"/path\" ~/.Trash/" with administrator privileges
        // 内层引号在 AppleScript 里要写成 \"，在 Swift 里就得是 \\\"。
        let admin = "do shell script \"mv -f \\\"\(shellQuoted)\\\" ~/.Trash/\" with administrator privileges"
        let viaAdmin = await runOsascript(admin, timeout: 120)
        if viaAdmin.ok { return (true, "") }

        // 三条路都报错，但源可能已经不在了（前一次成功 / 用户拖走 / Finder 代劳后
        // 我们没拿到返回）。**以磁盘事实为准**，别把已经卸掉的算成失败。
        if !FileManager.default.fileExists(atPath: path) {
            return (true, "")
        }

        let reason = viaFinder.message.isEmpty ? viaAdmin.message : viaFinder.message
        return (false, reason.isEmpty ? "移动被系统拒绝" : reason)
    }

    /// 跑一段 AppleScript：后台线程 + 超时，超时就终止进程。
    private func runOsascript(_ source: String, timeout: TimeInterval) async -> (ok: Bool, message: String) {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
                process.arguments = ["-e", source]
                let stderr = Pipe()
                process.standardError = stderr
                process.standardOutput = Pipe()

                do {
                    try process.run()
                } catch {
                    continuation.resume(returning: (false, error.localizedDescription))
                    return
                }

                let deadline = Date().addingTimeInterval(timeout)
                while process.isRunning && Date() < deadline {
                    usleep(80_000)
                }
                if process.isRunning {
                    process.terminate()
                    continuation.resume(returning: (false, "系统授权弹窗未响应（已超时）"))
                    return
                }

                let data = stderr.fileHandleForReading.readDataToEndOfFile()
                let text = String(data: data, encoding: .utf8)?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                continuation.resume(returning: (process.terminationStatus == 0, text))
            }
        }
    }

    private func apply() async {
        guard await BiometricGate.confirm(reason: "确认卸载 \(batch.plans.count) 个应用") else { return }
        applying = true
        timer.start()
        defer {
            applying = false
            timer.stop()
        }
        var movedTotal = 0
        // 体积要按**实际移走**的项算：之前用 pickedBytes（勾选总大小），
        // 结果"完成 0 项、体积 93.8 MB"——数字自相矛盾（2026-10-23 截图）。
        var movedBytes: Int64 = 0
        var failed: [(String, String)] = []
        do {
            for plan in batch.plans {
                let ids = plan.items.map(\.id).filter { checked.contains($0) }
                guard !ids.isEmpty else { continue }
                let data = try await CoreClient.shared.request(
                    "uninstall.apply",
                    args: ["path": .string(plan.appPath),
                           "item_ids": .array(ids.map { .string($0) })]
                )
                movedTotal += Int(data["moved_count"]?.intValue ?? 0)
                let movedPaths = Set((data["moved"]?.arrayValue ?? []).compactMap { $0["path"]?.stringValue })
                movedBytes += plan.items
                    .filter { movedPaths.contains($0.path) }
                    .reduce(Int64(0)) { $0 + $1.bytes }
                for item in data["failed"]?.arrayValue ?? [] {
                    let path = item["path"]?.stringValue ?? ""
                    let reason = item["reason"]?.stringValue ?? ""
                    // 内核用 `os.rename` 移动，被 TCC 的「App 管理」拦下时只会得到
                    // `[Errno 13] Permission denied` / `[Errno 1] Operation not permitted`，
                    // 而且**不会弹授权框**。
                    // 这里改用系统回收站 API 重试一次：它走正确的授权路径
                    // （首次会弹"MacCleaner 想要管理其他 App"），成功后计入完成。
                    if isPermissionDenied(reason) {
                        let outcome = await moveToTrash(path)
                        if outcome.ok {
                            movedTotal += 1
                            movedBytes += plan.items.first { $0.path == path }?.bytes ?? 0
                        } else {
                            failed.append((path, "移动被系统拒绝：\(outcome.message)"))
                        }
                        continue
                    }
                    failed.append((path, reason))
                }
            }
            let outcome = OperationResult(
                title: "卸载完成",
                count: movedTotal,
                bytes: movedBytes,
                failures: failed,
                cancelled: false,
                canOpenTrash: true
            )
            RecentActivity.record("卸载 \(batch.plans.count) 个应用（\(movedTotal) 项）")
            await Notifier.post(title: "卸载完成", body: "\(batch.plans.count) 个应用：已移走 \(movedTotal) 项到废纸篓")
            dismiss()
            onDone("已把 \(movedTotal) 项移入废纸篓；可在废纸篓里恢复", outcome)
        } catch {
            self.error = error.localizedDescription
        }
    }
}
