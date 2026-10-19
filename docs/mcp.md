# MacCleaner MCP

MacCleaner exposes a local stdio MCP server. It uses the same storage core as the CLI and never opens a network listener.

## Install

```bash
pipx install "maccleaner[mcp]"
```

Use this stdio command in an MCP client configuration:

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

## Tools

- `audit_storage`: read-only storage audit.
- `plan_storage`: read-only plan; returns `plan_id`, `plan_expires_at`, and `applicable_target_ids`.
- `trace_storage`: read-only source tracing for directories that reappear.
- `apply_storage_plan`: the only mutating tool for cleanup. Pass `plan_digest` (returned by
  `plan_storage`) to prove the plan being applied is the plan you showed the user; a mismatch is
  refused before anything is touched.
- `uninstall_plan`: read-only. Lists an app's leftovers (bundle id, container, name matches, system-level).
- `updates_check`: read-only. Lists third-party updates (Homebrew + App Store). macOS system updates are
  explicitly out of scope.
- `updates_apply`: upgrades the named packages (empty = all). Each group reports its own exit code, so one
  failing group does not hide the others.

## Calling tools

MCP clients render tools differently. These are tool name-and-argument examples, not raw JSON-RPC messages:

```json
{ "name": "audit_storage", "arguments": { "profile": "generic" } }
{ "name": "plan_storage", "arguments": { "profile": "generic" } }
```

Copy the returned `plan_id`, then select only IDs listed in `applicable_target_ids`:

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

Use `trace_storage` with `target_path` and `keyword` when a folder reappears. It is read-only.

## Apply Contract

1. Call `plan_storage` with the required scope.
2. Review `plan_items` and choose exact IDs from `applicable_target_ids`.
3. Call `apply_storage_plan` with the returned `plan_id`, non-empty `approved_targets`, and required `confirm_targets`.

The plan token is held only in the server process, expires after 15 minutes, and is consumed before execution. Do not restart `maccleaner-mcp` between planning and apply. The apply tool cannot accept new scan scope. It rescans before cleanup, blocks protected browser/session/credential data, and blocks every target outside `approved_targets`, including low-risk targets.

## Client configuration (copy-paste)

`maccleaner-mcp` speaks stdio only and needs the `mcp` extra:

```bash
pipx install "maccleaner[mcp]"        # or: pip install -e ".[mcp]" from a checkout
```

**Codex / Cursor / Claude Desktop** — same JSON shape, different file location:

```json
{
  "mcpServers": {
    "maccleaner": {
      "command": "maccleaner-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

If `maccleaner-mcp` is not on `PATH` (common when the app is launched from a GUI), point at the
interpreter instead — this is the most reliable form:

```json
{
  "mcpServers": {
    "maccleaner": {
      "command": "/usr/bin/env",
      "args": ["python3", "-m", "maccleaner.mcp_server"],
      "env": { "PYTHONPATH": "/path/to/MacCleaner/src" }
    }
  }
}
```

Where the file lives: Codex `~/.codex/config.toml` (use `[mcp_servers.maccleaner]` with
`command`/`args`), Cursor `~/.cursor/mcp.json`, Claude Desktop
`~/Library/Application Support/Claude/claude_desktop_config.json`.

### A minimal read-only session

```jsonc
{"name": "audit_storage", "arguments": {"profile": "generic"}}
{"name": "plan_storage",  "arguments": {"profile": "generic"}}   // returns plan_id + applicable_target_ids
// ...show the plan to the user, then:
{"name": "apply_storage_plan", "arguments": {
  "plan_id": "<from plan_storage>",
  "approved_targets": ["home-caches"],
  "plan_digest": "<optional: proves it is the plan you showed>"
}}
```

Nothing mutates until `apply_storage_plan`, and it refuses if `approved_targets` is empty or the
`plan_id` expired (15 minutes).

## Release

The repository release workflow uses PyPI Trusted Publishing. Before the first `v0.1.0` tag, create the `maccleaner` project on PyPI and configure its trusted publisher for GitHub repository `Matoya-Amadeus/MacCleaner`, workflow `.github/workflows/pypi-publish.yml`, and environment `pypi`.
