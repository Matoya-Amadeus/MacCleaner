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
import base64
import json
import os
import plistlib
import re
import shutil
import subprocess
import shlex
import tempfile
import time
from pathlib import Path
from typing import Any

from .core import move_to_trash, _protected_session_reason, StorageContext, StorageManager
from .session import SessionDeps
from .uninstall import apply_plan, build_plan, read_app_identity
from .updates import apply_updates, build_upgrade_plan, discover_updates

SKIP_APP_NAMES = {"Safari.app", "Notes.app"}   # 系统自带、通常不希望出现在卸载列表里


def _context(home: Path, root: Path, **overrides: Any) -> StorageContext:
    return StorageContext(home=home, root=root, **overrides)


APP_CATEGORY_LABELS: dict[str, str] = {
    "public.app-category.developer-tools": "开发工具",
    "public.app-category.productivity": "效率办公",
    "public.app-category.graphics-design": "设计与图像",
    "public.app-category.photography": "设计与图像",
    "public.app-category.video": "影音",
    "public.app-category.music": "影音",
    "public.app-category.entertainment": "影音",
    "public.app-category.games": "游戏",
    "public.app-category.social-networking": "社交与通讯",
    "public.app-category.news": "阅读资讯",
    "public.app-category.education": "教育",
    "public.app-category.finance": "财务",
    "public.app-category.business": "效率办公",
    "public.app-category.utilities": "系统工具",
    "public.app-category.reference": "阅读资讯",
    "public.app-category.medical": "其它",
    "public.app-category.weather": "其它",
}

# 展示顺序：用户最常清理的排在前面，"其它"垫底。
APP_CATEGORY_ORDER: tuple[str, ...] = (
    "浏览器", "开发工具", "社交与通讯", "效率办公", "设计与图像", "影音", "游戏", "阅读资讯", "系统工具", "其它",
)

_BROWSER_HINTS = ("safari", "chrome", "firefox", "edge", "brave", "arc", "opera", "vivaldi")


def app_category_label(raw: str, *, name: str = "", bundle_id: str = "") -> str:
    """把 `LSApplicationCategoryType` 映射成中文分类。

    为什么不用字母分组（2026-10-20 用户要求"按照分类，不要按照字母"）：
    A–Z 只能帮你找已知名字的应用，帮不了"我想看看有哪些开发工具占地方"。
    """
    key = str(raw or "").strip()
    label = APP_CATEGORY_LABELS.get(key, "")
    haystack = f"{name} {bundle_id}".lower()
    if any(hint in haystack for hint in _BROWSER_HINTS):
        return "浏览器"
    return label or "其它"

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
                    "category": app_category_label(
                        identity.get("category", ""),
                        name=str(identity.get("name") or ""),
                        bundle_id=str(identity.get("bundle_id") or ""),
                    ),
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


# 扫描缓存的结构版本：新增/删除清理目标时必须 +1，否则旧缓存里根本没有新目标
# （2026-10-20 实测：加了 browser-caches 后，缓存仍返回旧报告，页面上永远看不到浏览器组）。
SCAN_CACHE_VERSION = 3


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
            if (
                age <= ttl_seconds
                and int(entry.get("version") or 0) == SCAN_CACHE_VERSION
                and _signature(paths, home) == entry.get("signature")
            ):
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
            "version": SCAN_CACHE_VERSION,
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



def _open_app(path: str) -> None:
    """打开某个应用（让它的 Sparkle 更新器自己在后台检查更新）。"""
    subprocess.run(["/usr/bin/open", "-a", path], check=False, timeout=15)


def _open_app_store() -> None:
    """打开 App Store 的"更新"页。

    App Store 应用必须由 storeagent 用你的 Apple ID 下载安装，命令行绕不开登录；
    所以"mas 用不了"时的正确兜底是**把更新页打开**，让系统自己完成。
    """
    subprocess.run(["/usr/bin/open", "macappstore://showUpdatesPage"], check=False, timeout=10)


def _reveal(path: str) -> None:
    """在 Finder 中选中该路径，并把 Finder 带到前台。

    只做 `open -R` 时，实测在某些上下文里 Finder 只在后台打开（前台仍是别的 app），
    用户看到的就是"点了没反应"（2026-10-19 反馈）。补一次 `open -a Finder` 激活；
    两条都是 `open`，不需要辅助功能/自动化授权（AppleScript 才需要）。
    """
    subprocess.run(["/usr/bin/open", "-R", path], check=False, timeout=10)
    subprocess.run(["/usr/bin/open", "-a", "Finder"], check=False, timeout=10)


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


def _landing_history(home: Path, state_root: Path | None) -> dict[str, Any]:
    """落地页摘要：次数 + 释放量 + 最近一次时间（都从回执算）。"""
    report = history_report(home=home, state_root=state_root)
    entries = report.get("entries") or []
    last = entries[0] if entries else {}
    return {
        "total_runs": int(report.get("runs", 0) or 0),
        "total_freed_bytes": int(report.get("total_bytes", 0) or 0),
        "last_run": str(last.get("created_at") or ""),
        "last_items": int(last.get("items", 0) or 0),
        "last_bytes": int(last.get("bytes", 0) or last.get("estimated", 0) or 0),
    }


def _app_dirs(home: Path, *, system: bool = True) -> list[Path]:
    dirs = [Path(home) / "Applications"]
    if system:
        dirs.insert(0, Path("/Applications"))
    return dirs


