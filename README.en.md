# MacCleaner

![MacCleaner](assets/readme-header.svg)

> **Inspect first. Approve exact targets. Clean only what you selected.**
>
> MacCleaner audits macOS storage, builds an exact target list, and applies only items that pass the safety gates.

[中文](README.md) · [English](README.en.md)

<details>
<summary><strong>Recent notes</strong></summary>

Update time: 2026-07-12 00:28

Update content: Added an installable CLI, optional stdio MCP server, and one-time plan-token safety chain.

### 2026-05-19 21:20

Update content: Added the generic default profile, opt-in repo-evidence profile, protected-session blocking, receipts, backups, and post-cleanup residual validation.

</details>

## Contents

- [At a glance](#at-a-glance)
- [What it solves](#what-it-solves)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Common scenarios](#common-scenarios)
- [Safety boundaries](#safety-boundaries)
- [Configuration and options](#configuration-and-options)
- [Reading reports](#reading-reports)
- [Structure and workflow](#structure-and-workflow)
- [Developer notes](#developer-notes)
- [FAQ](#faq)

## At a glance

| Goal | Command | Result |
| --- | --- | --- |
| Inspect storage | `maccleaner audit --markdown` | Read-only scan |
| Build an exact plan | `maccleaner plan --markdown` | Lists planned, approval-needed, and blocked targets |
| Apply low-risk cleanup | `maccleaner clean --apply --yes --require-explicit-plan` | Applies only regenerable low-risk targets |
| Apply sensitive targets | Add `--approved-targets ID` | Applies only exact IDs you approved |

<details id="what-it-solves">
<summary><strong>What it solves</strong></summary>

When storage is full, the hard part is separating rebuildable caches from personal files, browser sessions, and system data.

The workflow is fixed:

```text
audit -> plan -> approve exact target IDs -> apply -> verify
```

</details>

<details id="installation">
<summary><strong>Installation</strong></summary>

Requirements: macOS and Python 3.10+. The base CLI has no third-party runtime dependency; MCP is an optional extra.

### CLI

```bash
pipx install maccleaner
maccleaner --help
```

Before the first PyPI release, install directly from GitHub:

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git"
```

### MCP

```bash
pipx install "maccleaner[mcp]"
maccleaner-mcp
```

Before the first PyPI release, use the GitHub version:

```bash
pipx install "git+https://github.com/Matoya-Amadeus/MacCleaner.git#egg=maccleaner[mcp]"
```

`maccleaner-mcp` uses stdio only. See the [MCP guide](docs/mcp.md) for client configuration and the plan-token apply flow.

### Codex Skill

The root `SKILL.md` remains the single skill source. In the Codex GitHub Skill installer, use repo `Matoya-Amadeus/MacCleaner`, path `.`, and install name `maccleaner`.

</details>

<details id="quick-start" open>
<summary><strong>Quick start</strong></summary>

### 1. Audit without changing files

```bash
maccleaner audit --markdown
```

### 2. Build the exact plan

```bash
maccleaner plan --markdown
```

Review `target_id`, `status`, `risk`, `protection`, and `reason`.

### 3. Apply low-risk cleanup

```bash
maccleaner clean --apply --yes --require-explicit-plan --markdown
```

This command changes files. Run `plan` first; the wrapper allows only low-risk, regenerable targets by default.

Sensitive targets require exact IDs from the current plan:

```bash
maccleaner plan --include-hidden-home --markdown
maccleaner clean --apply --yes --require-explicit-plan --markdown \
  --include-hidden-home \
  --approved-targets TARGET_ID
```

If the target is marked `exact_confirm`, also pass `--confirm-targets TARGET_ID`.

</details>

<details id="common-scenarios">
<summary><strong>Common scenarios</strong></summary>

Read-only output:

```bash
maccleaner audit --markdown
maccleaner audit --json
```

Trace a reappearing folder:

```bash
maccleaner trace \
  --path "<TARGET_PATH>" \
  --keyword "<KEYWORD>" \
  --markdown
```

Focus on an app or Flutter project:

```bash
maccleaner audit \
  --app-path "/Applications/Example.app" --markdown
maccleaner audit \
  --flutter-search-root "$HOME/Projects" --markdown
```

`trace` is read-only. Replace the example path and keyword with real values.

Source checkouts can still use `scripts/audit_storage.sh`, `scripts/plan_storage.sh`, and `scripts/apply_storage_plan.sh`; they are compatibility entry points.

</details>

<details id="safety-boundaries">
<summary><strong>Safety boundaries</strong></summary>

| Target | Default behavior |
| --- | --- |
| Ordinary caches, logs, and temporary files | Can be planned; `--yes` allows them during apply |
| Downloads, Trash, Docker, hidden-home, app leftovers, and system scope | Not cleaned automatically; exact approval is required |
| Browser login, cookies, sessions, tokens, Keychain, and credentials | Permanently blocked |
| Targets outside the current plan | Never executed |

`audit`, `plan`, and `trace` are read-only. `apply_storage_plan.sh` changes files. `safe_clean.sh` is only a deprecated compatibility shim.

MCP `apply_storage_plan` accepts no new scan-scope arguments. It requires the live `plan_id` from `plan_storage`, non-empty `approved_targets`, and any required `confirm_targets`. Each plan token is single-use.

</details>

<details id="configuration-and-options">
<summary><strong>Configuration and options</strong></summary>

- `--profile generic`: portable default; assumes no private repository layout.
- `--profile repo-evidence`: explicit opt-in for project evidence and historical-index tracing.
- `--state-root PATH`: default root for receipts and backups.
- `--receipt-dir PATH` / `--backup-dir PATH`: explicit directories; override `--state-root`.
- `--approved-targets ID1,ID2`: approve exact targets from the current plan.
- `--confirm-targets ID1,ID2`: extra confirmation for `exact_confirm` targets.
- `--include-hidden-home` / `--include-system`: widen the scan scope; off by default.
- `--app-path PATH` / `--flutter-search-root PATH`: focus the scan scope.
- `--json` / `--markdown`: choose the output format.
- `--apply` / `--dry-run` / `--yes`: control `clean` mode.

The default state directory is `~/.mac-storage-manager/`.

</details>

<details id="reading-reports">
<summary><strong>Reading reports</strong></summary>

- `target_id`: target identifier; copy it from the current plan for sensitive apply.
- `status`: states such as `planned`, `ready`, `blocked`, and `skipped`.
- `protection`: why approval, extra confirmation, or blocking applies.
- `backup_manifest`: backup and SHA-256 manifest when backups are needed.
- `receipt`: path to the Markdown/JSON cleanup receipt.

`empty` means there was nothing eligible to clean. Use `trace` when a target keeps reappearing.

</details>

<details id="structure-and-workflow">
<summary><strong>Structure and workflow</strong></summary>

```text
CLI/wrapper -> StorageContext -> profile discovery -> scan -> plan/gates
            -> optional apply -> renderer/receipt/residual validation
```

- `src/maccleaner/`: one canonical core plus CLI and MCP adapters.
- `scripts/mac_storage_manager.py`: legacy CLI compatibility facade.
- `scripts/_mac_storage_*.py`: legacy Python import-path shims.
- `scripts/*_storage.sh`: audit, plan, and apply wrappers for source checkouts.
- `tests/` and `references/`: regression tests and sensitive-case routing notes.

</details>

<details id="developer-notes">
<summary><strong>Developer notes</strong></summary>

```bash
python3 -m pip install ".[mcp]" build
python3 -m unittest discover -s tests -v
python3 -m build
```

Before the first PyPI release, configure `Matoya-Amadeus/MacCleaner` as a PyPI Trusted Publisher. Pushing tag `v0.1.0` verifies that the tag and package version match before publishing.

</details>

<details id="faq">
<summary><strong>FAQ</strong></summary>

### Will it clean directly if I do not say “list first”?

The recommended workflow does not skip the list: run `plan`, review it, then choose whether to run apply. Apply rescans and rechecks the risk and approval gates.

### Does `--yes` delete Downloads or Trash?

No. `--yes` allows only low-risk targets. Sensitive scopes require exact approval, while browser identity and credential data remain blocked.

### What if apply fails or frees little space?

Check `blocked`, `skipped`, `failed`, and `reason` in the report. `empty` is normal when nothing is eligible.

### Does MCP clean immediately?

No. MCP first returns a read-only `plan_storage` result and a short-lived `plan_id`. Apply requires that same token, exact target IDs, and any required confirmation; even unapproved low-risk targets stay blocked.

</details>

由 **AI·Maho** 和 **人类·Matoya** 共同维护
Maintained jointly by **AI·Maho** and **Human·Matoya**
