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

import hashlib
import json
import os
import plistlib
import subprocess
import time
from pathlib import Path
from typing import Any

from .core import StorageContext, StorageManager
from .session import SessionDeps
from .uninstall import apply_plan, build_plan, read_app_identity
from .updates import apply_updates, build_upgrade_plan, discover_updates

SKIP_APP_NAMES = {"Safari.app", "Notes.app"}   # 系统自带、通常不希望出现在卸载列表里


def _context(home: Path, root: Path, **overrides: Any) -> StorageContext:
    return StorageContext(home=home, root=root, **overrides)


def list_applications(
    *, home: Path | None = None, limit: int = 60, with_sizes: bool = False
) -> list[dict[str, Any]]:
    """列出用户级应用目录里的 `.app`。

    **默认不算体积**（2026-10-19 实测：50 个 app 用 `du -sk` 要 6.3s、用 `_allocated_bytes` 要 12.3s，
    共 32 GiB；用户看到的就是"正在读取应用列表"卡住）。体积在**点开某个应用**时再算——
    单个应用实测 0.1–0.5s，而且那时才真的有用。
    """
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
                return _with_sizes(apps) if with_sizes else apps
    return _with_sizes(apps) if with_sizes else apps


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


def history_report(
    *, home: Path, state_root: Path | None = None, limit: int = 20
) -> dict[str, Any]:
    """最近的清理回执（只读）。

    为什么读回执而不是另写 `history.json`：回执是**执行时**就落盘的证据，
    再造一份计数状态就有两个真相源，迟早对不上（`history.json` 现在根本没人写）。

    回执目录有两处：状态目录下的 `receipts/`，以及内核默认的 `~/.mac-storage-manager/receipts/`。
    """
    home = Path(home)
    directories = [home / ".mac-storage-manager" / "receipts"]
    if state_root is not None:
        directories.insert(0, Path(state_root) / "receipts")

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.glob("cleanup-receipt-*.json"):
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            items = [item for item in (data.get("plan_items") or []) if isinstance(item, dict)]
            cleaned = [item for item in items if str(item.get("status")) == "cleaned"]
            entries.append(
                {
                    "created_at": str(data.get("created_at") or ""),
                    "mode": str(data.get("mode") or ""),
                    "dry_run": bool(data.get("dry_run")),
                    "items": len(cleaned),
                    "bytes": int(data.get("actual_reclaimed_bytes") or 0),
                    "estimated": int(data.get("estimated_reclaimed_bytes") or 0),
                    "file": str(path),
                }
            )

    entries.sort(key=lambda item: item["created_at"], reverse=True)
    kept = entries[: max(1, limit)]
    return {
        "entries": kept,
        "runs": len(entries),
        "total_bytes": sum(int(item["bytes"]) for item in kept),
        "total_items": sum(int(item["items"]) for item in kept),
    }


SCAN_CACHE_SECONDS = 300


def _cache_path(state_root: Path) -> Path:
    return state_root / "scan-cache.json"


def _watched_paths(report: dict[str, Any]) -> list[str]:
    """把报告里出现的目标路径当作"变化信号"。

    缓存必须能自己判断"过期"，而判断依据只能来自上次扫描看到的路径——
    所以把路径连同结果一起存，下次先 stat 这些路径的 mtime。
    """
    paths: list[str] = []
    for item in report.get("plan_items") or []:
        for raw in item.get("paths") or []:
            if isinstance(raw, str) and raw:
                paths.append(raw)
    return sorted(set(paths))


