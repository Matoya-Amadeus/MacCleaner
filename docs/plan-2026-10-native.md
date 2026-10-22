# Mac Cleaner 优化计划（2026-10-22）

> 目标：把界面从「WKWebView + 本地 HTML」全面迁到 **SwiftUI 原生**，内核保留 Python 并以 **JSON/stdio** 对外，
> 不保留两套 UI。产品边界收敛为两条：**单机清理等功能完善** + **AI 能调用（CLI / MCP）**。

## 一、现状（基线数据）

| 项 | 数值 | 备注 |
|---|---|---|
| Python 代码 | **11,811 行 / 20 个文件** | `core.py` 2540、`deps.py` 1864、`session.py` 1080 |
| 其中 Web UI 层 | **3,431 行** | `pages.py` 2154、`shell.py` 740、`theme.py` 448、`treemap.py` 89 |
| 内核层 | **≈ 4,169 行** | deps / session / uninstall / updates / policy / leftover_rules |
| 测试 | **340 个用例 / 25 个测试文件** | 覆盖扫描、清理、卸载、更新、Sparkle、磁盘 |
| 外壳 | Swift 165 KB，整包 464 KB | 依赖系统 `python3` |
| 后端启动 | 0.11 s | 首个页面可服务 |
| 单次交互延迟 | **≈ 250–350 ms** | 200 ms 轮询 + 整页 reload（53 KB HTML + 30 KB 内联 CSS） |
| 整页刷新点 | 4 处 `location.reload` | 四类 UI bug 的根因 |

### 已知技术债（按危害排序）

| # | 债务 | 证据 | 处理 |
|---|---|---|---|
| 1 | 用「整页刷新」当导航 | 转圈、丢点击、闪屏、滚动位置丢失，三天内四次 | M0–M3 用事件流替代 |
| 2 | 依赖用户机器上的 `python3` | 壳用 `/usr/bin/env python3`；缺失即白屏 | **M0 打包验证** |
| 3 | UI 逻辑与 HTML 字符串耦合 | 2154 行 Python 拼 HTML，改细节要改代码 | 随迁移删除 |
| 4 | 测试集中在 HTML 结构 | 340 条里约 120 条断言 DOM 字符串 | 迁到 Swift 后改为契约测试 |

## 二、目标架构

```
MacCleaner.app  (SwiftUI, macOS 14+)
├── 视图层：SwiftUI + 少量 AppKit（NSWorkspace / NSMenu / NSItemProvider）
├── 状态：@Observable 单例 SessionModel（单向数据流，无整页刷新）
└── 子进程：maccleaner-core serve --stdio     (打包后的 Python 内核，自包含)
     ├── 事件：{"event":"scan.progress","done":1234,"bytes":…}
     ├── 结果：{"ok":true,"data":{…}}
     └── 同一二进制另有两个入口：
          maccleaner-core mcp                    (MCP server，stdio)
          maccleaner-core scan --json            (CLI，供人或 agent)
```

**三条不可让步的设计约束**

1. **内核是唯一真相源**：Swift 侧不复制任何清理/匹配逻辑，只渲染 JSON。
2. **进度靠事件推送**，不是轮询；每个长操作都先回一行 `*.started` 事件。
3. **内核自包含**：App 内嵌打包好的二进制，`python3` 不再是外部依赖。

## 三、阶段计划

### M0 · 内核契约 + 打包验证（1 天）

| 任务 | 产出 |
|---|---|
| 定义命令集：`scan / plan / clean / uninstall.plan / uninstall.apply / updates.check / updates.apply / disk / system / skills` | `docs/core-protocol.md`（请求/响应/事件 schema） |
| 实现 `maccleaner-core serve --stdio`（JSON Lines，逐行请求-响应 + 事件） | 新增 `core_service.py` |
| 进度事件化：扫描、清理、卸载清点、更新检查、系统目录测量 | 事件表 |
| **PyInstaller/Nuitka 打包**，在**无 python 环境**下验证 | `dist/maccleaner-core`，体积记录 |
| 契约测试：每个命令的 schema 快照 | `tests/test_protocol.py`（约 12 条） |

