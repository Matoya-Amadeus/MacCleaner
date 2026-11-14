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
    /// 0 = 瞬时 CPU（top 二次采样），1 = 累计平均 CPU（ps %cpu）。
    @State private var processMetric: Int = 0

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
    ///
    /// 只保留界面真正画得出来的字段：没有值就用 Optional/空值表示，
    /// 由视图整块省略；明细说明仍留在数据层给 agent 读取。
    struct Detail {
        let intervalMs: Int
        let cpuIdle: Double?
        let processes: [InstantProcess]
        let memoryFreePercent: Int?
        let swapUsed: Int64
        let smartStatus: String
        let diskFree: Int64
        let hardware: String
        let osVersion: String
        let displays: [String]
        let launchctlItems: Int
        let runAtLoad: Int
        let periodic: Int
        let bootToPowerd: Int?
        let filevault: String
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
            VStack(alignment: .leading, spacing: 18) {
                if let error {
                    StatusBanner(level: .error, text: error)
                }
                if let detailError {
                    StatusBanner(level: .warn, text: detailError)
                }
                if let model {
                    // 格式塔：算力 / 容量 / 电源各成一组，组间留白大于组内留白。
                    computeSection(model, detail)
                    capacitySection(model, detail)
                    powerSection(model)
                } else if error == nil {
                    ProgressView("读取系统状态…").padding(.top, 60)
                }
                if let detail {
                    startupSection(detail)
                    processSection(model, detail)
                    machineSection(detail)
                } else if detailError == nil && model != nil {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text(detailStage ?? "采样瞬时 CPU 与开机项…")
                            .font(.caption).foregroundStyle(.tertiary)
                    }
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

    /// 算力组：负载、核数、瞬时 CPU 空闲都是「算得过来 / 算不过来」，放一起。
    /// 只渲染真的测到的值（cpuIdle 为 nil 时整张卡不出现，不写「—」）。
    private func computeSection(_ model: Model, _ detail: Detail?) -> some View {
        let loads = model.load.compactMap(Double.init)
        let cores = Double(max(model.cpuCount, 1))
        return VStack(alignment: .leading, spacing: 8) {
            SystemSectionHeader(icon: "cpu", title: "算力与负载", note: "1 秒瞬时采样")
            HStack(alignment: .top, spacing: 12) {
                statCard(title: "负载 1 / 5 / 15 分钟",
                         value: model.load.joined(separator: " / "),
                         footnote: perCore(model)) {
                    LoadBars(values: loads, scale: cores)
                }
                statCard(title: "CPU", value: "\(model.cpuCount) 核",
                         footnote: perCore(model)) {
                    CoreGrid(count: model.cpuCount, columns: 5)
                }
                if let idle = detail?.cpuIdle {
                    statCard(title: "CPU 空闲（瞬时）",
                             value: String(format: "%.0f%%", idle),
                             footnote: nil) {
                        RingGauge(percent: idle,
                                  tint: idle < 15 ? Theme.warn : Theme.accent, size: 44)
                    }
                }
            }
        }
    }

    /// 容量组：内存、磁盘都是「还剩多少 / 健康否」，和电池分开。
    private func capacitySection(_ model: Model, _ detail: Detail?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SystemSectionHeader(icon: "memorychip", title: "内存与磁盘")
            HStack(alignment: .top, spacing: 12) {
                statCard(title: "内存",
                         value: "\(ByteText.format(model.memoryUsed)) / \(ByteText.format(model.memoryTotal))",
                         footnote: memoryPercent(model)) {
                    RingGauge(percent: memoryRatio(model) * 100,
                              tint: memoryTint(model), size: 44)
                }
                if let free = detail?.memoryFreePercent {
                    statCard(title: "内存空闲（压力）", value: "\(free)%",
                             footnote: "swap \(ByteText.format(detail?.swapUsed ?? 0))") {
                        MeterBar(ratio: Double(free) / 100,
                                 tint: free < 25 ? Theme.warn : Theme.accent, height: 8)
                            .frame(width: 54)
                    }
                }
                if let detail, detail.diskFree > 0 {
                    statCard(title: "磁盘可用", value: ByteText.format(detail.diskFree),
                             footnote: detail.smartStatus.isEmpty ? nil : detail.smartStatus) {
                        StatusPill(text: detail.smartStatus == "Verified" ? "正常" : detail.smartStatus,
                                   isGood: detail.smartStatus == "Verified")
                    }
                }
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
                        .lineLimit(2)
                        .truncationMode(.middle)
                }
                Spacer(minLength: 4)
                graphic()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(CardBackground(padding: 14))
    }

    /// 电源组：电池 / 循环健康 / 节流同属「供电与性能限制」，单独成组。
    /// 测不到的健康值不写「健康 —」，直接不显示那张卡。
    @ViewBuilder
    private func powerSection(_ model: Model) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SystemSectionHeader(icon: "battery.100", title: "电池与节流")
            HStack(alignment: .top, spacing: 12) {
                if let battery = model.battery {
                    statCard(title: "电池", value: "\(battery.percent)%", footnote: battery.state) {
                        RingGauge(percent: Double(battery.percent),
                                  tint: battery.percent <= 20 ? .orange : .green, size: 44)
                    }
                    if let health = battery.health {
                        statCard(title: "循环 / 健康", value: "\(battery.cycles) 次",
                                 footnote: "健康 \(health)%") {
                            MeterBar(ratio: Double(health) / 100,
                                     tint: health >= 80 ? .green : (health >= 60 ? .orange : .red),
                                     height: 8)
                                .frame(width: 54)
                        }
                    }
                }
                statCard(title: "性能节流",
                         value: model.throttled ? "已触发" : "正常",
                         footnote: model.throttled ? "系统正在限制性能" : "未检测到降频") {
                    StatusPill(text: model.throttled ? "降频中" : "全速", isGood: !model.throttled)
                }
            }
        }
    }

    /// 开机组：耗时条 + 三个计数胶囊。只画稳定来源，不写未采集说明。
    @ViewBuilder
    private func startupSection(_ detail: Detail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SystemSectionHeader(icon: "clock", title: "开机与后台项")
            HStack(alignment: .top, spacing: 12) {
                if let seconds = detail.bootToPowerd {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .firstTextBaseline, spacing: 4) {
                            Text("\(seconds)").font(.title2.weight(.semibold).monospacedDigit())
                            Text("s 到 powerd").font(.caption).foregroundStyle(.secondary)
                        }
                        SystemTimeBar(seconds: seconds)
                        Text("内核启动 → 系统守护就绪").font(.caption2).foregroundStyle(.tertiary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .card(padding: 12)
                }
                SystemCountChip(icon: "list.bullet", value: "\(detail.launchctlItems)",
                                label: "launchctl 项")
                SystemCountChip(icon: "power", value: "\(detail.runAtLoad)",
                                label: "开机自启")
                SystemCountChip(icon: "repeat", value: "\(detail.periodic)",
                                label: "周期任务")
            }
        }
    }

    /// 本机组：机型 / 系统 / 显示器 / 索引都是「这台机器是什么」，合成一组。
    /// 显示器用形状表示数量，不再逐行列分辨率文字。
    @ViewBuilder
    private func machineSection(_ detail: Detail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SystemSectionHeader(icon: "laptopcomputer", title: "本机与显示")
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(detail.hardware)
                        .font(.subheadline.weight(.medium)).lineLimit(1)
                    Text(detail.osVersion)
                        .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Spacer(minLength: 8)
                if !detail.displays.isEmpty {
                    HStack(spacing: 6) {
                        SystemScreenGlyph(count: detail.displays.count)
                        Text("\(detail.displays.count) 块屏")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
                if detail.filevault == "On" {
                    StatusPill(text: "FileVault", isGood: true)
                }
            }
            .card(padding: 12)
        }
    }

    /// 进程组：两种 CPU 口径是「同一件事的两种读数」，合并成一组用分段器切换，
    /// 不再一个在页面中段、一个在诊断区底部（格式塔的接近性）。
    /// 默认显示瞬时值；切到累计平均才用 `system` 的 limit 重取。
    @ViewBuilder
    private func processSection(_ model: Model?, _ detail: Detail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SystemSectionHeader(icon: "chart.bar", title: "进程",
                                note: "瞬时 = top 二次采样；累计平均 CPU（ps %cpu）= 自启动衰减均值")
            HStack(spacing: 10) {
                Picker("CPU 口径", selection: $processMetric) {
                    Text("瞬时 CPU").tag(0)
                    Text("累计平均 CPU（ps %cpu）").tag(1)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                Spacer(minLength: 8)
                Picker("显示数量", selection: $processLimit) {
                    Text("6 个").tag(6)
                    Text("12 个").tag(12)
                    Text("20 个").tag(20)
                }
                .labelsHidden()
                .frame(width: 90)
                .onChange(of: processLimit) {
                    // 快命令重取，保证切回「累计平均」时条数与选择器一致，
                    // 不会留着上一次的 6 条。
                    Task { await loadSystem() }
                }
            }
            VStack(spacing: 0) {
                if processMetric == 0 {
                    let rows = Array(detail.processes.prefix(processLimit))
                    let peak = max(rows.map(\.cpuInstant).max() ?? 100, 100)
                    ForEach(rows) { item in
                        SystemProcessRow(
                            name: item.name,
                            percent: item.cpuInstant,
                            ratio: item.cpuInstant / peak,
                            secondary: item.cpuLifetime.map { String(format: "累计 %.0f%%", $0) },
                            tint: item.cpuInstant >= 100 ? Theme.warn : Theme.accent
                        )
                    }
                } else if let model {
                    let peak = max(model.processes.map(\.cpu).max() ?? 100, 100)
                    ForEach(model.processes) { item in
                        SystemProcessRow(
                            name: item.name,
                            percent: item.cpu,
                            ratio: item.cpu / peak,
                            secondary: ByteText.format(item.rss),
                            tint: item.cpu >= 100 ? Theme.warn : Theme.accent
                        )
                    }
                }
            }
            .card(padding: 10)
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
        let chip = hardware?["chip"]?.stringValue ?? hardware?["model_name"]?.stringValue ?? ""
        let cores = hardware?["cores"]?.stringValue ?? ""
        let ram = hardware?["memory"]?.stringValue ?? ""
        let hardwareLine = [chip, cores.isEmpty ? nil : "\(cores) 核", ram]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        let version = hardware?["os_version"]?.stringValue ?? ""
        let build = hardware?["os_build"]?.stringValue ?? ""
        let osLine = [version.isEmpty ? nil : "macOS \(version)", build.isEmpty ? nil : "(\(build))"]
            .compactMap { $0 }.joined(separator: " ")
        // 显示器只数数量（图形表示），不再逐行堆分辨率文字。
        let displays = (data["displays"]?.arrayValue ?? []).compactMap { item -> String? in
            item["resolution"]?.stringValue
        }
        let processes: [InstantProcess] = (data["processes"]?.arrayValue ?? []).compactMap { item in
            guard let name = item["name"]?.stringValue,
                  let instant = item["cpu_instant"]?.doubleValue else { return nil }
            return InstantProcess(
                name: name,
                cpuInstant: instant,
                cpuLifetime: item["cpu_lifetime"]?.doubleValue,
                rss: item["rss"]?.intValue ?? 0
            )
        }
        return Detail(
            intervalMs: Int(data["sample_interval_ms"]?.intValue ?? 0),
            // 只接受真的测到的值：nil / 空串一律不画，不写「—」。
            cpuIdle: data["cpu_idle_percent"]?.doubleValue,
            processes: processes,
            memoryFreePercent: memory?["free_percentage"]?.intValue.map(Int.init),
            swapUsed: memory?["swap_used_bytes"]?.intValue ?? 0,
            smartStatus: disk?["smart_status"]?.stringValue ?? "",
            diskFree: disk?["free"]?.intValue ?? 0,
            hardware: hardwareLine,
            osVersion: osLine,
            displays: displays,
            launchctlItems: Int(startup?["launchctl"]?["count"]?.intValue ?? 0),
            runAtLoad: (startup?["run_at_load"]?.arrayValue ?? []).count,
            periodic: (startup?["periodic"]?.arrayValue ?? []).count,
            bootToPowerd: startup?["boot_to_powerd_seconds"]?.intValue.map(Int.init),
            filevault: data["filevault"]?.stringValue ?? ""
        )
    }
}