def _signature(paths: list[str], home: Path) -> str:
    """把 `~/...` 按**本次扫描的 home** 展开后再取 mtime。

    踩过的坑：用 `os.path.expanduser` 会展开成真实家目录，于是临时 home 的缓存永远"有效"——
    路径变了也不重扫（用例当场抓到）。
    """
    parts: list[str] = []
    for raw in paths:
        if raw.startswith("~/"):
            candidate = home / raw[2:]
        else:
            candidate = Path(os.path.expanduser(raw))
        try:
            stamp = int(candidate.stat().st_mtime)
        except OSError:
            stamp = -1
        parts.append(f"{raw}:{stamp}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def scan_report(
    *,
    home: Path,
    root: Path,
    state_root: Path,
    force: bool = False,
    ttl_seconds: int = SCAN_CACHE_SECONDS,
) -> dict[str, Any]:
    """带磁盘缓存的扫描。

    为什么要缓存：全盘扫描实测 **24.7s**（`~/Downloads` 5.5 GiB 占大头）。用户点两次就要等两次。
    但缓存必须诚实：**TTL 到期或目标路径 mtime 变化就重扫**，并把"这份数据是什么时候扫的"带回给页面，
    页面上明写时间、且【重新扫描】永远强制重扫。
    """
    cache_file = _cache_path(state_root)
    disabled = os.environ.get("MACCLEANER_SCAN_CACHE", "1") == "0"
    if not disabled and not force:
        try:
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entry = None
        if isinstance(entry, dict):
            age = time.time() - float(entry.get("scanned_at") or 0)
            paths = entry.get("paths") or []
            if age <= ttl_seconds and _signature(paths, home) == entry.get("signature"):
                report = entry.get("report") or {}
                if isinstance(report, dict):
                    return {**report, "scan_cached_at": float(entry.get("scanned_at") or 0)}

    # 扫描会遍历整个主目录；系统调用可能被信号打断（实测 `InterruptedError: [Errno 4]`，
    # 发生在 `rglob` 里），一次重试就能过去——总比让用户看到"出错了，可以重试"要好。
    last_error: BaseException | None = None
    report: dict[str, Any] = {}
    for attempt in range(2):
        try:
            report = StorageManager(StorageContext(home=home, root=root)).audit().to_dict()
            break
        except InterruptedError as exc:      # noqa: PERF203 - 只重试一次
            last_error = exc
            if attempt == 1:
                raise
    if last_error is not None and not report:
        raise last_error
    if not disabled:
        entry = {
            "scanned_at": time.time(),
            "paths": _watched_paths(report),
            "signature": _signature(_watched_paths(report), home),
            "report": report,
        }
        try:
            state_root.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, cache_file)
        except OSError:
            pass
    return {**report, "scan_cached_at": 0.0}



def _reveal(path: str) -> None:
    """在 Finder 中选中该路径（`open -R`）。"""
    subprocess.run(["/usr/bin/open", "-R", path], check=False)


def _open_trash(home: Path) -> None:
    """在 Finder 里打开废纸篓（扫描 home 下的 .Trash，没有就开用户的）。"""
    candidate = Path(home) / ".Trash"
    target = candidate if candidate.is_dir() else Path.home() / ".Trash"
    subprocess.run(["/usr/bin/open", str(target)], check=False)

DISK_SECTIONS: tuple[str, ...] = (
    "Desktop",
    "Documents",
    "Downloads",
    "Movies",
    "Music",
    "Pictures",
    "Library/Caches",
)


def _du_sizes(paths: list[Path], *, timeout: float = 8.0) -> dict[str, int]:
    """一次 `du -sk` 批量取体积；超时就用已经拿到的部分（不让页面卡住）。

    逐个 `os.walk` 在 Downloads/Pictures 这种目录上会卡十几秒（2026-10-19 实测），
    而 `du` 是系统实现；超时时 `TimeoutExpired.stdout` 里仍有已完成行。
    """
    existing = [str(path) for path in paths if path.exists()]
    if not existing:
        return {}
    argv = ["/usr/bin/du", "-sk", *existing]
    stdout = ""
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        stdout = completed.stdout or ""
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return {}
    sizes: dict[str, int] = {}
    for line in stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip().isdigit():
            sizes[parts[1]] = int(parts[0]) * 1024
    return sizes


def disk_report(*, home: Path) -> dict[str, Any]:
    """磁盘概览：整体容量 + 常用目录体积（只读）。"""
    import shutil as _shutil

    usage = _shutil.disk_usage(str(home))
    paths = [Path(home) / name for name in DISK_SECTIONS]
    sizes = _du_sizes(paths)
    sections = [
        {"name": name, "bytes": sizes.get(str(Path(home) / name), 0)}
        for name in DISK_SECTIONS
    ]
    sections.sort(key=lambda item: -int(item["bytes"]))
    return {
        "total": int(usage.total),
        "used": int(usage.used),
        "free": int(usage.free),
        "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        "sections": sections,
    }


def _memory_bytes() -> tuple[int, int]:
    """(总量, 已用) 字节。用 `sysctl hw.memsize` + `vm_stat`，不依赖 psutil。"""
    total = 0
    try:
        total = int(
            subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            .stdout.strip() or 0
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        total = 0
    used = 0
    try:
        out = subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=5).stdout
        page = 4096
        stats: dict[str, int] = {}
        for line in out.splitlines():
            if "page size of" in line:
                digits = "".join(ch for ch in line if ch.isdigit())
                page = int(digits) if digits else page
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            number = value.strip().rstrip(".").replace(".", "")
            if number.isdigit():
                stats[key.strip()] = int(number)
        # 已用 ≈ 活跃 + 有线 + 压缩（够用了；精确口径要 host_statistics64）
        active = stats.get("Pages active", 0)
        wired = stats.get("Pages wired down", 0)
        compressed = stats.get("Pages occupied by compressor", 0)
        used = (active + wired + compressed) * page
    except (OSError, subprocess.SubprocessError, ValueError):
        used = 0
    return total, used