def sparkle_apps(home: Path, *, limit: int = 40, system: bool = True) -> list[dict[str, Any]]:
    """列出**自带 Sparkle 更新器**的应用（只读，读 Info.plist / Frameworks）。

    为什么值得单独识别（2026-10-19 用户要求"先走应用自带更新，不行再去 App Store"）：
    Sparkle 应用可以在应用内自更新，**不需要 App Store 登录、也不受系统代理影响**
    （它用自己的网络请求）；只有没有 Sparkle 的才必须走 App Store。
    判定依据两条：`Info.plist` 里的 `SUFeedURL`，或 `Contents/Frameworks/Sparkle.framework`。
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in _app_dirs(home, system=system):
        if not directory.is_dir():
            continue
        try:
            entries = sorted(directory.glob("*.app"), key=lambda item: item.name.lower())
        except OSError:
            continue
        for app in entries:
            if app.name in seen:
                continue
            info = app / "Contents" / "Info.plist"
            data: dict[str, Any] = {}
            try:
                with info.open("rb") as handle:
                    data = plistlib.load(handle)
            except Exception:  # noqa: BLE001 - 坏 plist 只跳过这个应用
                data = {}
            framework = app / "Contents" / "Frameworks" / "Sparkle.framework"
            has_sparkle = bool(data.get("SUFeedURL")) or framework.exists()
            if not has_sparkle:
                continue
            seen.add(app.name)
            found.append(
                {
                    "name": str(data.get("CFBundleName") or app.stem),
                    "bundle_id": str(data.get("CFBundleIdentifier") or ""),
                    "version": str(data.get("CFBundleShortVersionString") or ""),
                    "path": str(app),
                    "feed": str(data.get("SUFeedURL") or ""),
                }
            )
            if len(found) >= limit:
                return found
    return found


def disk_report(*, home: Path) -> dict[str, Any]:
    """磁盘概览：整体容量 + 常用目录体积（只读）。"""
    import shutil as _shutil

    usage = _shutil.disk_usage(str(home))
    paths = [Path(home) / name for name in DISK_SECTIONS]
    sizes = _du_sizes(paths)
    sections = [
        {
            "name": name,
            "path": str(Path(home) / name),
            "bytes": sizes.get(str(Path(home) / name), 0),
        }
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


# 反向扫描的目录：只查"用户域里按 bundle id 命名"的位置。
# 刻意不含 `~/Library/Application Support`（很多目录是产品名而不是 bundle id，误报率高）。
ORPHAN_DIRS = (
    "Library/Caches",
    "Library/Preferences",
    "Library/Logs",
    "Library/Containers",
    "Library/HTTPStorages",
    "Library/WebKit",
    "Library/Saved Application State",
)

# 看起来像 bundle id：至少两段、只含字母数字与 . _ -
BUNDLE_LIKE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")

# 这些前缀不猜：苹果系统组件删了会出问题，也不该由第三方工具判定。
ORPHAN_SKIP_PREFIXES = ("com.apple.", "group.com.apple.", "system.", "org.swift.", "com.apple")


LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)
LS_BUNDLE_ID = re.compile(r"^bundle id:\s+(?P<id>\S+)")


LAUNCHSERVICES_CACHE_SECONDS = 600


def launchservices_bundle_ids(
    *, timeout: float = 8.0, cache_path: Path | None = None, ttl: int = LAUNCHSERVICES_CACHE_SECONDS
) -> set[str]:
    """从 LaunchServices 注册表抓**所有已注册** app 的 bundle id。

    为什么需要它（2026-10-20 实测）：只扫 `/Applications`、`~/Applications` 会把
    装在别处的应用误判成"已卸载"——本机 `com.epicgames.UnrealEditor` 装在
    `~/Workspace/UEProject/UE_8/...`，于是它 267 MB 的缓存被错误地报成"孤儿"。
    宁可多花 4 秒，也不能让用户删掉在用应用的数据。
    """
    # 缓存：`lsregister -dump` 实测 4.3 秒，第二次进页不该再等。
    if cache_path is not None:
        try:
            entry = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entry = None
        if isinstance(entry, dict):
            age = time.time() - float(entry.get("at") or 0)
            ids = entry.get("ids")
            if 0 <= age <= ttl and isinstance(ids, list):
                return {str(item) for item in ids}

    try:
        completed = subprocess.run(
            [LSREGISTER, "-dump"], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    ids: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        match = LS_BUNDLE_ID.match(line)
        if match:
            ids.add(match.group("id"))

    if cache_path is not None:
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(cache_path).with_suffix(".tmp")
            tmp.write_text(json.dumps({"at": time.time(), "ids": sorted(ids)}), encoding="utf-8")
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return ids


def installed_bundle_ids(
    home: Path, *, system: bool = True, cache_path: Path | None = None
) -> dict[str, str]:
    """已安装应用的 `bundle_id → 名字`（只读 Info.plist）。

    扫三个位置：`/Applications`、`/System/Applications`、`~/Applications`。
    """
    found: dict[str, str] = {}
    bases = [Path(home) / "Applications"]
    if system:
        bases = [Path("/Applications"), Path("/System/Applications"), *bases]
    for base in bases:
        if not base.is_dir():
            continue
        try:
            entries = list(base.glob("*.app"))
        except OSError:
            continue
        for app in entries:
            try:
                with (app / "Contents" / "Info.plist").open("rb") as handle:
                    data = plistlib.load(handle)
            except Exception:  # noqa: BLE001 - 坏 plist 跳过
                continue
            bundle_id = str(data.get("CFBundleIdentifier") or "").strip()
            if bundle_id:
                found[bundle_id] = str(data.get("CFBundleName") or app.stem)

    if system:
        # `/Users/Shared` 是不少大型软件（Epic、部分驱动）的默认位置。
        shared = Path("/Users/Shared")
        if shared.is_dir():
            try:
                for app in shared.glob("**/*.app"):
                    try:
                        with (app / "Contents" / "Info.plist").open("rb") as handle:
                            data = plistlib.load(handle)
                    except Exception:  # noqa: BLE001
                        continue
                    bundle_id = str(data.get("CFBundleIdentifier") or "").strip()
                    if bundle_id:
                        found.setdefault(bundle_id, str(data.get("CFBundleName") or app.stem))
            except OSError:
                pass
        # LaunchServices 覆盖"装在任意位置但已注册"的应用。
        for bundle_id in launchservices_bundle_ids(cache_path=cache_path):
            found.setdefault(bundle_id, "")
    return found


def _vendor(name: str) -> str:
    """取 bundle id 的"厂商前缀"：`com.epicgames.UnrealEditor` → `com.epicgames`。"""
    parts = [part for part in str(name or "").split(".") if part]
    return ".".join(parts[:2]) if len(parts) >= 2 else str(name or "")


def _belongs_to_installed(name: str, installed: dict[str, str]) -> bool:
    """名字是否"属于某个已装应用"。

    双向前缀匹配：`com.demo.app.ShipIt` 属于 `com.demo.app`；
    `com.demo` 也可能是 `com.demo.helper` 的父级——两者都算"不是孤儿"，
    宁可漏报也不误报（误报会让用户删掉正在用的应用数据）。
    """
    vendor = _vendor(name)
    for bundle_id in installed:
        if name == bundle_id:
            return True
        if name.startswith(bundle_id + ".") or bundle_id.startswith(name + "."):
            return True
        # 同厂商还装着别的应用时，**按保守处理**：不让它进"孤儿"列表。
        # 实测例子：`com.epicgames.UnrealEditor` 的缓存对应的是 `UnrealEditorServices`（装在
        # ~/Workspace/UEProject/…），bundle id 与缓存目录名并不逐字相同，靠前缀匹配抓不到。
        # 宁可漏报，也不建议用户删掉在用应用的数据。
        if vendor and _vendor(bundle_id) == vendor:
            return True
    return False


def orphan_leftovers(
    home: Path,
    *,
    limit: int = 200,
    min_age_days: int = 7,
    system: bool = True,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """找出"应用已经不在，但残留还在"的项（只读）。

    判定条件（三条同时满足）：
    1. 名字看起来是 bundle id（`a.b` 形态），且在 `ORPHAN_DIRS` 里按该名字存在；
    2. 没有任何**已安装**应用的 bundle id 与它相同/互为前缀；
    3. 不是 `com.apple.*` 等系统前缀，也没命中受保护路径，且最后修改早于 `min_age_days`。

    这是 Pearcleaner 的"孤儿文件"能力的最小可信版本：**默认不勾、只在废纸篓里可恢复**。
    """
    home_path = Path(home)
    installed = installed_bundle_ids(home_path, system=system, cache_path=cache_path)
    candidates: list[Path] = []
    seen: set[str] = set()
    skipped_vendor = 0

    for relative in ORPHAN_DIRS:
        directory = home_path / relative
        if not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            # 去掉常见后缀，还原成 bundle id 形态
            for suffix in (".plist", ".savedState", ".binarycookies", ".log"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
            if not BUNDLE_LIKE.match(name):
                continue
            if name.startswith(ORPHAN_SKIP_PREFIXES):
                continue
            if _belongs_to_installed(name, installed):
                # 同厂商还装着别的应用时也走这里：单独计数，页面上要说明"排除了多少"。
                if not any(name == bundle_id or name.startswith(bundle_id + ".") or bundle_id.startswith(name + ".")
                           for bundle_id in installed):
                    skipped_vendor += 1
                continue
            if _protected_session_reason(entry):
                continue
            key = str(entry)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(entry)

    cutoff = time.time() - max(0, min_age_days) * 86400
    kept: list[Path] = []
    for entry in candidates:
        try:
            if entry.stat().st_mtime > cutoff:
                continue  # 最近还在被写：可能只是暂时没装，先不动
        except OSError:
            continue
        kept.append(entry)

    sizes = _du_sizes(kept, timeout=8.0)
    items = [
        {
            "name": entry.name,
            "path": str(entry),
            "bytes": int(sizes.get(str(entry), 0)),
            "modified": time.strftime("%Y-%m-%d", time.localtime(entry.stat().st_mtime))
            if entry.exists()
            else "",
        }
        for entry in kept
    ]
    items.sort(key=lambda item: -int(item["bytes"]))
    return {
        "items": items[:limit],
        "total": len(items),
        "bytes": sum(int(item["bytes"]) for item in items[:limit]),
        "installed": len(installed),
        "skipped_vendor": skipped_vendor,
    }


def orphans_clean(home: Path, paths: Sequence[str]) -> dict[str, Any]:
    """把点名要清的孤儿残留移入废纸篓（可恢复）。

    只接受**当前扫描结果里出现过的路径**由会话侧校验；这里再做一次归属校验：
    必须以 `home` 为前缀，避免被当成任意文件删除器。
    """
    home_path = Path(home).resolve()
    moved: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    total_bytes = 0
    for raw in paths:
        target = Path(str(raw)).expanduser()
        try:
            resolved = target.resolve()
        except OSError:
            failed.append({"path": str(raw), "reason": "unresolvable"})
            continue
        if home_path not in resolved.parents:
            failed.append({"path": str(raw), "reason": "outside home"})
            continue
        if not resolved.exists():
            failed.append({"path": str(raw), "reason": "missing"})
            continue
        size = int(_du_sizes([resolved], timeout=5).get(str(resolved), 0))
        try:
            destination = move_to_trash(resolved, home_path)
        except OSError as exc:
            failed.append({"path": str(raw), "reason": str(exc)[:80]})
            continue
        total_bytes += size
        moved.append({"path": str(resolved), "to": str(destination), "bytes": size})
    return {"moved": moved, "failed": failed, "count": len(moved), "bytes": total_bytes}


def system_report() -> dict[str, Any]:
    """系统快照：负载 / 内存 / 磁盘 / CPU 核数 / 占用最高的进程（只读）。

    电池与节流用 `pmset` / `ioreg`（**免 sudo**，实测 0.04s）；
    **风扇转速不做**：那是 SMC 私有接口，第三方工具读它要额外权限，值也不稳定。
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
    def _run_text(argv: list[str], timeout: float = 5.0) -> str:
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    power = parse_pmset_batt(_run_text(["/usr/bin/pmset", "-g", "batt"]))
    battery = parse_battery_ioreg(_run_text(["/usr/sbin/ioreg", "-rn", "AppleSmartBattery"]))
    thermal = parse_thermal(_run_text(["/usr/bin/pmset", "-g", "therm"]))

    return {
        "power": {**power, **battery},
        "thermal": thermal,
        "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "cpu_count": os.cpu_count() or 0,
        "memory_total": mem_total,
        "memory_used": mem_used,
        "disk_total": int(disk.total),
        "disk_used": int(disk.used),
        "processes": processes,
    }


