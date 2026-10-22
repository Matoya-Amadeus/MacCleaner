import AppKit
import SwiftUI

/// 侧边栏 4 个入口（2026-10-22 合并，原 8 个）：
/// 清理 / 软件 / 磁盘 / 系统。技能列表移到右上角按钮——它不属于"日常清理"这件事。
enum SidebarItem: String, CaseIterable, Identifiable {
    case clean, software, disk, system

    var id: String { rawValue }

    var title: String {
        switch self {
        case .clean: return "清理"
        case .software: return "软件"
        case .disk: return "磁盘"
        case .system: return "系统"
        }
    }

    var symbol: String {
        switch self {
        case .clean: return "sparkles"
        case .software: return "shippingbox"
        case .disk: return "internaldrive"
        case .system: return "gauge.with.dots.needle.50percent"
        }
    }
}

@main
struct MacCleanerApp: App {
    var body: some Scene {
        WindowGroup("Mac Cleaner") {
            RootView()
                .frame(minWidth: 920, minHeight: 620)
        }
        .windowToolbarStyle(.unified)
        .commands {
            // 原生菜单：这是 WebView 版永远给不了的那一层的一部分。
            CommandGroup(replacing: .newItem) {}
        }
    }
}

struct RootView: View {
    // 记住上次停在哪个入口：原生 App 的默认期待（重开还在这儿）。
    @AppStorage("selectedSection") private var storedSection: String = SidebarItem.disk.rawValue
    @State private var selection: SidebarItem? = .disk
    @State private var showSkills = false

    var body: some View {
        NavigationSplitView {
            List(SidebarItem.allCases, selection: $selection) { item in
                Label(item.title, systemImage: item.symbol).tag(item)
            }
            .onAppear {
                // 开发钩子（MACCLEANER_DEV_PLAN）要落到「软件」页，否则截图得手点一次。
                if let path = ProcessInfo.processInfo.environment["MACCLEANER_DEV_PLAN"], !path.isEmpty {
                    selection = .software
                    return
                }
                if let restored = SidebarItem(rawValue: storedSection) { selection = restored }
            }
            .onChange(of: selection) { _, newValue in
                if let newValue { storedSection = newValue.rawValue }
            }
            .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 240)
            .listStyle(.sidebar)
        } detail: {
            Group {
                switch selection ?? .disk {
                case .clean: CleanView()
                case .software: SoftwareView()
                case .disk: DiskView()
                case .system: SystemView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        showSkills = true
                    } label: {
                        Label("技能", systemImage: "wand.and.stars")
                    }
                    .help("这台机器上 agent 能调用的 skill")
                }
            }
            .sheet(isPresented: $showSkills) { SkillsSheet() }
        }
    }
}

struct PlaceholderView: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "hammer.fill").font(.system(size: 28)).foregroundStyle(.tertiary)
            Text(title).font(.title3.weight(.semibold))
            Text(detail).font(.callout).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - 技能

struct SkillsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var skills: [Skill] = []
    @State private var error: String?

    struct Skill: Identifiable {
        let id = UUID()
        let name: String
        let description: String
        let root: String
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("可调用的 Skill").font(.headline)
                Spacer()
                Button("完成") { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding(16)
            Divider()

            if let error {
                Text(error).foregroundStyle(.red).padding()
            }

            List(skills) { skill in
                VStack(alignment: .leading, spacing: 2) {
                    Text(skill.name).font(.body.weight(.medium))
                    Text(skill.description).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    Text(skill.root).font(.caption2).foregroundStyle(.tertiary)
                }
                .padding(.vertical, 2)
            }
        }
        .frame(width: 560, height: 480)
        .task { await load() }
    }

    private func load() async {
        do {
            let data = try await CoreClient.shared.request("skills")
            skills = (data["skills"]?.arrayValue ?? []).compactMap { item in
                guard let name = item["name"]?.stringValue else { return nil }
                return Skill(
                    name: name,
                    description: item["description"]?.stringValue ?? "",
                    root: item["root"]?.stringValue ?? ""
                )
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
