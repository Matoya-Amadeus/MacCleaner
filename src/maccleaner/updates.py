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
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

BREW_CANDIDATES = ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
# mas 与 brew 一样有 Apple Silicon / Intel 两种默认前缀；写死一个在另一种机器上必然找不到。
MAS_CANDIDATES = ("/opt/homebrew/bin/mas", "/usr/local/bin/mas")

SCOPE_NOTE = "third-party only (brew + mas); macOS system updates are out of scope"


# 额外更新源（对齐 Topgrade 的思路：常见包管理器都覆盖）。
# App 从 Finder 启动时 PATH 很窄（/usr/bin:/bin:...），所以**每个都要给候选绝对路径**。
EXTRA_CANDIDATES: dict[str, tuple[str, ...]] = {
    "npm": ("~/.local/bin/npm", "/opt/homebrew/bin/npm", "/usr/local/bin/npm"),
    "pip3": ("~/.local/bin/pip3", "/opt/homebrew/bin/pip3", "/usr/local/bin/pip3"),
    "gem": ("/usr/bin/gem", "/opt/homebrew/bin/gem"),
    "rustup": ("~/.cargo/bin/rustup", "/opt/homebrew/bin/rustup"),
}

CANDIDATES: dict[str, tuple[str, ...]] = {
    "brew": BREW_CANDIDATES,
    "mas": MAS_CANDIDATES,
    **EXTRA_CANDIDATES,
}


def _resolve(name: str) -> str:
    """优先固定路径（PATH 里常常没有 `/opt/homebrew/bin`、`~/.local/bin`），再退回 PATH。"""
    for candidate in CANDIDATES.get(name, ()):
        expanded = Path(os.path.expanduser(candidate))
        if expanded.exists():
            return str(expanded)
        found = shutil.which(candidate)
        if found:
            return found
    return shutil.which(name) or ""
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


def _tool_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """子进程环境：补齐工具所在目录 + 关掉 brew 的自动更新。

    两个真机 bug 的来源（2026-10-19）：
    ① App 从 Finder 启动时 PATH 只有 `/usr/bin:/bin:...`，而 `npm` 是 `#!/usr/bin/env node`
       的脚本 —— 找到了 npm 也跑不起来，报 `env: node: No such file or directory`。
       所以把每个已解析工具的**父目录**加进 PATH。
    ② `brew outdated` 默认会先自动更新仓库，实测 4.05s → 关掉后 1.60s；
       检查更新不该顺手改 Homebrew 的元数据。
    """
    env = dict(os.environ)
    parts = [env.get("PATH", "")]
    for tool in ("brew", "mas", "npm", "pip3", "gem", "rustup"):
        binary = _resolve(tool)
        if binary:
            parts.append(str(Path(binary).parent))
    parts.extend(["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")])
    env["PATH"] = ":".join(dict.fromkeys(part for part in parts if part))
    env.setdefault("HOMEBREW_NO_AUTO_UPDATE", "1")
    env.setdefault("HOMEBREW_NO_INSTALL_CLEANUP", "1")
    env.setdefault("HOMEBREW_NO_ENV_HINTS", "1")
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