PMSET_BATT = re.compile(
    r"(?P<percent>\d+)%;\s*(?P<state>[a-z ]+?);\s*(?:(?P<remaining>[\d:]+) remaining)?"
)


def parse_pmset_batt(text: str) -> dict[str, Any]:
    """`pmset -g batt` 的两行输出 → 电量/状态/剩余。"""
    source = ""
    for line in (text or "").splitlines():
        if "drawing from" in line:
            source = "电池" if "'Battery" in line else ("电源" if "'AC" in line else "")
            break
    data: dict[str, Any] = {"source": source, "percent": None, "state": "", "remaining": ""}
    match = PMSET_BATT.search(text or "")
    if match:
        data["percent"] = int(match.group("percent"))
        data["state"] = (match.group("state") or "").strip()
        data["remaining"] = (match.group("remaining") or "").strip()
    return data


IOREG_INT = re.compile(r'"(?P<key>CycleCount|MaxCapacity|DesignCapacity)"\s*=\s*(?P<value>\d+)')


def parse_battery_ioreg(text: str) -> dict[str, Any]:
    """从 `ioreg -rn AppleSmartBattery` 取循环次数与健康度。

    健康度用 `BatteryData.FullChargeCapacity / DesignCapacity`：本机实测
    `MaxCapacity=100` 只是百分比，拿它算健康度会永远得到 100%。
    """
    values: dict[str, int] = {}
    for match in IOREG_INT.finditer(text or ""):
        values[match.group("key")] = int(match.group("value"))
    full = re.search(r'"FullChargeCapacity"=(\d+)', text or "")
    design = values.get("DesignCapacity") or 0
    full_capacity = int(full.group(1)) if full else 0
    health = round(full_capacity / design * 100) if design and full_capacity else None
    return {
        "cycles": values.get("CycleCount"),
        "health_percent": health,
        "design_mah": design or None,
        "full_mah": full_capacity or None,
    }


