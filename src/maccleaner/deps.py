"""把内核能力装配成会话依赖（2026-10-18）。

`session.InteractiveSession` 只认"函数"，不认内核对象——这样测试能注入假实现，几秒跑完整条流程。
本模块就是**真实装配**的那一层，把这四件事接上：

    audit / plan / clean      → StorageManager（target 既有）
    uninstall_plan / apply    → uninstall 模块
    updates_check / apply     → updates 模块
    apps / history            → /Applications 扫一遍、读历史摘要

设计取舍（有意为之）：

- **列应用不算体积**：`_allocated_bytes` 要把 `.app` 整个走一遍，几十个应用会让列表页卡住；
  列表只给名字与 bundle-id，体积在"预览残留"那一页才算。
- **历史摘要读不到就返回空**：它是装饰性信息，不能因为文件缺失让落地页失败。
"""
from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path
from typing import Any

from .core import StorageContext, StorageManager
from .session import SessionDeps
from .uninstall import apply_plan, build_plan, read_app_identity
from .updates import apply_updates, build_upgrade_plan, discover_updates

SKIP_APP_NAMES = {"Safari.app", "Notes.app"}   # 系统自带、通常不希望出现在卸载列表里


def _context(home: Path, root: Path) -> StorageContext:
    return StorageContext(home=home, root=root)


def list_applications(*, home: Path | None = None, limit: int = 60) -> list[dict[str, Any]]:
    """列出用户级应用目录里的 `.app`（不含体积，理由见模块文档）。"""
    home_path = Path(home) if home is not None else Path.home()
    apps: list[dict[str, Any]] = []
    for base in (Path("/Applications"), home_path / "Applications"):
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.glob("*.app"))
        except OSError:
            continue
        for path in entries:
            if path.name in SKIP_APP_NAMES:
                continue
            identity = read_app_identity(path)
            apps.append(
                {
                    "name": identity.get("name") or path.stem,
                    "bundle_id": identity.get("bundle_id", ""),
                    "path": str(path),
                    "source": "system" if base == Path("/Applications") else "user",
                }
            )
            if len(apps) >= limit:
                return _with_sizes(apps)
    return _with_sizes(apps)


def _with_sizes(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """用一次 `du -sk` 批量补体积。

    为什么不在 Python 里逐个数：`.app` 动辄几 GB、几十万个小文件，逐个 `os.walk` 会让列表页卡住；
    `du` 是系统实现、一次调用就够。`du` 失败就留空——页面会显示"—"而不是假的 0。
    """
    if not apps:
        return apps
    try:
        completed = subprocess.run(
            ["/usr/bin/du", "-sk", *[str(app["path"]) for app in apps]],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return apps
    sizes: dict[str, int] = {}
    for line in (completed.stdout or "").splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip().isdigit():
            sizes[parts[1]] = int(parts[0]) * 1024
    for app in apps:
        app["allocated_bytes"] = sizes.get(str(app["path"]), 0)
    return apps


def history_summary(*, state_root: Path | None = None) -> dict[str, Any]:
    """落地页的"上次清理"摘要；读不到就返回空（装饰性信息不该拖垮页面）。"""
    root = Path(state_root) if state_root is not None else Path.home() / ".maccleaner" / "state"
    path = root / "history.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "total_runs": int(data.get("total_runs") or 0),
        "total_freed_bytes": int(data.get("total_freed_bytes") or 0),
    }


def build_deps(
    *,
    home: Path | None = None,
    root: Path | None = None,
    state_root: Path | None = None,
    dry_run: bool = False,
) -> SessionDeps:
    """真实装配。`dry_run=True` 时 clean 不落盘（给 `maccleaner ui --dry-run` 用）。"""
    home_path = Path(home) if home is not None else Path.home()
    root_path = Path(root) if root is not None else home_path
    state_path = Path(state_root) if state_root is not None else home_path / ".maccleaner" / "state"

    def manager() -> StorageManager:
        return StorageManager(_context(home_path, root_path))

    def report_of(mode: str) -> dict[str, Any]:
        instance = manager()
        if mode == "audit":
            return instance.audit().to_dict()
        if mode == "plan":
            return instance.plan().to_dict()
        return instance.clean().to_dict()

    def audit() -> dict[str, Any]:
        return report_of("audit")

    def plan() -> dict[str, Any]:
        return report_of("plan")

    def clean() -> dict[str, Any]:
        if dry_run:
            return report_of("plan")
        return report_of("clean")

    def uninstall_plan(*, app_path: str, bundle_id: str = "", app_name: str = "") -> dict[str, Any]:
        identity = read_app_identity(app_path)
        return build_plan(
            {
                "path": app_path,
                "bundle_id": bundle_id or identity.get("bundle_id", ""),
                "name": app_name or identity.get("name", ""),
                "home": str(home_path),
            },
            home=home_path,
        )

    def uninstall_apply(*, plan: dict[str, Any], ids: list[str]) -> dict[str, Any]:
        return apply_plan(plan, home=home_path, selected_ids=list(ids) or None, dry_run=dry_run)

    def updates_check() -> dict[str, Any]:
        return discover_updates()

    def updates_apply(*, ids: list[str]) -> dict[str, Any]:
        found = discover_updates()
        wanted = {str(value) for value in ids}
        selected = [
            item
            for index, item in enumerate(found["items"])
            # 页面传的是**索引**（`data-update-id`），这里用同一编号定位，避免页面知道包名以外的结构。
            if not wanted or str(index) in wanted
        ]
        return apply_updates(build_upgrade_plan(selected), dry_run=dry_run)

    return SessionDeps(
        audit=audit,
        plan=plan,
        clean=clean,
        history=lambda: history_summary(state_root=state_path),
        apps=lambda: list_applications(home=home_path),
        uninstall_plan=uninstall_plan,
        uninstall_apply=uninstall_apply,
        updates_check=updates_check,
        updates_apply=updates_apply,
    )


def read_manifest(repo_root: Path) -> dict[str, Any]:
    """读仓库根的 `manifest.json`（插件协议的自描述）；坏文件要抛错而不是给默认值。"""
    path = Path(repo_root) / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(f"{path} 缺少 id")
    return data


__all__ = ["build_deps", "history_summary", "list_applications", "read_manifest"]
