"""第三方软件更新：只读发现 + 分组执行（2026-10-18 迁入）。

范围**只有第三方**：Homebrew（formula / cask）与 App Store（`mas`）。
**完全不碰 macOS 系统更新**——系统更新有自己的机制与重启语义，混进来只会让"代装"变成危险操作。

两个来源各自独立：某个 CLI 不在或报错，只记一条 note，不影响另一个来源。
解析不认识就返回空——**宁可少报，不瞎报**。

执行侧的原则：
1. 按**可执行组**跑（`brew upgrade a b` / `brew upgrade --cask x` / `mas upgrade 1 2`），
   而不是逐条，命令少且能在执行前把"将执行的确切命令"给人看；
2. **一组失败不拖累其它组**，结果按组记录 exit code 与输出尾部；
3. `dry_run` 只回命令、**不执行**——CLI 默认走 dry-run，`--apply` 才真跑。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

BREW_CANDIDATES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
# mas 与 brew 一样有 Apple Silicon / Intel 两种默认前缀；写死一个在另一种机器上必然找不到。
MAS_CANDIDATES = ("/opt/homebrew/bin/mas", "/usr/local/bin/mas")

SCOPE_NOTE = "third-party only (brew + mas); macOS system updates are out of scope"


def _resolve(name: str) -> str:
    """优先固定路径（PATH 里常常没有 `/opt/homebrew/bin`），再退回 PATH 查找。"""
    if name == "brew":
        for candidate in BREW_CANDIDATES:
            if Path(candidate).exists() or shutil.which(candidate):
                return candidate
        return ""
    if name == "mas":
        for candidate in MAS_CANDIDATES:
            if Path(candidate).exists():
                return candidate
        return shutil.which("mas") or ""
    return shutil.which(name) or ""


def _exec(execute: Any, argv: Sequence[str], *, timeout: float | None = None) -> Any:
    """统一两种 runner：可调用对象（测试注入）与带 `.run()` 的对象（会话里的 runner）。

    这在 maho 里踩过一次真机崩溃：`CommandRunner` **不可调用**、`.run()` 还不接受 `timeout`，
    直接 `runner(argv, ...)` 会 TypeError 把整个会话打成失败。这里一次处理掉两种形态。
    """
    if callable(execute):
        return execute(argv, capture_output=True, text=True, timeout=timeout)
    method = getattr(execute, "run", None)
    if method is None:
        raise TypeError("runner 既不可调用也没有 .run()")
    try:
        return method(argv, timeout=timeout)
    except TypeError:
        return method(argv)


def _run(argv: Sequence[str], *, runner: Any | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
    execute = runner or subprocess.run
    try:
        completed = _exec(execute, list(argv), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"
    return (
        int(getattr(completed, "returncode", 1) or 0),
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )


def parse_brew_outdated(payload: str) -> list[dict[str, Any]]:
    """`brew outdated --json=v2` → 统一条目（formula + cask）。形状不认识就返回空。"""
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return []
    items: list[dict[str, Any]] = []
    for key, kind in (("formulae", "formula"), ("casks", "cask")):
        for entry in data.get(key) or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("token") or "").strip()
            if not name:
                continue
            installed = entry.get("installed_versions") or []
            if isinstance(installed, str):
                installed = [installed]
            items.append(
                {
                    "manager": "brew",
                    "kind": kind,
                    "name": name,
                    "installed": str(installed[0]) if installed else "",
                    "available": str(entry.get("current_version") or ""),
                }
            )
    return items


MAS_LINE = re.compile(r"^(?P<app_id>\d+)\s+(?P<name>.+?)\s*\((?P<versions>[^()]*)\)\s*$")


def parse_mas_outdated(payload: str) -> list[dict[str, Any]]:
    """`mas outdated` 的文本输出：`<id> <name> (<old> -> <new>)`。

    2026-10-19 真机抓到的 bug：原来用 `split(None, 2)` 取第二段当名字，
    于是 **"Logic Pro" 被截成 "Logic"**、版本也丢成空——
    按名字过滤（`--only "Logic Pro"`）根本匹配不到，用户只会看到"没有可升级项"。
    这里改用正则：名字允许含空格，版本按 `->` 拆成 installed/available。
    """
    items: list[dict[str, Any]] = []
    for line in (payload or "").splitlines():
        text = line.strip()
        if not text:
            continue
        match = MAS_LINE.match(text)
        if match:
            versions = [part.strip() for part in match.group("versions").split("->")]
            installed = versions[0] if versions else ""
            available = versions[1] if len(versions) > 1 else (versions[0] if versions else "")
            items.append(
                {
                    "manager": "mas",
                    "kind": "app-store",
                    "app_id": match.group("app_id"),
                    "name": match.group("name").strip(),
                    "installed": installed,
                    "available": available,
                }
            )
            continue
        # 没有版本括号的行：仍按 id + 名字收下（不要因为格式少一截就整条丢掉）
        parts = text.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            items.append(
                {
                    "manager": "mas",
                    "kind": "app-store",
                    "app_id": parts[0],
                    "name": parts[1].strip(),
                    "installed": "",
                    "available": "",
                }
            )
    return items


def available_managers() -> dict[str, str]:
    """两个来源是否可用（名称 → 可执行路径，空串表示没有）。"""
    return {"brew": _resolve("brew"), "mas": _resolve("mas")}


def discover_updates(*, runner: Any | None = None) -> dict[str, Any]:
    """只读发现：`{items, count, managers, notes, scope}`；任何一步失败只记 note，不抛出。"""
    managers = available_managers()
    notes: list[str] = []
    items: list[dict[str, Any]] = []

    if managers["brew"]:
        code, out, err = _run([managers["brew"], "outdated", "--json=v2"], runner=runner)
        if code == 0:
            items.extend(parse_brew_outdated(out))
        else:
            notes.append(f"Homebrew 查询失败（exit {code}）：{(err or out).strip()[:200]}")
    else:
        notes.append("未安装 Homebrew：跳过 formula/cask 检查")

    if managers["mas"]:
        code, out, err = _run([managers["mas"], "outdated"], runner=runner)
        if code == 0:
            items.extend(parse_mas_outdated(out))
        else:
            notes.append(f"App Store（mas）查询失败（exit {code}）：{(err or out).strip()[:200]}")
    else:
        notes.append("未安装 mas：跳过 App Store 检查")

    items.sort(key=lambda item: (str(item.get("manager")), str(item.get("name")).lower()))
    return {"items": items, "count": len(items), "managers": managers, "notes": notes, "scope": SCOPE_NOTE}


def select_updates(items: list[dict[str, Any]], wanted: set[str]) -> list[dict[str, Any]]:
    """按名字或 app id 筛选要升级的项；`wanted` 为空表示全选。

    为什么单独抽出来：CLI 与 MCP 都要这套匹配规则，写两份必然漂移；
    而且它得能被单测直接钉住（真机 bug 就出在这条规则上）。
    """
    if not wanted:
        return list(items)
    lowered = {name.strip().lower() for name in wanted if name.strip()}
    picked: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "").strip().lower()
        app_id = str(item.get("app_id") or "").strip()
        if name in lowered or app_id in wanted:
            picked.append(item)
    return picked


def build_upgrade_plan(items: Sequence[dict[str, Any]], *, brew: str = "", mas: str = "") -> dict[str, Any]:
    """把选中条目分成可执行组；未知来源忽略并记进 `ignored`（宁可少升，不瞎跑）。"""
    brew_bin = brew or _resolve("brew") or "brew"
    mas_bin = mas or _resolve("mas") or "mas"
    formulae = [
        str(i.get("name")) for i in items if i.get("manager") == "brew" and i.get("kind") == "formula" and i.get("name")
    ]
    casks = [
        str(i.get("name")) for i in items if i.get("manager") == "brew" and i.get("kind") == "cask" and i.get("name")
    ]
    mas_ids = [str(i.get("app_id")) for i in items if i.get("manager") == "mas" and i.get("app_id")]
    ignored = [str(i.get("name") or i.get("app_id") or "") for i in items if i.get("manager") not in ("brew", "mas")]

    groups: list[dict[str, Any]] = []
    if formulae:
        groups.append(
            {
                "manager": "brew",
                "kind": "formula",
                "targets": formulae,
                "argv": [brew_bin, "upgrade", *formulae],
                "command": "brew upgrade " + " ".join(formulae),
            }
        )
    if casks:
        groups.append(
            {
                "manager": "brew",
                "kind": "cask",
                "targets": casks,
                "argv": [brew_bin, "upgrade", "--cask", *casks],
                "command": "brew upgrade --cask " + " ".join(casks),
            }
        )
    if mas_ids:
        groups.append(
            {
                "manager": "mas",
                "kind": "app-store",
                "targets": mas_ids,
                "argv": [mas_bin, "upgrade", *mas_ids],
                "command": "mas upgrade " + " ".join(mas_ids),
            }
        )
    return {"groups": groups, "count": sum(len(g["targets"]) for g in groups), "ignored": ignored}


def apply_updates(plan: dict[str, Any], *, runner: Any | None = None, dry_run: bool = False) -> dict[str, Any]:
    """按组执行更新；一组失败不影响其它组。`dry_run=True` 只回命令、不执行。"""
    groups = [g for g in (plan.get("groups") or []) if isinstance(g, dict) and g.get("argv")]
    if not groups:
        return {"status": "refused", "reason": "nothing selected", "groups": [], "commands": []}
    commands = [str(g.get("command", "")) for g in groups]
    if dry_run:
        return {"status": "dry-run", "groups": groups, "commands": commands}

    execute = runner or subprocess.run
    results: list[dict[str, Any]] = []
    for group in groups:
        argv = [str(part) for part in group["argv"]]
        try:
            completed = _exec(execute, argv, timeout=1800)
            code = int(getattr(completed, "returncode", 1) or 0)
            out = str(getattr(completed, "stdout", "") or "")
            err = str(getattr(completed, "stderr", "") or "")
        except (OSError, subprocess.SubprocessError) as exc:
            code, out, err = 1, "", f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "manager": group.get("manager"),
                "kind": group.get("kind"),
                "targets": group.get("targets"),
                "command": group.get("command"),
                "exit_code": code,
                "stdout_tail": out.strip()[-600:],
                "stderr_tail": err.strip()[-600:],
                "ok": code == 0,
            }
        )

    ok_count = sum(1 for item in results if item["ok"])
    status = "applied" if ok_count == len(results) else ("failed" if ok_count == 0 else "partial")
    return {
        "status": status,
        "groups": results,
        "commands": commands,
        "ok_count": ok_count,
        "total": len(results),
    }


def render_updates_text(payload: dict[str, Any], *, applied: dict[str, Any] | None = None) -> str:
    """人读的输出：先列可升级项，再（可选）列执行结果。"""
    items = payload.get("items") or []
    lines = [f"可升级: {payload.get('count', len(items))} 项（{payload.get('scope', SCOPE_NOTE)}）", ""]
    for item in items:
        transition = f"{item.get('installed') or '?'} -> {item.get('available') or '?'}"
        lines.append(f"  - [{item.get('manager')}/{item.get('kind')}] {item.get('name')}  {transition}")
    for note in payload.get("notes") or []:
        lines.append(f"  ! {note}")
    if applied is not None:
        lines.append("")
        lines.append(f"执行结果: {applied.get('status')}（成功 {applied.get('ok_count', 0)}/{applied.get('total', 0)} 组）")
        for group in applied.get("groups") or []:
            flag = "OK " if group.get("ok") else "FAIL"
            lines.append(f"  [{flag}] {group.get('command')} (exit {group.get('exit_code')})")
            tail = (group.get("stderr_tail") or group.get("stdout_tail") or "").strip()
            if tail:
                lines.append(f"        {tail[:200]}")
    return "\n".join(lines)


__all__ = [
    "SCOPE_NOTE",
    "apply_updates",
    "available_managers",
    "build_upgrade_plan",
    "discover_updates",
    "parse_brew_outdated",
    "parse_mas_outdated",
    "select_updates",
    "render_updates_text",
]
