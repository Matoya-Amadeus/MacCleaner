# Mac Storage Manager

![Mac Storage Manager](assets/readme-header.svg)

> **先看清单，再决定删什么。**
>
> **Inspect first. Approve exact targets. Clean only what you selected.**

`macOS` · `Python 标准库` · `generic 默认` · `先审计后执行`

Mac Storage Manager 是一个开源 macOS 磁盘空间审计与清理 CLI。它先告诉你哪里占空间、哪些目标可以处理、哪些目标需要明确批准；只有你运行 apply 并通过对应门禁后，才会执行清理。

Mac Storage Manager is an open-source macOS storage audit and cleanup CLI. It shows what is taking space and which targets need approval before it removes anything.

## 近期更新
## Recent Notes

更新时间：2026-07-11 15:51

Update time: 2026-07-11 15:51

更新内容：重写开源 README 的首次使用路径，明确 audit、plan、apply 的真实行为，并补充风险边界、输出示例和常见失败处理。

Update content: Reworked the open-source README around the real audit, plan, and apply behavior, with clearer safety boundaries, output examples, and troubleshooting.

### 2026-05-19 21:20

更新时间：2026-05-19 21:20

Update time: 2026-05-19 21:20

更新内容：新增 generic 默认 profile、repo-evidence opt-in、受保护会话阻断、receipt、backup 和清理后残留验证。

Update content: Added the generic default profile, opt-in repo-evidence profile, protected-session blocking, receipts, backups, and post-cleanup residual validation.

## 目录
## Table of Contents