**验收**：`echo '{"cmd":"disk"}' | ./maccleaner-core serve --stdio` 返回合法 JSON；打包产物在干净环境能跑；
体积 ≤ 40 MB。**这是全案唯一的技术不确定点，必须先验掉。**

> **M0 已完成（2026-10-22）**，实测结果：
> | 项 | 结果 |
> |---|---|
> | 打包方式 | PyInstaller **onedir**（`scripts/build_core.sh`），入口用 `scripts/core_entry.py` shim |
> | 体积 | **16–21 MB**（远低于 40 MB 预算） |
> | 冷启动 | **105 ms**（对比 onefile **1204 ms**——onefile 每次解压，会吃掉整个启动预算） |
> | 无 python 环境 | `env -i`（无 PATH / PYTHONPATH）下 `--version` 与 `ping` 均正常 |
> | 协议 | 15 个命令、14 条契约测试（`tests/test_protocol.py`） |
> | 真实命令 | `disk` 通过二进制返回 7 个目录块，317 ms |
>
> 踩到的坑：直接把 `core_cli.py` 当入口会让相对导入炸（`attempted relative import with no
> known parent package`），必须用 shim 以**包内模块**身份启动。


### M1 · SwiftUI 骨架 + 三个只读页（2–3 天）

页面：**磁盘 / 系统状态 / 技能**（只读、无破坏性操作，风险最低，用来定手感）。

- 窗口 + 侧边栏（`NavigationSplitView`）、深浅色、字号、图标系统（SF Symbols）；
- 磁盘：容量条 + 目录列表（图标 + 体积 + 点击进入下一级，用 `NavigationStack` 而不是换页）；
- 系统状态：负载/内存/电池/节流/进程；
- 技能：按来源分组的列表 + 搜索。

**验收**：与现 HTML 版并排对比，点击到更新的延迟 ≤ 50 ms；你能上手确认「原生手感值不值两周」。

### M2 · 三个列表页（3–4 天）

清理（候选分组 + 勾选 + 高风险标记）、软件卸载（分类 + 图标 + 搜索）、软件更新（来源分组 + Sparkle 确认）。

- 用 `List` + `@State` 选择集，全选用 `Set`；
- 图标：从 `.app` 读 `NSImage`（原生，不再注入 base64）；
- 底部操作条：`safeAreaInset(edge: .bottom)`，显示「已选 N · 共 M」+ 主按钮。

**验收**：与现版功能等价；50 个应用滚动 60 fps；全选/单选/搜索行为一致。

### M3 · 破坏性链路（3–4 天）

确认页 → 执行（进度 + 取消）→ 结果页 → 打开废纸篓。

- 安全规则必须逐条回归：**一律废纸篓、空勾选拒绝、高风险不默认勾、root 只测量、系统缓存需授权**；
- 进度用事件驱动（`ProgressView` + 可取消），不设「自刷」；
- 卸载详情：按 confidence 分组、系统级残留单列且不可勾。

**验收**：跑通一次真实清理 + 一次真实卸载；`git diff` 中内核文件零改动（证明只是换前端）。

### M4 · 原生系统集成（2–3 天）

| 项 | API |
|---|---|
| 拖 `.app` 到窗口/Dock 直接卸载 | `NSItemProvider` + `DropDelegate` |
| 右键菜单（在 Finder 中显示 / 拷贝路径 / 卸载） | `contextMenu` |
| 清理完成通知 | `UNUserNotificationCenter` |
| 破坏性操作用 Touch ID 确认 | `LAContext` |
| 菜单栏（清理进度 / 最近结果） | `MenuBarExtra` |
| 键盘：⌘R 重新扫描、⌘A 全选、空格预览 | `.keyboardShortcut` |
| 无障碍标签 | `.accessibilityLabel` |

**验收**：以上七项逐条手动走查；VoiceOver 能读完一个列表页。

### M5 · 收尾（1–2 天）

- 删除 `src/maccleaner/ui/`（3,431 行）与 `bridge.py`（265 行）；`maccleaner ui` 改为「打开 App」；
- README / README.en / `docs/comparison.md` 更新（技术栈、体积、依赖）；
- 安装脚本改为「拷贝 .app + 签名」；首次启动引导（可选）。

