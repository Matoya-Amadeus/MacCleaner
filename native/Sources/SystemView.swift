import SwiftUI

/// 系统状态：负载 / 内存 / 电池与节流 / 进程。只读。
struct SystemView: View {
    @Environment(\.appLanguage) private var language

    @State private var model: Model?
    @State private var detail: Detail?
    @State private var error: String?
    @State private var detailError: String?
    @State private var sampledAt: Date?
    @State private var detailStage: String?
    @State private var processLimit: Int = 6

    struct Process: Identifiable {
        let id = UUID()
        let name: String
        let cpu: Double
        let rss: Int64
    }

    struct InstantProcess: Identifiable {
        let id = UUID()
        let name: String
        let cpuInstant: Double
        let cpuLifetime: Double?
        let rss: Int64
    }

    struct Model {
        let load: [String]
        let cpuCount: Int
        let memoryUsed: Int64
        let memoryTotal: Int64
        let battery: Battery?
        let processes: [Process]
        let throttled: Bool
    }

    /// `system.detail` 的只读诊断数据；旧 `system` 的累计均值语义不在此复用。
    struct Detail {
        let sampledAt: String
        let intervalMs: Int
        let cpuIdle: Double?
        let cpuCount: Int
        let processes: [InstantProcess]
        let memoryFreePercent: Int?
        let swapUsed: Int64
        let compressorPages: Int64
        let pageins: Int64
        let smartStatus: String
        let diskFree: Int64
        let snapshots: [String]
        let hardware: String
        let osVersion: String
        let displays: [String]
        let enabledItems: Int
        let startupAvailable: Bool
        let launchctlItems: Int
        let runAtLoad: Int
        let periodic: Int
        let bootToPowerd: Int?
        let bootTime: String
        let indexingVolumes: [String]
        let filevault: String
        let thermalLimits: String
        let batteryCapacity: String
        let limitations: [String]
    }

