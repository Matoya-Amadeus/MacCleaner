---
name: "mac-cleaner"
description: "Audit and manage macOS disk usage safely with staged cleanup, explicit target approval, and generic-by-default open-source behavior. Use when the request clearly belongs to disk cleanup, cache cleanup, large-file triage, or reappearing storage artifacts."
---

# MacCleaner

## Trigger

Use this skill when the user asks to clean disk space, free storage, find large files, remove caches/logs/temp artifacts, reduce macOS storage pressure, or diagnose a folder/app/cache that reappears after deletion.

## First-principles contract

- Default to read-only `audit` or `plan`; never jump directly to apply.
- Cleanup is target-based: every action must map to an exact `target_id`.
- Execution may only consume the approved plan; it must not infer extra targets at apply time.
- Prefer regenerable data first: caches, logs, temp files, build outputs, and old tool downloads.
- Never delete personal documents, media, Downloads, Trash, hidden-home folders, Docker/VM data, app leftovers, system paths, or browser/session material from a broad request.
- Browser identity/session/credential material is `protected_session` and must stay blocked by default.
- User-facing numbered choices are not approval; resolve them back to exact target IDs before apply.

## Profiles

- `generic` is the default and is suitable for open-source use.
  - It audits generic macOS storage targets only.
  - It does not assume any private repo layout, historical evidence folders, route maps, or memory graph paths.
- `repo-evidence` is opt-in.
  - Use it only when the user explicitly asks to inspect repo references, generated evidence, historical indexes, route maps, manifests, or similar project-specific trace material.
  - When this profile is used, the operator must follow `references/historical-index-cleanup.md`.

CLI flags:

```bash
maccleaner audit --profile generic --markdown
maccleaner trace --profile repo-evidence --path <target-path> --keyword <word>
```

For a source checkout, `python3 scripts/mac_storage_manager.py ...` and the shell wrappers remain compatible. Install the optional local stdio MCP adapter with `pipx install "maccleaner[mcp]"`; it starts as `maccleaner-mcp`.

## Required reference routing

- Reappearing folder, old workspace, container, or cache: must follow `references/reappearing-folder-cleanup.md`.
- Browser/session/login/cookie/keychain/credential data: must follow `references/protected-browser-session.md`.
- Hidden home folders, container UUIDs, ownership mismatch, or root-owned cache entries: must follow `references/hidden-home-cleanup.md`.
- Repo/evidence/history cleanup: allowed only with `--profile repo-evidence` and must follow `references/historical-index-cleanup.md`.

## Workflow

1. Clarify the target path, keyword, and whether generic or `repo-evidence` profile is intended.
2. If a folder reappears, run `maccleaner trace --profile <profile> --path <target-path> --keyword <word>` and remove `active_trigger` causes first.
3. Run `maccleaner audit --markdown` for read-only audit or `maccleaner plan --markdown` for an exact cleanup plan.
4. List each cleanup candidate with `target_id`, `source_layer`, protection level, rollback strategy, blocked items, and explicit out-of-scope items.
5. Build and echo the exact approved target list before apply.
6. Apply only through `maccleaner clean --apply --yes --require-explicit-plan --approved-targets <ids> ...`; `scripts/safe_clean.sh` is a deprecated compatibility shim.
7. Re-audit after apply and use `--require-zero-hit <pattern>` when the task was keyword/path based.

## Capabilities beyond cleanup

Four surfaces share one set of protection rules (protected paths stay blocked; no bypass flag exists):

- **Uninstall** — `maccleaner uninstall --app-path <app>` lists leftovers only (bundle item, sandbox
  container, exact/name matches, system-level). `--apply` moves the selected user-scope items to Trash;
  `--ids` restricts to plan item ids, so the caller cannot swap paths. System-level leftovers require
  `--accept-admin` (one admin prompt) and are never touched implicitly.
- **Updates** — `maccleaner updates` lists third-party updates (Homebrew formulae/casks + App Store via
  `mas`) and never touches macOS system updates. Default is read-only; `--apply [--only a,b]` upgrades the
  named items only, and each executable group reports its own exit code.
- **Local UI** — `maccleaner ui` serves a temporary page on `127.0.0.1` and prints a one-time
  `/bootstrap/<secret>` link (invalid after first use). Every action needs a cookie + header credential
  pair plus an Origin check; only one session may run at a time (flock).
- **MCP** — `uninstall_plan`, `updates_check`, `updates_apply` join the existing tools. `apply_storage_plan`
  accepts `plan_digest`; a mismatch between the approved plan and the plan being applied is refused before
  anything is touched.

## Confirmation semantics

- Generic `--yes` can approve only low-risk targets.
- Medium/high-risk cleanup requires exact `--approved-targets <target_id>`.
- Targets with `exact_confirm` also require exact `--confirm-targets <target_id>`.
- Protected session targets stay blocked; do not offer a normal confirmation bypass.
- Category-level confirmation is allowed only for low-risk targets.
- Apply wrappers must not add targets, change profile, or broaden scope.
- MCP `apply_storage_plan` requires the live `plan_id` returned by MCP `plan_storage`, non-empty exact `approved_targets`, and required `confirm_targets`; it cannot accept new scan-scope parameters.
- A MCP plan token expires after 15 minutes and is consumed before execution. Unapproved low-risk targets are blocked as strictly as high-risk targets.
- Uninstall apply takes `selected_ids` from the rendered plan; ids that are not in the frozen plan are ignored,
  and an empty selection is refused rather than treated as "all".

## Source layers and protections

- `active_trigger`: launch agents/daemons, Docker containers, shell startup, scheduled launchers.
- `runtime_artifact`: caches, logs, temp files, build outputs, app runtime leftovers.
- `repo_reference`: repo scripts/configs/docs that can recreate or preserve a target; opt-in via `repo-evidence` where applicable.
- `historical_index`: metrics, audit receipts, graph JSONL, SBOM/provenance, route maps, generated snapshots; opt-in via `repo-evidence`.
- `user_data`: Downloads, Trash, media, documents, hidden home folders.
- `protected_session`: browser identity/session/cookie/login/token/key material.

Protection levels:

- `normal`: low-risk, regenerable cleanup.
- `exact_confirm`: needs exact `--confirm-targets`.
- `approved_plan`: needs exact `--approved-targets`.
- `blocked`: never cleaned by default.

## Output contract

Provide:

- Root conclusion and mode (`audit`, `plan`, `clean`, or `trace`).
- Top space consumers.
- Exact approved cleanup list.
- Source layer, protection level, rollback strategy, and status for every target.
- What was cleaned or planned.
- Backup manifest and cleanup receipt path for apply runs.
- Residual validation status for any `--require-zero-hit` pattern.
- Estimated reclaimed bytes and actual reclaimed bytes.
- Free before/after.
- Residual hotspots and next safe options.

## Open-source operating rules

- Treat this `SKILL.md`, the repo `README.md`, and `references/quality-gate-checklist.md` as the authoritative operating contract.
- Keep the default behavior generic and portable; do not add private repo assumptions, hardcoded user paths, or organization-specific defaults.
- Keep wrappers, CLI flags, renderer output, and tests semantically aligned; if one changes, update the others in the same patch.
- Preserve bounded execution: apply only the explicit approved scope, never inferred extra targets.
