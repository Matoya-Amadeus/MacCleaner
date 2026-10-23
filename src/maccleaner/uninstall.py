"""应用卸载的**残留发现**与**计划生成**（2026-10-18 迁入）。

本模块只做只读的事：找出一个应用在磁盘上留下的痕迹，并把它组织成一份可审阅的计划。
**不做删除**——写动作要与 `core`/`policy` 的 rollback 与保护语义对齐后再接，见文末说明。

为什么"卸不干净"是常态，以及这里怎么对症：

1. 很多应用**不用 bundle-id 建目录**（`~/Library/Application Support/<App Name>`、
   `~/Library/Logs/<App Name>`）——只按 bundle-id 找必然漏；
2. 沙盒应用的数据全在 `~/Library/Containers/<bundle-id>`；
3. `HTTPStorages` 下常见的是 `<bundle-id>.binarycookies` **文件**，不是同名目录；
4. 开机项是**带点边界的文件名前缀**（`<id>.helper.plist` 算，`<id>2.plist` 不算）；
5. 系统级残留（`/Library`、安装收据）需要管理员权限，所以与用户域**分开收集**。

名称匹配天然有误伤风险，因此三层约束：**目录名完全相等**（不做前缀/模糊）、**名称短于 4 字符跳过**、
结果标 `confidence="exact" | "name-match"`，让界面能把两者分开、默认不勾名称匹配项。
"""
from __future__ import annotations

import hashlib
import errno
import os
import plistlib
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .leftover_rules import rule_candidates
from .core import _allocated_bytes, _protected_session_reason

TRASH_DIRNAME = ".Trash"

# 用户域里按 bundle-id 精确命中的位置（kind 供界面分组显示）。
RELATED_SPECS: tuple[tuple[str, str], ...] = (
    ("Application Support", "app-support"),
    ("Caches", "caches"),
    ("Logs", "logs"),
    ("Containers", "container"),
    ("Application Scripts", "application-scripts"),
    ("HTTPStorages", "http-storages"),
    ("WebKit", "webkit"),
)

# 系统级位置：需要一次管理员授权才能清。
SYSTEM_LIBRARY_SPECS: tuple[tuple[str, str], ...] = (
    ("Application Support", "application-support-system"),
    ("Caches", "cache-system"),
    ("Preferences", "preferences-system"),
    ("LaunchAgents", "launch-agent-system"),
    ("LaunchDaemons", "launch-daemon-system"),
)

_MIN_NAME_LENGTH = 4


def item_id(path: str) -> str:
    """计划项的稳定短 id。

    页面/agent 勾选时只回传这些 id —— **调用方从不传路径**，服务端再用"本会话冻结的计划"里的 id
    求交集，这样即便请求被篡改也换不掉要删的路径。
    """
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _normalized(path: Path | str) -> Path:
    """统一路径写法（2026-10-18）。

    为什么必须统一：计划项的 `id = sha1(path)`，而 macOS 上同一目录可能写成 `/var/...` 或
    `/private/var/...`；两种写法会算出**不同 id**，勾选就对不上（CLI 冒烟时实测到：应用本体是
    `/var/...`、残留项是 `/private/var/...`）。这里用 `abspath` 统一，但**不**用 `resolve()`
    ——后者会把 `/var/folders/...` 改写成 `/private/var/...`，等于替用户改写他自己的路径。
    """
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _entry(path: Path, kind: str, confidence: str, *, requires_admin: bool = False) -> dict[str, Any]:
    path = _normalized(path)
    return {
        "id": item_id(str(path)),
        "path": str(path),
        "kind": kind,
        "allocated_bytes": _allocated_bytes(path),
        "confidence": confidence,
        "requires_admin": requires_admin,
    }


def _point_bounded_files(base: Path, bundle_id: str) -> list[Path]:
    """开机项按点边界匹配：`<id>.plist` 或 `<id>.<something>`，不匹配 `<id>2.plist`。"""
    try:
        items = sorted(base.glob(f"{bundle_id}*")) if base.is_dir() else []
    except OSError:
        return []
    return [item for item in items if item.name == f"{bundle_id}.plist" or item.name.startswith(f"{bundle_id}.")]