- [解决什么问题 / What It Solves](#解决什么问题)
- [一眼看懂 / At a Glance](#一眼看懂)
- [近期更新 / Recent Notes](#近期更新)
- [三分钟上手 / Quick Start](#三分钟上手)
- [安装 / Installation](#安装)
- [常用场景 / Common Scenarios](#常用场景)
- [安全边界 / Safety Boundaries](#安全边界)
- [配置与参数 / Configuration & CLI Reference](#配置与参数)
- [报告怎么看 / Reading Reports](#报告怎么看)
- [结构总览 / Structure Map](#结构总览)
- [工作链路 / How It Works](#工作链路)
- [开发者说明 / Developer Notes](#开发者说明)
- [常见问题 / FAQ](#常见问题)
- [许可证 / License](#许可证)

## 解决什么问题
## What It Solves

Mac 空间不足时，最容易出错的不是找不到大文件，而是把缓存、个人文件、浏览器登录状态和系统数据混在一起处理。

When storage is full, the hard part is separating rebuildable caches from personal files, browser sessions, and system data.

这个工具把操作分成四步：

The workflow has four steps:

```text
audit -> plan -> approve exact target IDs -> apply -> verify
```

适合：

Best for:

- 想先知道空间去哪了，再决定是否清理的人。

  People who want to see where space went before deleting anything.
- 需要处理 Xcode、包管理器、IDE、Flutter、Playwright、日志和缓存的开发者。

  Developers managing Xcode, package-manager, IDE, Flutter, Playwright, log, and cache data.
- 需要让 agent 或自动化流程“先列清单、再执行”的团队。

  Teams that need an explicit list-before-apply workflow.

不适合：

Not for:

- 让工具替你判断个人文件是否有价值。

  Deciding whether personal files are valuable.
- 把整个磁盘 `/` 当成默认清理范围。

  Treating `/` or the whole machine as a default cleanup scope.

## 一眼看懂
## At a Glance

| 你要做什么 | 运行什么 | 会发生什么 |
| --- | --- | --- |
| 只看空间占用 | `bash scripts/audit_storage.sh` | 只读扫描，不删除文件 |
| 生成可执行清单 | `bash scripts/plan_storage.sh` | 列出计划中、需要批准和被阻断的目标 |
| 清理低风险目标 | `bash scripts/apply_storage_plan.sh` | 实际执行可重新生成的低风险目标 |
| 清理高风险目标 | 在 apply 后加 `--approved-targets ID` | 只执行你明确批准的目标 |
| 追查反复出现的目录 | `python3 scripts/mac_storage_manager.py trace ...` | 查找触发源，不删除文件 |

| Goal | Command | Result |
| --- | --- | --- |
| Inspect storage | `bash scripts/audit_storage.sh` | Read-only scan |
| Build a plan | `bash scripts/plan_storage.sh` | Lists planned, approval-needed, and blocked targets |
| Apply low-risk cleanup | `bash scripts/apply_storage_plan.sh` | Removes eligible regenerable targets |
| Apply high-risk cleanup | Add `--approved-targets ID` | Applies only the exact IDs you approved |
| Trace a reappearing folder | `python3 scripts/mac_storage_manager.py trace ...` | Finds likely triggers without deleting |

## 安装
## Installation

### 环境要求
### Requirements

- macOS。

  macOS.
- Python 3.10+；不需要第三方 Python 包。

  Python 3.10+; no third-party Python packages are required.
- 使用 wrapper 需要 `zsh`；直接运行 CLI 只需要 Python。

  Wrappers use `zsh`; direct CLI use only requires Python.
- `brew`、`docker`、`flutter`、`xcrun` 是可选工具，只有相关目标才会用到。

  `brew`, `docker`, `flutter`, and `xcrun` are optional and used only by related targets.

### 获取并检查
### Get and Check Out

```bash
git clone https://github.com/Matoya-Amadeus/AISkill-MacStorageManager.git
cd AISkill-MacStorageManager
python3 scripts/mac_storage_manager.py --help
```

如果你是通过 ZIP 下载，进入解压目录后运行最后一条命令即可。

If you downloaded a ZIP, enter the extracted directory and run the last command.

如果 ZIP 下载丢失了 wrapper 的可执行权限，只需修复一次：

If a ZIP download drops executable bits, fix them once:

```bash
chmod +x scripts/audit_storage.sh scripts/plan_storage.sh scripts/apply_storage_plan.sh scripts/safe_clean.sh
```

## 三分钟上手
## Quick Start

### 第一步：先做只读审计
### Step 1: Run a read-only audit

```bash
bash scripts/audit_storage.sh
```

这一步只扫描，不删除。你会看到 `Top Consumers`、`Cleaned / Planned` 和安全边界。

This step only scans. Look for `Top Consumers`, `Cleaned / Planned`, and the cleanup boundary.

### 第二步：生成精确清单
### Step 2: Build the exact plan

```bash
bash scripts/plan_storage.sh
```

重点看每一行的 `target_id`、`status`、`risk`、`protection` 和 `reason`。

Review `target_id`, `status`, `risk`, `protection`, and `reason` for each item.

常见状态：

Common statuses:

- `planned`：已列入计划，但还没有执行。

  Listed in the plan but not applied.
- `ready`：在当前 apply 条件下可以执行。

  Eligible under the current apply conditions.
- `blocked`：需要批准、二次确认或受保护，当前不会执行。

  Needs approval, extra confirmation, or protection keeps it blocked.
- `skipped`：路径不存在、工具缺失或条件不满足。

  Skipped because a path, tool, or condition is unavailable.

### 第三步：只执行你确认过的目标
### Step 3: Apply only after reviewing the plan

低风险目标可以用推荐 wrapper：

For low-risk targets, use the recommended wrapper:

```bash
bash scripts/apply_storage_plan.sh
```

**这条命令会实际清理文件。**它会执行 `clean --apply --yes --require-explicit-plan --markdown`，只放行低风险、可重新生成的目标。运行前请先完成上一步 `plan`。

**This command changes files.** It runs `clean --apply --yes --require-explicit-plan --markdown` and only allows low-risk, regenerable targets. Run `plan` first.

对于 Downloads、Trash、Docker、hidden-home、App 残留和系统范围等目标，先从 `plan` 输出复制真实的 `target_id`，不要猜占位符：

For Downloads, Trash, Docker, hidden-home, app leftovers, and system targets, copy the real `target_id` from `plan`; do not type the placeholder literally:

```bash
bash scripts/plan_storage.sh --include-hidden-home

# Replace TARGET_ID with the exact ID printed above.
bash scripts/apply_storage_plan.sh \
  --include-hidden-home \
  --approved-targets TARGET_ID
```

如果报告显示 `exact_confirm`，还要同时传 `--confirm-targets TARGET_ID`：

If the report shows `exact_confirm`, also pass `--confirm-targets TARGET_ID`:

```bash
bash scripts/apply_storage_plan.sh \
  --include-hidden-home \
  --approved-targets TARGET_ID \
  --confirm-targets TARGET_ID
```

### 你应该看到什么
### What Success Looks Like

审计和计划不会删除文件。下面只是格式示例，不是你机器上的真实目标：

Audit and plan do not delete files. The following is only a format example, not output from your Mac:

```text
Cleaned / Planned:
- `home-caches` [planned] [in_scope] ...
- `downloads` [blocked] [outside_approved_plan] ...
- `<target-id>` [blocked] [protected_session] ...
```

真实的 target ID、路径和字节数会随你的 Mac 改变。不要复制上面示例中的 ID。

Real target IDs, paths, and byte counts depend on your Mac. Do not copy the example IDs.

## 常用场景
## Common Scenarios

### 只看空间，不做清理
### Inspect only

```bash
python3 scripts/mac_storage_manager.py audit --markdown
python3 scripts/mac_storage_manager.py audit --json
```

wrapper 默认输出 Markdown；CLI 不加格式参数时输出简短 text。

Wrappers default to Markdown; the CLI prints concise text unless you pass a format flag.

### 清理普通缓存和日志
### Clean ordinary caches and logs

```bash
bash scripts/plan_storage.sh
bash scripts/apply_storage_plan.sh
```

先看计划，再运行 apply。低风险目标通常可以执行；其他目标会保留为 `blocked` 或 `skipped`。

Review the plan before apply. Low-risk targets may run; other targets remain `blocked` or `skipped`.

### 追查反复出现的目录
### Trace a reappearing folder

```bash
python3 scripts/mac_storage_manager.py trace \
  --path "<TARGET_PATH>" \
  --keyword "<KEYWORD>" \
  --markdown
```

把 `<TARGET_PATH>` 和 `<KEYWORD>` 换成真实值。`trace` 只读，不会删除。

Replace `<TARGET_PATH>` and `<KEYWORD>` with real values. `trace` is read-only.

默认 `generic` 只查通用触发源和邻近证据；只有明确需要项目证据时才使用 `--profile repo-evidence`。

The default `generic` profile checks general triggers and nearby evidence. Use `--profile repo-evidence` only when you explicitly need project evidence.

### 聚焦某个 App 或 Flutter 工程
### Focus on an app or Flutter project

```bash
python3 scripts/mac_storage_manager.py audit \
  --app-path "/Applications/Example.app" \
  --markdown

python3 scripts/mac_storage_manager.py audit \
  --flutter-search-root "$HOME/Projects" \
  --markdown
```

这些参数只收窄扫描范围，不会自动扩大清理范围。

These options narrow the scan scope; they do not broaden cleanup automatically.

## 安全边界
## Safety Boundaries

### 用一句话理解
### The short version

默认规则很简单：**先列清单；apply 会重新检查目标，并且只执行通过门禁、且与批准 ID 匹配的目标。**

The rule is simple: **plan first; apply rechecks the targets and runs only items that pass the gates and match approved IDs.**

| 目标类型 | 默认行为 | 需要什么 |
| --- | --- | --- |
| 普通缓存、日志、临时文件 | 可以进入计划 | apply 时 `--yes` |
| Downloads、Trash、Docker、hidden-home、App 残留、系统范围 | 默认不自动清理 | 精确 `--approved-targets ID`；部分目标还需 `--confirm-targets ID` |
| 浏览器登录、Cookie、Session、Token、Keychain、凭据 | 永久阻断 | 不提供普通确认绕过 |
| 不在当前计划中的目标 | 不执行 | 先重新生成计划 |

| Target type | Default behavior | Required |
| --- | --- | --- |
| Ordinary caches, logs, and temp files | Can enter the plan | `--yes` during apply |
| Downloads, Trash, Docker, hidden-home, app leftovers, and system scope | Not auto-cleaned | Exact `--approved-targets ID`; some also need `--confirm-targets ID` |
| Browser login, cookies, sessions, tokens, keychain, and credentials | Always blocked | No normal confirmation bypass |
| Targets outside the current plan | Not executed | Generate a new plan |

### 重要提醒
### Important Notes

- `audit`、`plan`、`trace` 只读，不删除文件。

  `audit`, `plan`, and `trace` are read-only.
- `apply_storage_plan.sh` 会修改文件；不要把它当成预览命令。

  `apply_storage_plan.sh` changes files; it is not a preview command.
- `safe_clean.sh` 只是旧入口的兼容 shim，会提示弃用并转到 apply wrapper。

  `safe_clean.sh` is a deprecated compatibility shim.
- 报告、receipt 和 backup manifest 会尽量隐藏绝对路径，但不要把它们当作秘密存储。

  Reports, receipts, and backup manifests redact paths where possible, but are not secret storage.

## 配置与参数
## Configuration & CLI Reference

### 四个命令
### Four Commands

| 命令 | 作用 | 是否修改文件 |
| --- | --- | --- |
| `audit` | 扫描并报告空间热点 | 否 |
| `plan` | 生成清理计划 | 否 |
| `clean` | 不加 `--apply` 时报告；加上后执行 | 只有 `--apply` 时会修改 |
| `trace` | 追踪反复出现的目录来源 | 否 |

| Command | Purpose | Changes files |
| --- | --- | --- |
| `audit` | Scan and report storage hotspots | No |
| `plan` | Build a cleanup plan | No |
| `clean` | Reports by default; applies with `--apply` | Only with `--apply` |
| `trace` | Trace sources for reappearing folders | No |

### 常用参数
### Common Options

| 参数 | 作用 |
| --- | --- |
| `--profile generic` | 默认通用模式；不假定私有 repo 结构 |
| `--profile repo-evidence` | 显式开启项目证据和历史索引追踪 |
| `--state-root PATH` | 设置 receipt 和 backup 的默认根目录 |
| `--receipt-dir PATH` | 单独指定 receipt 目录，优先于 `--state-root` |
| `--backup-dir PATH` | 单独指定 backup 目录，优先于 `--state-root` |
| `--approved-targets ID1,ID2` | 精确批准目标；ID 必须来自当前 plan |
| `--confirm-targets ID1,ID2` | 为 `exact_confirm` 目标提供二次确认 |
| `--require-zero-hit WORD` | apply 后检查指定关键词是否还残留 |
| `--include-hidden-home` | 把 hidden-home 目标加入扫描 |
| `--include-system` | 把系统目标加入扫描；默认关闭 |
| `--app-path PATH` | 聚焦某个 `.app` 的残留 |
| `--flutter-search-root PATH` | 限制 Flutter 工程搜索范围 |
| `--json` / `--markdown` | 选择输出格式 |
| `--apply` | `clean` 模式实际修改文件 |
| `--dry-run` | `clean` 模式不修改文件；需要清单时优先用 `plan` |
| `--yes` | 只批准 low-risk 目标 |
| `--require-explicit-plan` | apply 前要求高风险目标有显式批准 |

| Option | Purpose |
| --- | --- |
| `--profile generic` | Default portable profile; assumes no private repo layout |
| `--profile repo-evidence` | Explicitly include project evidence and historical-index tracing |
| `--state-root PATH` | Default root for receipts and backups |
| `--receipt-dir PATH` | Receipt directory; overrides `--state-root` |
| `--backup-dir PATH` | Backup directory; overrides `--state-root` |
| `--approved-targets ID1,ID2` | Exact targets from the current plan |
| `--confirm-targets ID1,ID2` | Extra confirmation for `exact_confirm` targets |
| `--require-zero-hit WORD` | Check for a residual keyword after apply |
| `--include-hidden-home` | Include hidden-home targets in the scan |
| `--include-system` | Include system targets; off by default |
| `--app-path PATH` | Focus on one `.app` leftovers |
| `--flutter-search-root PATH` | Limit Flutter project search scope |
| `--json` / `--markdown` | Choose the output format |
| `--apply` | Actually modify files in `clean` mode |
| `--dry-run` | Run `clean` without modifying files; use `plan` for the exact list |
| `--yes` | Approve low-risk targets only |
| `--require-explicit-plan` | Require explicit approval for high-risk apply |

默认状态目录是 `~/.mac-storage-manager/`。未传 `--receipt-dir` 或 `--backup-dir` 时，`--state-root PATH` 会提供默认目录；单独传入的 receipt/backup 目录优先。

The default state directory is `~/.mac-storage-manager/`. `--state-root PATH` supplies defaults when receipt/backup directories are omitted; explicit directories take precedence.

## 报告怎么看
## Reading Reports

### 先看这五个字段
### Start with these five fields

- `target_id`：目标编号。高风险 apply 必须从当前 plan 复制它。

  `target_id`: the target identifier; high-risk apply must copy it from the current plan.
- `status`：`planned`、`ready`、`blocked`、`skipped` 等当前状态。

  `status`: the current state, such as `planned`, `ready`, `blocked`, or `skipped`.
- `protection`：为什么需要批准、二次确认或保持阻断。

  `protection`: why approval, extra confirmation, or blocking applies.
- `backup_manifest`：apply 时的备份清单和 SHA-256 清单（如果该目标需要备份）。

  `backup_manifest`: backup and SHA-256 manifests when backup is needed.
- `receipt`：本次 apply 的 Markdown/JSON 清理记录路径。

  `receipt`: Markdown/JSON receipt paths for the apply run.

### 运行完成后怎么判断
### How to Tell What Happened

- 审计或计划：看 `Top Consumers` 和 `Cleaned / Planned`，不会删除文件。

  Audit and plan: review `Top Consumers` and `Cleaned / Planned`; no files are deleted.
- apply：看 `cleaned`、`blocked`、`skipped` 的数量，再看 `receipt` 和 `Residual Validation`。

  Apply: review the `cleaned`, `blocked`, and `skipped` counts, then inspect the receipt and residual validation.
- 没有可清理内容：看到 `empty` 很正常，不代表命令失败。

  `empty` is normal when nothing is eligible; it does not mean the command failed.

## 结构总览
## Structure Map

```text
scripts/mac_storage_manager.py     compatibility facade and CLI entry
scripts/_mac_storage_cli.py        argument parser and context builder
scripts/_mac_storage_core.py       scanning, planning, execution, receipt, and backup
scripts/_mac_storage_policy.py     risk, approval, retention, and profile policy
scripts/_mac_storage_render.py     Markdown, text, and JSON rendering
scripts/audit_storage.sh           read-only audit wrapper
scripts/plan_storage.sh            read-only plan wrapper
scripts/apply_storage_plan.sh      apply wrapper for low-risk cleanup
scripts/safe_clean.sh              deprecated compatibility shim
tests/                             regression and open-source contract tests
references/                        routing notes for sensitive cleanup cases
```

- `scripts/mac_storage_manager.py`: compatibility facade and CLI entry.
- `scripts/_mac_storage_core.py`: scanning, planning, execution, receipts, and backups.
- `scripts/_mac_storage_policy.py`: risk, approval, retention, and profile policy.
- `scripts/_mac_storage_render.py`: Markdown, text, and JSON rendering.
- `scripts/`: shell wrappers for audit, plan, and apply.
- `tests/` and `references/`: regression coverage and sensitive-case routing notes.

## 工作链路
## How It Works

```text
CLI or wrapper
  -> StorageContext
  -> profile-aware target discovery
  -> scan facts
  -> plan and safety gate
  -> optional apply
  -> renderer, receipt, and residual validation
```

这里的 `SKILL.md` 是 agent 使用说明；`scripts/` 下的 Python 和 shell 文件才是实际执行入口。

`SKILL.md` is the agent-facing contract; the Python and shell files under `scripts/` are the executable entrypoints.

- CLI 或 wrapper 接收参数，构建 `StorageContext`。

  The CLI or wrapper builds a `StorageContext` from the arguments.
- profile 负责发现目标，核心模块收集扫描事实并执行安全门禁。

  The selected profile discovers targets, and the core collects scan facts and applies safety gates.
- 通过门禁后才会执行可选的 apply，并输出报告、receipt 和残留验证结果。

  Only gated items reach apply, followed by reports, receipts, and residual validation.

## 开发者说明
## Developer Notes

### 运行测试
### Run Tests

```bash
python3 -m unittest -v tests.test_mac_storage_manager tests.test_mac_storage_open_source_contract
```

### 语法检查
### Syntax Checks

```bash
python3 -m py_compile \
  scripts/mac_storage_manager.py \
  scripts/_mac_storage_cli.py \
  scripts/_mac_storage_core.py \
  scripts/_mac_storage_policy.py \
  scripts/_mac_storage_render.py \
  tests/test_mac_storage_manager.py \
  tests/test_mac_storage_open_source_contract.py

zsh -n scripts/audit_storage.sh
zsh -n scripts/plan_storage.sh
zsh -n scripts/apply_storage_plan.sh
zsh -n scripts/safe_clean.sh
```

提交文档或代码前，确认 CLI flag、wrapper、README、SKILL.md、renderer 和测试仍然一致。

Before contributing, keep CLI flags, wrappers, README, SKILL.md, renderers, and tests aligned.

## 常见问题
## FAQ

### 我没有说“先列清单”，它会直接清理吗？
### Will it clean directly if I do not say “list first”?

推荐流程不会直接跳过清单：先运行 `plan`，看完结果，再决定是否运行 apply wrapper。CLI 不会保存一个必须提交的计划文件；apply 时会重新扫描，并再次执行风险和批准检查。真正修改文件必须进入 `clean --apply`。

The recommended workflow does not skip the list: run `plan`, review it, then choose the apply wrapper. The CLI does not save a plan file that must be submitted; apply rescans and rechecks the approval gates. File changes require `clean --apply`.

### `--yes` 会删除 Downloads 或 Trash 吗？
### Does `--yes` delete Downloads or Trash?

不会。`--yes` 只放行 low-risk 目标。Downloads、Trash、Docker、hidden-home、App 残留和系统范围需要精确批准；浏览器登录、Cookie、Session、Token、Keychain 和凭据保持阻断。

No. `--yes` only allows low-risk targets. Sensitive scopes need exact approval, while browser identity and credential material stay blocked.

### `safe_clean.sh` 还能用吗？
### Can I still use `safe_clean.sh`?

可以，但它只是旧入口的兼容 shim，会打印弃用提示并转到 `apply_storage_plan.sh`。新流程直接使用 audit、plan、apply 三个入口。

Yes, but it is a deprecated compatibility shim. Prefer the audit, plan, and apply entrypoints.

### `repo-evidence` 什么时候用？
### When should I use `repo-evidence`?

只有在你明确需要追踪项目引用、生成证据或历史索引时才使用。普通 Mac 清理保持默认 `generic`。

Use it only when you explicitly need project references, generated evidence, or historical indexes. Keep ordinary cleanup on `generic`.

### apply 失败或没有释放空间怎么办？
### What if apply fails or frees little space?

先看报告里的 `blocked`、`skipped`、`failed` 和 `reason`。如果目标反复出现，用 `trace` 查触发源；如果只是没有可清理内容，`empty` 是正常结果。

Check `blocked`, `skipped`, `failed`, and `reason` in the report. If a target reappears, use `trace`; `empty` is normal when nothing is eligible.

## 许可证
## License

MIT License，详见 `LICENSE`。

MIT License. See `LICENSE`.

由 **AI·Maho** 和 **人类·Matoya** 共同维护
Maintained jointly by **AI·Maho** and **Human·Matoya**
