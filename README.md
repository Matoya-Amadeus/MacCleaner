# Mac Storage Manager

<p align="center">
  <img src="assets/readme-header.svg" alt="Mac Storage Manager hero banner" width="100%">
</p>

<p align="center">
  <strong>先审计，再列清单；先批准 exact target ID，再执行清理。</strong><br>
  <strong>Audit first, build an exact plan, approve target IDs, then clean.</strong>
</p>

<p align="center">
  <code>macOS only</code> · <code>Python stdlib</code> · <code>generic by default</code> · <code>audit-first</code> · <code>redacted receipts</code>
</p>

<p align="center">
  <a href="#解决什么问题">解决什么问题</a> ·
  <a href="#三分钟上手">三分钟上手</a> ·
  <a href="#安全模型">安全模型</a> ·
  <a href="#配置与参数">配置与参数</a> ·
  <a href="#开发者说明">开发者说明</a>
</p>

Mac Storage Manager 是一个开源 macOS 磁盘空间审计与清理 skill/CLI。它不是“闭眼一键清理器”：默认只读，先产出可复查的目标清单，再只执行你明确批准的目标。

Mac Storage Manager is an open-source macOS storage audit and cleanup skill/CLI. It is not a blind one-click cleaner: it defaults to read-only inspection, produces reviewable target lists, and applies only explicitly approved targets.

## 目录
## Table of Contents

