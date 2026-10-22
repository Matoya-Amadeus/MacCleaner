import SwiftUI

/// 清理页：推荐清理 / 大文件（原侧栏两个入口，2026-10-22 合并）。
struct CleanView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case recommended, large
        var id: String { rawValue }
        var title: String {
            switch self {
            case .recommended: return "推荐清理"
            case .large: return "大文件"
            }
        }
    }

    @State private var tab: Tab = .recommended

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                ForEach(Tab.allCases) { item in Text(item.title).tag(item) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            Divider()

            switch tab {
            case .recommended: RecommendedView()
            case .large: LargeFilesView()
            }
        }
    }
}

// MARK: - 推荐清理

struct RecommendedView: View {
    @State private var groups: [Group] = []
    @State private var checked: Set<String> = []
    @State private var loading = false
    @State private var scanning = false
    @State private var error: String?
    @State private var notice: String?
    @State private var confirming = false
    @StateObject private var timer = ElapsedTimer()
    @State private var busy = false
    @State private var completion: CleanCompletion?

    struct Item: Identifiable {
        let id: String          // target_id
        let name: String
        let path: String
        let bytes: Int64
        let risk: String
        let recoverable: Bool
    }

    struct Group: Identifiable {
        var id: String { key }
        let key: String
        let label: String
        let hint: String
        let items: [Item]
    }

    private var checkedBytes: Int64 {
        groups.flatMap(\.items).filter { checked.contains($0.id) }.reduce(0) { $0 + $1.bytes }
    }

    private var riskyChecked: Bool {
        groups.flatMap(\.items).contains { checked.contains($0.id) && $0.risk != "low" }
    }

    var body: some View {
        VStack(spacing: 0) {
            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red).padding(12)
            }
            if let notice {
                Text(notice).font(.callout).foregroundStyle(.secondary).padding(.top, 8)
            }

            if groups.isEmpty {
                scanningView
            } else {
                List {
                    ForEach(groups) { group in
                        Section {
                            ForEach(group.items) { item in row(item) }
                        } header: {
                            VStack(alignment: .leading, spacing: 1) {
                                Text("\(group.label) · \(group.items.count)").font(.caption)
                                if !group.hint.isEmpty {
                                    Text(group.hint).font(.caption2).foregroundStyle(.tertiary)
                                }
                            }
                        }
                    }
                }
                .listStyle(.inset)
            }