THERM_INT = re.compile(r"(?P<key>CPU_Speed_Limit|CPU_Scheduler_Limit)\s*=\s*(?P<value>\d+)")


def parse_thermal(text: str) -> dict[str, Any]:
    """`pmset -g therm`：有节流时才有 CPU_Speed_Limit；没有就是"未触发"。"""
    values = {m.group("key"): int(m.group("value")) for m in THERM_INT.finditer(text or "")}
    limit = values.get("CPU_Speed_Limit")
    return {
        "speed_limit": limit,
        "scheduler_limit": values.get("CPU_Scheduler_Limit"),
        "throttled": bool(limit is not None and limit < 100),
    }




# ---- 大文件视图 ----

LARGE_FILE_ROOTS = ("Downloads", "Desktop", "Documents", "Movies")
LARGE_FILE_SKIP = frozenset({".git", "node_modules", ".Trash", "Library"})


def large_files(
    home: Path, *, min_bytes: int = 500 * 2**20, limit: int = 200, timeout: float = 15.0
) -> dict[str, Any]:
    """列出用户目录里的大文件（只读，默认 >500 MB）。

    为什么用 `find` 而不是 `os.walk`：`~` 下的 Downloads/Documents 可能有几十万文件，
    Python 遍历要十几秒；`find -size` 是系统实现，实测 0.2s（超时也只拿已完成的部分）。
    """
    home_path = Path(home)
    roots = [home_path / name for name in LARGE_FILE_ROOTS if (home_path / name).is_dir()]
    if not roots:
        return {"items": [], "bytes": 0, "truncated": False, "scanned": 0}

    megabytes = max(1, int(min_bytes / 2**20))
    argv = ["/usr/bin/find", *map(str, roots), "-type", "f", "-size", f"+{megabytes}M"]
    for name in LARGE_FILE_SKIP:
        argv.extend(["-not", "-path", f"*/{name}/*"])
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        found = [line for line in (completed.stdout or "").splitlines() if line.strip()]
        truncated = False
    except subprocess.TimeoutExpired as exc:
        # 超时也要用已经拿到的部分（`TimeoutExpired.stdout` 里是有的）
        raw = exc.stdout or ""
        found = [line for line in raw.decode("utf-8", "replace").splitlines() if line.strip()] if isinstance(raw, bytes) else [line for line in raw.splitlines() if line.strip()]
        truncated = True
    except (OSError, subprocess.SubprocessError):
        return {"items": [], "bytes": 0, "truncated": False, "scanned": 0}

    items: list[dict[str, Any]] = []
    for raw in found[: limit * 4]:
        path = Path(raw)
        try:
            stat_result = path.stat()
        except OSError:
            continue
        if stat_result.st_size < min_bytes:
            continue
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "bytes": int(stat_result.st_size),
                "modified": time.strftime("%Y-%m-%d", time.localtime(stat_result.st_mtime)),
            }
        )
    items.sort(key=lambda item: -int(item["bytes"]))
    kept = items[:limit]
    return {
        "items": kept,
        "bytes": sum(int(item["bytes"]) for item in kept),
        "count": len(items),
        "truncated": truncated or len(items) > limit,
        "scanned": len(found),
        "roots": [str(path).replace(str(home_path), "~") for path in roots],
        "min_bytes": min_bytes,
    }


