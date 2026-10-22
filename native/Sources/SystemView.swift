import SwiftUI

/// 系统状态：负载 / 内存 / 电池与节流 / 进程。只读。
struct SystemView: View {
    @State private var model: Model?
    @State private var error: String?

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
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
                if let model {
                    statsGrid(model)
                    batteryBlock(model)
                    processList(model)
                } else if error == nil {
                    ProgressView("读取系统状态…").padding(.top, 60)
                }
            }
            .padding(28)
            .frame(maxWidth: 880, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task { await load() }
        .onReceive(NotificationCenter.default.publisher(for: .mcReload)) { _ in
            Task { await load() }
        }
    }

    // MARK: - 区块

    private func statsGrid(_ model: Model) -> some View {
        HStack(alignment: .top, spacing: 14) {
            statCard(
                title: "负载（1 / 5 / 15 分钟）",
                value: model.load.joined(separator: " / "),
                footnote: perCore(model)
            )
            statCard(
                title: "内存",
                value: "\(ByteText.format(model.memoryUsed)) / \(ByteText.format(model.memoryTotal))",
                footnote: memoryPercent(model)
            )
            statCard(title: "CPU", value: "\(model.cpuCount) 核", footnote: nil)
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
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.weight(.semibold)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.7)
            if let footnote {
                Text(footnote).font(.caption2).foregroundStyle(.tertiary)
            } else {
                Text(" ").font(.caption2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color.secondary.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder
    private func batteryBlock(_ model: Model) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("电池与节流").font(.headline)
            HStack(alignment: .top, spacing: 14) {
                if let battery = model.battery {
                    statCard(title: "电池", value: "\(battery.percent)%", footnote: battery.state)
                    statCard(title: "循环 / 健康", value: "\(battery.cycles) / \(battery.health.map { "\($0)%" } ?? "—")", footnote: nil)
                }
                statCard(title: "性能节流", value: model.throttled ? "已触发" : "正常", footnote: nil)
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
                VStack(spacing: 0) {
                    ForEach(model.processes) { item in
                        HStack {
                            Image(systemName: "terminal").foregroundStyle(.secondary).frame(width: 20)
                            Text(item.name).lineLimit(1)
                            Spacer(minLength: 12)
                            Text(ByteText.format(item.rss)).font(.caption).foregroundStyle(.secondary).monospacedDigit()
                            Text(String(format: "%.1f%%", item.cpu))
                                .font(.caption).monospacedDigit().frame(width: 56, alignment: .trailing)
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
        } catch {
            self.error = error.localizedDescription
        }
    }
}
