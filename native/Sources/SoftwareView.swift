import SwiftUI

/// 软件页：卸载 / 更新 / 残留（原来是三个侧栏入口，2026-10-22 合并）。
struct SoftwareView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case uninstall, updates, orphans
        var id: String { rawValue }
        var title: String {
            switch self {
            case .uninstall: return "卸载"
            case .updates: return "更新"
            case .orphans: return "残留"
            }
        }
    }

    @State private var tab: Tab = .uninstall

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
            case .uninstall:
                UninstallListView()
            case .updates:
                UpdatesListView()
            case .orphans:
                OrphansListView()
            }
        }
    }
}

// MARK: - 卸载（列表 → 残留 → 执行 → 结果）

struct UninstallListView: View {
    @State private var groups: [Category] = []
    @State private var loading = false
    @State private var error: String?
    @State private var search = ""
    @State private var planning: String?
    @State private var plan: Plan?
    @State private var notice: String?

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

    struct Plan: Identifiable {
        var id: String { appPath }
        let appName: String
        let appPath: String
        let items: [PlanItem]
        let totalBytes: Int64
    }

    struct PlanItem: Identifiable {
        let id: String
        let path: String
        let kind: String
        let bytes: Int64
        let confidence: String
        let requiresAdmin: Bool
    }