def trash_paths(home: Path, paths: Sequence[str]) -> dict[str, Any]:
    """把点名要删的文件/目录移入废纸篓（只接受 home 内的路径）。"""
    home_path = Path(home).resolve()
    moved: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    total_bytes = 0
    for raw in paths:
        target = Path(str(raw)).expanduser()
        try:
            resolved = target.resolve()
        except OSError:
            failed.append({"path": str(raw), "reason": "unresolvable"})
            continue
        if home_path not in resolved.parents:
            failed.append({"path": str(raw), "reason": "outside home"})
            continue
        if not resolved.exists():
            failed.append({"path": str(raw), "reason": "missing"})
            continue
        try:
            size = int(resolved.stat().st_size) if resolved.is_file() else int(
                _du_sizes([resolved], timeout=5).get(str(resolved), 0)
            )
        except OSError:
            size = 0
        try:
            destination = move_to_trash(resolved, home_path)
        except OSError as exc:
            failed.append({"path": str(raw), "reason": str(exc)[:80]})
            continue
        total_bytes += size
        moved.append({"path": str(resolved), "to": str(destination), "bytes": size})
    return {"moved": moved, "failed": failed, "count": len(moved), "bytes": total_bytes}


# ---- 系统级只读测量（需要一次管理员授权，**只测量不删除**） ----

SYSTEM_SIZE_PATHS = ("/Library/Caches", "/Library/Logs", "/var/log", "/private/var/folders")
SYSTEM_SIZE_TTL = 6 * 3600


def _parse_du(output: str) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for line in (output or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            kib = int(parts[0])
        except ValueError:
            continue
        sizes[parts[1].strip()] = kib * 1024
    return sizes


def system_sizes(cache_path: Path | None = None, *, ttl: int = SYSTEM_SIZE_TTL) -> dict[str, Any]:
    """读缓存；没有缓存就**无授权**量一遍（数字偏低），并标记 `admin=False`。

    为什么"只测量不删除"：root 域没有"你的废纸篓"，删了不可恢复；而 `du` 只读，
    一次密码换来准确数字，风险最低。
    """
    if cache_path is not None:
        try:
            cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, dict) and time.time() - float(cached.get("at") or 0) <= ttl:
            return {**cached, "cached": True}

    code, out, _ = _run_cmd(["/usr/bin/du", "-sk", *SYSTEM_SIZE_PATHS], timeout=15)
    sizes = _parse_du(out)
    return {
        "at": time.time(),
        "admin": False,
        "cached": False,
        "sizes": sizes,
        "paths": list(SYSTEM_SIZE_PATHS),
        "note": "未授权：系统目录读不全，数字可能明显偏低。",
        "exit": code,
    }


def system_sizes_cached(cache_path: Path | None, *, ttl: int = SYSTEM_SIZE_TTL) -> dict[str, Any]:
    """**只读缓存**的系统目录体积：不发 `du`，不弹授权。

    为什么不在页面加载时跑 `du`（2026-10-20 真机自测）：首次进磁盘页同步跑
    `du -sk /private/var/folders`，磁盘一忙就会阻塞 20 多秒（实测 8s+15s 两个超时叠加），
    页面像卡死。测量只该发生在用户**点击授权按钮**那一刻。
    """
    if cache_path is None:
        return {}
    try:
        cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(cached, dict):
        return {}
    if time.time() - float(cached.get("at") or 0) > ttl:
        return {}
    return {**cached, "cached": True}


# 只允许动这三个根**下面**的条目；根本身不行（否则等于搬走整个 /Library/Caches）。
SYSTEM_TRASH_ROOTS: tuple[Path, ...] = (
    Path("/Library/Caches"),
    Path("/Library/Logs"),
    Path("/var/log"),
)


