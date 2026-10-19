**中文** · [English](README.en.md)

# Mac Cleaner

一个能看、能选、能反悔的 Mac 清理工具。

清理之前先把"要删什么"摆给你看，**删掉的东西一律进废纸篓**——点错了还能拖回来。
不想用界面也行：它同时是一个命令行工具，也能让 AI（Claude / Codex / Cursor）直接调用。

---

<details id="ai-prompt-quick-start" open>
<summary><strong>给小白：连接 AI 后这样说</strong></summary>

把仓库接到你的 AI 客户端（配置见 [docs/mcp.md](docs/mcp.md)），然后原样粘这两句：

**第一句（只看不动）**

```text
先只做审计和清单，不要删除、不要修改任何文件。
把每一项是什么、多大、能不能恢复，用大白话解释给我听。
```

**第二句（只删你点头的）**

```text
只执行当前计划中我明确批准的这些 target_id：home-caches、vscode-cache
其他一律不要动。
```

这两句的意义：AI 再热情，也只能在你**点名**的范围内动手。

</details>

<details id="功能" open>
<summary><strong>它能干什么（大白话）</strong></summary>

| 你想干的事 | 它怎么做 |
|---|---|
| **磁盘快满了，想清点垃圾** | 扫一遍缓存、日志、Xcode 垃圾、包管理器缓存，列成清单给你看，**你不勾就不动** |
| **删掉不用的软件，还要删干净** | 除了应用本体，把它留下的缓存、偏好、容器、后台项一起找出来（含 `.ShipIt` 这类更新残留） |
| **软件该升级了** | Homebrew、App Store、npm 一起查；能应用内更新的（Sparkle）优先，商店应用再打开 App Store |
| **想知道到底谁在占空间** | 磁盘页从"总览"一层层点进去，看到最里面的大文件 |
| **想确认上次到底删了什么** | 清理历史页读每次的回执：时间、几项、多少体积、是否预演 |
| **想让 AI 帮你清理** | 7 个 MCP 工具 + 一次性入口，AI 只能在你批准的范围内动 |

几个刻意的"慢一点"：

- 扫描只是看，不动文件；要动手必须再点一次【开始清理】；
- 删之前还有**一页确认**，写清几组、多少体积；
- `~/Downloads`、Docker 数据这种高风险项**默认勾不上**，要在确认页单独再确认一次；
- 删错不慌：全部进废纸篓。

</details>

<details id="安装" open>
<summary><strong>安装</strong></summary>

需要 macOS + Python 3.10 以上。基础功能**没有第三方依赖**。

```bash
pipx install maccleaner
maccleaner --help
```