def discover_related_paths(*, home: Path, bundle_id: str, app_name: str = "") -> list[dict[str, Any]]:
    """用户域残留（bundle-id 精确项 + 名称匹配项 + 沙盒容器）。"""
    home = Path(home)
    library = home / "Library"
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path: Path, kind: str, confidence: str) -> None:
        key = str(path)
        if key in seen or not _exists(path):
            return
        seen.add(key)
        found.append(_entry(path, kind, confidence))

    if bundle_id:
        for folder, kind in RELATED_SPECS:
            add(library / folder / bundle_id, kind, "exact")
        add(library / "Group Containers" / bundle_id, "group-container", "exact")
        add(library / "Saved Application State" / f"{bundle_id}.savedState", "saved-state", "exact")
        add(library / "Preferences" / f"{bundle_id}.plist", "preferences", "exact")
        add(library / "Cookies" / f"{bundle_id}.binarycookies", "cookies", "exact")
        # HTTPStorages 下常见的是带后缀的**文件**，同名目录往往不存在。
        add(library / "HTTPStorages" / f"{bundle_id}.binarycookies", "http-storages-cookies", "exact")
        for item in _point_bounded_files(library / "LaunchAgents", bundle_id):
            add(item, "launch-agent", "exact")
        # 变体规则（Sparkle 的 .ShipIt、自带更新器缓存等）：来自真实采样，不是拍脑袋。
        for hit in rule_candidates(home, bundle_id):
            add(Path(hit["path"]), hit["kind"], hit["confidence"])

    name = (app_name or "").strip()
    if len(name) >= _MIN_NAME_LENGTH:
        # `suffix` 表达"目录名 = 名字 + 后缀"（.plist / .savedState），其余是纯目录名完全相等。
        for folder, suffix, kind in (
            ("Application Support", "", "application-support-name"),
            ("Caches", "", "cache-name"),
            ("Logs", "", "log-name"),
            ("Preferences", ".plist", "preferences-name"),
            ("WebKit", "", "webkit-name"),
            ("HTTPStorages", "", "http-storages-name"),
            ("Saved Application State", ".savedState", "saved-state-name"),
        ):
            add(library / folder / f"{name}{suffix}", kind, "name-match")

    return found


def discover_system_related_paths(
    *,
    bundle_id: str,
    app_name: str = "",
    library_root: Path | None = None,
    receipts_root: Path | None = None,
) -> list[dict[str, Any]]:
    """系统级残留（`/Library` + 安装收据）。全部标 `requires_admin`。"""
    if not bundle_id and not app_name:
        return []
    library = Path(library_root) if library_root is not None else Path("/Library")
    receipts = Path(receipts_root) if receipts_root is not None else Path("/private/var/db/receipts")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(path: Path, kind: str) -> None:
        key = str(path)
        if key in seen or not _exists(path):
            return
        seen.add(key)
        found.append(_entry(path, kind, "exact", requires_admin=True))

    if bundle_id:
        for folder, kind in SYSTEM_LIBRARY_SPECS:
            add(library / folder / bundle_id, kind)
            if folder in ("LaunchAgents", "LaunchDaemons"):
                for item in _point_bounded_files(library / folder, bundle_id):
                    add(item, kind)
        try:
            tickets = sorted(receipts.glob(f"{bundle_id}*")) if receipts.is_dir() else []
        except OSError:
            tickets = []
        for ticket in tickets:
            add(ticket, "install-receipt")

    name = (app_name or "").strip()
    if len(name) >= _MIN_NAME_LENGTH:
        for folder, kind in (("Application Support", "application-support-system"), ("Logs", "log-system")):
            candidate = library / folder / name
            if _exists(candidate):
                key = str(candidate)
                if key not in seen:
                    seen.add(key)
                    found.append(_entry(candidate, kind, "name-match", requires_admin=True))
    return found


def _total(items: Iterable[dict[str, Any]]) -> int:
    return sum(int(item.get("allocated_bytes", 0) or 0) for item in items)