def _run(
    argv: Sequence[str],
    *,
    runner: Any | None = None,
    timeout: float = 120.0,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    if runner is None:
        try:
            completed = subprocess.run(
                list(argv), capture_output=True, text=True, timeout=timeout, env=_tool_env(extra_env)
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, "", f"{type(exc).__name__}: {exc}"
    else:
        try:
            completed = _exec(runner, list(argv), timeout=timeout)
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



def parse_npm_outdated(payload: str) -> list[dict[str, Any]]:
    """`npm outdated -g --json`：`{name: {current, wanted, latest}}`。

    注意：**有更新时 npm 的退出码是 1**（不是错误），所以调用方按 0/1 都算成功。
    """
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    items: list[dict[str, Any]] = []
    for name, info in data.items():
        if not isinstance(info, dict):
            continue
        latest = str(info.get("latest") or "")
        current = str(info.get("current") or info.get("wanted") or "")
        if not latest or latest == current:
            continue
        items.append(
            {"manager": "npm", "kind": "npm-global", "name": str(name),
             "installed": current, "available": latest}
        )
    return items


def parse_pip_outdated(payload: str) -> list[dict[str, Any]]:
    """`pip list --outdated --format=json`：[{name, version, latest_version}]。"""
    try:
        data = json.loads(payload or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        items.append(
            {"manager": "pip", "kind": "pip", "name": str(entry["name"]),
             "installed": str(entry.get("version") or ""),
             "available": str(entry.get("latest_version") or "")}
        )
    return items


GEM_LINE = re.compile(r"^(?P<name>[^\s(]+)\s+\((?P<installed>[^<)\s]+)(?:\s*<\s*(?P<available>[^)]+))?\)")


def parse_gem_outdated(payload: str) -> list[dict[str, Any]]:
    """`gem outdated`：`name (current < latest)` 每行一条。"""
    items: list[dict[str, Any]] = []
    for line in (payload or "").splitlines():
        match = GEM_LINE.match(line.strip())
        if not match:
            continue
        items.append(
            {"manager": "gem", "kind": "gem", "name": match.group("name"),
             "installed": match.group("installed").strip(),
             "available": (match.group("available") or "").strip()}
        )
    return items


RUSTUP_UPDATE = re.compile(
    r"(?P<name>[\w.-]+)\s*-\s*Update available\s*:\s*(?P<installed>[\w.\-]+)\s*->\s*(?P<available>[\w.\-]+)"
)


def parse_rustup_check(payload: str) -> list[dict[str, Any]]:
    """`rustup check` 的更新行：`stable-aarch64-apple-darwin - Update available : 1.89 -> 1.90`。"""
    items: list[dict[str, Any]] = []
    for line in (payload or "").splitlines():
        match = RUSTUP_UPDATE.search(line)
        if match:
            items.append(
                {"manager": "rustup", "kind": "toolchain", "name": match.group("name"),
                 "installed": match.group("installed"), "available": match.group("available")}
            )
    return items


def available_managers() -> dict[str, str]:
    """两个来源是否可用（名称 → 可执行路径，空串表示没有）。"""
    managers = {"brew": _resolve("brew"), "mas": _resolve("mas")}
    for extra in ("npm", "pip3", "gem", "rustup"):
        managers[extra] = _resolve(extra)
    return managers


SOURCES: tuple[dict[str, Any], ...] = (
    {"tool": "brew", "argv": ["outdated", "--json=v2"], "parser": "parse_brew_outdated",
     "label": "Homebrew", "timeout": 60.0, "ok_codes": (0,), "default": True},
    {"tool": "mas", "argv": ["outdated"], "parser": "parse_mas_outdated",
     "label": "App Store（mas）", "timeout": 15.0, "ok_codes": (0,), "default": True},
    {"tool": "npm", "argv": ["outdated", "-g", "--json"], "parser": "parse_npm_outdated",
     "label": "npm 全局包", "timeout": 20.0, "ok_codes": (0, 1), "default": True},
    {"tool": "rustup", "argv": ["check"], "parser": "parse_rustup_check",
     "label": "Rust 工具链", "timeout": 20.0, "ok_codes": (0,), "default": True},
    # pip / gem 要联网到 PyPI / rubygems，实测各要 20s+（国内网络常常超时）；
    # 默认关闭，用 MACCLEANER_UPDATE_SOURCES=brew,mas,npm,pip,gem 显式打开。
    {"tool": "pip3", "argv": ["list", "--outdated", "--format=json", "--disable-pip-version-check"],
     "parser": "parse_pip_outdated", "label": "Python 包", "timeout": 25.0,
     "ok_codes": (0,), "default": False},
    {"tool": "gem", "argv": ["outdated"], "parser": "parse_gem_outdated",
     "label": "Ruby gem", "timeout": 25.0, "ok_codes": (0,), "default": False},
)


UPDATES_CACHE_SECONDS = 120


def _updates_cache_path(state_root: Path) -> Path:
    return Path(state_root) / "updates-cache.json"


def updates_report(
    *, state_root: Path | None = None, force: bool = False, ttl: int = UPDATES_CACHE_SECONDS
) -> dict[str, Any]:
    """带缓存的更新检查。

    为什么要缓存：一次检查要跑 brew/mas/npm 等外部命令（实测 1.6–6s），
    用户来回切页签时不该每次都重跑；但**必须诚实**——返回 `checked_at`，
    页面写明"数据来自 HH:MM"，【重新检查】强制绕过缓存。
    """
    cache_file = _updates_cache_path(state_root) if state_root is not None else None
    if cache_file is not None and not force:
        try:
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entry = None
        if isinstance(entry, dict):
            age = time.time() - float(entry.get("checked_at") or 0)
            if 0 <= age <= ttl:
                payload = entry.get("report") or {}
                if isinstance(payload, dict):
                    return {**payload, "checked_at": float(entry.get("checked_at") or 0), "cached": True}

    report = discover_updates()
    checked_at = time.time()
    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"checked_at": checked_at, "report": report}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, cache_file)
        except OSError:
            pass
    return {**report, "checked_at": checked_at, "cached": False}


def _system_proxy_state() -> dict[str, str]:
    """读系统代理配置（`scutil --proxy`），用于把 mas 的失败翻译成人话。"""
    try:
        out = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    state: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in {"SOCKSEnable", "SOCKSPort", "SOCKSProxy", "HTTPEnable", "HTTPPort", "HTTPProxy",
                   "HTTPSEnable", "HTTPSPort", "HTTPSProxy"}:
            state[key] = value
    return state


def _proxy_hint() -> str:
    """如果系统代理开着，回一句"代理不可用"的提示；否则空串。"""
    state = _system_proxy_state()
    if not state:
        return ""
    if state.get("SOCKSEnable") == "1":
        host = state.get("SOCKSProxy", "127.0.0.1")
        port = state.get("SOCKSPort", "")
        return f"系统 SOCKS 代理 {host}:{port} 启用中但连不上（代理进程没开？）"
    if state.get("HTTPEnable") == "1" or state.get("HTTPSEnable") == "1":
        host = state.get("HTTPSProxy") or state.get("HTTPProxy") or "127.0.0.1"
        port = state.get("HTTPSPort") or state.get("HTTPPort") or ""
        return f"系统 HTTP(S) 代理 {host}:{port} 启用中但连不上"
    return ""


MAS_LIST = re.compile(r"^\s*(?P<app_id>\d+)\s+(?P<name>.+?)\s+\((?P<version>[^)]*)\)\s*$")


def parse_mas_list(payload: str) -> list[dict[str, str]]:
    """`mas list`（**本地库**，不需要网络）：`<id> <名字> (<版本>)`。"""
    items: list[dict[str, str]] = []
    for line in (payload or "").splitlines():
        match = MAS_LIST.match(line)
        if match:
            items.append(
                {
                    "app_id": match.group("app_id"),
                    "name": match.group("name").strip(),
                    "installed": match.group("version").strip(),
                }
            )
    return items


def _version_tuple(text: str) -> tuple[int, ...]:
    """把 `1.2.3` / `10.4.14` 变成可比较的元组；非数字段退回 0。"""
    parts: list[int] = []
    for chunk in re.split(r"[.\-]", str(text or "")):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    # 去掉尾部 0：`1.0` 与 `1` 是同一个版本，不该判成"有更新"。
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def app_store_outdated_via_lookup(
    *, store: str = "CN", timeout: float = 3.0, limit: int = 40
) -> list[dict[str, Any]]:
    """不依赖 mas 联网的 App Store 更新发现：`mas list`（本地）+ iTunes 公开查询。

    为什么要这条兜底：`mas outdated` 走 URLSession，会跟随**系统代理**；
    代理不可用时整条链路就断了（实测），但其实"有没有新版本"用公开 API 就能问。
    注意：这里只解决**发现**，真正升级仍必须 `mas upgrade`（需要 App Store 登录与可用网络）。
    """
    import urllib.parse
    import urllib.request

    binary = _resolve("mas")
    if not binary:
        return []
    code, out, _ = _run([binary, "list"], timeout=15)
    if code != 0:
        return []
    installed = parse_mas_list(out)[:limit]

    store_code = store
    code, config_out, _ = _run([binary, "config"], timeout=10)
    if code == 0:
        for line in config_out.splitlines():
            if line.strip().startswith("store"):
                store_code = line.split()[-1].strip() or store_code

    items: list[dict[str, Any]] = []
    # 直连：为的是**绕过**系统代理（代理坏了，但直连是通的）。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for entry in installed:
        query = urllib.parse.urlencode(
            {"id": entry["app_id"], "country": store_code, "entity": "desktopSoftware", "media": "software"}
        )
        try:
            with opener.open(f"https://itunes.apple.com/lookup?{query}", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - 单个应用查不到就跳过，不要毁掉整页
            continue
        results = payload.get("results") or []
        if not results:
            continue
        latest = str(results[0].get("version") or "")
        if not latest:
            continue
        if _version_tuple(latest) > _version_tuple(entry["installed"]):
            items.append(
                {
                    "manager": "mas",
                    "kind": "app-store",
                    "app_id": entry["app_id"],
                    "name": results[0].get("trackName") or entry["name"],
                    "installed": entry["installed"],
                    "available": latest,
                    "source": "itunes-lookup",
                }
            )
    return items


def _enabled_sources() -> list[dict[str, Any]]:
    """按 `MACCLEANER_UPDATE_SOURCES`（逗号分隔）挑源；未设置时用各自的 default。"""
    raw = os.environ.get("MACCLEANER_UPDATE_SOURCES", "").strip()
    if not raw:
        return [dict(source) for source in SOURCES if source.get("default")]
    wanted = {part.strip().lower() for part in raw.split(",") if part.strip()}
    picked = []
    for source in SOURCES:
        tool = source["tool"].lower()
        # pip3 与 pip 视为同一个源（用户可能写 pip，也可能写 pip3）。
        names = {tool, tool.removesuffix("3"), f"{tool}3" if not tool.endswith("3") else tool}
        if names & wanted:
            picked.append(dict(source))
    return picked


def discover_updates(*, runner: Any | None = None) -> dict[str, Any]:
    """只读发现：`{items, count, managers, notes, scope}`；任何一步失败只记 note，不抛出。

    六个源**并行**查：串行时 `pip`/`gem` 各自超时会拖到 4 分钟（2026-10-19 实测 241s）。
    并行的总耗时约等于最慢的那个源（默认最慢 25s），且每源有独立超时，一个卡住不影响别人。
    """
    from concurrent.futures import ThreadPoolExecutor

    managers = available_managers()
    notes: list[str] = []
    items: list[dict[str, Any]] = []
    sources = _enabled_sources()

    def probe(source: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        tool = str(source["tool"])
        binary = managers.get(tool) or ""
        if not binary:
            return [], f"未安装 {tool}：跳过{source['label']}检查"
        code, out, err = _run([binary, *source["argv"]], runner=runner, timeout=float(source["timeout"]))
        if code in source["ok_codes"]:
            parser = globals().get(str(source["parser"]))
            return (parser(out) if callable(parser) else []), ""
        detail = (err or out).strip()[:160]
        if tool == "mas" and ("NSURLError" in detail or code == 6):
            # 实测最常见的不是"没登录"，而是**系统代理开着但代理进程没运行**：
            # mas 的 URLSession 跟随系统代理，curl 直连却是通的。
            hint = _proxy_hint() or "可能未登录 App Store 或网络受限"
            return [], f"App Store（mas）查询失败：{hint}（exit {code}）"
        if code == 1 and "Timeout" in detail:
            return [], f"{source['label']} 超时（{int(source['timeout'])}s，多半是网络）：{detail[:80]}"
        return [], f"{source['label']} 查询失败（exit {code}）：{detail}"

    if sources:
        with ThreadPoolExecutor(max_workers=min(6, len(sources))) as pool:
            for parsed, note in pool.map(probe, sources):
                items.extend(parsed)
                if note:
                    notes.append(note)

    # App Store 兜底：mas 联网失败（代理/网络）时，用本地库 + 公开查询仍然把"有更新"列出来。
    if not any(item.get("manager") == "mas" for item in items):
        fallback = app_store_outdated_via_lookup()
        if fallback:
            items.extend(fallback)
            notes.append("mas 联网不可用，App Store 更新改用公开查询发现（升级仍需 App Store 可用）")

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
    ignored = [
        str(i.get("name") or i.get("app_id") or "")
        for i in items
        if i.get("manager") not in ("brew", "mas", "npm", "pip", "gem", "rustup")
    ]

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
    # 额外源：按 manager 分组；都只升级**点名的**那些。
    npm_names = [str(i.get("name")) for i in items if i.get("manager") == "npm" and i.get("name")]
    pip_names = [str(i.get("name")) for i in items if i.get("manager") == "pip" and i.get("name")]
    gem_names = [str(i.get("name")) for i in items if i.get("manager") == "gem" and i.get("name")]
    rustup_names = [str(i.get("name")) for i in items if i.get("manager") == "rustup" and i.get("name")]
    if npm_names:
        binary = _resolve("npm") or "npm"
        specs = [f"{name}@latest" for name in npm_names]
        groups.append({"manager": "npm", "kind": "npm-global", "targets": npm_names,
                       "argv": [binary, "install", "-g", *specs],
                       "command": "npm install -g " + " ".join(specs)})
    if pip_names:
        binary = _resolve("pip3") or "pip3"
        groups.append({"manager": "pip", "kind": "pip", "targets": pip_names,
                       "argv": [binary, "install", "--upgrade", *pip_names],
                       "command": "pip3 install --upgrade " + " ".join(pip_names)})
    if gem_names:
        binary = _resolve("gem") or "gem"
        groups.append({"manager": "gem", "kind": "gem", "targets": gem_names,
                       "argv": [binary, "update", *gem_names],
                       "command": "gem update " + " ".join(gem_names)})
    if rustup_names:
        binary = _resolve("rustup") or "rustup"
        groups.append({"manager": "rustup", "kind": "toolchain", "targets": rustup_names,
                       "argv": [binary, "update"], "command": "rustup update"})

    return {"groups": groups, "count": sum(len(g["targets"]) for g in groups), "ignored": ignored}


def apply_updates(plan: dict[str, Any], *, runner: Any | None = None, dry_run: bool = False) -> dict[str, Any]:
    """按组执行更新；一组失败不影响其它组。`dry_run=True` 只回命令、不执行。"""
    groups = [g for g in (plan.get("groups") or []) if isinstance(g, dict) and g.get("argv")]
    if not groups:
        return {"status": "refused", "reason": "nothing selected", "groups": [], "commands": []}
    commands = [str(g.get("command", "")) for g in groups]
    if dry_run:
        return {"status": "dry-run", "groups": groups, "commands": commands}

    results: list[dict[str, Any]] = []
    for group in groups:
        argv = [str(part) for part in group["argv"]]
        code, out, err = _run(argv, runner=runner, timeout=1800)
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
