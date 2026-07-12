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
- `apply_storage_plan`: the only mutating tool.

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

## Release

The repository release workflow uses PyPI Trusted Publishing. Before the first `v0.1.0` tag, create the `maccleaner` project on PyPI and configure its trusted publisher for GitHub repository `Matoya-Amadeus/MacCleaner`, workflow `.github/workflows/pypi-publish.yml`, and environment `pypi`.