def build_plan(
    app: dict[str, Any],
    *,
    home: Path | None = None,
    library_root: Path | None = None,
    receipts_root: Path | None = None,
) -> dict[str, Any]:
    """生成卸载计划（只读）。

    `app` 需要 `path` / `bundle_id` / `name`；`home` 缺省取当前用户主目录。
    计划里每项都带稳定 `id`，供调用方只回传 id（不传路径）。
    """
    home_path = _normalized(app.get("home") or home or Path.home())
    bundle_id = str(app.get("bundle_id") or "").strip()
    app_name = str(app.get("name") or "").strip()
    app_path = str(_normalized(app["path"])) if str(app.get("path") or "").strip() else ""

    items: list[dict[str, Any]] = []
    if app_path and _exists(Path(app_path)):
        bundle_entry = _entry(Path(app_path), "app-bundle", "exact")
        items.append(bundle_entry)
    items.extend(discover_related_paths(home=home_path, bundle_id=bundle_id, app_name=app_name))

    system_items = discover_system_related_paths(
        bundle_id=bundle_id,
        app_name=app_name,
        library_root=library_root,
        receipts_root=receipts_root,
    )

    user_items = [item for item in items if not item.get("requires_admin")]
    digest = hashlib.sha256(
        "".join(sorted(str(item["path"]) for item in items)).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "app": {"path": app_path, "bundle_id": bundle_id, "name": app_name},
        "items": items,
        "system_items": system_items,
        "user_total_bytes": _total(user_items),
        "system_total_bytes": _total(system_items),
        "user_count": len(user_items),
        "system_count": len(system_items),
        "plan_hash": digest,
    }


def _trash_dir(home: Path) -> Path:
    return _normalized(home) / TRASH_DIRNAME


def _move_to_trash(path: Path, trash: Path) -> Path:
    """移入废纸篓，重名自动加序号（绝不覆盖废纸篓里已有的东西）。"""
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{path.name}"
    target = trash / base
    counter = 1
    while target.exists() or target.is_symlink():
        target = trash / f"{base}-{counter}"
        counter += 1
    # **同卷 rename 优先**：只要求"父目录可写"，不需要读包内文件。
    # `shutil.move` 在同卷时会先试 rename，失败后退化成 copytree+rmtree；
    # 对 `/Applications` 里 root 拥有的包，rename 本该成功，但 shutil 的退化路径
    # 会去读/删包内 root 文件 → `PermissionError: Cannot move the non-empty directory`
    # （2026-10-23 用户截图：同花顺卸载"完成 0 项、失败 2 项"）。
    try:
        os.rename(path, target)
        return target
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    # 真的跨卷（EXDEV）才复制——这时无法避免读内容。
    shutil.move(str(path), str(target))
    return target