- [解决什么问题 / What It Solves](#解决什么问题)
- [一眼看懂 / At a Glance](#一眼看懂)
- [近期更新 / Recent Notes](#近期更新)
- [安装 / Installation](#安装)
- [三分钟上手 / Three-Minute Start](#三分钟上手)
- [常用场景 / Common Scenarios](#常用场景)
- [安全模型 / Safety Model](#安全模型)
- [配置与参数 / Configuration & CLI Reference](#配置与参数)
- [报告怎么看 / How to Read Reports](#报告怎么看)
- [结构总览 / Structure Map](#结构总览)
- [开发者说明 / Developer Notes](#开发者说明)
- [常见问题 / FAQ](#常见问题)

## 解决什么问题
## What It Solves

你的 Mac 空间满了，但真正危险的不是“空间不够”，而是为了腾空间误删个人文件、会话数据、凭据、系统目录或还在使用的开发环境。

The hard problem is not just low disk space; it is freeing space without deleting personal files, session data, credentials, system paths, or active development state.

这个仓库把清理拆成一条可验证链路：

This repository turns cleanup into a verifiable chain:

```text
audit -> plan -> approve exact target IDs -> apply -> receipt + residual validation
```

适合：

Best for:

- 想先知道空间去哪了的普通 macOS 用户。
  macOS users who want to see where space went before deleting anything.
- 被 Xcode、包管理器、IDE、Flutter、Playwright、日志和缓存占用空间的开发者。
  Developers dealing with Xcode, package managers, IDEs, Flutter, Playwright, logs, and caches.
- 需要“先列清单，再确认执行”边界的 agent / automation 工作流。
  Agent and automation workflows that require an explicit list-before-apply boundary.

不适合：

Not for:

- 替你判断个人文件是否该删。
  Deciding whether your personal files should be deleted.
- 绕过确认清理 Downloads、Trash、Docker、hidden-home、浏览器会话或系统范围。
  Bypassing approval for Downloads, Trash, Docker, hidden-home, browser sessions, or system scope.
- 把 `/` 或整台机器当作默认清理目标。
  Treating `/` or the entire machine as a default cleanup target.

## 一眼看懂
## At a Glance

| 能力 | 默认行为 | 人需要做什么 |
| --- | --- | --- |
| 审计空间 | 只读扫描，输出 Markdown/JSON | 看 `Top Consumers` 和 target ID |
| 生成计划 | 只读 `plan`，列出可执行、被阻断和需批准目标 | 复制真实 target ID，不要猜 |
| 执行清理 | 只通过 approved plan 执行 | 低风险可 `--yes`；中高风险传 `--approved-targets` |
| 保护会话 | 浏览器登录、cookie、token、key material 永久阻断 | 不把它们当普通缓存清理 |
| 留痕复盘 | 写 receipt、backup manifest、sha256 manifest、residual validation | 用报告确认结果 |

| Capability | Default behavior | Human action |
| --- | --- | --- |
| Audit storage | Read-only scan with Markdown/JSON output | Review `Top Consumers` and target IDs |
| Build plan | Read-only `plan` with executable, blocked, and approval-needed targets | Copy real target IDs; do not guess |
| Apply cleanup | Executes only through an approved plan | Low risk can use `--yes`; medium/high risk needs `--approved-targets` |
| Protect sessions | Browser login, cookies, tokens, and key material stay blocked | Do not treat them as normal cache |
| Keep evidence | Writes receipts, backup manifests, sha256 manifests, and residual validation | Use the report to verify results |

## 近期更新
## Recent Notes

**最新更新 / Latest note**

- 更新时间：2026-07-10 23:18
  Update time: 2026-07-10 23:18
- 更新内容：按开源 README 规则重写首页：把首屏改成“问题 -> 安全链路 -> 三分钟上手”，突出 `generic` 默认 profile、`repo-evidence` opt-in、audit/plan/apply 分离、风险门禁、状态目录和脱敏输出。
  Update content: Rewrote the homepage for open-source use: the first screen now follows problem -> safety chain -> three-minute start, with clear coverage for the default `generic` profile, opt-in `repo-evidence`, audit/plan/apply separation, risk gates, state root, and redacted output.

**最近一条 / One recent note**

- 更新时间：2026-05-19 21:20
  Update time: 2026-05-19 21:20
- 更新内容：新增 trace-first 触发源分析、source_layer / protection / rollback_strategy / validation_patterns、protected_session 默认阻断、receipt / backup / sha256 / residual validation，以及 README / SKILL / tests 的脱敏同步。
  Update content: Added trace-first source analysis, source_layer / protection / rollback_strategy / validation_patterns, default blocking for protected_session, receipt / backup / sha256 / residual validation, and redacted sync across README / SKILL / tests.

## 安装
## Installation

### 环境要求
### Requirements

| 项目 | 要求 |
| --- | --- |
| 系统 | macOS |
| Python | Python 3.10+ recommended；当前测试在 Python 3.12 通过 |
| Python 依赖 | 无第三方依赖，只使用标准库 |
| Shell | `zsh` 或能运行 `bash` wrapper 的终端 |
| 可选工具 | `brew`、`docker`、`flutter`、`xcrun`；缺失时相关目标跳过 |

| Item | Requirement |
| --- | --- |
| OS | macOS |
| Python | Python 3.10+ recommended; currently tested with Python 3.12 |
| Python packages | No third-party dependencies; standard library only |
| Shell | `zsh` or a terminal that can run the `bash` wrappers |
| Optional tools | `brew`, `docker`, `flutter`, `xcrun`; related targets are skipped when missing |

### 获取仓库
### Get the Repository

```bash
git clone https://github.com/<OWNER>/AISkill-MacStorageManager.git
cd AISkill-MacStorageManager
python3 scripts/mac_storage_manager.py --help
```

如果你通过 ZIP 下载，进入解压目录后直接运行同样的 `python3 ... --help` 检查即可。

If you downloaded a ZIP, enter the extracted directory and run the same `python3 ... --help` check.

Wrapper 已在仓库中提供。如果 ZIP 下载丢失可执行位，可修复一次：

Wrappers are included in the repository. If a ZIP download drops executable bits, fix them once:

```bash
chmod +x scripts/audit_storage.sh scripts/plan_storage.sh scripts/apply_storage_plan.sh scripts/safe_clean.sh
```

## 三分钟上手
## Three-Minute Start

### 1) 只读审计：先看空间热点
### 1) Read-only audit: inspect storage hotspots

```bash
bash scripts/audit_storage.sh
```

成功时你会看到 Markdown 报告，包括 `Top Consumers`、`Cleanup Boundary`、`Cleaned / Planned`、`Backup / Receipt` 和 `Next Step Options`。这一步不会删除文件。

On success, you will see a Markdown report with `Top Consumers`, `Cleanup Boundary`, `Cleaned / Planned`, `Backup / Receipt`, and `Next Step Options`. This step does not delete files.

### 2) 只读计划：拿到 exact target list
### 2) Read-only plan: get the exact target list

```bash
bash scripts/plan_storage.sh
```

`plan` 不是 `audit` 的别名。它会把候选目标分成 ready、blocked、outside approved plan、explicit approval needed，并告诉你 apply 前需要哪些 `--approved-targets` / `--confirm-targets`。

`plan` is not an alias for `audit`. It separates ready, blocked, outside-approved-plan, and explicit-approval-needed targets, then tells you which `--approved-targets` / `--confirm-targets` are required before apply.

### 3) 低风险清理：确认计划后再 apply
### 3) Low-risk cleanup: apply only after reviewing the plan

```bash
bash scripts/apply_storage_plan.sh
```

这个 wrapper 会运行 `clean --apply --yes --require-explicit-plan --markdown`。`--yes` 只放行低风险、可重建目标；不会解锁 Downloads、Trash、Docker、hidden-home、app leftovers、system 或 protected session。

This wrapper runs `clean --apply --yes --require-explicit-plan --markdown`. `--yes` only approves low-risk, regenerable targets; it does not unlock Downloads, Trash, Docker, hidden-home, app leftovers, system scope, or protected sessions.

### 4) 中高风险目标：必须传 exact target ID
### 4) Medium/high-risk targets: pass exact target IDs

先从报告复制真实 target ID：

Copy the real target ID from the report first:

```bash
bash scripts/plan_storage.sh --include-hidden-home
```

再执行精确批准：

Then apply exact approval:

```bash
bash scripts/apply_storage_plan.sh \
  --include-hidden-home \
  --approved-targets TARGET_ID
```

如果该目标的 protection 是 `exact_confirm`，还必须加 `--confirm-targets TARGET_ID`：

If the target protection is `exact_confirm`, also pass `--confirm-targets TARGET_ID`:

```bash
bash scripts/apply_storage_plan.sh \
  --include-hidden-home \
  --approved-targets TARGET_ID \
  --confirm-targets TARGET_ID
```

不要猜 ID；先看报告，再复制。

Do not guess IDs; read the report, then copy the exact value.

### 5) 反复生成目录：先 trace 触发源
### 5) Reappearing folders: trace the source first

```bash
python3 scripts/mac_storage_manager.py trace \
  --path "<TARGET_PATH>" \
  --keyword "<KEYWORD>" \
  --markdown
```

`trace` 是只读命令。默认 `generic` profile 会查通用 active trigger、runtime artifact 和目标路径邻近证据；只有显式 `--profile repo-evidence` 才会加入 repo reference / historical index 证据层。

`trace` is read-only. The default `generic` profile checks general active triggers, runtime artifacts, and nearby target evidence; repo reference / historical index layers are included only with explicit `--profile repo-evidence`.

## 常用场景
## Common Scenarios

### 只想知道空间去哪了
### Inspect storage usage only

```bash
python3 scripts/mac_storage_manager.py audit --markdown
python3 scripts/mac_storage_manager.py audit --json
```

### 只清普通缓存和日志
### Clean ordinary caches and logs

```bash
bash scripts/plan_storage.sh
bash scripts/apply_storage_plan.sh
```

先读 `plan` 输出。低风险目标可以通过 apply wrapper 执行；被标记为 medium/high/exact_confirm/protected_session 的目标不会被 `--yes` 自动清理。

Read the `plan` output first. Low-risk targets can be handled by the apply wrapper; targets marked medium/high/exact_confirm/protected_session are not auto-cleaned by `--yes`.

### 检查 hidden-home，例如 `~/.git`
### Inspect hidden-home items such as `~/.git`

```bash
python3 scripts/mac_storage_manager.py audit --include-hidden-home --markdown
```

hidden-home 默认属于敏感范围。清理前必须先列清单，再传 exact `--approved-targets`，必要时再传 `--confirm-targets`。

hidden-home is sensitive by default. List it first, then pass exact `--approved-targets`; add `--confirm-targets` when required.

### 排查某个 App 的残留
### Inspect leftovers for one app

```bash
python3 scripts/mac_storage_manager.py audit \
  --app-path "/Applications/Example.app" \
  --markdown
```

App leftovers 属于高风险匹配结果，必须人工确认 target ID 后才能执行。

App leftovers are high-risk matches and require human confirmation of target IDs before apply.

### 限制 Flutter 工程扫描范围
### Limit Flutter project scanning

```bash
python3 scripts/mac_storage_manager.py audit \
  --flutter-search-root "$HOME/Projects" \
  --markdown
```

### 需要系统范围审计
### Audit system scope when needed

```bash
python3 scripts/mac_storage_manager.py audit \
  --include-system \
  --system-roots /Library,/private/var/db/receipts,/private/var/tmp,/tmp \
  --markdown
```

系统范围默认关闭，且 `--system-roots` 至少需要四个路径。不要把 `/` 当作清理目标。

System scope is disabled by default, and `--system-roots` requires at least four paths. Do not use `/` as a cleanup target.

## 安全模型
## Safety Model

<p align="center">
  <img src="assets/readme-workflow.svg" alt="Workflow from audit to plan to approve to apply to verify" width="100%">
</p>

### 命令阶段
### Command Stages

| 阶段 | 是否删除 | 作用 |
| --- | --- | --- |
| `audit` | 否 | 扫描并报告空间热点、目标、边界 |
| `plan` | 否 | 生成 exact cleanup candidates、blocked、out-of-scope、approval requirements |
| `clean --dry-run` | 否 | 走 clean 路径预演 |
| `clean --apply --yes --require-explicit-plan` | 是，只限低风险 | 执行低风险、可重建目标 |
| `clean --apply --approved-targets ID` | 是，限批准目标 | 执行中高风险 approved-plan 目标 |
| `clean --apply --approved-targets ID --confirm-targets ID` | 是，限双确认目标 | 执行 exact-confirm 目标 |
| `trace` | 否 | 追踪反复生成目录的触发源 |

| Stage | Deletes files | Purpose |
| --- | --- | --- |
| `audit` | No | Scans and reports storage hotspots, targets, and boundaries |
| `plan` | No | Builds exact cleanup candidates, blocked items, out-of-scope items, and approval requirements |
| `clean --dry-run` | No | Previews through the clean path |
| `clean --apply --yes --require-explicit-plan` | Yes, low-risk only | Applies low-risk, regenerable targets |
| `clean --apply --approved-targets ID` | Yes, approved targets only | Applies medium/high approved-plan targets |
| `clean --apply --approved-targets ID --confirm-targets ID` | Yes, double-confirmed targets only | Applies exact-confirm targets |
| `trace` | No | Traces sources for reappearing folders |

### 风险门禁
### Risk Gates

| 风险/保护 | 默认行为 | apply 条件 |
| --- | --- | --- |
| `low` / `normal` | 可计划 | `--yes` 足够 |
| `medium` / `high` / `approved_plan` | 阻断 | exact `--approved-targets TARGET_ID` |
| `exact_confirm` | 阻断 | exact `--approved-targets TARGET_ID` + `--confirm-targets TARGET_ID` |
| `protected_session` | 永久阻断 | 不提供普通确认绕过 |

| Risk/protection | Default behavior | Apply condition |
| --- | --- | --- |
| `low` / `normal` | Can be planned | `--yes` is enough |
| `medium` / `high` / `approved_plan` | Blocked | exact `--approved-targets TARGET_ID` |
| `exact_confirm` | Blocked | exact `--approved-targets TARGET_ID` + `--confirm-targets TARGET_ID` |
| `protected_session` | Always blocked | No normal confirmation bypass |

### 默认阻断范围
### Default Blocked Scope

- Downloads、Trash、Docker prune、hidden-home、app leftovers、system scope。
  Downloads, Trash, Docker prune, hidden-home, app leftovers, and system scope.
- 浏览器登录、cookie、session、token、keychain、credential material。
  Browser login, cookies, sessions, tokens, keychain, and credential material.
- 任何未进入 explicit plan 或不在 exact approved target list 中的目标。
  Any target not in the explicit plan or exact approved target list.

## 配置与参数
## Configuration & CLI Reference

### 主入口
### Main Entrypoints

```bash
python3 scripts/mac_storage_manager.py audit [options]
python3 scripts/mac_storage_manager.py plan [options]
python3 scripts/mac_storage_manager.py clean [options]
python3 scripts/mac_storage_manager.py trace --path <TARGET_PATH> --keyword <KEYWORD> [options]
```

### Wrapper 入口
### Wrapper Entrypoints

| Wrapper | 行为 |
| --- | --- |
| `scripts/audit_storage.sh` | 只运行 `audit --markdown` |
| `scripts/plan_storage.sh` | 只运行 `plan --markdown` |
| `scripts/apply_storage_plan.sh` | 推荐 apply 入口：`clean --apply --yes --require-explicit-plan --markdown` |
| `scripts/safe_clean.sh` | 兼容 shim；打印 deprecation 提示后转到 `apply_storage_plan.sh` |

| Wrapper | Behavior |
| --- | --- |
| `scripts/audit_storage.sh` | Runs only `audit --markdown` |
| `scripts/plan_storage.sh` | Runs only `plan --markdown` |
| `scripts/apply_storage_plan.sh` | Recommended apply entrypoint: `clean --apply --yes --require-explicit-plan --markdown` |
| `scripts/safe_clean.sh` | Compatibility shim; prints a deprecation warning and delegates to `apply_storage_plan.sh` |

Wrapper 不会自动切 profile、不会自动推断 target、不会扩大清理范围。

Wrappers do not switch profiles automatically, infer targets automatically, or broaden cleanup scope.

### Profile
### Profiles

| Profile | 默认 | 用途 |
| --- | --- | --- |
| `generic` | 是 | 开源通用 macOS 清理；不假定任何私有 repo 结构 |
| `repo-evidence` | 否 | opt-in repo 证据层；用于 repo references、generated evidence、historical indexes、route maps、manifests 等 |

| Profile | Default | Use |
| --- | --- | --- |
| `generic` | Yes | Open-source generic macOS cleanup; assumes no private repo structure |
| `repo-evidence` | No | Opt-in repo evidence layer for repo references, generated evidence, historical indexes, route maps, manifests, and similar material |

```bash
python3 scripts/mac_storage_manager.py audit --profile generic --markdown
python3 scripts/mac_storage_manager.py trace --profile repo-evidence --path "<TARGET_PATH>" --keyword "<KEYWORD>" --markdown
```

### 状态目录
### State Root

默认状态目录是：

The default state directory is:

```text
~/.mac-storage-manager/
```

当未显式传 `--receipt-dir` / `--backup-dir` 时，`--state-root PATH` 会作为 receipt 和 backup 的默认根目录：

When `--receipt-dir` / `--backup-dir` are not passed, `--state-root PATH` becomes the default root for receipts and backups:

```bash
python3 scripts/mac_storage_manager.py clean \
  --apply --yes --require-explicit-plan \
  --state-root "$HOME/.mac-storage-manager-demo" \
  --markdown
```

优先级：`--receipt-dir` / `--backup-dir` 高于 `--state-root`。

Precedence: `--receipt-dir` / `--backup-dir` override `--state-root`.

### 常用参数
### Common Options

| 参数 | 作用 |
| --- | --- |
| `--home PATH` | 指定 home，默认当前用户 home |
| `--root PATH` | 指定扫描根目录，默认等于 home |
| `--profile MODE` | 选择 `generic` 或 `repo-evidence` |
| `--state-root PATH` | 设置 receipt / backup 默认根目录 |
| `--days-to-keep N` | 全局保留天数，默认 7；target 级 `min_age_days` 可覆盖 |
| `--topk N` | 报告显示前 N 个空间热点，默认 5 |
| `--json` / `--markdown` | 输出格式 |
| `--include-hidden-home` | 纳入 hidden-home 目标 |
| `--include-system` | 纳入 system 目标 |
| `--system-roots A,B,C,D` | 覆盖 system roots，至少四个路径 |
| `--flutter-search-root PATH` | 限制 Flutter 工程搜索范围 |
| `--app-path PATH` | 扫描某个 `.app` 的残留 |
| `--approved-targets ID1,ID2` | exact approved target list |
| `--confirm-targets ID1,ID2` | exact-confirm target list |
| `--require-zero-hit WORD` | apply 后做 scoped residual validation |
| `--receipt-dir PATH` | 指定 cleanup receipt 输出目录 |
| `--backup-dir PATH` | 指定 backup manifest 输出目录 |
| `--apply` / `--dry-run` | clean 模式实际执行或预演 |
| `--yes` | 只放行 low-risk 目标 |
| `--require-explicit-plan` | apply 前强制执行 explicit plan gate |

| Option | Purpose |
| --- | --- |
| `--home PATH` | Set home; defaults to the current user home |
| `--root PATH` | Set scan root; defaults to home |
| `--profile MODE` | Choose `generic` or `repo-evidence` |
| `--state-root PATH` | Set the default receipt / backup root |
| `--days-to-keep N` | Global retention days, default 7; target-level `min_age_days` can override it |
| `--topk N` | Show top N consumers, default 5 |
| `--json` / `--markdown` | Output format |
| `--include-hidden-home` | Include hidden-home targets |
| `--include-system` | Include system targets |
| `--system-roots A,B,C,D` | Override system roots; at least four paths |
| `--flutter-search-root PATH` | Limit Flutter project search scope |
| `--app-path PATH` | Scan leftovers for one `.app` |
| `--approved-targets ID1,ID2` | Exact approved target list |
| `--confirm-targets ID1,ID2` | Exact-confirm target list |
| `--require-zero-hit WORD` | Run scoped residual validation after apply |
| `--receipt-dir PATH` | Set cleanup receipt output directory |
| `--backup-dir PATH` | Set backup manifest output directory |
| `--apply` / `--dry-run` | Execute or preview clean mode |
| `--yes` | Approve only low-risk targets |
| `--require-explicit-plan` | Enforce the explicit-plan gate before apply |

### 环境变量
### Environment Variables

| 变量 | 作用 |
| --- | --- |
| `MAC_STORAGE_SYSTEM_ROOTS` | 不传 `--system-roots` 时覆盖默认 system roots；逗号分隔 |

| Variable | Purpose |
| --- | --- |
| `MAC_STORAGE_SYSTEM_ROOTS` | Overrides default system roots when `--system-roots` is not passed; comma-separated |

## 报告怎么看
## How to Read Reports

核心输出字段保持稳定，方便人和自动化消费：

Core output fields stay stable for both humans and automation:

- `approved_targets`：本次 apply 明确批准的 target ID。
  `approved_targets`: exact target IDs approved for this apply run.
- `backup_manifest`：backup dir、touched-files manifest、sha256 manifest、复制数量和路径清单。
  `backup_manifest`: backup dir, touched-files manifest, sha256 manifest, copied count, and path list.
- `receipt`：cleanup receipt 的 Markdown/JSON 路径。
  `receipt`: Markdown/JSON cleanup receipt paths.
- `residual_validation`：`--require-zero-hit` 的 scoped 验证结果。
  `residual_validation`: scoped validation result for `--require-zero-hit`.
- `Cleaned / Planned`：每个 target 的 status、risk、source layer、protection、rollback、blocked reason。
  `Cleaned / Planned`: status, risk, source layer, protection, rollback, and blocked reason per target.

常见状态：

Common statuses:

| 状态 | 含义 |
| --- | --- |
| `planned` | 只读计划中，尚未删除 |
| `ready` | apply 模式下可执行 |
| `cleaned` | 已执行清理 |
| `blocked` | 被安全规则阻断 |
| `skipped` | 缺路径、缺工具或条件不满足 |
| `empty` | 没有可清理内容 |

| Status | Meaning |
| --- | --- |
| `planned` | Read-only plan, not deleted |
| `ready` | Eligible during apply mode |
| `cleaned` | Cleanup executed |
| `blocked` | Blocked by safety policy |
| `skipped` | Missing path, missing tool, or unmet condition |
| `empty` | Nothing eligible to clean |

## 隐私与可移植性
## Privacy & Portability

- `generic` 是默认 profile，适合开源使用；默认不会查找私有 repo 结构。
  `generic` is the default profile and is suitable for open-source use; it does not look for private repo structures by default.
- 报告、trace、receipt 和 JSON 会对 home/root/private absolute paths 做脱敏显示。
  Reports, trace output, receipts, and JSON redact home/root/private absolute paths in public display.
- `repo-evidence` 是显式 opt-in；只有你传 `--profile repo-evidence` 时才加入 repo/evidence/history 语义。
  `repo-evidence` is explicit opt-in; repo/evidence/history semantics are included only when you pass `--profile repo-evidence`.
- 不要把 receipt、backup manifest 或 trace 输出当作秘密存储；它们是复盘证据，不是保险箱。
  Do not treat receipts, backup manifests, or trace output as secret storage; they are review evidence, not a vault.

## 结构总览
## Structure Map

```text
scripts/mac_storage_manager.py     compatibility facade + CLI entry
scripts/_mac_storage_cli.py        argument parser + context builder
scripts/_mac_storage_core.py       data model, scanning, plan/apply engine, receipt/backup
scripts/_mac_storage_policy.py     single source of truth for risk, approval, retention policy
scripts/_mac_storage_render.py     Markdown/text/JSON report rendering
scripts/audit_storage.sh           read-only audit wrapper
scripts/plan_storage.sh            read-only plan wrapper
scripts/apply_storage_plan.sh      recommended apply wrapper
scripts/safe_clean.sh              deprecated compatibility shim
tests/                             regression and open-source contract tests
references/                        required cleanup routing references
```

工作链路：

How it works:

```text
CLI/wrapper -> StorageContext -> profile target discovery -> scan facts -> plan gate -> optional apply -> renderer + receipt
```

设计原则：

Design principles:

- 通用核心默认安全，repo/evidence 能力通过 profile 插拔。
  The generic core is safe by default; repo/evidence behavior is pluggable through profiles.
- 风险判定、retention、目标执行只保留一条 authoritative path。
  Risk decisions, retention, and target execution each have one authoritative path.
- Wrapper 只缩窄权限，不放大权限。
  Wrappers narrow permissions; they do not expand scope.
- `plan()` 是真实阶段；`clean()` 只消费已批准计划项。
  `plan()` is a real stage; `clean()` consumes only approved plan items.

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
python3 -m py_compile   scripts/mac_storage_manager.py   scripts/_mac_storage_cli.py   scripts/_mac_storage_core.py   scripts/_mac_storage_policy.py   scripts/_mac_storage_render.py   tests/test_mac_storage_manager.py   tests/test_mac_storage_open_source_contract.py

zsh -n scripts/audit_storage.sh
zsh -n scripts/plan_storage.sh
zsh -n scripts/apply_storage_plan.sh
zsh -n scripts/safe_clean.sh
```

### 贡献前检查
### Before Contributing

- 如果改 CLI flag，也同步更新 wrappers、README、SKILL.md 和 tests。
  If you change CLI flags, update wrappers, README, SKILL.md, and tests together.
- 如果改风险规则，只改 `_mac_storage_policy.py` 的 authoritative path，并补 gate matrix 测试。
  If you change risk rules, update the authoritative path in `_mac_storage_policy.py` and add gate matrix tests.
- 如果改输出字段，保持 Markdown/text/JSON renderer 语义一致。
  If you change output fields, keep Markdown/text/JSON renderer semantics aligned.
- 如果加入 repo-specific discovery，不要放进默认 `generic` profile。
  If you add repo-specific discovery, do not put it in the default `generic` profile.

## 常见问题
## FAQ

### 如果我没说“先列清单”，这个 skill 会不会直接清理？
### If I do not say “list first,” will this skill clean directly?

不会。skill 合同和 wrapper 入口都要求默认先 `audit` 或 `plan`。真正删除必须进入 `clean --apply`，并通过 `--yes` / `--approved-targets` / `--confirm-targets` 的门禁。

No. The skill contract and wrappers default to `audit` or `plan`. Deletion requires `clean --apply` plus the relevant `--yes` / `--approved-targets` / `--confirm-targets` gates.

### `safe_clean.sh` 还能用吗？
### Can I still use `safe_clean.sh`?

能，但它只是兼容 shim，会打印 deprecation 提示并转到 `apply_storage_plan.sh`。新用法请直接使用 `audit_storage.sh`、`plan_storage.sh` 和 `apply_storage_plan.sh`。

Yes, but it is only a compatibility shim. It prints a deprecation warning and delegates to `apply_storage_plan.sh`. New usage should call `audit_storage.sh`, `plan_storage.sh`, and `apply_storage_plan.sh` directly.

### `--yes` 是否会删除 Downloads 或 Trash？
### Does `--yes` delete Downloads or Trash?

不会。`--yes` 只对 low-risk 目标生效。Downloads、Trash、Docker、hidden-home、app leftovers、system scope 等需要 exact target approval，protected session 永久阻断。

No. `--yes` only applies to low-risk targets. Downloads, Trash, Docker, hidden-home, app leftovers, and system scope require exact target approval, while protected sessions stay blocked.

### 什么时候用 `repo-evidence`？
### When should I use `repo-evidence`?

只有当你明确要追踪 repo references、generated evidence、historical indexes、route maps、manifests 等项目证据层时才使用。普通 macOS 清理保持默认 `generic`。

Use it only when you explicitly need repo references, generated evidence, historical indexes, route maps, manifests, or similar project evidence layers. For ordinary macOS cleanup, keep the default `generic` profile.

### License
### License

MIT License. See `LICENSE`.

MIT License. See `LICENSE`.
