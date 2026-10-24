**中文** · [English](README.en.md)

# 给人类看的

![Mac Cleaner 审阅页](assets/screenshot.png)

EMM...就一般清理工具，跟 AI 说用 mac cleaner 清理，能直接调用。

# 给 AI 看的

macOS 清理 / 卸载 / 更新工具。三个入口，同一套内核：**扫描只读，删除一律进废纸篓**。

- CLI：`maccleaner audit | plan | clean | uninstall | updates | trace | ui | mcp`
- MCP：`maccleaner-core mcp`（7 个工具，stdio）——内核自带，无需另装
- 原生界面：`bash scripts/build_native.sh --run`（SwiftUI；`maccleaner ui` 等同打开它）

必须"先计划再执行"：`plan_storage` 给 `plan_id`，`apply_storage_plan` 必须带
`approved_targets`；`plan_id` 15 分钟过期就作废。高风险目标（`~/Downloads`、Docker 数据）
要显式确认，`~/.ssh`、钥匙串、浏览器登录数据永远不会出现在清单里。

<h1 id="安装">安装</h1>

原生 App **不需要 Python**（内核已打包进 `.app`，33 MB 自包含）。
只有想用命令行时才需要 Python 3.10+，CLI 本身没有第三方依赖。

```bash
pipx install maccleaner
```

还没上 PyPI，也可以从源码装：

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git"
```

给 AI 客户端用（MCP）：装完 App 就能用 `maccleaner-core mcp`，不需要再装 Python 包。

构建并安装原生窗口：`bash scripts/install_app.sh` → `/Applications/MacCleaner.app`（不可写时退回 `~/Applications`）

自己构建离线包：

```bash
python3 -m pip install wheel
python3 -m build --no-isolation
```


# 用法

## 安装与构建

```bash
bash scripts/build_core.sh     # 内核（PyInstaller onedir，33 MB 自包含，含 MCP）
bash scripts/build_native.sh   # SwiftUI 界面（swiftc，无需 Xcode 工程；产物在 .build/native）
bash scripts/install_app.sh    # 装到 /Applications
```

首次打开后，在磁盘页点「打开『完全磁盘访问权限』设置」，勾上 MacCleaner 并重启 App——
否则读不到目录体积（macOS 对清理类应用的硬门槛）。

## 界面

双击 `/Applications/MacCleaner.app`，或 `maccleaner ui`（打开原生 App）。侧栏 5 个入口：

- **清理**：推荐清理（缓存 / 日志 / 开发工具 / 容器 / 你的文件）+ 大文件
- **软件**：卸载（单个看残留，或多选批量）/ 更新（按来源分组；Sparkle 先走应用内更新）/ 残留体检
- **磁盘**：整机占比 + 目录清单 + 系统级目录（需一次性授权，只读不删）
- **系统**：负载、内存、电池与节流、占用最高的进程
- **AI**：可被 agent 直接调用的工具清单（MCP 7 个 + stdio 命令），以及怎么接上

菜单「前往」可 `⌘1`–`⌘5` 切换入口，`⌘R` 重新读取本页；列表行右键可「在 Finder 中显示 / 拷贝路径 / 卸载」；
把 `.app` 拖进窗口可直接卸载。

`⌘A` 全选、`Shift+点击` 连选、`Enter` 执行、右键复制路径或在 Finder 中显示。

## 命令行

```bash
maccleaner audit                      # 只看
maccleaner plan                       # 列清单（target_id / 风险 / 原因）
maccleaner clean --apply --yes        # 真删，默认只清低风险、可再生成的目标
maccleaner uninstall --app-path /Applications/Foo.app --apply
maccleaner updates --apply --only aom,cmake
maccleaner trace <plan_id>            # 某次计划到底做了什么
```

## MCP

```json
{"name": "audit_storage", "arguments": {"profile": "generic"}}
{"name": "plan_storage", "arguments": {"profile": "generic"}}
{"name": "apply_storage_plan", "arguments": {
  "plan_id": "<上一步返回的>",
  "approved_targets": ["home-caches"]
}}
```

客户端配置见 [docs/mcp.md](docs/mcp.md)。

## 自己验证

```bash
python3 -m unittest discover -s tests -v
```

真机验收（需要 GUI，人工跑）：`bash tests/acceptance_native_app.sh`、
`bash tests/acceptance_portability.sh`、`python3 tests/acceptance_recovery_smoke.py`。
本轮的真实点击验收记录见 [docs/acceptance-2026-10-24.md](docs/acceptance-2026-10-24.md)。

## 安全与隐私

不收集遥测；原生界面与内核只通过 stdio 通信，**不开端口、不起本地服务**。细节见 [PRIVACY.md](PRIVACY.md)。

与 Mole / Pearcleaner 的功能与安全模型差异，见 [docs/comparison.md](docs/comparison.md)。

---

由 **AI·Maho** 和 **人类·Matoya** 共同维护