def system_report() -> dict[str, Any]:
    """系统快照：负载 / 内存 / 磁盘 / CPU 核数 / 占用最高的进程（只读）。

    **不做温度与风扇**：那需要 `powermetrics`（每次 sudo），不适合一个"打开就看"的页面。
    """
    import shutil as _shutil

    load1 = load5 = load15 = 0.0
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        pass
    mem_total, mem_used = _memory_bytes()
    disk = _shutil.disk_usage(str(Path.home()))
    processes: list[dict[str, Any]] = []
    try:
        out = subprocess.run(
            ["/bin/ps", "-A", "-o", "%cpu=,rss=,comm=", "-r"],
            capture_output=True, text=True, timeout=6,
        ).stdout
        for line in out.splitlines()[:6]:
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0].replace(".", "", 1).isdigit():
                processes.append(
                    {"cpu": float(parts[0]), "rss": int(parts[1]) * 1024,
                     "name": parts[2].rsplit("/", 1)[-1][:40]}
                )
    except (OSError, subprocess.SubprocessError, ValueError):
        processes = []
    return {
        "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "cpu_count": os.cpu_count() or 0,
        "memory_total": mem_total,
        "memory_used": mem_used,
        "disk_total": int(disk.total),
        "disk_used": int(disk.used),
        "processes": processes,
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

    def approved_manager(approved: Sequence[str], confirm: Sequence[str] = ()) -> StorageManager:
        """真正执行用的上下文：**apply=True 且带上批准的目标 id**。

        2026-10-19 真机抓到的问题：原来 clean() 用的是默认上下文（`dry_run=True, apply=False`），
        内核只回了一份"计划"，页面却发布了"完成"——用户看到"清理完成"，文件一个都没动。
        另外 `enforce_approved_scope=True` 让内核只动批准过的目标，与"先给清单再清"的承诺一致。
        """
        return StorageManager(
            _context(
                home_path,
                root_path,
                apply=True,
                dry_run=False,
                approved_targets=frozenset(str(item) for item in approved if str(item)),
                # 高风险项（~/Downloads、Docker 数据…）内核要求**单独确认**，不传就只能被 blocked。
                confirm_targets=frozenset(str(item) for item in confirm if str(item)),
                require_explicit_plan=True,
                enforce_approved_scope=True,
                # 界面承诺"一律移入废纸篓（可恢复）"：缓存/日志也要走废纸篓，不能直接抹掉。
                prefer_trash=True,
            )
        )

    def report_of(mode: str) -> dict[str, Any]:
        instance = manager()
        if mode == "audit":
            return instance.audit().to_dict()
        if mode == "plan":
            return instance.plan().to_dict()
        return instance.clean().to_dict()

    def audit() -> dict[str, Any]:
        return scan_report(home=home_path, root=root_path, state_root=state_path)

    def rescan() -> dict[str, Any]:
        return scan_report(home=home_path, root=root_path, state_root=state_path, force=True)

    def plan() -> dict[str, Any]:
        return report_of("plan")

    def clean(approved: Sequence[str] = (), confirm: Sequence[str] = ()) -> dict[str, Any]:
        """执行清理。

        `approved` 必须由调用方给出（界面上就是用户点过的那批 target id）；
        没给就**拒绝执行**，而不是"尽力清一点"——空批准不等于全部批准。
        """
        wanted = [str(item) for item in approved if str(item)]
        if dry_run:
            return report_of("plan")
        if not wanted:
            return {
                "mode": "clean",
                "plan_items": [],
                "actual_reclaimed_bytes": 0,
                "notes": ["refused: nothing approved"],
            }
        report = approved_manager(wanted, [str(item) for item in confirm if str(item)]).clean().to_dict()
        # 走废纸篓时内核不把字节算作"已释放"（它们还在 .Trash 里），所以 actual_bytes 是 0。
        # 但界面必须能说"可恢复 N"——否则完成页又变成"可恢复 0 B"，用户以为没清掉。
        # 这里按"已移入废纸篓"的语义补上字节数：可恢复 = 移走的量，释放仍要等清空废纸篓。
        for item in report.get("plan_items") or []:
            if str(item.get("status")) == "cleaned" and not int(item.get("actual_bytes") or 0):
                item["actual_bytes"] = int(item.get("estimated_bytes") or 0)
        report["notes"] = list(report.get("notes") or []) + [
            "files were moved to Trash: recoverable until the Trash is emptied"
        ]
        return report

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

    def uninstall_apply(*, plan: dict[str, Any], ids: list[str] | None) -> dict[str, Any]:
        """执行卸载。

        `ids=None` 表示"全部用户域项"（命令行默认）；`ids=[]` 表示**用户什么都没勾**，
        必须原样传下去让 `apply_plan` 拒绝 —— 曾经写成 `list(ids) or None`，
        于是"全不勾"被当成"全选"，点一下卸载就把所有残留都搬走了（2026-10-19 复查发现）。
        """
        selected = None if ids is None else [str(item) for item in ids]
        return apply_plan(plan, home=home_path, selected_ids=selected, dry_run=dry_run)

    def updates_check() -> dict[str, Any]:
        return discover_updates()

    def updates_apply(*, ids: list[str]) -> dict[str, Any]:
        """按页面勾选执行更新。

        **空勾选必须拒绝**：原来 `if not wanted or ...` 让"一个都不勾"变成"全部升级"，
        79 个包会被一口气升掉（2026-10-19 复查发现，与卸载那条同一个病）。
        """
        if not ids:
            return {"status": "refused", "reason": "nothing selected", "groups": []}
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
        rescan=rescan,
        plan=plan,
        clean=clean,
        clean_approved=clean,   # clean(approved) 同一实现：无参时 dry-run，带 id 才真执行
        open_trash=lambda: _open_trash(home_path),
        reveal=_reveal,
        history=lambda: history_summary(state_root=state_path),
        apps=lambda: list_applications(home=home_path),
        skills=list_skills,
        disk=lambda: disk_report(home=home_path),
        system=system_report,
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

DEFAULT_SKILL_ROOTS: tuple[str, ...] = (
    "~/.codex/skills",
    "~/.codebuddy/skills",
    "~/.claude/skills",
)


def _display_path(path: Path) -> str:
    """把家目录前缀缩成 `~`（只用于展示）。"""
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def _skill_summary(skill_md: Path) -> dict[str, Any]:
    """读 `SKILL.md` 前部的 name/description（frontmatter 优先，缺失退回首个正文行）。"""
    info: dict[str, Any] = {
        "name": skill_md.parent.name,
        "description": "",
        "path": _display_path(skill_md),
        # 显示成 `~/...`：绝对路径对用户没有信息量，还会被样式大写化后更难读。
        "root": _display_path(skill_md.parent.parent),
    }
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return info
    in_front = False
    for line in text.splitlines()[:40]:
        stripped = line.strip()
        if stripped == "---":
            in_front = not in_front
            continue
        if in_front and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip().lower(), value.strip().strip('"').strip("'")
            if key == "name" and value:
                info["name"] = value
            elif key == "description" and value:
                info["description"] = value
    if not info["description"]:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "---", "|", ">")):
                info["description"] = stripped[:160]
                break
    return info


