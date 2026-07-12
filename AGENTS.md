# MacCleaner Contributor Rules

## Canonical implementation

- Keep `src/maccleaner/` as the only implementation source for core, policy, render, CLI, and MCP behavior.
- Keep `scripts/` as compatibility facades only; do not duplicate cleanup policy or execution logic there.
- Preserve the public CLI commands: `audit`, `plan`, `clean`, and `trace`.

## Safety contract

- `audit`, `plan`, and `trace` are read-only.
- CLI cleanup keeps the existing explicit approval and confirmation gates.
- MCP is stdio-only. `apply_storage_plan` must require a live, one-time `plan_id`, non-empty exact `approved_targets`, and required `confirm_targets`.
- MCP apply must retain strict scope: do not execute any target outside `approved_targets`, including low-risk targets.
- Browser identity, sessions, credentials, and other `protected_session` targets stay blocked.

## Change and release checks

- Update `README.md`, `README.en.md`, `SKILL.md`, and tests whenever public CLI or MCP behavior changes.
- Run `python3 -m unittest discover -s tests -v`, `python3 -m build`, and `git diff --check` before release work.
- Keep PyPI release tags aligned with `pyproject.toml` package version and use the Trusted Publisher workflow.