def _applescript_literal(text: str) -> str:
    """AppleScript 字符串字面量（只处理反斜杠与双引号）。"""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def system_trash_paths(
    paths: list[str],
    *,
    runner: Any | None = None,
    trash_dir: Path | None = None,
) -> dict[str, Any]:
    """把系统级目录**整目录**移进"当前用户"的废纸篓（需一次管理员授权）。

    为什么不是删除：废纸篓里的东西还能拿回来；这也是我们敢碰 root 域的前提。
    做不到的部分（别处已写明）：文件属主是 root，**清空废纸篓可能还要授权**，
    且 Finder 的「放回原处」对它们不可用。

    参数：
    - `paths`：要搬的绝对路径（只接受 `SYSTEM_TRASH_ROOTS` 的**子项**）；
    - `runner`：测试注入，签名同 `subprocess.run`；
    - `trash_dir`：测试注入，默认 `~/.Trash`。
    """
    target_trash = Path(trash_dir) if trash_dir is not None else Path.home() / ".Trash"
    run = runner or subprocess.run

    accepted: list[Path] = []
    failed: list[dict[str, str]] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        candidate = Path(text)
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            failed.append({"path": text, "reason": "路径无法解析"})
            continue
        # 根也要 resolve：macOS 上 /var 是 /private/var 的软链，
        # 否则 `/var/log/xxx` 解析后永远匹配不上 `/var/log`（真机上等于这个根失效）。
        roots = tuple(root.resolve(strict=False) for root in SYSTEM_TRASH_ROOTS)
        inside = any(root in resolved.parents for root in roots)
        if not inside:
            failed.append({"path": text, "reason": "不在允许范围（只动 /Library/Caches、/Library/Logs、/var/log 的子项）"})
            continue
        if not candidate.exists():
            failed.append({"path": text, "reason": "不存在"})
            continue
        accepted.append(resolved)

    if not accepted:
        return {"status": "refused", "moved": [], "failed": failed, "trash": str(target_trash)}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    script_lines = ["set -e"]
    for index, source in enumerate(accepted):
        dest = target_trash / f"{source.name}-{stamp}-{index}"
        script_lines.append(f"/bin/mv {shlex.quote(str(source))} {shlex.quote(str(dest))}")

    with tempfile.TemporaryDirectory(prefix="mc-system-trash-") as tmp:
        script_path = Path(tmp) / "move.sh"
        script_path.write_text("\n".join(script_lines) + "\n", encoding="utf-8")
        script_path.chmod(0o700)
        command = [
            "/usr/bin/osascript",
            "-e",
            f"do shell script {_applescript_literal('/bin/sh ' + str(script_path))}"
            " with administrator privileges",
        ]
        try:
            result = run(command, capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "status": "error",
                "moved": [],
                "failed": [{"path": str(item), "reason": str(exc)} for item in accepted],
                "trash": str(target_trash),
            }

    stderr = getattr(result, "stderr", b"") or b""
    text_err = stderr.decode("utf-8", "replace") if isinstance(stderr, (bytes, bytearray)) else str(stderr)
    if getattr(result, "returncode", 1) != 0:
        cancelled = "User canceled" in text_err or "-128" in text_err
        return {
            "status": "cancelled" if cancelled else "error",
            "moved": [],
            "failed": [{"path": str(item), "reason": text_err.strip()[:200] or "授权未通过"} for item in accepted],
            "trash": str(target_trash),
        }
    return {
        "status": "ok",
        "moved": [str(item) for item in accepted],
        "failed": failed,
        "trash": str(target_trash),
    }


def system_sizes_admin(cache_path: Path | None = None) -> dict[str, Any]:
    """弹**一次**管理员授权，读准系统目录体积（只读，不删任何文件）。

    用 `osascript ... with administrator privileges` 而不是让 Python 自己 sudo：
    这样系统弹的是标准授权框，进程本身不提权；脚本里只有固定路径，没有用户输入。
    """
    quoted = " ".join(SYSTEM_SIZE_PATHS)
    script = f'do shell script "/usr/bin/du -sk {quoted} 2>/dev/null" with administrator privileges'
    try:
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=180
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"at": time.time(), "admin": False, "cached": False, "sizes": {},
                "paths": list(SYSTEM_SIZE_PATHS), "note": f"授权失败：{exc}", "exit": 1}
    if completed.returncode != 0:
        return {"at": time.time(), "admin": False, "cached": False, "sizes": {},
                "paths": list(SYSTEM_SIZE_PATHS),
                "note": (completed.stderr or "").strip()[:160] or "已取消授权", "exit": completed.returncode}
    result = {
        "at": time.time(),
        "admin": True,
        "cached": False,
        "sizes": _parse_du(completed.stdout),
        "paths": list(SYSTEM_SIZE_PATHS),
        "note": "已授权读取（只测量，不删除任何文件）。",
        "exit": 0,
    }
    if cache_path is not None:
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return result

CASK_INFO_TIMEOUT = 20.0



BREW_CANDIDATES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")


def _brew_path() -> str:
    for candidate in BREW_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("brew")
    return found or ""


def _run_cmd(argv: list[str], *, timeout: float) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"
    return (
        int(getattr(completed, "returncode", 1) or 0),
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )



def app_version(app_path: str) -> str:
    """读某个 .app 的版本号（`CFBundleShortVersionString`，退回 `CFBundleVersion`）。

    Sparkle 更新是**应用自己**完成的，我们只能对比前后版本号来判断是否真的更新了——
    这比"点了按钮就当更新了"诚实。
    """
    try:
        with (Path(app_path) / "Contents" / "Info.plist").open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return ""
    return str(data.get("CFBundleShortVersionString") or data.get("CFBundleVersion") or "")


