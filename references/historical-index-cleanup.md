# Historical Index Cleanup

Use this reference when old project names remain in generated repo evidence after runtime files are gone.

## Historical index families

- `manifests/**`
- `reports/**`
- `graph/**`
- `knowledge/**`
- `config/**`
- route maps, alias maps, test snapshots, eval outputs, generated reports, and other structured repo evidence

## Required behavior

1. Scope by explicit keyword/path; never perform a repo-wide fuzzy deletion without a target.
2. Dry-run or trace first and list exact files.
3. Back up touched files and write sha256 manifests before apply.
4. Regenerate dependent route maps or eval suites when removal changes structured topics.
5. Validate with scoped residual search and relevant config/schema/unit gates.
