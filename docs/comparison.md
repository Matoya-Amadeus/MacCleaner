# 与 Mole / Pearcleaner 的差异

> **核对时间：2026-10-22**，依据是各自仓库的 README（Mole `tw93/Mole`、Pearcleaner `alienator88/Pearcleaner`）。
> 它们改版后本文可能过期；冲突时以各自仓库为准。

## 一句话定位

| 工具 | 定位 | 形态 | 授权 |
|---|---|---|---|
| **Mac Cleaner**（本项目） | 一个窗口里"看清单 → 勾选 → 移入废纸篓"的清理 / 卸载 / 更新 | **SwiftUI 原生界面**（迁移中；旧 Web UI 将删除）+ CLI + MCP，Python 内核走 stdio JSON | 自有 |
| **Mole** | macOS 终端清理与系统洞察工具包（clean / uninstall / purge / installer / slim / optimize / analyze） | **TUI**，CLI 本体免费开源；图形界面是**另一个独立产品**（Mole for Mac，闭源） | GPL-3.0（CLI） |
| **Pearcleaner** | 应用卸载 + 残留清理 | 原生 macOS App（SwiftUI）+ Finder 扩展 + 特权 Helper | Apache 2.0 + Commons Clause |

## 功能对照（✅ 有 / ❌ 无 / — 不适用）

| 能力 | Mac Cleaner | Mole | Pearcleaner |
|---|---|---|---|
| 缓存 / 日志 / 临时文件清理 | ✅ 带保留期（用户缓存 1 天、日志 7 天） | ✅ `clean` | ❌（只做应用残留） |
| 浏览器缓存 | ✅ Firefox / Chrome / Safari，整目录搬 | ✅ Safari / Chrome | ❌ |
| 开发工具缓存 | ✅ Xcode / 包管理器 / IDE | ✅ 含 npm / pnpm 等 | 部分（Homebrew Manager、Dev 环境清理） |
| 应用卸载 + 残留 | ✅ 按 bundle id / 名称匹配，分"确定项 / 名称匹配" | ✅ `uninstall` | ✅ 核心；另有 Sentinel Monitor（应用进废纸篓时自动清残留） |
| 第三方包更新（brew / npm / pip / gem / rustup / App Store） | ✅ 六源并行 | ❌（`mo update` 是**更新 Mole 自身**） | 部分（Apps Updater / Homebrew Manager） |
| 自带更新器（Sparkle）应用 | ✅ 列出并引导"在应用内更新" | ❌ | ❌ |
| 磁盘占用分布 | ✅ 容量条 + treemap + 目录清单（只读展示） | ✅ `analyze`（TUI，可下钻，支持 `--json`） | ❌ |
| 系统状态（负载 / 内存 / 电池 / 节流 / 进程） | ✅ 只读 | ✅ 实时监控 + 健康分 | ❌ |
| 项目产物清理（node_modules / target / dist） | ❌ | ✅ `purge` | ❌ |
| 安装包清理（dmg / pkg / iso） | ❌ | ✅ `installer` | ❌ |
| 剥离通用二进制里的 Intel 代码 | ❌ | ✅ `slim` | ✅ App Lipo |
| 白名单 | ❌ | ✅ `~/.config/mole/whitelist` | 自定义包含/排除目录 |
| dry-run | ❌ | ✅ `--dry-run` | — |
| 操作日志 | ✅ JSON 回执（每次清理） | ✅ `mo history` | — |
| AI agent 可调用 | ✅ MCP 工具 + CLI | 部分（技能包形式） | ❌ |

**差距最明显的三项**：`purge`（项目产物）、`installer`（安装包）、`slim`（剥 Intel 代码）我们都没做；
反过来，**第三方包更新**与 **Sparkle 引导**是它们没有的。

## 安全模型（这是最大的差异）