# 常见浏览器的 bundle 路径：只用来给"浏览器缓存"那几行配图标。
BROWSER_BUNDLES: tuple[tuple[str, str], ...] = (
    ("Safari", "/Applications/Safari.app"),
    ("Google Chrome", "/Applications/Google Chrome.app"),
    ("Firefox", "/Applications/Firefox.app"),
    ("Microsoft Edge", "/Applications/Microsoft Edge.app"),
    ("Brave Browser", "/Applications/Brave Browser.app"),
    ("Arc", "/Applications/Arc.app"),
)

ICON_CACHE_TTL = 7 * 24 * 3600


def app_icon_data_uri(app_path: str, *, size: int = 32) -> str:
    """把某个 `.app` 的图标转成 data URI（32px PNG，约 2 KB）。

    为什么要转：`NSWorkspace` 需要原生桥；`sips` 是系统自带工具，实测 3 个图标共 0.10s。
    图标来自**用户自己机器上已安装的应用**，不随包分发任何厂商素材。
    """
    bundle = Path(app_path)
    if not bundle.is_dir():
        return ""
    resources = bundle / "Contents" / "Resources"
    icon: Path | None = None
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        name = str(info.get("CFBundleIconFile") or "")
        if name:
            candidate = resources / (name if name.endswith(".icns") else name + ".icns")
            if candidate.is_file():
                icon = candidate
    except Exception:  # noqa: BLE001 - 有的应用 Info.plist 本身是坏的（实测 ExpatError）
        icon = None
    if icon is None:
        try:
            icon = next(iter(sorted(resources.glob("*.icns"))), None)
        except OSError:
            icon = None
    if icon is None:
        return ""
    # sips 不接受 `/dev/stdout` 作为输出（实测返回空），必须落到临时文件再读回来。
    with tempfile.TemporaryDirectory(prefix="mc-icon-") as tmp:
        out = Path(tmp) / "icon.png"
        try:
            result = subprocess.run(
                ["/usr/bin/sips", "-s", "format", "png",
                 "--resampleHeightWidth", str(size), str(size), str(icon), "--out", str(out)],
                capture_output=True, timeout=8,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if result.returncode != 0 or not out.is_file():
            return ""
        try:
            payload = out.read_bytes()
        except OSError:
            return ""
    if not payload:
        return ""
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")



def icons_for(
    paths: Sequence[str], cache_path: Path | None = None, *, ttl: int = ICON_CACHE_TTL
) -> dict[str, str]:
    """批量取应用图标：`{app 路径: data URI}`，按路径 + mtime 缓存。

    39 个应用 × ~30ms ≈ 1.2s，所以**必须**缓存（否则每次进卸载页都要等）。
    只处理真实存在的 `.app`，取不到就跳过（页面退回内置 SVG 图标）。
    """
    entries: dict[str, Any] = {}
    if cache_path is not None:
        try:
            cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            entries = cached.get("apps") or {}
        except (OSError, json.JSONDecodeError):
            entries = {}
    now = time.time()
    icons: dict[str, str] = {}
    dirty = False
    for raw in paths:
        bundle = Path(str(raw))
        if not bundle.is_dir():
            continue
        try:
            mtime = bundle.stat().st_mtime
        except OSError:
            continue
        entry = entries.get(str(bundle))
        if isinstance(entry, dict) and entry.get("mtime") == mtime and entry.get("uri"):
            if now - float(entry.get("at") or 0) <= ttl:
                icons[str(bundle)] = str(entry["uri"])
                continue
        uri = app_icon_data_uri(str(bundle))
        if not uri:
            continue
        icons[str(bundle)] = uri
        entries[str(bundle)] = {"mtime": mtime, "uri": uri, "at": now}
        dirty = True
    if cache_path is not None and dirty:
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(cache_path).with_suffix(".tmp")
            tmp.write_text(json.dumps({"apps": entries}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return icons

def browser_icons(cache_path: Path | None = None, *, ttl: int = ICON_CACHE_TTL) -> dict[str, str]:
    """已安装浏览器的 `{名称: data URI}`；按应用 mtime 缓存，装/升级后自动刷新。"""
    cached: dict[str, Any] = {}
    if cache_path is not None:
        try:
            cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
    entries: dict[str, Any] = cached.get("apps") or {}
    now = time.time()
    icons: dict[str, str] = {}
    dirty = False
    for name, bundle in BROWSER_BUNDLES:
        path = Path(bundle)
        if not path.is_dir():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        entry = entries.get(bundle)
        if isinstance(entry, dict) and entry.get("mtime") == mtime and entry.get("uri"):
            age = now - float(entry.get("at") or 0)
            if age <= ttl:
                icons[name] = str(entry["uri"])
                continue
        uri = app_icon_data_uri(bundle)
        if uri:
            icons[name] = uri
            entries[bundle] = {"mtime": mtime, "uri": uri, "at": now}
            dirty = True
    if cache_path is not None and dirty:
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(cache_path).with_suffix(".tmp")
            tmp.write_text(json.dumps({"apps": entries}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return icons

def parse_cask_targets(payload: str) -> dict[str, str]:
    """`brew info --cask --json=v2` → `{app 路径: cask token}`。

    cask token 与 app 名并不同名（`ollama-app` → `Ollama.app`、`devin-desktop` → `Devin.app`），
    靠名字猜必错，所以只认 artifacts 里的 target 路径。
    """
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return {}
    mapping: dict[str, str] = {}
    for cask in data.get("casks") or []:
        if not isinstance(cask, dict):
            continue
        token = str(cask.get("token") or "")
        if not token:
            continue
        for artifact in cask.get("artifacts") or []:
            if isinstance(artifact, dict) and artifact.get("target"):
                mapping[str(artifact["target"])] = token
    return mapping


def cask_app_map(*, runner: Any | None = None) -> dict[str, str]:
    """当前已安装 cask 的 `{app 路径: token}`；brew 不可用/失败就返回空。"""
    binary = _brew_path()
    if not binary:
        return {}
    code, out, _ = _run_cmd([binary, "list", "--cask"], timeout=15)
    if code != 0:
        return {}
    tokens = [line.strip() for line in (out or "").splitlines() if line.strip()]
    if not tokens:
        return {}
    code, info, _ = _run_cmd(
        [binary, "info", "--cask", "--json=v2", *tokens], timeout=CASK_INFO_TIMEOUT
    )
    if code != 0:
        return {}
    return parse_cask_targets(info)


def uninstall_cask(token: str, *, runner: Any | None = None) -> dict[str, Any]:
    """用 Homebrew 卸载 cask（只在界面显式点击时调用）。

    cask 装的 app 如果只把 .app 拖进废纸篓，`brew list --cask` 仍认为它装着，
    下次 `brew upgrade` 会"复活"或报错。
    """
    binary = _brew_path()
    if not binary:
        return {"status": "missing-tool", "token": token, "output": "brew 不可用"}
    code, out, err = _run_cmd([binary, "uninstall", "--cask", token], timeout=300)
    return {
        "status": "ok" if code == 0 else "failed",
        "token": token,
        "exit": code,
        "output": (out or err or "").strip()[-800:],
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
        plan = build_plan(
            {
                "path": app_path,
                "bundle_id": bundle_id or identity.get("bundle_id", ""),
                "name": app_name or identity.get("name", ""),
                "home": str(home_path),
            },
            home=home_path,
        )
        # 由 Homebrew cask 装的 app：预览页要提示改用 brew 卸载（否则 brew 记录与磁盘不一致）。
        plan["cask"] = cask_app_map().get(str(app_path), "")
        return plan

    def uninstall_apply(*, plan: dict[str, Any], ids: list[str] | None) -> dict[str, Any]:
        """执行卸载。

        `ids=None` 表示"全部用户域项"（命令行默认）；`ids=[]` 表示**用户什么都没勾**，
        必须原样传下去让 `apply_plan` 拒绝 —— 曾经写成 `list(ids) or None`，
        于是"全不勾"被当成"全选"，点一下卸载就把所有残留都搬走了（2026-10-19 复查发现）。
        """
        selected = None if ids is None else [str(item) for item in ids]
        return apply_plan(plan, home=home_path, selected_ids=selected, dry_run=dry_run)

    def updates_refresh() -> dict[str, Any]:
        return updates_report(state_root=state_path, force=True)

    def updates_check() -> dict[str, Any]:
        # Sparkle 应用（自带更新器）不走包管理器，得单独扫一遍 /Applications。
        # 之前这里只返回 `discover_updates()`，页面上的"自带更新"组**永远是空的**
        # （本机实测 sparkle_apps() 有 4 个，页面却一个都不显示，2026-10-21 核对发现）。
        found = discover_updates()
        try:
            found["sparkle"] = sparkle_apps(home_path)
        except Exception:  # noqa: BLE001 - 图标/plist 读坏了不该拖垮整个检查
            found.setdefault("sparkle", [])
        return found

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
        plan=plan,
        clean=clean,
        clean_approved=clean,   # clean(approved) 同一实现：无参时 dry-run，带 id 才真执行
        open_trash=lambda: _open_trash(home_path),
        reveal=_reveal,
        open_app_store=_open_app_store,
        open_app=_open_app,
        uninstall_cask=lambda token: uninstall_cask(token),
        app_version=app_version,
        app_icons=lambda paths: icons_for(
            list(paths), (state_path / "app-icons.json") if state_path else None
        ),
        browser_icons=lambda: browser_icons(
            (state_path / "browser-icons.json") if state_path else None
        ),
        large_files=lambda: large_files(home_path),
        trash_paths=lambda paths: trash_paths(home_path, paths),
        system_sizes_cached=lambda: system_sizes_cached(
            (state_path / "system-sizes.json") if state_path else None
        ),
        system_sizes=lambda: system_sizes(
            (state_path / "system-sizes.json") if state_path else None
        ),
        system_trash_paths=lambda paths: system_trash_paths(list(paths)),
        system_sizes_admin=lambda: system_sizes_admin(
            (state_path / "system-sizes.json") if state_path else None
        ),
        sparkle_apps=lambda: sparkle_apps(home_path),
        orphans_scan=lambda: orphan_leftovers(
            home_path, cache_path=(state_path / "launchservices-ids.json") if state_path else None
        ),
        orphans_apply=lambda paths: orphans_clean(home_path, paths),
        # 落地页的"上次清理"也从回执算：`history.json` 没人写，读它永远是空
        # （2026-10-19 发现；现在与「清理历史」页共用同一真相源）。
        history=lambda: _landing_history(home_path, state_path),
        apps=lambda: list_applications(home=home_path),
        skills=list_skills,
        disk=lambda: disk_report(home=home_path),
        system=system_report,
        uninstall_plan=uninstall_plan,
        uninstall_apply=uninstall_apply,
        updates_check=updates_check,
        updates_refresh=updates_refresh,
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