**总计：约 12–17 个工作日**（含缓冲）。

## 四、并行线（不占迁移主线）

| 线 | 内容 | 频率 |
|---|---|---|
| 内核质量 | 新增清理规则（每周从 `~/Library` 实测里挑）、误删回归用例 | 每周 0.5 天 |
| AI 契约 | `docs/core-protocol.md` 与 MCP 工具描述同步；给 agent 的用法示例 | 每阶段末 |
| 文档 | 每个 M 结束更新 README 的「当前状态」一节 | 每阶段末 |

## 五、度量（迁移前后对比）

| 指标 | 现在 | 目标 |
|---|---|---|
| 单次交互延迟 | 250–350 ms | **< 50 ms** |
| 冷启动到可交互 | ≈ 0.6–1 s（壳 + 后端 + 首帧） | **< 0.4 s** |
| 包体积 | 464 KB（+ 外部 python） | **≤ 40 MB 自包含** |
| 外部依赖 | 需要 python3 | **零** |
| 整页刷新点 | 4 | **0** |
| UI 代码 | 3,431 行 HTML 拼接 | SwiftUI 视图（无字符串拼 HTML） |
| 内核测试 | 340 | 不减（只增） |

## 六、风险登记

| 风险 | 影响 | 概率 | 应对 |
|---|---|---|---|
| PyInstaller 打包失败/体积失控 | 高（阻塞全案） | 中 | **M0 先验**；失败退路：内嵌 Python framework，或改用 Nuitka |
| 内核迁移期被需求打断 | 高（拖长 2 倍） | 高 | 迁移期冻结新功能；新需求排进 M5 之后 |
| 安全规则回归 | 极高（删错文件） | 中 | M3 逐条验收 + 内核零改动约束 + 真实小样本清理 |
| SwiftUI 列表性能 | 中 | 低 | 用 `List` + 稳定 `id`；必要时 `LazyVStack` |
| 签名/公证（内嵌子进程） | 中 | 中 | M4 前做一次 `codesign --deep` 试验，确认 entitlements |
| 手感不及预期 | 中（返工） | 低 | M1 就交付可上手版本，早否决早止损 |

## 七、明确不做（迁移期）

| 不做 | 原因 |
|---|---|
| 保留 HTML UI 第二套 | 双份维护，正是本次要消掉的负债 |
| 内核换 Rust / Swift | 收益（去依赖）M0 已用打包解决；重写风险极高。**触发条件**：跨平台、或需要 60fps 实时文件树 |
| 新功能（Treemap 增强、定时清理等） | 迁移期只做等价替换 |
| 依赖第三方 UI 库 | SwiftUI 原生足够；减少供应链风险 |

## 八、决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-10-22 | 界面全面迁 SwiftUI（方案 B），不保留双 UI | A 方案（保留 WebView 改增量）会持续打补丁；三天内四类 bug 均源于整页刷新 |
| 2026-10-22 | 内核保留 Python | 340 条测试 + 安全规则是核心资产；耗时瓶颈在系统 IO，换语言无收益 |
| 2026-10-22 | 不走 Electron | 体积 1.6 GB 级、且非原生观感（Codex App 的选择，但目标不同） |
| 2026-10-22 | 协议从 HTTP+HTML 改为 stdio JSON | 去掉端口/CSRF/生命周期问题，天然支持流式进度 |

## 九、Definition of Done

- [ ] App 在**未安装 Python** 的机器上可启动、可完成一次扫描 + 清理
- [ ] 一次真实卸载（含残留）走完：列表 → 详情 → 确认 → 执行 → 结果
- [ ] 安全规则五条逐条验证通过（废纸篓 / 空勾选 / 高风险 / root 只读 / 授权）
- [ ] 内核测试数 ≥ 340 且全绿；新增协议测试全绿
- [x] `src/maccleaner/ui/` 已删除（连同 `bridge.py` / `session.py` / WKWebView 壳），仓库内仅一套 UI
- [ ] README 与 `docs/comparison.md` 反映新架构
- [ ] 冷启动 < 0.4 s，交互 < 50 ms（用 Instruments / 日志时间戳测量）
