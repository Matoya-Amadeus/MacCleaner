# Reappearing Folder Cleanup

Use this reference when a folder, old app workspace, container, or cache returns after deletion.

## Required sequence

1. Treat the path as a symptom, not the root cause.
2. Run `mac_storage_manager.py trace --path <target-path> --keyword <keyword>`.
3. Classify every finding by `source_layer`:
   - `active_trigger`: LaunchAgents/Daemons, Docker containers, shell startup, scheduled launchers.
   - `runtime_artifact`: the folder/cache/container data itself.
   - `repo_reference`: scripts, rules, IDE history, route maps, config.
   - `historical_index`: audit receipts, metrics, graph JSONL, SBOM/provenance, generated snapshots.
4. Remove or disable `active_trigger` entries before deleting runtime artifacts.
5. Back up any high-risk, repo-reference, or historical-index touched file before apply.
6. Finish with scoped residual search (`--require-zero-hit <keyword>`) and a cleanup receipt.

## Non-goals

- Do not run broad system cleanup to solve a single reappearing folder.
- Do not delete browser/session/credential data while tracing old workspace references.