def list_skills(roots: list[str] | None = None, *, limit: int = 300) -> list[dict[str, Any]]:
    """列出本机可被 agent 调用的 skill（读 `SKILL.md`，只读，不执行）。

    为什么要走"根目录"而不是写死某个仓库：skill 由**客户端的根**决定（codex / codebuddy / claude），
    同一台机器上可能装在不同地方；用 `MACCLEANER_SKILL_ROOTS` 还能临时加别的根（冒号分隔）。
    """
    candidates: list[str] = list(roots or [])
    if not candidates:
        env_roots = os.environ.get("MACCLEANER_SKILL_ROOTS", "")
        candidates = [part for part in env_roots.split(":") if part.strip()] or list(DEFAULT_SKILL_ROOTS)
    skills: list[dict[str, Any]] = []
    for raw in candidates:
        root = Path(os.path.expanduser(str(raw)))
        if not root.is_dir():
            continue
        try:
            found = sorted(root.rglob("SKILL.md"))
        except OSError:
            continue
        for skill_md in found:
            if ".git" in skill_md.parts:
                continue
            skills.append(_skill_summary(skill_md))
            if len(skills) >= limit:
                return skills
    skills = sorted(skills, key=lambda item: (str(item["root"]), str(item["name"]).lower()))
    return _with_self(skills)


def _with_self(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把**本工具自己**放到列表最前（并标 `root=本工具`）。

    它通常不在那三个 skill 根下（它是独立安装的插件），如果不主动加进去，
    用户在"本机全部 skill"里反而找不到正在用的这一个。
    """
    repo_root = Path(__file__).resolve().parents[2]
    own = repo_root / "SKILL.md"
    if not own.is_file():
        return skills
    entry = _skill_summary(own)
    entry["root"] = "本工具"
    entry["name"] = entry.get("name") or "Mac Cleaner"
    return [entry, *skills]
