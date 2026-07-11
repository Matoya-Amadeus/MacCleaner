from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from _mac_storage_core import ExplicitPlanRequiredError, PROFILES, StorageContext, StorageManager
from _mac_storage_render import render_markdown, render_text, render_trace_markdown, render_trace_text

def _parse_csv(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return frozenset(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit and clean macOS storage safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--home", default=str(Path.home()))
        p.add_argument("--root", default="")
        p.add_argument("--profile", choices=sorted(PROFILES), default="generic")
        p.add_argument("--state-root", default="")
        p.add_argument("--days-to-keep", type=int, default=7)
        p.add_argument("--confirm-targets", default="")
        p.add_argument("--approved-targets", default="")
        p.add_argument("--require-zero-hit", action="append", default=[])
        p.add_argument("--receipt-dir", default="")
        p.add_argument("--backup-dir", default="")
        p.add_argument("--flutter-search-root", default="")
        p.add_argument("--app-path", default="")
        p.add_argument("--include-system", action="store_true")
        p.add_argument("--include-hidden-home", action="store_true")
        p.add_argument("--json", action="store_true")
        p.add_argument("--markdown", action="store_true")

    audit = sub.add_parser("audit", help="Scan and report without changing files")
    add_common(audit)
    audit.add_argument("--topk", type=int, default=5)

    plan = sub.add_parser("plan", help="Build a cleanup plan without changing files")
    add_common(plan)
    plan.add_argument("--topk", type=int, default=5)

    clean = sub.add_parser("clean", help="Run the plan and clean eligible targets")
    add_common(clean)
    clean.add_argument("--apply", action="store_true")
    clean.add_argument("--yes", action="store_true")
    clean.add_argument("--dry-run", action="store_true")
    clean.add_argument("--require-explicit-plan", action="store_true")
    clean.add_argument("--topk", type=int, default=5)

    trace = sub.add_parser("trace", help="Trace repeated regeneration sources for a target")
    add_common(trace)
    trace.add_argument("--path", required=True)
    trace.add_argument("--keyword", required=True)
    trace.add_argument("--topk", type=int, default=20)
    return parser


def _context_from_args(args: argparse.Namespace) -> StorageContext:
    home = Path(args.home).expanduser().resolve()
    root = Path(args.root).expanduser().resolve() if args.root else home
    flutter_root = Path(args.flutter_search_root).expanduser().resolve() if args.flutter_search_root else None
    app_path = Path(args.app_path).expanduser().resolve() if args.app_path else None
    receipt_dir = Path(args.receipt_dir).expanduser().resolve() if args.receipt_dir else None
    backup_dir = Path(args.backup_dir).expanduser().resolve() if args.backup_dir else None
    state_root = Path(args.state_root).expanduser().resolve() if getattr(args, "state_root", "") else None
    require_zero_hit = tuple(
        part.strip()
        for value in getattr(args, "require_zero_hit", [])
        for part in str(value).split(",")
        if part.strip()
    )
    return StorageContext(
        home=home,
        root=root,
        days_to_keep=int(args.days_to_keep),
        dry_run=bool(getattr(args, "dry_run", False) or args.command in {"audit", "plan", "trace"}),
        apply=bool(getattr(args, "apply", False)),
        yes=bool(getattr(args, "yes", False)),
        include_system=bool(args.include_system),
        confirm_targets=_parse_csv(args.confirm_targets),
        approved_targets=_parse_csv(getattr(args, "approved_targets", "")),
        require_zero_hit=require_zero_hit,
        include_hidden_home=bool(getattr(args, "include_hidden_home", False)),
        flutter_search_root=flutter_root,
        app_path=app_path,
        receipt_dir=receipt_dir,
        backup_dir=backup_dir,
        profile=str(getattr(args, "profile", "generic")),
        state_root=state_root,
        require_explicit_plan=bool(getattr(args, "require_explicit_plan", False)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = _context_from_args(args)
    manager = StorageManager(ctx)

    if args.command == "trace":
        trace_report = manager.trace(Path(args.path), str(args.keyword))
        if getattr(args, "json", False):
            print(json.dumps(trace_report.to_dict(), ensure_ascii=False, indent=2))
        elif getattr(args, "markdown", False):
            print(render_trace_markdown(trace_report))
        else:
            print(render_trace_text(trace_report))
        return 0

    try:
        if args.command == "audit":
            report = manager.audit()
        elif args.command == "plan":
            report = manager.plan()
        else:
            report = manager.clean() if ctx.apply and not ctx.dry_run else manager.audit()
    except ExplicitPlanRequiredError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif getattr(args, "markdown", False):
        print(render_markdown(report))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
