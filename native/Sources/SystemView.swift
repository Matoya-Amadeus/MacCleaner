import SwiftUI

/// 系统状态：负载 / 内存 / 电池与节流 / 进程。只读。
struct SystemView: View {
    @Environment(\.appLanguage) private var language

    @State private var model: Model?
    @State private var error: String?
    @State private var sampledAt: Date?

    struct Process: Identifiable {
        let id = UUID()
        let name: String
        let cpu: Double
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
                if let model {
                    statsGrid(model)
                    batteryBlock(model)
                    processList(model)
                } else if error == nil {
                    ProgressView("读取系统状态…").padding(.top, 60)
                }
            }
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
    private func processList(_ model: Model) -> some View {
        if !model.processes.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("占用最高的进程").font(.headline)
                    Text("按 CPU 排序 · \(model.processes.count) 个").font(.caption).foregroundStyle(.secondary)
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
        do {
            let data = try await CoreClient.shared.request("system")
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
}
