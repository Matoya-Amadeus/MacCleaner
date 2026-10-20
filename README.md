**中文** · [English](README.en.md)

# 给人类看的

![Mac Cleaner 审阅页](assets/screenshot.png)

EMM...就一般清理工具，AI能直接调用。

# 给 AI 看的

macOS 清理 / 卸载 / 更新工具。三个入口，同一套内核：**扫描只读，删除一律进废纸篓**。

- CLI：`maccleaner audit | plan | clean | uninstall | updates | trace | ui`
- MCP：`maccleaner-mcp`（7 个工具，stdio）
- 本地界面：`maccleaner ui`

必须"先计划再执行"：`plan_storage` 给 `plan_id`，`apply_storage_plan` 必须带
`approved_targets`；`plan_id` 15 分钟过期就作废。高风险目标（`~/Downloads`、Docker 数据）
要显式确认，`~/.ssh`、钥匙串、浏览器登录数据永远不会出现在清单里。

<h1 id="安装">安装</h1>

需要 macOS + Python 3.10 以上，核心 CLI 没有第三方依赖。

```bash
pipx install maccleaner
```

还没上 PyPI，也可以从源码装：

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git"
```

给 AI 客户端用（MCP）：`pipx install "maccleaner[mcp]"`

要原生窗口（不在浏览器里）：`bash scripts/install_launcher.sh` → `~/Applications/MacCleaner.app`

自己构建离线包：

```bash
python3 -m pip install wheel
python3 -m build --no-isolation
```


# 用法

## 界面

双击 `~/Applications/MacCleaner.app`，或 `maccleaner ui`。侧栏 8 个入口：

- **Mac 清理**：扫描 → 逐条勾选 → 确认 → 完成；含安装包（.dmg/.pkg）与 iOS 备份两类长尾目标
- **软件卸载**：单个看残留，或多选批量卸
- **软件更新**：按来源分组；自带 Sparkle 的应用先走应用内更新
- **残留体检**：应用删了但缓存/日志/容器还在？反向扫出来（默认不勾）
- **磁盘**：整机占比 + **treemap 方块图**（面积=体积），点方块进下一层
- **系统状态**：负载、内存、最吃 CPU 的进程
- **清理历史**：每次清理的回执
- **可调用的 Skill**：本机装了哪些 agent 技能

`⌘A` 全选、`Shift+点击` 连选、`Enter` 执行、列头按体积/名称排序、右键复制路径或在 Finder 中显示。

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

真机验收（需要 GUI，人工跑）：`bash tests/acceptance_native_smoke.sh`（11 步，含真实清理）、
`tests/acceptance_uninstall_batch.py`、`tests/acceptance_quit.sh`、`tests/acceptance_portability.sh`、
`tests/acceptance_package.sh`。

## 安全与隐私

不收集遥测；界面只监听 `127.0.0.1`，入口是一次性链接。细节见 [PRIVACY.md](PRIVACY.md)。

---

由 **AI·Maho** 和 **人类·Matoya** 共同维护
