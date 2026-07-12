# MacCleaner

<p align="center">
  <img src="assets/readme-header.svg" alt="MacCleaner：安全的 Mac 存储审计与清理流程" width="100%" />
</p>

> **先看清单，再决定删什么。**
>
> MacCleaner 先审计空间、生成目标清单，再按安全门禁执行清理。

[中文](README.md) · [English](README.en.md)

<details>
<summary><strong>近期更新</strong></summary>

更新时间：2026-07-12 00:28

更新内容：新增可安装 CLI、可选 MCP stdio 服务和一次性 plan token 安全链。

### 2026-05-19 21:20

更新内容：新增 generic 默认 profile、repo-evidence opt-in、受保护会话阻断、receipt、backup 和清理后残留验证。

</details>

## 目录

- [一眼看懂](#一眼看懂)
- [给小白：连接 AI 后这样说](#ai-prompt-quick-start)
- [解决什么问题](#解决什么问题)
- [安装](#安装)
- [三分钟上手](#三分钟上手)
- [CLI 怎么用](#cli-怎么用)
- [MCP 怎么用](#mcp-怎么用)
- [常用场景](#常用场景)
- [安全边界](#安全边界)
- [配置与参数](#配置与参数)
- [报告怎么看](#报告怎么看)
- [结构与工作链路](#结构与工作链路)
- [开发者说明](#开发者说明)
- [常见问题](#常见问题)

## 一眼看懂

| 你是谁 | 从哪里开始 | 会发生什么 |
| --- | --- | --- |
| 已把 MCP 连到 AI 的小白 | 复制下面第一段提示词 | AI 先只给清单，不会清理 |
| 想自己在终端操作 | [三分钟上手](#三分钟上手) | `audit → plan → apply` 三步走 |
| 需要精细控制的人 | [CLI 怎么用](#cli-怎么用) / [MCP 怎么用](#mcp-怎么用) | 只执行你明确批准的精确目标 |

> **只想安全开始？** 连接好 MCP 后，只复制下面的「第一步」给 AI。它会先列清单；不确认，不清理。

<details id="ai-prompt-quick-start" open>
<summary><strong>给小白：连接 AI 后这样说</strong></summary>

不需要懂命令或 `target_id`。如果还没有把 MacCleaner 连到 AI，先看 [安装 → MCP](#安装)；连好后，按顺序把下面的话发给 AI。

### 第一步：只看，不删（建议先只发这一段）

```text
请使用 MacCleaner 帮我检查 Mac 存储。先只做审计和清单，不要删除、不要修改任何文件。
请用简单的话告诉我：哪些可以安全清理、哪些需要我确认、哪些绝不会动，并按预计可释放空间排序。
```

你会先得到一份清单。浏览器登录、Cookie、会话、密码和 Keychain 不会被列成可执行清理项。

### 第二步：让 AI 解释计划，仍然不执行

```text
根据刚才的检查，生成一个清理计划，但先不要执行。
请把每一项分成「可安全清理」「需要我确认」「不会清理」三类；说明预计释放多少空间，并告诉我需要我选择哪些 target_id。
```

只选择你看得懂、愿意删除的项目。看不懂就让 AI 解释，不要确认。

### 第三步：只执行你选中的项目

从 AI 给出的**当前计划**里复制你要清理的真实 `target_id`，再发送：

```text
我确认只执行当前计划中我明确批准的这些 target_id：TARGET_ID_1、TARGET_ID_2。
其他内容均不要动；如果其中任何项目需要二次确认，请先告诉我，不要执行。
```

把示例中的 `TARGET_ID_1`、`TARGET_ID_2` 换成当前计划里真实显示的编号。没有选编号时，不要进入这一步。

**记住这一条就够了：** 先让 AI 列清单；只用第三步批准你亲自选出的编号。

</details>

<details id="解决什么问题">
<summary><strong>解决什么问题</strong></summary>

Mac 空间不足时，最容易出错的不是找不到大文件，而是把缓存、个人文件、浏览器登录状态和系统数据混在一起处理。

工具流程固定为：

```text
audit -> plan -> approve exact target IDs -> apply -> verify
```

</details>

<details id="安装">
<summary><strong>安装</strong></summary>

要求：macOS、Python 3.10+。基础 CLI 没有第三方运行依赖；MCP 是可选 extra。

### CLI

```bash
pipx install maccleaner
maccleaner --help
```

PyPI 首发前，直接从 GitHub 安装：

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git"
```

### MCP

```bash
pipx install "maccleaner[mcp]"
maccleaner-mcp
```

PyPI 首发前使用 GitHub 版本：

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git#egg=maccleaner[mcp]"
```

`maccleaner-mcp` 只使用 stdio。客户端配置和 plan token apply 示例见 [MCP 使用说明](docs/mcp.md)。

### Codex Skill

根目录 `SKILL.md` 保留为唯一 Skill 真相源。使用 Codex 的 GitHub Skill installer 时，指定 repo `Matoya-Amadeus/MacCleaner`、path `.`、安装名 `maccleaner`。

</details>

<details id="三分钟上手" open>
<summary><strong>三分钟上手</strong></summary>

### 1. 审计：只读查看空间

```bash
maccleaner audit --markdown
```

### 2. 计划：生成精确清单

```bash
maccleaner plan --markdown
```

重点看 `target_id`、`status`、`risk`、`protection` 和 `reason`。

### 3. 执行：只清理低风险目标

```bash
maccleaner clean --apply --yes --require-explicit-plan --markdown
```

这条命令会实际修改文件。运行前先完成 `plan`；它默认只放行低风险、可重新生成的目标。

高风险目标必须从当前计划复制真实 ID：

```bash
maccleaner plan --include-hidden-home --markdown
maccleaner clean --apply --yes --require-explicit-plan --markdown \
  --include-hidden-home \
  --approved-targets TARGET_ID
```

如果目标显示 `exact_confirm`，还要同时加上 `--confirm-targets TARGET_ID`。

</details>

<details id="cli-怎么用">
<summary><strong>CLI 怎么用</strong></summary>

CLI 适合终端、shell 脚本和 CI；始终按“审计 → 计划 → 执行”走，不要跳过 `plan`。

```bash
# 1. 只读：先看空间和候选目标。
maccleaner audit --markdown
maccleaner plan --json > maccleaner-plan.json

# 2. 只清理当前可执行的低风险目标。
# 若当前存在 medium/high-risk 候选但未精确批准，命令会拒绝执行，不会部分清理。
maccleaner clean --apply --yes --require-explicit-plan --markdown

# 3. 只在 plan 中确认真实 ID 后，才清理敏感范围。
maccleaner clean --apply --yes --require-explicit-plan --markdown \
  --include-hidden-home \
  --approved-targets TARGET_ID \
  --confirm-targets TARGET_ID

# 4. 反复出现的目录：先找触发源，不删除文件。
maccleaner trace --path "<TARGET_PATH>" --keyword "<KEYWORD>" --markdown
```

- `audit`、`plan`、`trace` 永远只读。
- `--json` 适合脚本读取；`--markdown` 适合人审阅。
- 只有报告显示 `exact_confirm` 时才需要 `--confirm-targets`；不要把示例 `TARGET_ID` 当作真实 ID。

</details>

<details id="mcp-怎么用">
<summary><strong>MCP 怎么用</strong></summary>

先在 MCP 客户端配置本地 stdio 服务，然后**重启或重新加载客户端**：

```json
{
  "mcpServers": {
    "maccleaner": {
      "command": "maccleaner-mcp",
      "args": []
    }
  }
}
```

客户端显示的 UI 不同；下面 JSON 表示应调用的工具名与参数，不是要求手写 JSON-RPC：

```json
{ "name": "audit_storage", "arguments": { "profile": "generic" } }

{ "name": "plan_storage", "arguments": { "profile": "generic" } }
```

从 `plan_storage` 返回结果复制 `plan_id`，并只从 `applicable_target_ids` 选择真实 ID：

```json
{
  "name": "apply_storage_plan",
  "arguments": {
    "plan_id": "PLAN_ID_FROM_PLAN",
    "approved_targets": ["TARGET_ID_FROM_PLAN"],
    "confirm_targets": ["TARGET_ID_FROM_PLAN"]
  }
}
```

四个工具分别是：`audit_storage`（只读审计）、`plan_storage`（只读计划与 token）、`trace_storage`（只读追查）和 `apply_storage_plan`（唯一会修改文件的工具）。

- plan token 只在当前 MCP 服务进程内保存，15 分钟过期且只能使用一次；**plan 和 apply 之间不要重启 `maccleaner-mcp`**。
- `apply_storage_plan` 不能传入新的扫描范围；它只执行同一 plan 中、你精确批准的 IDs。未批准的 low-risk 目标也不会执行。
- 某个 ID 需要二次确认时才传入 `confirm_targets`；浏览器会话、Cookie、Token、Keychain 和凭据不会成为可执行候选。

完整参数表和发布说明见 [MCP 使用说明](docs/mcp.md)。

</details>

<details id="常用场景">
<summary><strong>常用场景</strong></summary>

只读输出：

```bash
maccleaner audit --markdown
maccleaner audit --json
```

追查反复出现的目录：

```bash
maccleaner trace \
  --path "<TARGET_PATH>" \
  --keyword "<KEYWORD>" \
  --markdown
```

聚焦某个 App 或 Flutter 工程：

```bash
maccleaner audit \
  --app-path "/Applications/Example.app" --markdown
maccleaner audit \
  --flutter-search-root "$HOME/Projects" --markdown
```

`trace` 只读，不会删除文件。把示例路径和关键词替换成真实值。

源码 checkout 仍可使用 `scripts/audit_storage.sh`、`scripts/plan_storage.sh`、`scripts/apply_storage_plan.sh`；它们是兼容入口。

</details>

<details id="安全边界">
<summary><strong>安全边界</strong></summary>

| 目标 | 默认行为 |
| --- | --- |
| 普通缓存、日志、临时文件 | 可以计划；apply 时由 `--yes` 放行 |
| Downloads、Trash、Docker、hidden-home、App 残留、系统范围 | 默认不自动清理，需要精确批准 |
| 浏览器登录、Cookie、Session、Token、Keychain、凭据 | 永久阻断 |
| 不在当前计划中的目标 | 不执行 |

`audit`、`plan`、`trace` 都是只读命令。`apply_storage_plan.sh` 会修改文件；`safe_clean.sh` 只是旧入口的兼容 shim。

MCP 的 `apply_storage_plan` 不接受新的扫描参数：它必须使用 `plan_storage` 返回的未过期 `plan_id`、非空 `approved_targets`，以及必要的 `confirm_targets`。每个 plan token 只能执行一次。

</details>

<details id="配置与参数">
<summary><strong>配置与参数</strong></summary>

- `--profile generic`：默认通用模式，不假定私有 repo 结构。
- `--profile repo-evidence`：显式开启项目证据和历史索引追踪。
- `--state-root PATH`：设置 receipt 和 backup 的默认根目录。
- `--receipt-dir PATH` / `--backup-dir PATH`：单独指定目录，优先于 `--state-root`。
- `--approved-targets ID1,ID2`：批准当前 plan 中的精确目标。
- `--confirm-targets ID1,ID2`：为 `exact_confirm` 目标提供二次确认。
- `--include-hidden-home` / `--include-system`：扩大扫描范围，默认关闭。
- `--app-path PATH` / `--flutter-search-root PATH`：聚焦扫描范围。
- `--json` / `--markdown`：选择输出格式。
- `--apply` / `--dry-run` / `--yes`：控制 `clean` 模式的执行方式。

默认状态目录是 `~/.mac-storage-manager/`。

</details>

<details id="报告怎么看">
<summary><strong>报告怎么看</strong></summary>

- `target_id`：目标编号，高风险 apply 必须从当前 plan 复制。
- `status`：`planned`、`ready`、`blocked`、`skipped` 等状态。
- `protection`：需要批准、二次确认或保持阻断的原因。
- `backup_manifest`：需要备份时的备份和 SHA-256 清单。
- `receipt`：apply 的 Markdown/JSON 清理记录路径。

`empty` 表示没有可清理内容，属于正常结果。目标反复出现时，用 `trace` 查触发源。

</details>

<details id="结构与工作链路">
<summary><strong>结构与工作链路</strong></summary>

```text
CLI/wrapper -> StorageContext -> profile discovery -> scan -> plan/gates
            -> optional apply -> renderer/receipt/residual validation
```

- `src/maccleaner/`：唯一核心实现，以及 CLI 与 MCP adapter。
- `scripts/mac_storage_manager.py`：旧 CLI 兼容 facade。
- `scripts/_mac_storage_*.py`：旧 Python 导入路径兼容 shim。
- `scripts/*_storage.sh`：源码 checkout 的 audit、plan、apply wrapper。
- `tests/`、`references/`：测试和敏感场景路由说明。

</details>

<details id="开发者说明">
<summary><strong>开发者说明</strong></summary>

```bash
python3 -m pip install ".[mcp]" build
python3 -m unittest discover -s tests -v
python3 -m build
```

PyPI 首发前，在 PyPI 为 `Matoya-Amadeus/MacCleaner` 配置 Trusted Publisher；push `v0.1.0` tag 后发布工作流会验证 tag 与包版本一致。

</details>

<details id="常见问题">
<summary><strong>常见问题</strong></summary>

### 我没有说“先列清单”，它会直接清理吗？

推荐流程不会跳过清单：先运行 `plan`，看完结果，再决定是否运行 apply。apply 会重新扫描，并再次执行风险和批准检查。

### `--yes` 会删除 Downloads 或 Trash 吗？

不会。`--yes` 只放行 low-risk 目标。敏感范围需要精确批准，浏览器身份和凭据数据保持阻断。

### apply 失败或没有释放空间怎么办？

查看报告里的 `blocked`、`skipped`、`failed` 和 `reason`。`empty` 表示没有可清理内容，属于正常结果。

### MCP 会直接清理吗？

不会。MCP 先返回只读 `plan_storage` 结果和短期 `plan_id`。apply 必须带同一个 token、精确 target IDs 和需要时的二次确认；未批准的 low-risk target 也会保持阻断。

</details>

由 **AI·Maho** 和 **人类·Matoya** 共同维护
