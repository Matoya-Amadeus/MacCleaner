# MacCleaner

![MacCleaner](assets/readme-header.svg)

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
- [解决什么问题](#解决什么问题)
- [安装](#安装)
- [三分钟上手](#三分钟上手)
- [常用场景](#常用场景)
- [安全边界](#安全边界)
- [配置与参数](#配置与参数)
- [报告怎么看](#报告怎么看)
- [结构与工作链路](#结构与工作链路)
- [开发者说明](#开发者说明)
- [常见问题](#常见问题)

## 一眼看懂

| 你要做什么 | 运行什么 | 会发生什么 |
| --- | --- | --- |
| 只看空间占用 | `maccleaner audit --markdown` | 只读扫描，不删除文件 |
| 生成精确清单 | `maccleaner plan --markdown` | 列出计划中、需批准和被阻断的目标 |
| 清理低风险目标 | `maccleaner clean --apply --yes --require-explicit-plan` | 只执行可重新生成的低风险目标 |
| 清理高风险目标 | apply 时加 `--approved-targets ID` | 只执行你明确批准的目标 |

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
Maintained jointly by **AI·Maho** and **Human·Matoya**