还没发到 PyPI，也可以直接从源码装：

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git"
```

想让 AI 客户端调用，装带 MCP 的版本：

```bash
pipx install "maccleaner[mcp]"
```

想用**原生窗口**（不在浏览器里）：装完跑一次

```bash
bash scripts/install_launcher.sh     # 生成 ~/Applications/MacCleaner.app，图标已就位
```

也可以自己构建离线包（干净环境 `pip install --no-index` 实测可用）：

```bash
python3 -m pip install wheel        # 首次构建需要
python3 -m build --no-isolation     # 产出 dist/*.whl 与 *.tar.gz
```

</details>

<details id="界面" open>
<summary><strong>打开界面</strong></summary>

双击 `~/Applications/MacCleaner.app`，或命令行 `maccleaner ui`。侧栏 7 个入口：

| 入口 | 干什么 |
|---|---|
| **Mac 清理** | 扫描 → 逐条勾选 → 确认 → 完成 |
| **软件卸载** | 应用列表；可以单个看残留，也可以多选批量卸 |
| **软件更新** | 按来源分组（Homebrew / App Store / npm…）；Sparkle 应用单独一组 |
| **磁盘** | 整机占比 + 常用目录，可逐层点进去 |
| **系统状态** | 负载、内存、最吃 CPU 的进程 |
| **清理历史** | 每次清理的回执（时间 / 项数 / 体积） |
| **可调用的 Skill** | 本机装了哪些 agent 技能 |

手感尽量贴近 macOS 原生列表：

- 左侧小方框改勾选，**点行其它地方 = 打开详情**（不会误勾）；
- `⌘A` 全选（再按取消）／`Shift+点击` 连选／`Enter` 执行主操作／`Esc` 关菜单；
- 列头按**体积 / 名称**排序；长列表右侧有 A–Z 索引条，点了直接跳；
- 右键可以「复制路径」「在 Finder 中显示」；
- 从列表点进详情再返回，**回到原来的滚动位置**。

</details>

<details id="cli-怎么用">
<summary><strong>命令行怎么用</strong></summary>

```bash
maccleaner audit                      # 只看：哪能清、能清多少
maccleaner plan                       # 列清单：每项的 target_id / 风险 / 为什么
maccleaner clean --apply --yes        # 真删（默认只清低风险、可再生成的目标）
maccleaner uninstall --app-path /Applications/Foo.app          # 只看残留
maccleaner uninstall --app-path /Applications/Foo.app --apply   # 移入废纸篓
maccleaner updates                    # 查更新（默认只读）
maccleaner updates --apply --only aom,cmake                     # 只升点名的
maccleaner trace <plan_id>            # 查某次计划到底做了什么
```

`plan` 里重点看三样：`target_id`（要删谁）、`risk`（低/高）、`reason`（为什么进清单）。

</details>

<details id="mcp-怎么用">
<summary><strong>让 AI 调用（MCP）</strong></summary>

`maccleaner-mcp` 只用 stdio，7 个工具：

| 工具 | 作用 |
|---|---|
| `audit_storage` | 只读：有什么可清 |
| `plan_storage` | 生成计划，返回 `plan` + `plan_id` |
| `apply_storage_plan` | 执行；要带 `approved_targets`，可选 `plan_digest` 证明"执行的就是给你看的那份" |
| `uninstall_plan` / `uninstall_apply` | 卸载：先列残留，再执行 |
| `updates_check` / `updates_apply` | 更新：先查，再升 |

最小的一次只读对话：

```json
{"name": "audit_storage", "arguments": {"profile": "generic"}}
{"name": "plan_storage", "arguments": {"profile": "generic"}}
{"name": "apply_storage_plan", "arguments": {
  "plan_id": "<上一步返回的>",
  "approved_targets": ["home-caches"]
}}
```

没有 `approved_targets` 或 `plan_id` 过期（15 分钟），它会**拒绝执行**。
客户端配置（Codex / Cursor / Claude Desktop）见 [docs/mcp.md](docs/mcp.md)。

</details>

<details id="验证">
<summary><strong>自己验证一遍</strong></summary>

```bash
python3 -m unittest discover -s tests -v      # 262 条单测
```

真机验收（都需要 GUI，人工跑）：

```bash
bash tests/acceptance_native_smoke.sh      # 真窗口走 11 步：7 个入口 + 清理链路 + 文件级判定
bash tests/acceptance_uninstall_batch.py   # 批量卸载：多选 → 一次确认 → 文件真的进废纸篓
bash tests/acceptance_quit.sh              # 关闭后进程/端口/状态四项归零
bash tests/acceptance_portability.sh       # 复制到别处 + 全新 HOME 也能跑
bash tests/acceptance_package.sh           # 构建 + 离线安装 + 真实审计
```

</details>

<details id="安全边界">
<summary><strong>安全与隐私</strong></summary>

- **不收集遥测**，不上传文件名、路径或使用数据；
- 界面只监听 `127.0.0.1`，入口是一次性链接，每个动作要 cookie + 请求头双凭据；
- 删除一律进废纸篓；`.ssh`、钥匙串、浏览器登录数据这类路径**永不出现**；
- 会联网的地方只有：包管理器自己的检查、App Store 版本查询（只传 app id 和国家）。

细节见 [PRIVACY.md](PRIVACY.md)。许可证 MIT。

</details>

---

由 **AI·Maho** 和 **人类·Matoya** 共同维护
