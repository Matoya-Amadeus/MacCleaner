from __future__ import annotations

import json

from _mac_storage_core import StorageReport, TraceReport, human_bytes

def render_markdown(report: StorageReport) -> str:
    lines = [
        "# macOS Storage Report",
        "",
        "## Summary",
        f"- Mode: {report.mode}",
        f"- Free before: {human_bytes(report.before_free_bytes)}",
        f"- Free after: {human_bytes(report.after_free_bytes)}",
        f"- Estimated reclaimed: {human_bytes(report.estimated_reclaimed_bytes)}",
        f"- Actual reclaimed: {human_bytes(report.actual_reclaimed_bytes)}",
        f"- Approved targets: {', '.join(report.approved_targets) if report.approved_targets else 'none'}",
        "",
        "## Top Consumers",
    ]
    for index, item in enumerate(report.top_consumers[:5], start=1):
        lines.append(
            f"{index}. {item['name']} ({item['target_id']}) - {human_bytes(int(item['eligible_bytes']))} reclaimable "
            f"[layer={item.get('source_layer', 'runtime_artifact')} protection={item.get('protection', 'normal')}]"
        )
    if not report.top_consumers:
        lines.append("1. None")
    lines.extend(
        [
            "",
            "## Cleanup Boundary",
            "- Review the exact target list first.",
            "- Confirm exact targets before apply.",
            "- Cleanup must stay inside the approved target list and explicit confirmations.",
            "",
            "## Cleaned / Planned",
        ]
    )
    for item in report.plan_items:
        lines.append(
            f"- `{item.target_id}` [{item.status}] [{item.scope_status}] "
            f"layer={item.source_layer} protection={item.protection} rollback={item.rollback_strategy} - {item.reason}"
        )
    lines.extend(["", "## Backup / Receipt"])
    backup = report.backup_manifest or {}
    if backup.get("enabled"):
        lines.append(f"- Backup dir: {backup.get('backup_dir', '')}")
        lines.append(f"- Touched manifest: {backup.get('touched_manifest', '')}")
        lines.append(f"- SHA256 manifest: {backup.get('sha256_manifest', '')}")
        lines.append(f"- Copied small text files: {backup.get('copied_count', 0)}")
    else:
        lines.append("- Backup manifest: not required for this plan")
    if report.receipt:
        lines.append(f"- Receipt markdown: {report.receipt.get('markdown', '')}")
        lines.append(f"- Receipt json: {report.receipt.get('json', '')}")
    else:
        lines.append("- Receipt: not written in dry-run/audit mode")
    lines.extend(["", "## Residual Validation"])
    if report.residual_validation:
        for row in report.residual_validation:
            lines.append(
                f"- `{row.get('pattern', '')}` [{row.get('status', '')}] "
                f"hits={row.get('hit_count', 0)} command=`{row.get('command', '')}`"
            )
    else:
        lines.append("- No zero-hit validation patterns requested")
    lines.extend(
        [
            "",
            "## Remaining Hotspots",
        ]
    )
    remaining = [item for item in report.top_consumers if int(item["eligible_bytes"]) > 0]
    if remaining:
        for item in remaining[:5]:
            lines.append(f"- {item['name']}: {human_bytes(int(item['eligible_bytes']))}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Next Step Options",
            "1. Re-run `plan` or `audit` to review the exact list before any cleanup.",
            "2. Re-run with `--approved-targets <exact-target-ids>` and any required `--confirm-targets <exact-target-id>` after reviewing blocked targets.",
            "3. Narrow the scan with `--flutter-search-root`, `--app-path`, or `--include-hidden-home` for focused cleanup.",
        ]
    )
    return "\n".join(lines)


def render_trace_markdown(report: TraceReport) -> str:
    lines = [
        "# macOS Reappearing Target Trace",
        "",
        "## Summary",
        f"- Target path: `{report.target_path}`",
        f"- Keyword: `{report.keyword}`",
        f"- Findings: {report.summary.get('finding_count', 0)}",
        f"- Layer counts: {json.dumps(report.summary.get('layer_counts', {}), ensure_ascii=False)}",
        "",
        "## Findings",
    ]
    if not report.findings:
        lines.append("- None")
    for finding in report.findings:
        lines.append(
            f"- `{finding.source_layer}` / `{finding.source}` / `{finding.target_id or finding.path}`: "
            f"matched `{finding.matched}` — {finding.reason}; evidence: {finding.evidence}"
        )
    lines.extend(
        [
            "",
            "## Next Step Options",
            "1. Remove active triggers first; deleting the folder alone is not sufficient.",
            "2. Then clean runtime artifacts and repo references inside the explicit target list.",
            "3. Finish with scoped residual search and receipt evidence.",
        ]
    )
    return "\n".join(lines)


def render_trace_text(report: TraceReport) -> str:
    layers = ", ".join(f"{key}={value}" for key, value in report.summary.get("layer_counts", {}).items()) or "none"
    return (
        f"Trace findings: {report.summary.get('finding_count', 0)} for {report.keyword}. "
        f"Layers: {layers}. Next: remove active triggers before deleting runtime artifacts."
    )


def render_text(report: StorageReport) -> str:
    lines = [
        f"Root conclusion: {human_bytes(report.actual_reclaimed_bytes)} reclaimed, {human_bytes(report.estimated_reclaimed_bytes)} estimated.",
        f"Actions taken: {sum(1 for item in report.plan_items if item.status == 'cleaned')} cleaned, {sum(1 for item in report.plan_items if item.status == 'blocked')} blocked, {sum(1 for item in report.plan_items if item.status == 'skipped')} skipped.",
        f"Verification status: {'dry-run' if report.dry_run else 'applied'}.",
        f"Free space: {human_bytes(report.before_free_bytes)} -> {human_bytes(report.after_free_bytes)}.",
        f"Approved scope: {', '.join(report.approved_targets) if report.approved_targets else 'none'}.",
        f"Receipt: {report.receipt.get('markdown', 'not written') if report.receipt else 'not written'}.",
        "Next safe step: inspect the exact list first, then re-run with approved targets and explicit confirmations only.",
    ]
    return "\n".join(lines)
