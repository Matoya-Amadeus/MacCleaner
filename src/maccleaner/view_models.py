"""内核 → 界面的**视图模型**：分组、排序、口径，全在这一层。

为什么要把它从 `ui/pages.py` 里搬出来（2026-10-22，M2 前置）：
界面正在换成 SwiftUI，如果分组规则留在 HTML 那一层，Swift 侧就必须**复制一份**同样的规则
（哪些类别归到"开发工具"、更新按来源怎么分组、残留按哪个目录分桶）——两份规则早晚分叉。
搬进内核后，界面只负责画，规则只有一处。

这一层**不产出 HTML**，只产出结构化数据（`groups` + `items`），HTML 版与原生版共用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------- 清理候选分组

# 顺序即展示顺序：越靠前越"该被看到"。
REVIEW_GROUPS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("system", "系统数据", "需管理员权限，本工具只测量不删除", ()),
    ("browser", "浏览器", "浏览器留下的缓存（不含 Cookies / 登录数据），默认已勾选", ("browser",)),
    ("app", "App 缓存与日志", "应用运行时生成，删了会重建", ("cache", "logs")),
    (
        "dev",
        "开发工具",
        "Xcode / 包管理器 / 编辑器缓存",
        ("xcode", "android", "ios", "ide", "package-cache", "homebrew", "flutter", "browser-cache"),
    ),
    ("containers", "容器与虚拟机", "Docker 等运行时数据，删除后需要重新拉取", ("docker",)),
    ("user", "你的文件", "Downloads、安装包、iOS 备份——删前自己确认", ("user-files",)),
    ("trash", "废纸篓", "清空后不可恢复", ("__trash__",)),
)

_CLEANED_STATES = {"cleaned", "applied", "done", "moved"}


def review_group_for(candidate: dict[str, Any]) -> str:
    """一个候选项归到哪个组。未知类别落到 `app`（别让它凭空消失）。"""
    if str(candidate.get("target_id") or "") == "trash":
        return "trash"
    category = str(candidate.get("kind") or candidate.get("category") or "")
    for key, _label, _hint, categories in REVIEW_GROUPS:
        if category in categories:
            return key
    return "app"


def _plan_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (report.get("plan_items") or []) if isinstance(item, dict)]


def _first_path(item: dict[str, Any]) -> str:
    paths = item.get("paths") or []
    if isinstance(paths, str):
        return paths
    return str(paths[0]) if paths else ""


def review_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    """内核报告 → 审阅候选（只保留**有体量**的条目，避免一屏 0 字节噪声）。"""
    candidates: list[dict[str, Any]] = []
    for item in _plan_items(report):
        estimated = int(item.get("estimated_bytes") or 0)
        if estimated <= 0:
            continue
        candidates.append(
            {
                "path": _first_path(item),
                # target 的**名字**要带上：以前拿路径末级名当标题，多个 "Homebrew" 会显示成同一行。
                "name": str(item.get("name") or ""),
                "kind": str(item.get("category") or item.get("kind") or ""),
                "allocated_bytes": estimated,
                "recoverable": bool(item.get("recoverable")),
                "risk": str(item.get("risk") or "low"),
                "requires_confirmation": bool(item.get("requires_confirmation")),
                "status": str(item.get("status") or ""),
                "target_id": str(item.get("target_id") or ""),
            }
        )
    return candidates


def review_view(report: dict[str, Any]) -> dict[str, Any]:
    """审阅页数据：候选 + **已分好组**（界面不需要知道分类规则）。"""
    candidates = review_candidates(report)
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key, *_rest in REVIEW_GROUPS}
    for candidate in candidates:
        buckets.setdefault(review_group_for(candidate), []).append(candidate)

    groups: list[dict[str, Any]] = []
    for key, label, hint, _categories in REVIEW_GROUPS:
        items = buckets.get(key) or []
        if not items:
            continue
        groups.append(
            {
                "key": key,
                "label": label,
                "hint": hint,
                "count": len(items),
                "bytes": sum(int(item["allocated_bytes"]) for item in items),
                "items": items,
            }
        )
    return {
        "candidates": candidates,
        "groups": groups,
        "count": len(candidates),
        "total_bytes": sum(int(candidate["allocated_bytes"]) for candidate in candidates),
        "mode": str(report.get("mode") or ""),
        "dry_run": bool(report.get("dry_run")),
        "scan_cached_at": float(report.get("scan_cached_at") or 0),
    }


# ---------------------------------------------------------------- 应用分类

# 展示顺序：最常清理的排前面，"其它"垫底。
APP_CATEGORY_ORDER: tuple[str, ...] = (
    "浏览器", "开发工具", "社交与通讯", "效率办公", "设计与图像", "影音", "游戏", "阅读资讯", "系统工具", "其它",
)


def app_category_rank(label: str) -> tuple[int, str]:
    try:
        return (APP_CATEGORY_ORDER.index(label), "")
    except ValueError:
        return (len(APP_CATEGORY_ORDER), label)


def apps_view(apps: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """已安装应用：按 macOS 官方分类分组（浏览器/开发工具/…），顺序固定。"""
    items = [item for item in apps if isinstance(item, dict)]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = str(item.get("category") or "其它")
        buckets.setdefault(key, []).append(item)

    groups = [
        {"label": key, "count": len(buckets[key]), "items": buckets[key]}
        for key in sorted(buckets, key=app_category_rank)
    ]
    return {"apps": items, "groups": groups, "count": len(items)}


# ---------------------------------------------------------------- 更新

UPDATE_GROUP_LABELS: dict[tuple[str, str], str] = {
    ("brew", "formula"): "Homebrew formula",
    ("brew", "cask"): "Homebrew cask",
    ("mas", "app-store"): "App Store",
    ("npm", "npm-global"): "npm 全局包",
    ("pip", "pip"): "Python 包",
    ("gem", "gem"): "Ruby gem",
    ("rustup", "toolchain"): "Rust 工具链",
}

UPDATE_GROUP_ORDER: tuple[str, ...] = (
    "Homebrew formula",
    "Homebrew cask",
    "App Store",
    "npm 全局包",
    "Python 包",
    "Ruby gem",
    "Rust 工具链",
)


def update_group_label(item: dict[str, Any]) -> str:
    manager = str(item.get("manager") or "")
    kind = str(item.get("kind") or "")
    return UPDATE_GROUP_LABELS.get((manager, kind), f"{manager}/{kind}".strip("/"))


def updates_view(found: dict[str, Any]) -> dict[str, Any]:
    """更新清单：按来源分组 + Sparkle **只保留确认有更新**的（其余单列）。"""
    # 给每一项补一个**稳定 id**（manager|kind|name）：界面按分组渲染后回传时不会错位。
    items = [
        {**item, "id": f"{item.get('manager') or ''}|{item.get('kind') or ''}|{item.get('name') or ''}"}
        for item in (found.get("items") or [])
        if isinstance(item, dict)
    ]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(update_group_label(item), []).append(item)

    def rank(label: str) -> tuple[int, str]:
        try:
            return (UPDATE_GROUP_ORDER.index(label), "")
        except ValueError:
            return (len(UPDATE_GROUP_ORDER), label)

    groups = [
        {"label": label, "count": len(buckets[label]), "items": buckets[label]}
        for label in sorted(buckets, key=rank)
    ]

    sparkle = [item for item in (found.get("sparkle") or []) if isinstance(item, dict)]
    sparkle_updates = [item for item in sparkle if item.get("update_available")]
    sparkle_rest = [item for item in sparkle if not item.get("update_available")]

    # Electron（自带 app-update.yml）与"无法自动检测"也要透出去。
    # 之前这里只挑固定字段，deps 里算好的 electron/undetectable 被静默丢掉，
    # 界面自然一条都不显示（2026-10-23 排查：内核有数据、界面空白）。
    electron = [item for item in (found.get("electron") or []) if isinstance(item, dict)]
    electron_updates = [item for item in electron if item.get("update_available")]
    electron_rest = [item for item in electron if not item.get("update_available")]
    undetectable = [item for item in (found.get("undetectable") or []) if isinstance(item, dict)]

    return {
        "items": items,
        "groups": groups,
        "count": len(items),
        "sparkle": sparkle,
        "sparkle_updates": sparkle_updates,
        "sparkle_rest": sparkle_rest,
        "electron": electron,
        "electron_updates": electron_updates,
        "electron_rest": electron_rest,
        "undetectable": undetectable,
        "notes": [str(note) for note in (found.get("notes") or [])],
        "scope": str(found.get("scope") or ""),
    }


# ---------------------------------------------------------------- 残留

_ORPHAN_BUCKET_ALIASES = {
    "Saved Application State": "Saved State",
    "Application Support": "Application Support",
}


def orphan_bucket(path: str) -> str:
    """残留路径归到"藏在哪个目录"：用户判断"能不能删"靠的就是这个。"""
    parts = [part for part in Path(path).parts if part]
    if "Library" in parts:
        index = parts.index("Library")
        if index + 1 < len(parts):
            name = parts[index + 1]
            return _ORPHAN_BUCKET_ALIASES.get(name, name)
    return "其它"


def orphans_view(report: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in (report.get("items") or []) if isinstance(item, dict)]
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(orphan_bucket(str(item.get("path") or "")), []).append(item)

    groups = [
        {
            "label": label,
            "count": len(buckets[label]),
            "bytes": sum(int(entry.get("bytes") or 0) for entry in buckets[label]),
            "items": buckets[label],
        }
        for label in sorted(buckets, key=lambda key: (-len(buckets[key]), key))
    ]
    return {
        "items": items,
        "groups": groups,
        "count": len(items),
        "total_bytes": sum(int(item.get("bytes") or 0) for item in items),
        "installed": int(report.get("installed") or 0),
        "skipped_vendor": int(report.get("skipped_vendor") or 0),
    }


# ---------------------------------------------------------------- 大文件


def large_view(report: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in (report.get("items") or []) if isinstance(item, dict)]
    items.sort(key=lambda item: int(item.get("bytes") or 0), reverse=True)
    return {
        "items": items,
        "count": len(items),
        "total_bytes": sum(int(item.get("bytes") or 0) for item in items),
        "roots": [str(root) for root in (report.get("roots") or [])],
        "min_bytes": int(report.get("min_bytes") or 0),
    }


# ---------------------------------------------------------------- 完成页

def _actual_bytes(item: dict[str, Any]) -> int:
    actual = int(item.get("actual_bytes") or 0)
    if actual:
        return actual
    status = str(item.get("status") or "")
    return int(item.get("estimated_bytes") or 0) if status in _CLEANED_STATES else 0


def completion_view(report: dict[str, Any]) -> dict[str, Any]:
    """完成页数据：可恢复字节优先，实际释放量取内核的 `actual_reclaimed_bytes`。"""
    items = _plan_items(report)
    recoverable = sum(_actual_bytes(item) for item in items if item.get("recoverable"))
    failed = sum(1 for item in items if str(item.get("status")) == "failed")
    # 这两类都不是"出问题"，不该计进"跳过"：
    # - `target path missing`：目标是空的/不存在；
    # - `outside approved cleanup plan`：用户没勾的目标。
    ignored = ("target path missing", "outside approved cleanup plan")
    skipped = [
        {"path": _first_path(item), "reason": str(item.get("reason") or "")}
        for item in items
        if str(item.get("status")) in {"skipped", "blocked", "protected"}
        and not any(marker in str(item.get("reason") or "") for marker in ignored)
    ]
    receipt = report.get("receipt")
    receipt_path = ""
    if isinstance(receipt, dict):
        receipt_path = str(receipt.get("json") or receipt.get("path") or "")
    elif receipt:
        receipt_path = str(receipt)
    # 内核的 `actual_reclaimed_bytes` 是"处理掉的字节"，不等于"释放的字节"：
    # 移进废纸篓的那部分仍在磁盘上。这里把可恢复部分扣掉（2026-10-23 端到端验收发现
    # 走废纸篓却报了 100 KB 已释放）。
    reported = int(report.get("actual_reclaimed_bytes") or 0)
    return {
        "recoverable_bytes": recoverable,
        "actual_freed_bytes": max(0, reported - recoverable),
        "failed_count": failed,
        "skipped_count": len(skipped),
        "skipped_items": skipped,
        "receipt_path": receipt_path,
        "before_free_bytes": int(report.get("before_free_bytes") or 0),
        "after_free_bytes": int(report.get("after_free_bytes") or 0),
    }

def cleaned_count(report: dict[str, Any]) -> int:
    """统计真正被移走的条目数（`status` 落在 CLEANED_STATES 里）。"""
    return sum(1 for item in _plan_items(report) if str(item.get("status")) in _CLEANED_STATES)

# ---------------------------------------------------------------- 通用结果页

_RESULT_TITLES = {
    "uninstall": "卸载完成",
    "updates": "更新完成",
    "orphans": "残留清理完成",
    "clean": "清理完成",
    "files": "大文件清理完成",
}


def result_view(kind: str, report: dict[str, Any]) -> dict[str, Any]:
    """把四种执行结果收敛成同一张"结果页"需要的字段。

    四种内核返回的形状各不相同（`moved/count/bytes`、`results[].ok`、`plan_items[].status`），
    界面不该逐个适配——**口径收在内核**。
    """
    moved = [item for item in (report.get("moved") or []) if isinstance(item, dict)]
    failed = [item for item in (report.get("failed") or []) if isinstance(item, dict)]
    results = [item for item in (report.get("results") or []) if isinstance(item, dict)]

    count = int(report.get("count") or report.get("moved_count") or len(moved) or 0)
    total_bytes = int(report.get("bytes") or report.get("recovered_bytes") or 0)

    if results:  # 更新：一条命令一项
        ok_results = [item for item in results if item.get("ok")]
        count = len(ok_results)
        failed = [
            {"path": str(item.get("command") or ""), "reason": str(item.get("stdout_tail") or "")[:120]}
            for item in results
            if not item.get("ok")
        ]

    failures = [
        {"path": str(item.get("path") or item.get("command") or ""), "reason": str(item.get("reason") or "")[:120]}
        for item in failed[:20]
    ]
    return {
        "kind": kind,
        "title": _RESULT_TITLES.get(kind, "完成"),
        "count": count,
        "bytes": total_bytes,
        "failed_count": len(failed),
        "failures": failures,
        "cancelled": bool(report.get("cancelled")),
        "status": str(report.get("status") or ""),
    }


# ---------------------------------------------------------------- AI 可调用面

# MCP 工具是**另一套入口**（给 agent 直接调，不经 stdio 协议），所以单独列。
# 摘要取自各工具的 docstring 首行——改 MCP 那侧时记得同步这里（有测试盯着数量）。
MCP_TOOLS: tuple[tuple[str, str], ...] = (
    ("audit_storage", "只读扫描，返回可清理项与体积"),
    ("plan_storage", "生成只读计划，返回一次性 plan_id"),
    ("trace_storage", "只读追查某个目录/缓存属于哪个目标"),
    ("uninstall_plan", "列出某应用的残留（只读，不删除）"),
    ("updates_check", "列出第三方可升级项（Homebrew + App Store）"),
    ("updates_apply", "按包名升级（空 = 全部）"),
    ("apply_storage_plan", "按 plan_id + 精确 target id 执行清理"),
)


def tools_view(command_help: dict[str, str]) -> dict[str, Any]:
    """这一页要回答的问题：**AI 到底能怎么用 Mac Cleaner**。

    两个入口分开列：MCP（agent 直接调）与 stdio 命令（脚本/别的前端用）。
    """
    # MCP 依赖 `mcp` 包。现在**打包进内核**（core_cli 的 `mcp` 子命令），
    # 所以正常安装即有；这里仍做检测，用于自建/裁剪包时如实提示。
    try:
        import mcp  # noqa: F401

        mcp_available = True
    except Exception:
        mcp_available = False
    return {
        "mcp_available": mcp_available,
        "mcp_install_hint": "" if mcp_available else 'pipx install "maccleaner[mcp]"',
        "mcp": [{"name": name, "summary": text} for name, text in MCP_TOOLS],
        "commands": [{"name": name, "summary": text} for name, text in command_help.items()],
        # 顺序本身就是契约：**先列清单、让人确认，才执行**。
        # MCP 侧靠 plan_id 单次消费强制这一点；stdio 侧靠调用方守规矩，所以写在这里提醒。
        "workflow": [
            {"step": 1, "cmd": "scan 或 audit_storage", "note": "只读扫描，拿到候选与体积"},
            {"step": 2, "cmd": "plan_storage / review.payload",
             "note": "把清单（路径 + 体积 + 风险）**给用户看**，等他确认"},
            {"step": 3, "cmd": "apply_storage_plan / clean",
             "note": "只执行用户勾选的那些 id；空列表一律拒绝"},
        ],
        # 界面上列了工具却不说怎么启动，等于只给了半张说明书（2026-10-23 补）。
        "launch": [
            # 安装包内的内核自带 mcp（33 MB 里含依赖），不用另外 pip 安装。
            {"kind": "MCP", "command": "maccleaner-core mcp",
             "note": "在 agent 的 MCP 配置里指向这条命令（stdio，无需端口；已随 App 安装）"},
            {"kind": "stdio", "command": "maccleaner-core serve --stdio",
             "note": "脚本或其它前端：一行 JSON 一次请求，事件逐行返回"},
        ],
        "safety": [
            "所有删除都是移入废纸篓（可恢复），不调用 rm",
            "系统级目录（/Library、/var/log）默认只测量；root 域删除需一次管理员授权",
            "浏览器 Cookies / 登录数据始终拦掉",
            "plan_id 一次性消费；过期或已用都要重新生成",
        ],
        "example": (
            "echo '{\"id\":\"1\",\"cmd\":\"disk.summary\"}' "
            "| maccleaner-core serve --stdio"
        ),
    }
