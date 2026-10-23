import SwiftUI

/// 「AI」页：回答一个问题——**agent 到底能怎么用 Mac Cleaner**。
///
/// 两段：
/// - 工具：MCP 工具（agent 直接调）+ stdio 命令（脚本/别的前端用）+ 一条示例；
/// - 本机 Skill：这台机器上装了哪些 skill（原来挂在右上角按钮里）。
struct ToolsView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case tools, skills
        var id: String { rawValue }
        var title: String {
            switch self {
            case .tools: return "可调用"
            case .skills: return "软件 Skill"
            }
        }
    }

    @State private var tab: Tab = .tools

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(title: "AI 能力", subtitle: "agent 可直接调用的工具：MCP 与 stdio 命令")

            ChipPicker(options: Tab.allCases.map { ($0, $0.title) }, selection: $tab)
                .padding(.bottom, 10)

            switch tab {
            case .tools: ToolCatalogView()
            case .skills: SkillCatalogView()
            }
        }
    }
}

// MARK: - 可调用清单

struct ToolCatalogView: View {
    @State private var mcp: [Entry] = []
    @State private var commands: [Entry] = []
    @State private var example = ""
    @State private var workflow: [(String, String)] = []
    @State private var safety: [String] = []
    @State private var loadedAt: Date?
    @State private var sectionFilter: String?   // nil = 全部分类
    @State private var search = ""
    @State private var error: String?

    struct Entry: Identifiable {
        var id: String { name }
        let name: String
        let summary: String
    }

    private func filtered(_ entries: [Entry]) -> [Entry] {
        let needle = search.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return entries }
        return entries.filter {
            $0.name.lowercased().contains(needle) || $0.summary.lowercased().contains(needle)
        }
    }

    private var sections: [(label: String, count: Int)] {
        var out: [(String, Int)] = []
        if !workflow.isEmpty { out.append(("推荐调用顺序", workflow.count)) }
        if !safety.isEmpty { out.append(("安全边界", safety.count)) }
        if !mcp.isEmpty { out.append(("MCP 工具", mcp.count)) }
        if !commands.isEmpty { out.append(("stdio 命令", commands.count)) }
        return out
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("搜索工具或命令", text: $search).textFieldStyle(.plain)
                if !search.isEmpty {
                    Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.plain).foregroundStyle(.tertiary)
                }
            }
            .padding(8)
            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
            .padding(.horizontal, 16)
            .padding(.top, 12)

            HStack {
                FilterBar(status: .constant(.all), category: $sectionFilter, categories: sections)
                Spacer()
                if let loadedAt {
                    Text("读取于 \(Self.clock.string(from: loadedAt))")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 6)

            if let error {
                StatusBanner(level: .error, text: error)
            }

            List {
                if !workflow.isEmpty, sectionFilter == nil || sectionFilter == "推荐调用顺序" {
                    Section("推荐调用顺序 · 先列清单，等用户确认再执行") {
                        ForEach(Array(workflow.enumerated()), id: \.offset) { index, step in
                            HStack(alignment: .top, spacing: 8) {
                                Text("\(index + 1)")
                                    .font(.caption.weight(.semibold)).monospacedDigit()
                                    .frame(width: 16, height: 16)
                                    .background(Color.accentColor.opacity(0.15), in: Circle())
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(step.0).font(.system(.body, design: .monospaced))
                                    Text(step.1).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
                if !safety.isEmpty, sectionFilter == nil || sectionFilter == "安全边界" {
                    Section("安全边界") {
                        ForEach(safety, id: \.self) { line in
                            Label(line, systemImage: "checkmark.shield")
                                .font(.caption)
                                .labelStyle(.titleAndIcon)
                        }
                    }
                }

                let mcps = sectionFilter == nil || sectionFilter == "MCP 工具" ? filtered(mcp) : []
                if !mcps.isEmpty {
                    Section("MCP 工具 · \(mcps.count) 个（agent 直接调用）") {
                        ForEach(mcps) { entry in row(entry) }
                    }
                }
                let cmds = sectionFilter == nil || sectionFilter == "stdio 命令" ? filtered(commands) : []
                if !cmds.isEmpty {
                    Section("stdio 命令 · \(cmds.count) 个（脚本 / 其它前端）") {
                        ForEach(cmds) { entry in row(entry) }
                    }
                }
                if !example.isEmpty {
                    Section("调用示例") {
                        Text(example)
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                            .padding(.vertical, 2)
                    }
                }
            }
            .listStyle(.inset)
            .id("tool-catalog")   // 数据载入后不要跳到中间（行内 selectable 文本会把焦点带走）
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

    private func row(_ entry: Entry) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(entry.name)
                .font(.system(.body, design: .monospaced))
            Text(entry.summary)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(entry.name)，\(entry.summary)")
        .contextMenu {
            Button("拷贝名字") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(entry.name, forType: .string)
            }
        }
    }

    private func load() async {
        do {
            let data = try await CoreClient.shared.request("tools.list")
            mcp = (data["mcp"]?.arrayValue ?? []).compactMap { item in
                guard let name = item["name"]?.stringValue else { return nil }
                return Entry(name: name, summary: item["summary"]?.stringValue ?? "")
            }
            commands = (data["commands"]?.arrayValue ?? []).compactMap { item in
                guard let name = item["name"]?.stringValue else { return nil }
                return Entry(name: name, summary: item["summary"]?.stringValue ?? "")
            }
            example = data["example"]?.stringValue ?? ""
            workflow = (data["workflow"]?.arrayValue ?? []).compactMap { step in
                guard let cmd = step["cmd"]?.stringValue else { return nil }
                return (cmd, step["note"]?.stringValue ?? "")
            }
            safety = (data["safety"]?.arrayValue ?? []).compactMap { $0.stringValue }
            loadedAt = Date()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - 本机 Skill

struct SkillCatalogView: View {
    @State private var skills: [Skill] = []
    @State private var search = ""
    @State private var error: String?

    struct Skill: Identifiable {
        var id: String { root + name }
        let name: String
        let description: String
        let root: String
    }

    private var groups: [(label: String, items: [Skill])] {
        let needle = search.trimmingCharacters(in: .whitespaces).lowercased()
        let matched = needle.isEmpty ? skills : skills.filter {
            $0.name.lowercased().contains(needle) || $0.description.lowercased().contains(needle)
        }
        var buckets: [String: [Skill]] = [:]
        for skill in matched { buckets[skill.root, default: []].append(skill) }
        return buckets.keys.sorted().map { ($0, buckets[$0] ?? []) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("搜索 skill 名称或说明", text: $search).textFieldStyle(.plain)
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
                StatusBanner(level: .error, text: error)
            }

            List {
                ForEach(groups, id: \.label) { group in
                    Section("\(group.label) · \(group.items.count)") {
                        ForEach(group.items) { skill in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(skill.name).lineLimit(1)
                                Text(skill.description)
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
            }
            .listStyle(.inset)
        }
        .task { if skills.isEmpty { await load() } }
    }

    private func load() async {
        do {
            let data = try await CoreClient.shared.request("skills")
            skills = (data["skills"]?.arrayValue ?? []).compactMap { item in
                guard let name = item["name"]?.stringValue else { return nil }
                return Skill(name: name,
                             description: item["description"]?.stringValue ?? "",
                             root: item["root"]?.stringValue ?? "")
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