            Divider()
            HStack {
                Text("已选 \(checked.count) 项 · \(ByteText.format(checkedBytes))")
                    .font(.callout.weight(.medium)).monospacedDigit()
                Spacer()
                Button("清理 \(checked.count) 项") {
                    confirming = true
                }
                .keyboardShortcut(.defaultAction)
                .disabled(checked.isEmpty)
            }
            .padding(16)
        }
        .task {
            if groups.isEmpty { await scan() }
            // 开发钩子：MACCLEANER_DEV_COMPLETION=1 时直接弹一张样例完成页，便于截图/验收。
            if ProcessInfo.processInfo.environment["MACCLEANER_DEV_COMPLETION"] != nil, completion == nil {
                completion = CleanCompletion(
                    recoverableBytes: 2_570_000_000,
                    freedBytes: 0,
                    skipped: [(path: "/Users/x/Library/Caches/com.demo/locked.db", reason: "permission denied")],
                    receiptPath: "/Users/x/.maccleaner/receipts/cleanup-2026-10-22.json"
                )
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .mcReload)) { _ in
            Task { await scan() }
        }
        .progressOverlay(busy, title: "正在清理…", detail: "移入废纸篓，可在废纸篓里恢复",
                         onCancel: { Task { await CoreClient.shared.cancelCurrent() } }, timer: timer)
        .sheet(item: $completion) { sheet in
            CompletionSheet(completion: sheet) { completion = nil }
        }
        .sheet(isPresented: $confirming) {
            ConfirmCleanSheet(
                count: checked.count,
                bytes: checkedBytes,
                hasRisk: riskyChecked,
                onConfirm: { Task { await performClean() } },
                onCancel: { confirming = false }
            )
        }
    }

    private var scanningView: some View {
        VStack(spacing: 10) {
            ProgressView()
            Text(scanning ? "正在扫描可清理项…" : "还没有扫描")
                .font(.callout).foregroundStyle(.secondary)
            Text("只读扫描：读取大小与修改时间，不会改动任何文件。")
                .font(.caption).foregroundStyle(.tertiary)
            if !scanning {
                Button("开始扫描") { Task { await scan() } }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func row(_ item: Item) -> some View {
        Toggle(isOn: Binding(
            get: { checked.contains(item.id) },
            set: { isOn in
                if isOn { checked.insert(item.id) } else { checked.remove(item.id) }
            }
        )) {
            HStack(spacing: 10) {
                Image(systemName: symbol(for: item))
                    .frame(width: 20).foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text(item.name).lineLimit(1)
                        if item.risk != "low" {
                            Text("需确认").font(.caption2)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(Color.orange.opacity(0.16), in: Capsule())
                                .foregroundStyle(.orange)
                        }
                    }
                    Text(displayPath(item.path)).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(ByteText.format(item.bytes)).monospacedDigit().foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.checkbox)
        .padding(.vertical, 2)
    }

    private func symbol(for item: Item) -> String {
        switch item.id {
        case "browser-caches": return "safari"
        case "trash": return "trash"
        case "user-downloads", "user-files": return "arrow.down.circle"
        case "docker": return "shippingbox"
        default: return "internaldrive"
        }
    }

    private func displayPath(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix(home) ? "~" + path.dropFirst(home.count) : path
    }

    private func scan() async {
        scanning = true
        defer { scanning = false }
        do {
            let data = try await CoreClient.shared.request("review.payload")
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let key = group["key"]?.stringValue, let label = group["label"]?.stringValue else { return nil }
                let items = (group["items"]?.arrayValue ?? []).compactMap { raw -> Item? in
                    guard let id = raw["target_id"]?.stringValue, let name = raw["name"]?.stringValue else { return nil }
                    return Item(
                        id: id,
                        name: name,
                        path: raw["path"]?.stringValue ?? "",
                        bytes: raw["allocated_bytes"]?.intValue ?? 0,
                        risk: raw["risk"]?.stringValue ?? "low",
                        recoverable: raw["recoverable"]?.boolValue ?? true
                    )
                }
                return items.isEmpty ? nil : Group(key: key, label: label, hint: group["hint"]?.stringValue ?? "", items: items)
            }
            // 低风险默认勾上（与旧界面同一规则）；"你的文件"这类要用户自己点。
            checked = Set(groups.filter { $0.key != "user" && $0.key != "trash" && $0.key != "system" }
                .flatMap(\.items).filter { $0.risk == "low" }.map(\.id))
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func performClean() async {
        confirming = false
        let approved = checked.sorted()
        // 指纹确认（没有 Touch ID 的机器直接放行，见 BiometricGate 的注释）。
        guard await BiometricGate.confirm(reason: "确认清理 \(approved.count) 项") else { return }

        busy = true
        timer.start()
        defer {
            busy = false
            timer.stop()
        }
        do {
            let result = try await CoreClient.shared.request(
                "clean",
                args: ["approved_ids": .array(approved.map { .string($0) }),
                       "selected_ids": .array(approved.map { .string($0) })]
            )
            // 完成页数据由内核给（口径统一）：可恢复 / 实际释放 / 跳过原因。
            if let payload = result["completion"], let object = payload.objectValue {
                let skipped = (object["skipped_items"]?.arrayValue ?? []).compactMap { item -> (String, String)? in
                    guard let path = item["path"]?.stringValue else { return nil }
                    return (path, item["reason"]?.stringValue ?? "")
                }
                completion = CleanCompletion(
                    recoverableBytes: object["recoverable_bytes"]?.intValue ?? 0,
                    freedBytes: object["actual_freed_bytes"]?.intValue ?? 0,
                    skipped: skipped.map { (path: $0.0, reason: $0.1) },
                    receiptPath: object["receipt_path"]?.stringValue ?? "",
                    cancelled: result["cancelled"]?.boolValue ?? false
                )
            } else {
                let moved = result["moved_count"]?.intValue ?? 0
                notice = "已把 \(moved) 项移入废纸篓；可在废纸篓里恢复"
            }
            await Notifier.post(
                title: "清理完成",
                body: "已把 \(result["moved_count"]?.intValue ?? 0) 项移入废纸篓，可在废纸篓里恢复"
            )
            checked = []
            await scan()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - 确认（安全规则：高风险再确认一次）

struct ConfirmCleanSheet: View {
    let count: Int
    let bytes: Int64
    let hasRisk: Bool
    let onConfirm: () -> Void
    let onCancel: () -> Void

    @State private var riskAcknowledged = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("确认清理").font(.headline)
            Text("将把 \(count) 项（\(ByteText.format(bytes))）移入废纸篓。")
                .font(.callout)
            Text("移入废纸篓后可以恢复；清空废纸篓才会真正释放空间。")
                .font(.caption).foregroundStyle(.secondary)

            if hasRisk {
                Toggle("包含需要你确认的项目（Downloads / 安装包 / 容器等）", isOn: $riskAcknowledged)
                    .toggleStyle(.checkbox)
                    .font(.callout)
            }

            HStack {
                Spacer()
                Button("取消", action: onCancel).keyboardShortcut(.cancelAction)
                Button("移入废纸篓", action: onConfirm)
                    .keyboardShortcut(.defaultAction)
                    .disabled(hasRisk && !riskAcknowledged)
            }
        }
        .padding(20)
        .frame(width: 440)
    }
}

// MARK: - 大文件

struct LargeFilesView: View {
    @State private var items: [Item] = []
    @State private var checked: Set<String> = []
    @State private var loading = false
    @State private var busy = false
    @State private var error: String?
    @State private var notice: String?
    @State private var result: OperationResult?
    @StateObject private var applyTimer = ElapsedTimer()
    @StateObject private var timer = ElapsedTimer()

    struct Item: Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let bytes: Int64
    }

    private var checkedBytes: Int64 {
        items.filter { checked.contains($0.id) }.reduce(0) { $0 + $1.bytes }
    }

    var body: some View {
        VStack(spacing: 0) {
            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red).padding(12)
            }
            if let notice {
                Text(notice).font(.callout).foregroundStyle(.secondary).padding(.top, 8)
            }

            if loading {
                ProgressView("正在扫描大文件…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if items.isEmpty {
                Text("没有超过阈值的文件").foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(items) { item in
                        Toggle(isOn: Binding(
                            get: { checked.contains(item.id) },
                            set: { isOn in
                                if isOn { checked.insert(item.id) } else { checked.remove(item.id) }
                            }
                        )) {
                            HStack(spacing: 10) {
                                Image(systemName: "doc").frame(width: 20).foregroundStyle(.secondary)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(item.name).lineLimit(1)
                                    Text(item.path).font(.caption2).foregroundStyle(.tertiary).lineLimit(1).truncationMode(.middle)
                                }
                                Spacer(minLength: 8)
                                Text(ByteText.format(item.bytes)).monospacedDigit().foregroundStyle(.secondary)
                            }
                        }
                        .toggleStyle(.checkbox)
                    }
                }
                .listStyle(.inset)
            }

            Divider()
            HStack {
                Text("已选 \(checked.count) 个 · \(ByteText.format(checkedBytes))")
                    .font(.callout.weight(.medium)).monospacedDigit()
                Spacer()
                Button("移入废纸篓 \(checked.count) 个") { Task { await trash() } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(checked.isEmpty)
            }
            .padding(16)
        }
        .task { if items.isEmpty { await load() } }
        .onReceive(NotificationCenter.default.publisher(for: .mcReload)) { _ in
            Task { await load() }
        }
        .progressOverlay(loading, title: "正在扫描大文件…", detail: "只读，不会改动任何文件", timer: timer)
        .progressOverlay(busy, title: "正在移入废纸篓…", detail: "每项开始前会检查一次取消",
                         onCancel: { Task { await CoreClient.shared.cancelCurrent() } }, timer: applyTimer)
        .sheet(item: $result) { sheet in
            ResultSheet(result: sheet) { result = nil }
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request("large.list")
            items = (data["items"]?.arrayValue ?? []).compactMap { raw in
                guard let path = raw["path"]?.stringValue else { return nil }
                return Item(
                    name: raw["name"]?.stringValue ?? URL(fileURLWithPath: path).lastPathComponent,
                    path: path,
                    bytes: raw["bytes"]?.intValue ?? 0
                )
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func trash() async {
        let paths = checked.sorted()
        guard await BiometricGate.confirm(reason: "确认移走 \(paths.count) 个大文件") else { return }
        busy = true
        applyTimer.start()
        defer {
            busy = false
            applyTimer.stop()
        }
        do {
            let result = try await CoreClient.shared.request(
                "files.trash", args: ["paths": .array(paths.map { .string($0) })]
            )
            if let outcome = OperationResult.from(result["result"], canOpenTrash: true) {
                self.result = outcome
            } else {
                let moved = (result["moved"]?.arrayValue ?? []).count
                notice = "已把 \(moved) 个文件移入废纸篓"
            }
            await Notifier.post(title: "大文件已移入废纸篓", body: "移走 \(paths.count) 个，可在废纸篓里恢复")
            checked = []
            await load()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