    private var filtered: [Category] {
        let needle = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return groups }
        return groups.compactMap { group in
            let hits = group.apps.filter {
                $0.name.lowercased().contains(needle) || $0.bundleID.lowercased().contains(needle)
            }
            return hits.isEmpty ? nil : Category(label: group.label, apps: hits)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("搜索应用名或 bundle id", text: $search)
                    .textFieldStyle(.plain)
                if !search.isEmpty {
                    Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).foregroundStyle(.tertiary)
                }
            }
            .padding(8)
            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
            .padding(.horizontal, 16)
            .padding(.top, 12)

            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red).padding(12)
            }
            if let notice {
                Text(notice).font(.callout).foregroundStyle(.secondary).padding(.top, 8)
            }

            if loading && groups.isEmpty {
                ProgressView("读取应用列表…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(filtered) { group in
                        Section {
                            ForEach(group.apps) { app in
                                row(app)
                            }
                        } header: {
                            Text("\(group.label) · \(group.apps.count)").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .listStyle(.inset)
            }
        }
        .task {
            await load()
            // 开发/自测用：MACCLEANER_DEV_PLAN=/Applications/xxx.app 时自动打开残留清单，
            // 这样截图与人工验收不必"手点一下"（也不影响正常使用）。
            if let devPath = ProcessInfo.processInfo.environment["MACCLEANER_DEV_PLAN"], !devPath.isEmpty,
               let app = groups.flatMap(\.apps).first(where: { $0.path == devPath }) {
                await makePlan(app)
            }
        }
        .sheet(item: $plan) { plan in
            UninstallPlanSheet(plan: plan) { message in
                self.plan = nil
                self.notice = message
                Task { await load() }
            }
        }
    }

    private func row(_ app: App) -> some View {
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
            if planning == app.path {
                ProgressView().controlSize(.small)
            } else {
                Button("卸载") { Task { await makePlan(app) } }
                    .controlSize(.small)
            }
        }
        .padding(.vertical, 2)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request("apps")
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let label = group["label"]?.stringValue else { return nil }
                let apps = (group["items"]?.arrayValue ?? []).compactMap { item -> App? in
                    guard let path = item["path"]?.stringValue, let name = item["name"]?.stringValue else { return nil }
                    return App(id: path, name: name, bundleID: item["bundle_id"]?.stringValue ?? "", path: path)
                }
                return apps.isEmpty ? nil : Category(label: label, apps: apps)
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func makePlan(_ app: App) async {
        planning = app.path
        defer { planning = nil }
        do {
            let data = try await CoreClient.shared.request(
                "uninstall.plan",
                args: ["path": .string(app.path), "name": .string(app.name),
                       "bundle_id": .string(app.bundleID)]
            )
            let items = (data["items"]?.arrayValue ?? []).compactMap { item -> PlanItem? in
                guard let path = item["path"]?.stringValue, let id = item["id"]?.stringValue else { return nil }
                return PlanItem(
                    id: id,
                    path: path,
                    kind: item["kind"]?.stringValue ?? "",
                    bytes: item["allocated_bytes"]?.intValue ?? 0,
                    confidence: item["confidence"]?.stringValue ?? "exact",
                    requiresAdmin: item["requires_admin"]?.boolValue ?? false
                )
            }
            plan = Plan(
                appName: data["app"]?["name"]?.stringValue ?? app.name,
                appPath: app.path,
                items: items,
                totalBytes: data["user_total_bytes"]?.intValue ?? 0
            )
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - 残留清单（sheet）

struct UninstallPlanSheet: View {
    let plan: UninstallListView.Plan
    let onDone: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var checked: Set<String> = []
    @State private var applying = false
    @State private var error: String?

    private var exact: [UninstallListView.PlanItem] { plan.items.filter { $0.confidence != "name-match" && !$0.requiresAdmin } }
    private var guessed: [UninstallListView.PlanItem] { plan.items.filter { $0.confidence == "name-match" && !$0.requiresAdmin } }
    private var admin: [UninstallListView.PlanItem] { plan.items.filter { $0.requiresAdmin } }

    private var pickedBytes: Int64 {
        plan.items.filter { checked.contains($0.id) }.reduce(0) { $0 + $1.bytes }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("卸载 \(plan.appName)").font(.headline)
                    Text("残留 \(plan.items.count) 项 · 共 \(ByteText.format(plan.totalBytes))")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }
            }
            .padding(16)

            Divider()

            List {
                if !exact.isEmpty {
                    Section("确定项 · 路径与 bundle id 对得上") {
                        ForEach(exact) { item in toggleRow(item) }
                    }
                }
                if !guessed.isEmpty {
                    Section("按名称匹配 · 默认不勾（可能误伤别的应用）") {
                        ForEach(guessed) { item in toggleRow(item) }
                    }
                }
                if !admin.isEmpty {
                    Section("系统级残留 · 需要管理员权限，本工具不动") {
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
                Text("已选 \(checked.count) 项 · \(ByteText.format(pickedBytes))")
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
        .frame(width: 640, height: 560)
        .onAppear { checked = Set(exact.map(\.id)) }
    }

    private func toggleRow(_ item: UninstallListView.PlanItem) -> some View {
        Toggle(isOn: Binding(
            get: { checked.contains(item.id) },
            set: { isOn in
                if isOn { checked.insert(item.id) } else { checked.remove(item.id) }
            }
        )) {
            VStack(alignment: .leading, spacing: 1) {
                Text(URL(fileURLWithPath: item.path).lastPathComponent).lineLimit(1)
                Text(item.kind).font(.caption2).foregroundStyle(.tertiary)
            }
            Spacer()
            Text(ByteText.format(item.bytes)).font(.caption).monospacedDigit().foregroundStyle(.secondary)
        }
        .toggleStyle(.checkbox)
    }

    private func apply() async {
        applying = true
        defer { applying = false }
        do {
            let result = try await CoreClient.shared.request(
                "uninstall.apply",
                args: [
                    "path": .string(plan.appPath),
                    "item_ids": .array(checked.sorted().map { .string($0) }),
                ]
            )
            let moved = result["moved_count"]?.intValue ?? 0
            onDone("已把 \(moved) 项移入废纸篓；可在废纸篓里恢复")
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - 更新 / 残留（先只读，M2 后续接线）

struct UpdatesListView: View {
    @State private var groups: [(label: String, count: Int)] = []
    @State private var loading = false
    @State private var error: String?

    var body: some View {
        Group {
            if loading {
                ProgressView("检查更新…（brew outdated 可能要几秒）")
            } else if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
            } else {
                List {
                    ForEach(groups, id: \.label) { group in
                        HStack {
                            Text(group.label)
                            Spacer()
                            Text("\(group.count) 项").foregroundStyle(.secondary).monospacedDigit()
                        }
                    }
                }
                .listStyle(.inset)
            }
        }
        .task { await load() }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request("updates.list")
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let label = group["label"]?.stringValue else { return nil }
                return (label, Int(group["count"]?.intValue ?? 0))
            }
            if let sparkle = data["sparkle_updates"]?.arrayValue, !sparkle.isEmpty {
                groups.append(("自带更新（Sparkle）", sparkle.count))
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct OrphansListView: View {
    @State private var groups: [(label: String, count: Int, bytes: Int64)] = []
    @State private var loading = false
    @State private var error: String?

    var body: some View {
        Group {
            if loading {
                ProgressView("扫描残留…（会读 LaunchServices，可能要几秒）")
            } else if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
            } else {
                List {
                    ForEach(groups, id: \.label) { group in
                        HStack {
                            Text(group.label)
                            Spacer()
                            Text(ByteText.format(group.bytes)).font(.caption).foregroundStyle(.secondary).monospacedDigit()
                            Text("\(group.count) 项").foregroundStyle(.secondary).monospacedDigit()
                        }
                    }
                }
                .listStyle(.inset)
            }
        }
        .task { await load() }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            let data = try await CoreClient.shared.request("orphans.list")
            groups = (data["groups"]?.arrayValue ?? []).compactMap { group in
                guard let label = group["label"]?.stringValue else { return nil }
                return (label, Int(group["count"]?.intValue ?? 0), group["bytes"]?.intValue ?? 0)
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