| 规则 | Mac Cleaner | Mole | Pearcleaner |
|---|---|---|---|
| 删除默认进废纸篓 | ✅ **所有路径**都走废纸篓 | ⚠️ 按命令区分：`uninstall`/`analyze`/`slim` 进废纸篓；**`clean`/`purge`/`installer` 是永久删除**（且 `clean` 默认还会清空 `~/.Trash`） | ✅（卸载走废纸篓） |
| root 域（`/Library/Caches`、`/var/log`） | 见下节：需显式授权，整目录搬进你的废纸篓 | 由 CLI 自行判断（不要求 `sudo`） | 通过 Privileged Helper + 完全磁盘访问权限 |
| 高风险项不默认勾选 | ✅ Downloads / Docker / 安装包要自己勾 + 确认页再确认 | ✅（`purge` 7 天内活跃的默认不选） | —（按应用粒度） |
| 空勾选 ≠ 全选 | ✅ 空勾选被拒绝 | ✅（`purge` 只删确认过的条目） | — |
| 从不静默提权 | ✅ 只有"测量系统目录体积"与"移系统缓存"会请求一次授权 | ✅ 明确"不要用 sudo 运行" | ⚠️ 装 Privileged Helper（常驻） |
| 网络面 | **不开放任何端口**：界面与内核用 stdio 子进程通信（旧 Web UI 时期是 127.0.0.1 + 一次性链接） | 本地 | 本地 |

**结论**：Mole 更快更全（它就是为"一条命令清干净"设计的），代价是 `clean` 永久删除；
我们的取舍是"慢一点、多点一次，但任何删除都能从废纸篓拿回来"。

## 系统缓存 / 日志怎么处理（常见疑问）

你手动在 Finder 里删 `/Library/Caches/xxx`，是**会进废纸篓**的——因为 Finder 用管理员授权
代你移动，并写入了"放回原处"所需的元数据。

第三方工具要复刻完整链路，需要同时满足三件事：

1. 拿到 root（每次输密码，或常驻特权助手）；
2. 把 root 拥有的文件移进**当前用户**的 `~/.Trash`，且之后能清空它；
3. 写入 Finder 的"放回原处"信息（Finder 私有格式，无公开 API）。

第 3 条我们做不到。所以本工具提供的是**折中方案（实验）**：

- 勾选系统级目录 → 点【授权并移入废纸篓】→ 系统弹一次密码框 → 整目录移进 `~/.Trash`；
- **能拿回来**（文件还在废纸篓里，只是属主是 root）；
- 但**"放回原处"不可用**，且清空废纸篓时可能还要再授权一次；
- 默认**不勾**，页面上写明上述限制。

要完整的"正规链路"，请用 Finder 或 Mole 的 `clean`（后者是永久删除，注意区别）。

## 我们明确不做的事

| 事项 | 原因 |
|---|---|
| 临时文件 `$TMPDIR` 清理 | 本机实测 78 MB 里 98% 是 1 天内活跃文件，只清 1 天以上剩 0.3 MB，还会误伤运行中的应用 |
| 磁盘目录下钻浏览 | 这一页回答"谁占地方"，逐层钻对判断没有增量价值（Mole 的 `analyze` 有，那是它的长处） |
| 定时 / 后台自动清理 | 与"用户看清单再决定"的产品前提冲突 |
| 排序条 | 列表按分类/体积固定顺序更省心（卸载页以前有，已移除） |
| 遥测 / 云同步 | 不做 |

## 附：几处容易记错的事实

| 常见误解 | 事实 |
|---|---|
| "Mole 是个 GUI 工具" | CLI 本体是 **TUI**；图形界面是另一个独立、闭源的产品（Mole for Mac），`brew install mole` 只装 CLI |
| "Mole 清理都进废纸篓" | 只有 `uninstall`/`analyze`/`slim` 进；`clean`/`purge`/`installer` 是**永久删除**，`clean` 还会默认清空 `~/.Trash` |
| "`mo update` 会升级我的 Homebrew 包" | 不会，它只更新 Mole 自身 |
| "Pearcleaner 一直在更新" | README 写明自 2025 年底起 **On Hold**（作者失去可用的 Mac 设备），现有功能可用但无后续维护承诺 |
| "Pearcleaner 也能清磁盘" | 不能，它没有磁盘分析；只做应用级清理（+ Homebrew 管理、App Lipo 等） |
