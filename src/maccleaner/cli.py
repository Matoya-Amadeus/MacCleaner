from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .core import ExplicitPlanRequiredError, PROFILES, StorageContext, StorageManager
from .render import render_markdown, render_text, render_trace_markdown, render_trace_text

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

    uninstall = sub.add_parser("uninstall", help="List an app's leftover files (read-only)")
    add_common(uninstall)
    uninstall.add_argument("--bundle-id", default="")
    uninstall.add_argument("--app-name", default="")
    uninstall.add_argument("--apply", action="store_true", help="actually move the selected items to Trash")
    uninstall.add_argument("--ids", default="", help="comma separated plan item ids (default: all user-scope items)")
    uninstall.add_argument("--accept-admin", action="store_true", help="also remove system-level leftovers (asks for admin once)")

    ui = sub.add_parser("ui", help="Open the local UI (loopback page, one session at a time)")
    add_common(ui)
    ui.add_argument("--no-open", action="store_true", help="print the URL instead of opening a browser")
    ui.add_argument("--dry-run", action="store_true", help="rehearse cleanup without touching files")

    updates = sub.add_parser("updates", help="List third-party updates (brew/mas); --apply to install")
    add_common(updates)
    updates.add_argument("--apply", action="store_true", help="actually run the upgrades (default: dry-run)")
    updates.add_argument("--only", default="", help="comma separated names / app ids to upgrade")

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

    if args.command == "ui":
        # 2026-10-22：本地网页 UI 已随原生界面迁移一起删除（见 docs/plan-2026-10-native.md）。
        # 这里保留 `maccleaner ui` 只是为了让老习惯能用——它现在**打开原生 App**。
        app = _native_app_path()
        if app is None:
            print(
                "原生界面还没构建：先跑\n"
                "  bash scripts/build_core.sh\n"
                "  bash scripts/build_native.sh --run\n"
                "（旧版 `maccleaner ui` 的本地网页已移除）",
                file=sys.stderr,
            )
            return 2
        if args.no_open:
            print(str(app), flush=True)
            return 0
        import subprocess as _subprocess

        _subprocess.Popen(["open", str(app)])
        print(f"已打开 {app}", flush=True)
        return 0

    if args.command == "updates":
        from .updates import (
            apply_updates,
            build_upgrade_plan,
            discover_updates,
            render_updates_text,
            select_updates,
        )

        found = discover_updates()
        wanted = {part.strip() for part in str(getattr(args, "only", "") or "").split(",") if part.strip()}
        selected = select_updates(found["items"], wanted)

        # `--only` 一个都没匹配到：必须明确报错并退出非 0，而不是把**全量列表**打出来 ——
        # 否则用户会以为"点了名的那些"就是屏幕上这些（2026-10-19 真机撞到过）。
        if wanted and not selected:
            print(f"没有匹配到：{', '.join(sorted(wanted))}", file=sys.stderr)
            return 2

        plan = build_upgrade_plan(selected)
        applied = None
        if getattr(args, "apply", False):
            if not plan["groups"]:
                print("没有可升级项。", file=sys.stderr)
                return 2
            applied = apply_updates(plan, dry_run=False)

        view = {**found, "items": selected, "count": len(selected)} if wanted else found
        if getattr(args, "json", False):
            payload = {
                **view,
                "selected": plan["count"],
                "commands": [group["command"] for group in plan["groups"]],
            }
            if applied is not None:
                payload["applied"] = applied
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_updates_text(view, applied=applied))
        return 0

    if args.command == "uninstall":
        from .uninstall import build_plan, read_app_identity, render_plan_text, summarize

        app_path = str(getattr(args, "app_path", "") or "").strip()
        if not app_path:
            print("uninstall 需要 --app-path（例如 /Applications/Foo.app）", file=sys.stderr)
            return 2
        identity = read_app_identity(app_path)
        bundle_id = str(getattr(args, "bundle_id", "") or identity.get("bundle_id", ""))
        app_name = str(getattr(args, "app_name", "") or identity.get("name", ""))
        plan = build_plan(
            {"path": app_path, "bundle_id": bundle_id, "name": app_name, "home": ctx.home},
            home=ctx.home,
        )
        if not getattr(args, "apply", False):
            if getattr(args, "json", False):
                print(json.dumps({**summarize(plan), "items": plan["items"], "system_items": plan["system_items"]},
                                 ensure_ascii=False, indent=2))
            else:
                print(render_plan_text(plan))
            return 0

        from .uninstall import apply_plan, apply_system_leftovers

        ids = [part.strip() for part in str(getattr(args, "ids", "") or "").split(",") if part.strip()]
        result = apply_plan(plan, home=ctx.home, selected_ids=ids or None)
        if getattr(args, "accept_admin", False) and plan.get("system_items"):
            result["system"] = apply_system_leftovers([item["path"] for item in plan["system_items"]])
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"卸载 {result['status']}：移入废纸篓 {result['moved_count']} 项"
                  + (f"，跳过 {len(result['skipped'])} 项" if result.get("skipped") else "")
                  + (f"，失败 {result['failed_count']} 项" if result.get("failed_count") else ""))
            for item in result.get("moved") or []:
                print(f"  -> {item['trash_path']}")
        return 0 if result["status"] in {"applied", "dry-run"} else 1

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


def _native_app_path() -> Path | None:
    """找原生 App：先看环境变量，再看仓库构建产物，最后看 ~/Applications 的安装版。"""
    candidates: list[Path] = []
    env = os.environ.get("MACCLEANER_APP")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(Path("build/native/MacCleaner.app"))
    candidates.append(Path.home() / "Applications" / "MacCleaner.app")
    for path in candidates:
        if path.exists():
            return path.resolve()
    return None


if __name__ == "__main__":
    raise SystemExit(main())