def apply_plan(
    plan: dict[str, Any],
    *,
    home: Path | None = None,
    selected_ids: Sequence[str] | None = None,
    dry_run: bool = False,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """执行卸载计划：**只移勾选项、只移用户域**，一律移入废纸篓（可恢复）。

    安全口径（与发现侧同源，不另造一套）：

    1. `selected_ids` 为 `None` 表示全选；传了就只保留**冻结计划里存在**的 id——
       调用方换不掉路径（哪怕直接塞路径字符串，也匹配不到任何 id）；
    2. 空选 → `refused`，**一个都不动**；
    3. 系统级项（`requires_admin`）**一律不动**，交给 `apply_system_leftovers`；
    4. 命中内核的受保护路径（`.ssh`、钥匙串、浏览器身份数据…）→ 跳过并记原因；
    5. `dry_run` 只回清单，不移动任何东西。
    """
    home_path = _dict_home(plan, home)
    items = [item for item in (plan.get("items") or []) if isinstance(item, dict)]
    user_items = [item for item in items if not item.get("requires_admin")]

    if selected_ids is not None:
        wanted = {str(value) for value in selected_ids}
        user_items = [item for item in user_items if str(item.get("id", "")) in wanted]
        if not user_items:
            return {"status": "refused", "reason": "nothing selected", "moved": [], "skipped": []}
    if not user_items:
        # 计划里只有系统级项时，user 域无事可做——报 applied 会让人以为"清过了"。
        return {"status": "refused", "reason": "no user-scope items", "moved": [], "skipped": []}

    would_move: list[str] = []
    skipped: list[dict[str, str]] = []
    for item in user_items:
        path = Path(str(item.get("path", "")))
        reason = _protected_session_reason(path)
        if reason:
            skipped.append({"path": str(path), "reason": reason})
            continue
        if not _exists(path):
            skipped.append({"path": str(path), "reason": "already gone"})
            continue
        would_move.append(str(path))

    if dry_run:
        return {"status": "dry-run", "would_move": would_move, "skipped": skipped, "moved": []}

    trash = _trash_dir(home_path)
    moved: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    cancelled = False
    for index, path_text in enumerate(would_move):
        if should_stop is not None and should_stop():
            cancelled = True
            remaining = would_move[index:]
            break
        source = Path(path_text)
        try:
            destination = _move_to_trash(source, trash)
        except OSError as exc:
            # **报错不等于没卸掉**：如果源已经不在了，说明它其实已经被移走
            # （前一次尝试成功、或用户手动拖走、或 Finder 代劳时我们没拿到返回）。
            # 之前这里一律记 failed，于是界面上"完成 0 项"、而 App 其实早没了
            # （2026-10-23 验收发现：/Applications/同花顺.app 已消失，结果页仍报失败）。
            if not _exists(source):
                moved.append({"path": path_text, "trash_path": "", "note": "already gone"})
                continue
            failed.append({"path": path_text, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        moved.append({"path": path_text, "trash_path": str(destination)})

    status = "applied" if not failed else ("failed" if not moved else "partial")
    payload = {
        "status": status,
        "moved": moved,
        "moved_count": len(moved),
        "skipped": skipped,
        "failed": failed,
        "failed_count": len(failed),
        "trash_dir": str(trash),
    }
    if cancelled:
        payload["status"] = "cancelled"
        payload["cancelled"] = True
        payload["remaining"] = remaining
    return payload


def _dict_home(plan: dict[str, Any], home: Path | None) -> Path:
    app = plan.get("app") if isinstance(plan.get("app"), dict) else {}
    return _normalized(home or app.get("home") or Path.home())


def build_admin_command(paths: Sequence[str]) -> list[str]:
    """一次管理员调用：`osascript ... with administrator privileges` 里跑 `rm -rf -- <quoted>`。"""
    quoted = " ".join(shlex.quote(str(path)) for path in paths)
    script = f'/bin/rm -rf -- {quoted}'
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    return ["/usr/bin/osascript", "-e", f'do shell script "{escaped}" with administrator privileges']


def _admin_guard(paths: Sequence[str]) -> tuple[list[str], str]:
    """代跑前的硬性校验：绝对路径、拒绝 `/`、拒绝 `..`、拒绝空。"""
    cleaned: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            return [], "empty path"
        if not text.startswith("/"):
            return [], f"relative path refused: {text}"
        if ".." in Path(text).parts:
            return [], f"parent traversal refused: {text}"
        if text.rstrip("/") == "":
            return [], "refusing to remove /"
        cleaned.append(text)
    return cleaned, ""


def _exec(execute: Any, argv: Sequence[str], *, timeout: float | None = None) -> Any:
    if callable(execute):
        return execute(argv, capture_output=True, text=True, timeout=timeout)
    method = getattr(execute, "run", None)
    if method is None:
        raise TypeError("runner 既不可调用也没有 .run()")
    try:
        return method(argv, timeout=timeout)
    except TypeError:
        return method(argv)


def apply_system_leftovers(
    paths: Sequence[str],
    *,
    runner: Any | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """代跑系统级残留：一次授权、逐条校验、失败要记录（不吞）。"""
    cleaned, error = _admin_guard(paths)
    if error:
        return {"status": "refused", "reason": error, "paths": [], "command": []}
    if not cleaned:
        return {"status": "refused", "reason": "nothing selected", "paths": [], "command": []}
    command = build_admin_command(cleaned)
    if dry_run:
        return {"status": "dry-run", "paths": cleaned, "command": command}

    # 快照必须在**执行之前**：命令跑完路径就没了，之后再数只会得到 0，
    # 回执就会撒谎说"一项都没删"。这个错在 maho 里踩过一次，移植时又写反了一次。
    pre_existing = [path for path in cleaned if os.path.lexists(path)]
    execute = runner or subprocess.run
    try:
        completed = _exec(execute, command, timeout=180)
    except (OSError, subprocess.SubprocessError, TypeError) as exc:
        return {
            "status": "failed",
            "paths": cleaned,
            "command": command,
            "error": f"{type(exc).__name__}: {exc}",
            "remaining": pre_existing,
            "removed_count": 0,
            "pre_existing_count": len(pre_existing),
        }
    code = int(getattr(completed, "returncode", 0) or 0)
    stderr = str(getattr(completed, "stderr", "") or "").strip()
    remaining = [path for path in pre_existing if os.path.lexists(path)]
    return {
        "status": "applied" if code == 0 else "failed",
        "paths": cleaned,
        "command": command,
        "exit_code": code,
        "error": stderr[:400],
        "remaining": remaining,
        "removed_count": len(pre_existing) - len(remaining),
        "pre_existing_count": len(pre_existing),
    }


def summarize(plan: dict[str, Any]) -> dict[str, Any]:
    """给 CLI / MCP 的紧凑视图：只回答"有多少、多大、要不要管理员"。"""
    return {
        "app": plan.get("app", {}),
        "user_count": plan.get("user_count", 0),
        "user_total_bytes": plan.get("user_total_bytes", 0),
        "system_count": plan.get("system_count", 0),
        "system_total_bytes": plan.get("system_total_bytes", 0),
        "needs_admin": bool(plan.get("system_count", 0)),
        "plan_hash": plan.get("plan_hash", ""),
    }


__all__ = [
    "RELATED_SPECS",
    "SYSTEM_LIBRARY_SPECS",
    "apply_plan",
    "apply_system_leftovers",
    "build_admin_command",
    "build_plan",
    "discover_related_paths",
    "discover_system_related_paths",
    "item_id",
    "read_app_identity",
    "render_plan_text",
    "summarize",
]

def read_app_identity(app_path: str | Path) -> dict[str, str]:
    """从 `.app/Contents/Info.plist` 读 bundle-id 与显示名（读不到就返回空字段）。

    为什么不要求调用方必填：命令行里人只会给一个 `.app` 路径；让工具自己去读，
    比要求手敲 `--bundle-id` 可靠得多（敲错一个字符就会漏掉全部残留）。
    """
    path = Path(app_path)
    identity = {"path": str(path), "bundle_id": "", "name": path.stem}
    plist_path = path / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as handle:
            data = plistlib.load(handle)
    except Exception:  # noqa: BLE001 - 见下
        # **故意宽捕获**：Info.plist 可能是坏 XML（`xml.parsers.expat.ExpatError`）、
        # 二进制格式、权限不足……任何一种都不该让"列应用"整体失败。
        # 2026-10-19 实测：本机某个 app 的 plist 损坏 → 异常穿透到会话 → 页面显示"共 0 个应用"。
        return identity
    if isinstance(data, dict):
        identity["bundle_id"] = str(data.get("CFBundleIdentifier") or "").strip()
        identity["name"] = str(data.get("CFBundleName") or data.get("CFBundleDisplayName") or path.stem).strip()
        # macOS 官方的应用分类（同一套 App Store 分类），用来按类别分组而不是按字母。
        identity["category"] = str(data.get("LSApplicationCategoryType") or "").strip()
    return identity


def render_plan_text(plan: dict[str, Any]) -> str:
    """人读的计划文本（CLI 默认输出；`--json` 时走结构化）。"""
    app = plan.get("app") or {}
    lines = [
        f"应用: {app.get('name') or '(未知)'}  {app.get('bundle_id') or '(无 bundle id)'}",
        f"路径: {app.get('path') or '(未提供)'}",
        "",
        f"用户域: {plan.get('user_count', 0)} 项，约 {int(plan.get('user_total_bytes', 0)) / 1048576:.1f} MiB",
    ]
    for item in plan.get("items") or []:
        mark = "*" if item.get("confidence") == "name-match" else "-"
        lines.append(f"  {mark} [{item.get('kind')}] {item.get('path')}")
    if plan.get("system_count"):
        lines.append("")
        lines.append(
            f"系统级: {plan.get('system_count', 0)} 项（需要管理员权限），约 "
            f"{int(plan.get('system_total_bytes', 0)) / 1048576:.1f} MiB"
        )
        for item in plan.get("system_items") or []:
            lines.append(f"  ! [{item.get('kind')}] {item.get('path')}")
    lines.append("")
    lines.append(f"plan_hash: {plan.get('plan_hash', '')}")
    lines.append("说明: 本命令**只列出**，不删除任何东西。`*` 表示按应用名匹配，可能是别的应用。")
    return "\n".join(lines)