    struct Battery {
        let percent: Int
        let state: String
        let cycles: Int
        let health: Int?
    }

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(title: L10n.t("system.title", language), subtitle: L10n.t("system.subtitle", language)) {
                if let sampledAt {
                    Text("采样于 \(Self.clock.string(from: sampledAt))")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }

            ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if let error {
                    StatusBanner(level: .error, text: error)
                }
                if let detailError {
                    StatusBanner(level: .warn, text: detailError)
                }
                if let model {
                    statsGrid(model)
                    batteryBlock(model)
                    processList(model)
                } else if error == nil {
                    ProgressView("读取系统状态…").padding(.top, 60)
                }
                if let detail {
                    diagnosticsBlock(detail)
                } else if detailError == nil && model != nil {
                    ProgressView(detailStage ?? "采样瞬时 CPU 与开机项…").padding(.top, 20)
                }
            }
            .scrollIndicators(.never)
            .padding(.horizontal, Theme.Space.page)
            .padding(.bottom, Theme.Space.page)
            .frame(maxWidth: 880, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .task { await load() }
        .onReceive(NotificationCenter.default.publisher(for: .mcReload)) { _ in
            Task { await load() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .mcDiagnosticProgress)) { note in
            if let op = note.userInfo?["op"] as? String {
                detailStage = "正在采样 \(op)…"
            }
        }
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    // MARK: - 区块

    private func statsGrid(_ model: Model) -> some View {
        let loads = model.load.compactMap(Double.init)
        let cores = Double(max(model.cpuCount, 1))
        return HStack(alignment: .top, spacing: 14) {
            statCard(
                title: "负载（1 / 5 / 15 分钟）",
                value: model.load.joined(separator: " / "),
                footnote: perCore(model)
            ) {
                LoadBars(values: loads, scale: cores)
            }
            statCard(
                title: "内存",
                value: "\(ByteText.format(model.memoryUsed)) / \(ByteText.format(model.memoryTotal))",
                footnote: memoryPercent(model)
            ) {
                VStack(spacing: 4) {
                    RingGauge(percent: memoryRatio(model) * 100, tint: memoryTint(model), size: 44)
                }
            }
            statCard(
                title: "CPU",
                value: "\(model.cpuCount) 核",
                footnote: perCore(model)
            ) {
                CoreGrid(count: model.cpuCount, columns: 5)
            }
        }
    }

    private func memoryRatio(_ model: Model) -> Double {
        guard model.memoryTotal > 0 else { return 0 }
        return Double(model.memoryUsed) / Double(model.memoryTotal)
    }

    private func memoryTint(_ model: Model) -> Color {
        switch memoryRatio(model) {
        case 0.85...: return .red
        case 0.65...: return .orange
        default: return Theme.accent
        }
    }

    private func perCore(_ model: Model) -> String? {
        guard let first = Double(model.load.first ?? ""), model.cpuCount > 0 else { return nil }
        return String(format: "每核 %.2f", first / Double(model.cpuCount))
    }

    private func memoryPercent(_ model: Model) -> String? {
        guard model.memoryTotal > 0 else { return nil }
        let percent = Double(model.memoryUsed) / Double(model.memoryTotal) * 100
        return String(format: "已用 %.0f%%", percent)
    }

    private func statCard(title: String, value: String, footnote: String?) -> some View {
        statCard(title: title, value: value, footnote: footnote) { EmptyView() }
    }

    /// 带图形的数值卡：图形只占右侧固定宽度，数字仍在左，扫视顺序不变。
    private func statCard<Graphic: View>(
        title: String,
        value: String,
        footnote: String?,
        @ViewBuilder graphic: () -> Graphic
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .center, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(value)
                        .font(.title3.weight(.semibold))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                    Text(footnote ?? " ")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Spacer(minLength: 4)
                graphic()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(CardBackground(padding: 14))
    }

    @ViewBuilder
    private func batteryBlock(_ model: Model) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("电池与节流").font(.headline)
            HStack(alignment: .top, spacing: 14) {
                if let battery = model.battery {
                    statCard(title: "电池", value: "\(battery.percent)%", footnote: battery.state) {
                        RingGauge(
                            percent: Double(battery.percent),
                            tint: battery.percent <= 20 ? .orange : .green,
                            size: 44
                        )
                    }
                    statCard(
                        title: "循环 / 健康",
                        value: "\(battery.cycles) 次",
                        footnote: battery.health.map { "健康 \($0)%" } ?? "健康 —"
                    ) {
                        if let health = battery.health {
                            MeterBar(
                                ratio: Double(health) / 100,
                                tint: health >= 80 ? .green : (health >= 60 ? .orange : .red),
                                height: 8
                            )
                            .frame(width: 54)
                        } else {
                            Text("—").foregroundStyle(.tertiary)
                        }
                    }
                }
                statCard(
                    title: "性能节流",
                    value: model.throttled ? "已触发" : "正常",
                    footnote: model.throttled ? "系统正在限制性能" : "未检测到降频"
                ) {
                    StatusPill(text: model.throttled ? "降频中" : "全速", isGood: !model.throttled)
                }
            }
        }
    }

    @ViewBuilder
    private func diagnosticsBlock(_ detail: Detail) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("性能诊断").font(.headline)
                Text("只读 · \(detail.intervalMs) ms 瞬时采样 · \(detail.sampledAt)")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text("下方「瞬时 CPU」是 top 二次采样值；上面「累计平均 CPU」是 ps %cpu 自进程启动以来的衰减均值，两者口径不同，不能混用。")
                .font(.caption2).foregroundStyle(.tertiary)

            HStack(alignment: .top, spacing: 14) {
                statCard(title: "CPU 空闲（瞬时）",
                         value: detail.cpuIdle.map { String(format: "%.0f%%", $0) } ?? "—",
                         footnote: "\(detail.cpuCount) 核" )
                statCard(title: "内存压力",
                         value: detail.memoryFreePercent.map { "空闲 \($0)%" } ?? "—",
                         footnote: "swap \(ByteText.format(detail.swapUsed)) · 压缩 \(detail.compressorPages) 页 · pageins \(detail.pageins)")
                statCard(title: "磁盘健康",
                         value: detail.smartStatus,
                         footnote: "可用 \(ByteText.format(detail.diskFree)) · 本地快照 \(detail.snapshots.count) 个")
            }
            HStack(alignment: .top, spacing: 14) {
                statCard(title: "机型与系统",
                         value: detail.hardware,
                         footnote: detail.osVersion)
                statCard(title: "开机与后台项",
                         value: detail.bootToPowerd.map { "\($0) s 到 powerd" } ?? "—",
                         footnote: (detail.startupAvailable
                            ? "BTM 已启用 \(detail.enabledItems)"
                            : "BTM 未测到")
                            + " · launchctl \(detail.launchctlItems) · RunAtLoad \(detail.runAtLoad) · 周期 \(detail.periodic)")
                statCard(title: "显示器 / 索引",
                         value: "\(detail.displays.count) 块屏",
                         footnote: "索引卷 \(detail.indexingVolumes.count) · FileVault \(detail.filevault)")
            }
            if !detail.thermalLimits.isEmpty || !detail.batteryCapacity.isEmpty {
                Text([detail.thermalLimits, detail.batteryCapacity].filter { !$0.isEmpty }.joined(separator: "　·　"))
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            if !detail.processes.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("瞬时 CPU 占用最高的进程").font(.headline)
                    let peak = max(detail.processes.map(\.cpuInstant).max() ?? 100, 100)
                    ForEach(Array(detail.processes.prefix(8))) { item in
                        HStack {
                            Image(systemName: "bolt.horizontal").foregroundStyle(.secondary).frame(width: 20)
                            Text(item.name).lineLimit(1)
                            Spacer(minLength: 12)
                            if let lifetime = item.cpuLifetime {
                                Text(String(format: "累计 %.1f%%", lifetime))
                                    .font(.caption2).foregroundStyle(.tertiary).monospacedDigit()
                            }
                            Text(String(format: "%.1f%%", item.cpuInstant))
                                .font(.caption).monospacedDigit()
                                .frame(width: 56, alignment: .trailing)
                            MiniBar(ratio: item.cpuInstant / peak, tint: Theme.accent)
                                .frame(width: 60)
                        }
                        .padding(.vertical, 3)
                        Divider().opacity(0.4)
                    }
                }
            }
            if !detail.displays.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("显示器").font(.subheadline)
                    ForEach(detail.displays, id: \.self) { line in
                        Text(line).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            if !detail.limitations.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("测不到的项目（明说）").font(.subheadline)
                    ForEach(detail.limitations, id: \.self) { line in
                        Text("· \(line)").font(.caption2).foregroundStyle(.tertiary)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func processList(_ model: Model) -> some View {
        if !model.processes.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("累计平均 CPU（ps %cpu）").font(.headline)
                    Text("前 \(model.processes.count) 个 · 非瞬时值").font(.caption).foregroundStyle(.secondary)
                    Spacer(minLength: 8)
                    Picker("显示数量", selection: $processLimit) {
                        Text("6 个").tag(6)
                        Text("12 个").tag(12)
                        Text("20 个").tag(20)
                    }
                    .labelsHidden()
                    .frame(width: 96)
                    .onChange(of: processLimit) { _ in
                        Task { await loadSystem() }
                    }
                }
                let peak = max(model.processes.map(\.cpu).max() ?? 100, 100)
                VStack(spacing: 0) {
                    ForEach(model.processes) { item in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Image(systemName: "terminal").foregroundStyle(.secondary).frame(width: 20)
                                Text(item.name).lineLimit(1)
                                Spacer(minLength: 12)
                                Text(ByteText.format(item.rss)).font(.caption).foregroundStyle(.secondary).monospacedDigit()
                                Text(String(format: "%.1f%%", item.cpu))
                                    .font(.caption).monospacedDigit()
                                    .foregroundStyle(item.cpu >= 100 ? Color.orange : Color.primary)
                                    .frame(width: 56, alignment: .trailing)
                            }
                            // 基准取"最高的那个进程"与 100% 的较大者，条长度才有可比性。
                            MiniBar(ratio: item.cpu / peak,
                                    tint: item.cpu >= 100 ? .orange : Theme.accent)
                                .padding(.leading, 30)
                        }
                        .padding(.vertical, 7)
                        Divider().opacity(0.4)
                    }
                }
            }
        }
    }

    // MARK: - 数据

    private func load() async {
        await loadSystem()
        await loadDetail()
    }

    /// 快快照单独拆出来：改「显示几个进程」时只重取这一条，不重跑 3 秒诊断采样。
    private func loadSystem() async {
        do {
            let data = try await CoreClient.shared.request(
                "system", args: ["limit": .int(processLimit)])
            let power = data["power"]
            let battery: Battery? = {
                guard let power, let percent = power["percent"]?.intValue else { return nil }
                return Battery(
                    percent: Int(percent),
                    state: power["state"]?.stringValue ?? "",
                    cycles: Int(power["cycles"]?.intValue ?? 0),
                    health: power["health_percent"]?.intValue.map(Int.init)
                )
            }()
            model = Model(
                load: (data["load"]?.arrayValue ?? []).compactMap { $0.stringValue ?? $0.intValue.map(String.init) },
                cpuCount: Int(data["cpu_count"]?.intValue ?? 0),
                memoryUsed: data["memory_used"]?.intValue ?? 0,
                memoryTotal: data["memory_total"]?.intValue ?? 0,
                battery: battery,
                processes: (data["processes"]?.arrayValue ?? []).compactMap { item in
                    guard let name = item["name"]?.stringValue else { return nil }
                    return Process(
                        name: name,
                        cpu: item["cpu"]?.doubleValue ?? 0,
                        rss: item["rss"]?.intValue ?? 0
                    )
                },
                throttled: data["thermal"]?["throttled"]?.boolValue ?? false
            )
            sampledAt = Date()
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// 诊断是慢命令（>0.3s，内核先发 started 事件）；单独请求，失败不影响上方快快照。
    private func loadDetail() async {
        do {
            let data = try await CoreClient.shared.request("system.detail") { event in
                if case .started(let op) = event {
                    NotificationCenter.default.post(name: .mcDiagnosticProgress,
                                                    object: nil, userInfo: ["op": op])
                }
            }
            detail = Self.parseDetail(data)
            detailError = nil
            detailStage = nil
        } catch {
            detailError = "性能诊断采样失败：\(error.localizedDescription)"
            detailStage = nil
        }
    }

    private static func parseDetail(_ data: JSONValue) -> Detail {
        let memory = data["memory"]
        let disk = data["disk"]
        let hardware = data["hardware"]
        let startup = data["startup"]
        let thermal = data["thermal"]
        let power = data["power"]
        let chip = hardware?["chip"]?.stringValue ?? hardware?["model_name"]?.stringValue ?? "—"
        let cores = hardware?["cores"]?.stringValue ?? ""
        let ram = hardware?["memory"]?.stringValue ?? ""
        let hardwareLine = [chip, cores.isEmpty ? nil : "\(cores) 核", ram]
            .compactMap { $0 }.joined(separator: " · ")
        let version = hardware?["os_version"]?.stringValue ?? ""
        let build = hardware?["os_build"]?.stringValue ?? ""
        let osLine = [version.isEmpty ? nil : "macOS \(version)", build.isEmpty ? nil : "(\(build))"]
            .compactMap { $0 }.joined(separator: " ")
        let limits = [thermal?["speed_limit"]?.intValue.map { "速度上限 \($0)%" },
                      thermal?["scheduler_limit"]?.intValue.map { "调度上限 \($0)%" }]
            .compactMap { $0 }.joined(separator: " · ")
        let capacity = [power?["design_mah"]?.intValue.map { "设计 \($0) mAh" },
                        power?["full_mah"]?.intValue.map { "满充 \($0) mAh" }]
            .compactMap { $0 }.joined(separator: " · ")
        let displays = (data["displays"]?.arrayValue ?? []).map { item -> String in
            let resolution = item["resolution"]?.stringValue ?? "—"
            let looks = item["looks_like"]?.stringValue
            let main = item["main"]?.stringValue == "Yes" ? " · 主屏" : ""
            return [resolution, looks].compactMap { $0 }.joined(separator: " · ") + main
        }
        let processes: [InstantProcess] = (data["processes"]?.arrayValue ?? []).compactMap { item in
            guard let name = item["name"]?.stringValue else { return nil }
            return InstantProcess(
                name: name,
                cpuInstant: item["cpu_instant"]?.doubleValue ?? 0,
                cpuLifetime: item["cpu_lifetime"]?.doubleValue,
                rss: item["rss"]?.intValue ?? 0
            )
        }
        return Detail(
            sampledAt: data["sampled_at"]?.stringValue ?? "",
            intervalMs: Int(data["sample_interval_ms"]?.intValue ?? 0),
            cpuIdle: data["cpu_idle_percent"]?.doubleValue,
            cpuCount: Int(data["cpu_count"]?.intValue ?? 0),
            processes: processes,
            memoryFreePercent: memory?["free_percentage"]?.intValue.map(Int.init),
            swapUsed: memory?["swap_used_bytes"]?.intValue ?? 0,
            compressorPages: memory?["compressor_pages"]?.intValue ?? 0,
            pageins: memory?["pageins"]?.intValue ?? 0,
            smartStatus: disk?["smart_status"]?.stringValue ?? "—",
            diskFree: disk?["free"]?.intValue ?? 0,
            snapshots: (disk?["snapshots"]?.arrayValue ?? []).compactMap { $0.stringValue },
            hardware: hardwareLine,
            osVersion: osLine,
            displays: displays,
            enabledItems: Int(startup?["enabled_count"]?.intValue ?? 0),
            startupAvailable: startup?["available"]?.boolValue ?? false,
            launchctlItems: Int(startup?["launchctl"]?["count"]?.intValue ?? 0),
            runAtLoad: (startup?["run_at_load"]?.arrayValue ?? []).count,
            periodic: (startup?["periodic"]?.arrayValue ?? []).count,
            bootToPowerd: startup?["boot_to_powerd_seconds"]?.intValue.map(Int.init),
            bootTime: startup?["boot_time"]?.stringValue ?? "",
            indexingVolumes: (data["indexing"]?["volumes"]?.arrayValue ?? []).compactMap { $0["volume"]?.stringValue },
            filevault: data["filevault"]?.stringValue ?? "—",
            thermalLimits: limits,
            batteryCapacity: capacity,
            limitations: (data["limitations"]?.arrayValue ?? []).compactMap { $0.stringValue }
        )
    }
}
