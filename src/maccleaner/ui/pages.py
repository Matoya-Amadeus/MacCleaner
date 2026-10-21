"""页面渲染（2026-10-18 迁入）。

**只吃 dict**：页面不碰文件系统、不碰 core，因此全部可以用示例数据单测。
真数据由会话层/服务层提供（下一步：适配器）。

统一的几条约定：

- 每个页面都有明确的 `data-stage`，测试与验收脚本靠它判断"现在在哪一屏"；
- 按钮一律通过 `state_page(actions=...)` 注入，页面不自己拼 `<body>`；
- 金额/字节走 `human_bytes`，**回收量口径与清理侧一致**：走废纸篓显示"可恢复"，真删才显示"实际释放"；
- 页面上**不出现硬编码色值**（`tests/test_ui_pages.py` 会检查）。
"""
from __future__ import annotations

import html
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .treemap import squarify as treemap_squarify
from typing import Any, Iterable, Sequence

from .shell import state_page


def human_bytes(value: int | float) -> str:
    """字节 → 人类单位，用**十进制**（1 KB = 1000 B）。

    为什么不是 KiB/MiB（2026-10-20 用户要求）：Finder 和系统设置都用 MB/GB，
    用户看到 "784.97 MiB" 会换算一次才知道多大；这里跟 Finder 对齐。
    """
    number = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(round(number))} B"
            return f"{number:.2f} {unit}"
        number /= 1000
    return f"{number:.2f} TB"


def _button(
    label: str,
    action: str,
    *,
    primary: bool = False,
    element_id: str = "",
    payload: dict[str, Any] | None = None,
    ghost: bool = False,
) -> str:
    """按钮只携带**动作名 + 数据**；参数走 data-bridge-payload。

    为什么参数不拼进动作名（`uninstall-plan:<id>`）：桥的动作白名单是按**裸动作名**匹配的，
    拼字符串会被 400 拒掉；把参数放进 payload，白名单与校验逻辑就能保持单一来源。
    """
    import json as _json

    cls = "button primary" if primary else ("button ghost" if ghost else "button")
    ident = f' id="{html.escape(element_id)}"' if element_id else ""
    data = ""
    if payload:
        data = f" data-bridge-payload='{html.escape(_json.dumps(payload, ensure_ascii=False))}'"
    return (
        f'<button class="{cls}" type="button"{ident}{data} data-bridge-action="{html.escape(action)}">'
        f"{html.escape(label)}</button>"
    )


def _actions(*buttons: str) -> str:
    return '<div class="actions">' + "".join(buttons) + "</div>" if buttons else ""



_CATEGORY_LABEL = {
    "cache": "缓存",
    "logs": "日志",
    "xcode": "Xcode 生成物",
    "ide": "编辑器缓存",
    "homebrew": "Homebrew",
    "docker": "Docker 数据",
    "user-files": "你的文件",
    "simulator": "模拟器数据",
    "browser": "浏览器",
    "browser-cache": "浏览器组件",
    "package-cache": "包管理器缓存",
    "android": "Android 构建",
    "ios": "iOS 构建",
    "flutter": "Flutter 构建",
}


def _category_label(kind: str) -> str:
    return _CATEGORY_LABEL.get(str(kind or "").lower(), str(kind or ""))



def _display_path(path: str) -> str:
    """把家目录缩成 `~`（只用于展示）。"""
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


_ICON_PATHS: dict[str, str] = {
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.8 2.6 15.2 0 18M12 3c-2.6 2.8-2.6 15.2 0 18"/>',
    "box": '<path d="M3 7.5 12 3l9 4.5-9 4.5-9-4.5z"/><path d="M3 7.5v9L12 21l9-4.5v-9"/><path d="M12 12v9"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 10l3 2.5-3 2.5M13 15h4"/>',
    "cube": '<path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5z"/><path d="M4 8.5 12 13l8-4.5M12 13v7"/>',
    "doc": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5"/>',
    "trash": '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "gauge": '<circle cx="12" cy="12" r="9"/><path d="M12 12l4-3"/>',
    "battery": '<rect x="3" y="8" width="15" height="8" rx="2"/><path d="M21 11v2M7 11v2"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 11h.01M3 16h.01"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "picture": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="M21 16l-5-5-4 4-2-2-4 4"/>',
    "download": '<path d="M12 3v12M7 11l5 5 5-5M4 21h16"/>',
    "music": '<path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="2.6"/><circle cx="16" cy="16" r="2.6"/>',
    "film": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 10h4M3 15h4M17 10h4M17 15h4"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M9 20h6M12 16v4"/>',
}

# 常用目录 → 图标（按名字认，不按内部 key）：用户认图标比认字快。
_FOLDER_ICONS: dict[str, str] = {
    "pictures": "picture",
    "photos": "picture",
    "downloads": "download",
    "music": "music",
    "movies": "film",
    "documents": "doc",
    "desktop": "monitor",
    "library": "box",
    "applications": "cube",
}

# 行图标按"这东西是什么"选，而不是按内部 category 名——用户认图标比认字快。
_KIND_ICONS: dict[str, str] = {
    "browser": "globe",
    "cache": "box",
    "logs": "doc",
    "temp": "clock",
    "docker": "cube",
    "user-files": "doc",
    "xcode": "terminal",
    "ide": "terminal",
    "package-cache": "terminal",
    "homebrew": "terminal",
    "flutter": "terminal",
    "android": "terminal",
    "ios": "terminal",
    "browser-cache": "globe",
    "system": "lock",
    "trash": "trash",
}

_GROUP_ICONS = {
    "system": "lock",
    "browser": "globe",
    "app": "box",
    "dev": "terminal",
    "containers": "cube",
    "user": "doc",
    "trash": "trash",
    "temp": "clock",
}


def _icon(name: str) -> str:
    """内联 SVG 图标：用 currentColor，跟着主题深浅色走，不引入外部资源。"""
    path = _ICON_PATHS.get(name)
    if not path:
        return ""
    return (
        '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        f"{path}</svg>"
    )


def _kind_icon(kind: str) -> str:
    return _icon(_KIND_ICONS.get(str(kind or ""), "box"))


def _folder_icon(name: str, path: str = "", *, is_dir: bool = True) -> str:
    """目录/文件图标：常用目录各用一个，其余给通用文件夹/文档。"""
    key = str(name or "").strip().lower()
    if not is_dir:
        return _icon("doc")
    icon = _FOLDER_ICONS.get(key)
    if icon:
        return _icon(icon)
    if "/Library/Caches" in str(path):
        return _icon("box")
    return _icon("folder")


def _app_icon(uri: Any) -> str:
    """真实应用图标（base64 PNG）。只接受 `data:image/` 前缀，挡掉任意 URI 注入。"""
    text = str(uri or "")
    if not text.startswith("data:image/"):
        return ""
    return f'<img class="app-ico" src="{html.escape(text)}" alt="" width="22" height="22">'


# 应用分类的展示顺序（卸载页左栏）：最常清理的排前面，"其它"垫底。
# 放在页面层而不是 deps：这是**展示顺序**，不是数据事实（deps 只负责把
# LSApplicationCategoryType 映射成中文名）。
_APP_CATEGORY_ORDER: tuple[str, ...] = (
    "浏览器", "开发工具", "社交与通讯", "效率办公", "设计与图像", "影音", "游戏", "阅读资讯", "系统工具", "其它",
)

def _rows(
    items: Iterable[dict[str, Any]],
    *,
    note_key: str = "reason",
    selectable: bool = False,
    preselected: frozenset[str] = frozenset(),
    default_checked: bool = False,
) -> str:
    """列表行。

    `selectable=True` 时每行带勾选框（`data-target-id`）——审阅页要能"逐条决定清不清"，
    而不是只有"全部清理"一个按钮（2026-10-19 用户指出）。

    标题优先用 target 的 **name**：以前取路径末级名，不同目标会显示成同一个名字
    （例如两个 Homebrew 目标都叫 "Homebrew"）；副标题给出真实路径。
    """
    rows: list[str] = []
    for item in items:
        path = str(item.get("path", "") or "")
        name = str(item.get("name") or "") or (path.rstrip("/").split("/")[-1] or path)
        kind = str(item.get("kind", "") or item.get("status", "") or "")
        note = str(item.get(note_key, "") or "")
        size = human_bytes(int(item.get("allocated_bytes", 0) or item.get("bytes", 0) or 0))
        label = _category_label(kind)
        meta = " · ".join(part for part in (label, _display_path(path), note) if part)
        reveal_attr = f' data-reveal-path="{html.escape(path)}"' if path else ""
        sort_attrs = (
            f' data-sort-text="{html.escape(name.lower())}"'
            f' data-sort-bytes="{int(item.get("allocated_bytes", 0) or item.get("bytes", 0) or 0)}"'
        )
        # 真实应用图标（浏览器缓存那几行）：本机读出来的 data URI，不随包分发厂商素材。
        stack = ""
        icon_uris = [str(uri) for uri in (item.get("icons") or []) if str(uri).startswith("data:image/")]
        if icon_uris:
            imgs = "".join(
                f'<img src="{html.escape(uri)}" alt="" width="18" height="18">' for uri in icon_uris[:4]
            )
            stack = f'<span class="ico-stack">{imgs}</span>'
        body = (
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(meta)}</div>'
        )
        if selectable:
            target_id = html.escape(str(item.get("target_id", "") or ""))
            risky = bool(item.get("requires_confirmation"))
            # 默认**不勾**；高风险项也能勾，但确认页会再问一次。
            # 默认勾选**只给低风险**：高风险（Downloads/Docker/安装包）必须由人自己勾，
            # 否则"点一下开始清理"就等于清空下载目录。
            default_on = default_checked and not risky
            checked = " checked" if (target_id and (default_on or str(item.get("target_id")) in preselected)) else ""
            # 高风险项**可以勾**（2026-10-20 用户反馈"点不动"）：勾了之后确认页还要再确认一次，
            # 两道门都在。之前禁用勾选框，等于这一项永远清不掉。
            risky_attr = ' data-risky="1"' if risky else ""
            box = f'<input type="checkbox" data-target-id="{target_id}"{risky_attr}{checked}>' 
            risk_note = (
                '<span class="pill risk">高风险 · 确认页单独确认</span>' if risky else ""
            )
            rows.append(
                f'<label class="row opt"{sort_attrs}{reveal_attr}>{box}{stack or _kind_icon(kind)}'
                f'<div>{body}{risk_note}</div>'
                f'<span class="meta value">{size}</span></label>'
            )
        else:
            rows.append(
                f'<div class="row"{sort_attrs}{reveal_attr}>{stack or _kind_icon(kind)}'
                f'<div>{body}</div><span class="meta value">{size}</span></div>'
            )
    return "".join(rows)


# --------------------------------------------------------------------------- 清理链路



_ICON_CHECK = (
    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="24" r="17"/>'
    '<path d="M16 25l6 6 11-13"/></svg>'
)
_ICON_WARN = (
    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="24" r="17"/>'
    '<path d="M24 15v12"/><path d="M24 33h.01"/></svg>'
)


def empty_block(icon: str, title: str, text: str) -> str:
    """空状态/提示块：图标 + 结论 + 下一步。

    为什么单独做组件：原来空结果只剩一行灰字（"没有找到可清理的内容"），
    用户看不出"这是好消息"还是"坏了"，也不知道下一步能做什么。
    """
    glyph = _ICON_WARN if icon == "warn" else _ICON_CHECK
    return (
        '<div class="empty">'
        + glyph
        + f'<p class="empty-title">{html.escape(title)}</p>'
        + f'<p class="empty-text">{html.escape(text)}</p>'
        + "</div>"
    )





def render_landing_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """落地页：**打开不扫**，点【开始扫描】才扫。

    为什么要有这一页：扫描是**动作**而不是窗口的副作用。此前"打开即扫"会在用户还没看屏幕时
    就读磁盘，而且"扫描耗时"里混进了他发呆的时间。
    """
    history = payload.get("history") or {}
    total = int(history.get("total_freed_bytes") or 0)
    runs = int(history.get("total_runs") or 0)
    last_run = str(history.get("last_run") or "").replace("T", " ")[:16]
    summary = (
        f"已清理 {runs} 次，可恢复 {human_bytes(total)}（清空废纸篓后才真正释放）"
        + (f" · 最近 {last_run}" if last_run else "")
        if (total or runs)
        else "还没有清理记录"
    )
    actions = (
        '<div class="actions" style="justify-content:center">'
        '<button class="button round primary" type="button" id="start-scan" '
        'data-bridge-action="start">开始扫描</button></div>'
        if interactive
        else ""
    )
    # 落地页也去掉标题区与那句排比（"开始一次清理" / "扫描你的 Mac，先看清单…" 是同一句话）：
    # 侧栏已经高亮"Mac 清理"，这里只需要一句承诺 + 一个大按钮（2026-10-21 统一）。
    page = state_page(
        {
            "message": "扫描只读取文件大小与修改时间，不会改动或删除任何内容。",
            "detail": "扫完先看清单，再决定删什么。",
        },
        stage="idle",
        title="开始一次清理",
        body="",
        with_header=False,
        actions=actions,
        current="clean",
    )
    return page.replace("</section>", f'<p class="muted" style="margin-top:14px">{html.escape(summary)}</p></section>')


def render_progress_html(payload: dict[str, Any] | None = None, *, stage: str = "scanning") -> str:
    """进度页：扫描/清理时给一句话，**不要借审阅页当进度页**。

    借用的后果是：扫描阶段页面上会显示 review 的标题和"没有找到可清理的内容"——
    用户在扫描时就先看到一句错误结论（会话用例抓到的就是这个）。
    """
    data = payload or {}
    # 加载动画 + 骨架：进度页可能停留 1–3 秒（扫描/检查更新），静止的标题看起来像"卡死"。
    # `role="status"` + `aria-live` 让读屏软件也知道"正在忙"，而不是突然出现一堆内容。
    # 注意：**不要复用 `.row`**——它是 `space-between`，会把提示文字甩到最右边
    # （2026-10-19 截图里就是"转圈在左、文字在最右"）。加载头有自己的布局。
    loading = (
        '<div class="loading-head">'
        '<span class="loader lg" role="status" aria-live="polite" aria-label="正在处理"></span>'
        "<div>"
        f'<div class="loading-title">{html.escape(str(data.get("hint") or "正在读取，请稍候…"))}</div>'
        f'<div class="meta">{html.escape(str(data.get("subhint") or "只读操作，不会改动任何文件"))}</div>'
        "</div></div>"
        '<div class="skeleton-stack"><div class="skeleton row"></div>'
        '<div class="skeleton w85"></div><div class="skeleton w65"></div></div>'
    )
    return state_page(
        {
            "message": str(data.get("message") or "正在扫描，请稍候…"),
            "detail": str(data.get("detail") or "扫描只读；这一步不会改动任何文件。"),
        },
        stage=stage,
        title=str(data.get("title") or "正在扫描"),
        body=str(data.get("body") or "正在扫描"),
        # 进度页也不要标题栏（2026-10-21 用户要求）：这一屏只在几秒内出现，
        # 再顶一行"软件更新/残留体检"既没用又跳一下。
        with_header=False,
        # 进度页**自己轮询刷新**：慢操作（例如 brew outdated 要几秒）期间服务端不会发新页，
        # 不自刷的话用户就一直停在"正在…"（2026-10-18 真浏览器实测过的坑）。
        actions=loading + (
            "<p class=\"meta\" id=\"mc-elapsed\" aria-live=\"polite\"></p>"
            "<script>(function(){"
            "var t0=Number(sessionStorage.getItem('mc-progress-start')||0)||Date.now();"
            "sessionStorage.setItem('mc-progress-start',t0);"
            "function tick(){var el=document.getElementById('mc-elapsed');if(!el)return;"
            "var s=Math.round((Date.now()-t0)/1000);"
            "el.textContent='已用 '+s+' 秒'+(s>=20?'（比平时慢，可能在等 App Store 登录或网络）':'');}"
            "tick();setInterval(tick,200);"
            "setTimeout(function(){location.reload()}, 1500);})()</script>"
            if data.get("auto_refresh", True)
            else ""
        ),
        current=str(data.get("nav") or "clean"),
    )


# 按"谁产生"分组（学 Mole 的分类法）：用户不需要知道 category，
# 只需要知道"这是谁留下的、删了会怎样"。
_REVIEW_GROUPS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("system", "系统数据", "需管理员权限，本工具只测量不删除", ()),
    ("browser", "浏览器", "浏览器留下的缓存（不含 Cookies / 登录数据），默认已勾选", ("browser",)),
    ("app", "App 缓存与日志", "应用运行时生成，删了会重建", ("cache", "logs")),
    ("dev", "开发工具", "Xcode / 包管理器 / 编辑器缓存", (
        "xcode", "android", "ios", "ide", "package-cache", "homebrew", "flutter", "browser-cache",
    )),
    ("containers", "容器与虚拟机", "Docker 等运行时数据，删除后需要重新拉取", ("docker",)),
    ("user", "你的文件", "Downloads、安装包、iOS 备份——删前自己确认", ("user-files",)),
    ("trash", "废纸篓", "清空后不可恢复", ("__trash__",)),
)


def _review_group(candidate: dict[str, Any]) -> str:
    if str(candidate.get("target_id") or "") == "trash":
        return "trash"
    category = str(candidate.get("kind") or "")
    for key, _label, _hint, categories in _REVIEW_GROUPS:
        if category in categories:
            return key
    return "app"


def _review_system_html(system: dict[str, Any] | None, *, interactive: bool) -> str:
    """系统数据组：只读（root 域不删），展开能看到每个目录的体积。"""
    payload = system or {}
    sizes = payload.get("sizes") or {}
    if not sizes:
        return ""
    rows = "".join(
        '<div class="row"><div style="min-width:0;flex:1">'
        f'<strong>{html.escape(str(path))}</strong>'
        f'<div class="meta">{"已授权读取（只测量）" if payload.get("admin") else "未授权：可能读不全"}</div></div>'
        f'<span class="meta value">{human_bytes(int(size or 0))}</span></div>'
        for path, size in sizes.items()
    )
    total = sum(int(value or 0) for value in sizes.values())
    button = _button("用管理员授权测量一次（只读）", "system-sizes", ghost=True) if interactive else ""
    return (
        '<details class="group review" data-group-key="system">'
        "<summary>"
        f'{_icon("lock")}'
        '<span class="group-name">系统数据</span>'
        f'<span class="meta">{len(sizes)} 项 · {human_bytes(total)} · 只测量不删除</span>'
        "</summary>"
        '<p class="group-hint meta">/Library/Caches、/var/log 属于 root：'
        "不授权读不全，本工具不会删除它们。</p>"
        f'<div class="rows">{rows}</div>{button}'
        "</details>"
    )


def _review_groups_html(
    candidates: list[dict[str, Any]],
    *,
    interactive: bool,
    system: dict[str, Any] | None = None,
    preselected: frozenset[str] = frozenset(),
    default_checked: bool = False,
) -> str:
    """把候选按组折叠：每组一个 details，展开就是这一组的具体条目。"""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        buckets.setdefault(_review_group(candidate), []).append(candidate)

    blocks: list[str] = []
    for key, label, hint, _categories in _REVIEW_GROUPS:
        if key == "system":
            block = _review_system_html(system, interactive=interactive)
            if block:
                blocks.append(block)
            continue
        items = buckets.get(key) or []
        if not items:
            continue
        size = sum(int(item.get("allocated_bytes", 0) or 0) for item in items)
        blocks.append(
            f'<details class="group review" open data-group-key="{key}">'
            "<summary>"
            f'{_icon(_GROUP_ICONS.get(key, "box"))}'
            f'<span class="group-name">{label}</span>'
            f'<span class="meta">{len(items)} 项 · {human_bytes(size)}</span>'
            "</summary>"
            f'<p class="group-hint meta">{hint}</p>'
            f'<div class="rows">'
            f'{"".join(_rows(items, selectable=interactive, preselected=preselected, default_checked=default_checked))}</div>'
            "</details>"
        )
    return "".join(blocks)


def _review_filter_bar(groups: list[tuple[str, str]]) -> str:
    """审阅页的筛选标签：「全部」+ 实际出现的分组名。

    为什么不用排序（2026-10-20 用户明确要求）：清理清单本来就按体积/分组排好了，
    排序按钮对"我该不该清这一组"没有帮助，只占地方。筛选才有用——只想看浏览器或开发工具时。
    """
    if len(groups) < 2:
        return ""
    chips = ['<button class="chip is-on" type="button" data-filter-group="all">全部</button>']
    chips += [
        f'<button class="chip" type="button" data-filter-group="{html.escape(key)}">'
        f"{html.escape(label)}</button>"
        for key, label in groups
    ]
    return '<div class="chips" role="tablist" aria-label="按类型筛选">' + "".join(chips) + "</div>"


def _present_review_groups(
    candidates: list[dict[str, Any]], system: dict[str, Any] | None
) -> list[tuple[str, str]]:
    """返回页面上**真实存在**的分组 (key, label)，顺序与展示顺序一致。"""
    present: set[str] = set()
    for candidate in candidates:
        present.add(_review_group(candidate))
    if (system or {}).get("sizes"):
        present.add("system")
    return [(key, label) for key, label, _hint, _categories in _REVIEW_GROUPS if key in present]


def _rail(items: list[tuple[str, str, str, str]]) -> str:
    """通用左栏：`(key, 名称, 图标名, 右侧小字)`；第一项默认选中。

    审阅页与系统页共用同一种"左栏筛选"语义——JS 那边只认 `[data-filter-group]`
    与 `[data-group-key]`，所以两边不用各写一套。
    """
    if len(items) < 2:
        return ""
    return '<aside class="rail" aria-label="分类">' + _rail_body(items) + "</aside>"


def _rail_body(items: list[tuple[str, str, str, str]]) -> str:
    buttons = []
    for index, (key, label, icon_name, meta) in enumerate(items):
        active = " is-on" if index == 0 else ""
        meta_html = f'<span class="rail-meta">{html.escape(meta)}</span>' if meta else ""
        buttons.append(
            f'<button class="rail-item{active}" type="button" data-filter-group="{key}">'
            f'{_icon(icon_name)}<span class="rail-name">{html.escape(label)}</span>{meta_html}</button>'
        )
    return "".join(buttons)


def _review_rail(
    groups: list[tuple[str, str]], candidates: list[dict[str, Any]], system: dict[str, Any] | None
) -> str:
    """左栏：固定的分类入口（图标 + 名称 + 数量/体积）。

    为什么要左栏（2026-10-20）：筛选胶囊放上面时，滚动之后要回到顶部才能换类别；
    竖在左边就一直在。右栏只负责滚动，两栏各干一件事。
    """
    if len(groups) < 2:
        return ""
    sizes: dict[str, tuple[int, int]] = {}
    for candidate in candidates:
        key = _review_group(candidate)
        count, total = sizes.get(key, (0, 0))
        sizes[key] = (count + 1, total + int(candidate.get("allocated_bytes", 0) or 0))
    if system and (system.get("sizes") or {}):
        sizes["system"] = (
            len(system["sizes"]),
            sum(int(value or 0) for value in system["sizes"].values()),
        )

    items: list[tuple[str, str, str, str]] = [("all", "全部", "box", "")]
    for key, label in groups:
        count, total = sizes.get(key, (0, 0))
        items.append((key, label, _GROUP_ICONS.get(key, "box"), f"{count} · {human_bytes(total)}"))
    back = (
        '<button class="rail-item rail-back" type="button" data-nav-action="home">'
        '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 6l-6 6 6 6"/></svg><span class="rail-name">返回</span></button>'
    )
    return ('<aside class="rail" aria-label="分类">' + back + _rail_body(items) + "</aside>") if len(items) >= 2 else ""


def render_review_html(
    payload: dict[str, Any],
    *,
    interactive: bool = True,
    notice: str = "",
    preselected: Sequence[str] | None = None,
    default_checked: bool = True,
) -> str:
    """审阅页：列出候选，**用户可以逐条不选**；没有候选时明确说"没找到"。

    这一页的核心承诺是"先看清单再决定删什么"——所以候选必须逐条可见（名称、类型、大小），
    而不是只给一个总数。
    """
    candidates = [item for item in (payload.get("candidates") or []) if isinstance(item, dict)]
    total = sum(int(item.get("allocated_bytes", 0) or 0) for item in candidates)
    selectable_total = sum(
        int(item.get("allocated_bytes", 0) or 0)
        for item in candidates
        if _review_group(item) != "browser" and not item.get("requires_confirmation")
    )
    # 空结果时不写 state-head/state-msg：结论交给下面的 empty 块，否则同一句话说三遍
    # （2026-10-19 截图里一眼看到三处重复）。
    body = "找到可清理的内容" if candidates else ""
    detail = (
        f"共 {len(candidates)} 组候选，目录占用 {human_bytes(total)}；"
        f"其中可勾选 {human_bytes(selectable_total)}"
        "（浏览器与系统数据默认不选，高风险项在确认页单独确认）。"
        "文件一律移入废纸篓，可从废纸篓恢复。"
        if candidates
        else ""   # 空结果时这句交给 empty 块，避免同一屏说两遍
    )
    cached_at = float(payload.get("scan_cached_at") or 0)
    if cached_at:
        import time as _time

        stamp = _time.strftime("%H:%M", _time.localtime(cached_at))
        detail += f" 数据来自 {stamp} 的扫描（点【重新扫描】可强制刷新）。"
    # 有候选时也要能【重新扫描】：只给"开始清理"会把人锁死在一次结果上。
    # 底部固定条（2026-10-20 用户要求，参考 CleanMyMac）：左边显示"已选 / 共"，
    # 右边一个主按钮，按钮文字带上可清理的空间；不再放"取消/重新扫描"——
    # 返回走左栏顶部的【返回】，重扫走落地页。
    actions = (
        '<div class="review-footer">'
        '<div class="review-sum">'
        '<span class="review-sum-main" id="mc-picked-bytes">已选 0 B</span>'
        f'<span class="review-sum-total">共 {human_bytes(total)}</span>'
        "</div>"
        '<button class="button primary" type="button" data-bridge-action="approval" id="mc-clean-btn">'
        "清理</button>"
        "</div>"
        if (interactive and candidates)
        else _actions(_button("退出", "cancel"))
    )
    empty = (
        empty_block("check", "没有找到可清理的内容", "你的 Mac 现在挺干净。可以稍后再扫一次，或先去看看卸载残留。")
        if not candidates
        else ""
    )
    # 头部固定（2026-10-20 用户要求：滚列表时这半部分一直在）。
    # 标题区与"找到可清理的内容…"整块已删——它只是重复下面的数字。
    sel_all_checked = " checked" if (default_checked and not any(
        item.get("requires_confirmation") for item in candidates
    )) else ""
    head = (
        (f'<p class="pill warn" role="status">{html.escape(notice)}</p>' if notice else "")
        + (
            '<label class="row opt select-all">'
            f'<input type="checkbox" data-select-all{sel_all_checked}>'
            '<div><strong>全选（不含高风险）</strong>'
            '<div class="meta">低风险项已默认勾选；高风险项需要自己勾，并在确认页再确认一次</div></div>'
            "</label>"
            if candidates and interactive
            else ""
        )
    )
    groups = _present_review_groups(candidates, payload.get("system"))
    return state_page(
        {"message": "", "detail": ""},
        stage="review",
        title="审阅清单",
        body="",
        with_header=False,
        actions=(
            empty
            + '<div class="review-split">'
            + _review_rail(groups, candidates, payload.get("system"))
            + '<div class="review-right">'
            + (f'<div class="review-head">{head}</div>' if head else "")
            + '<div class="review-detail">'
            + _review_groups_html(
                candidates,
                interactive=interactive and bool(candidates),
                system=payload.get("system"),
                preselected=frozenset(str(x) for x in (preselected or ())),
                default_checked=default_checked,
            )
            + "</div>"
            + actions
            + "</div></div>"
        ),
        current="clean",
    )


def render_confirmation_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """确认页：再拦一次（这是"删除"前的最后一道门）。"""
    count = int(payload.get("selected_count", 0) or 0)
    size = human_bytes(int(payload.get("selected_bytes", 0) or 0))
    actions = _actions(
        _button("返回修改", "back"),
        _button("确认清理", "confirm", primary=True),
    ) if interactive else ""

    risk_items = [item for item in (payload.get("risk_items") or []) if isinstance(item, dict)]
    risk_block = ""
    if risk_items and interactive:
        # 高风险项（例如 ~/Downloads、Docker 数据）**单独确认**：内核本来就要 `confirm_targets`，
        # 而界面之前根本不传 → 它们只能被 blocked，用户勾了却什么都没发生。
        rows = "".join(
            '<div class="row"><div><strong>'
            + html.escape(str(item.get("name", "")))
            + "</strong>"
            + f'<div class="meta">{html.escape(str(item.get("path", "")))}</div></div>'
            + f'<span class="meta value">{human_bytes(int(item.get("allocated_bytes", 0) or 0))}</span></div>'
            for item in risk_items
        )
        risk_block = (
            '<p class="group-title">高风险项（需单独确认）</p>'
            + rows
            + '<label class="row opt"><input type="checkbox" data-confirm-risk>'
            '<div><strong>我确认清理上面这些高风险项</strong>'
            '<div class="meta">不勾选则本次只清低风险项</div></div></label>'
        )

    return state_page(
        {
            "message": f"将移入废纸篓：{count} 组，共 {size}",
            "detail": "点【确认清理】立即执行；文件仍可从废纸篓恢复。",
        },
        stage="confirming",
        with_header=False,
        title="确认清理",
        body="确认清理",
        actions=risk_block + actions,
        current="clean",
    )


def render_completion_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """完成页：头条数字是**可恢复**字节。

    走废纸篓不会立即释放空间（字节还在废纸篓里），所以这里显示"可恢复"并注明
    "清空废纸篓后释放"；只有真删路径（`actual_freed_bytes`）才显示"实际释放"。
    曾经这里显示 `0 B`，用户以为没清掉。
    """
    actual = int(payload.get("actual_freed_bytes", 0) or 0)
    recoverable = int(payload.get("recoverable_bytes", 0) or 0)
    via_trash = not actual and bool(recoverable)
    hero = human_bytes(actual or recoverable)
    caveat = "（已移入废纸篓，清空废纸篓后释放）" if via_trash else ""
    receipt = str(payload.get("receipt_path", "") or "")
    buttons = (
        # 只留【打开废纸篓】："再看一眼"点了只是重扫，用户看完结果不会退回清单，
        # 属于无效按钮（2026-10-20 用户要求删掉）。
        _actions(_button("打开废纸篓", "open-trash", primary=True))
        if interactive
        else ""
    )
    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="k">{"可恢复" if via_trash else "实际释放"}</div>'
        f'<div class="v">{html.escape(hero)}</div></div>'
        f'<div class="stat"><div class="k">失败</div>'
        f'<div class="v">{int(payload.get("failed_count", 0) or 0)}</div></div>'
        f'<div class="stat"><div class="k">跳过</div>'
        f'<div class="v">{int(payload.get("skipped_count", 0) or 0)}</div></div>'
        "</div>"
    )
    return state_page(
        {
            # 数字只在 hero 与三格里出现一次；这句话负责"这意味着什么"。
            "message": "已移入废纸篓，清空废纸篓后释放空间" if via_trash else "已直接删除并释放空间",
            # 之前是 `(回执) + " · 失败/跳过：0"`——没有回执时就变成以 " · " 开头的一行。
            "detail": " · ".join(
                part
                for part in (
                    f"回执：{receipt}" if receipt else "",
                    f"失败/跳过：{int(payload.get('failed_count', 0) or 0)}",
                )
                if part
            ),
        },
        stage="complete",
        with_header=False,
        title="清理完成",
        body="",          # 标题已写"清理完成"，正文再写一遍就是重复
        hero=hero,
        actions=stats + buttons,   # 数字在按钮上方：先看结果，再决定下一步
        current="clean",
    )


def render_cancelled_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    actions = _actions(_button("重新开始", "start", primary=True)) if interactive else ""
    return state_page(
        {"message": "分析已取消", "detail": "没有文件被删除；你可以重新开始一次分析。"},
        stage="cancelled",
        with_header=False,
        title="分析已取消",
        body="分析已取消",
        actions=actions,
        current="clean",
    )


def render_recovery_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """出错后的恢复页：**说明原因 + 可重试**，不是一张死掉的失败页。"""
    reason = str(payload.get("detail", "") or "")
    buttons = _actions(_button("退出", "cancel"), _button("重试", "start", primary=True)) if interactive else ""
    # 警示图标 + 承诺句放在同一块里：出错时用户第一眼要看到"没有删除任何东西"。
    block = empty_block("warn", "这次没有完成，但没有删除任何东西", reason or "点【重试】重新开始；也可以退出后再打开。")
    return state_page(
        {
            "message": "",
            "detail": "",
        },
        stage="error",
        title="可以重试",
        body="",
        with_header=False,
        actions=block + buttons,
        current="clean",
    )


# --------------------------------------------------------------------------- 卸载


def render_uninstall_list_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """应用列表：**首字母分组 + 搜索 + 粘性工具条**（2026-10-19 用户反馈"50 项往下拉太费劲"）。

    字母分组对应"我记得名字开头"的找法，搜索对应"我知道叫什么"的找法；
    两者一起解决滚动，而不是把行做矮。
    """
    apps = [item for item in (payload.get("apps") or []) if isinstance(item, dict)]
    buckets: dict[str, list[str]] = {}

    for app in apps:
        size = int(app.get("allocated_bytes") or 0)
        size_text = f'<span class="meta value">{human_bytes(size)}</span>' if size else ""
        name = str(app.get("name", ""))
        bundle = str(app.get("bundle_id", ""))
        path = str(app.get("path", ""))
        button = (
            _button("卸载", "uninstall-plan", payload={"bundle_id": bundle, "path": path}, ghost=True)
            if interactive
            else ""
        )
        checkbox = (
            f'<input type="checkbox" data-app-path="{html.escape(path)}"'
            f' data-app-bundle="{html.escape(bundle)}" data-app-name="{html.escape(name)}">'
            if interactive
            else ""
        )
        # 行**不是** label：整行 label 会让"点应用名想打开"变成"误勾选"（2026-10-19 截图发现）。
        # 勾选只由左侧那个小 label 触发；点行其它位置 = 打开残留预览（JS 代理到行内按钮）。
        row = (
            f'<div class="row opt clickable" data-row data-select-row data-sort-text="{html.escape(name.lower())}"'
            f' data-sort-bytes="{size}" data-reveal-path="{html.escape(path)}">'
            '<label class="checkbox-only">'
            + (checkbox or '<span style="width:16px"></span>')
            + "</label>"
            + _app_icon(app.get("icon"))
            + '<div style="min-width:0;flex:1">'
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(bundle)}</div>'
            "</div>"
            f'<div class="row-actions">{size_text}{button}</div></div>'
        )
        # 按 macOS 官方应用分类分组（2026-10-20 用户要求"按照分类，不要按照字母"）。
        key = str(app.get("category") or "其它")
        buckets.setdefault(key, []).append(row)

    groups: list[str] = []

    def category_rank(label: str) -> tuple[int, str]:
        try:
            return (_APP_CATEGORY_ORDER.index(label), "")
        except ValueError:
            return (len(_APP_CATEGORY_ORDER), label)

    for key in sorted(buckets, key=category_rank):
        rows = buckets[key]
        groups.append(
            f'<details class="group review" open data-group data-group-key="{html.escape(key)}"'
            f' data-letter="{html.escape(key)}">'
            f'<summary><span class="group-name">{html.escape(key)}</span>'
            f'<span class="meta">{len(rows)} 个</span></summary>'
            f'<div class="rows">{"".join(rows)}</div></details>'
        )

    toolbar = ""
    if interactive and apps:
        toolbar = (
            '<div class="toolbar-left">'
            '<label class="checkbox-inline"><input type="checkbox" data-select-all-apps>'
            "<span>全选</span></label>"
            '<input class="search" type="search" placeholder="搜索名称或 bundle id"'
            ' data-filter aria-label="搜索应用">'
            "</div>"
        )

    if groups:
        categories = sorted(buckets, key=category_rank)
        rail_items: list[tuple[str, str, str, str]] = [("all", "全部", "doc", "")]
        for key in categories:
            rail_items.append((key, key, "doc", f"{len(buckets[key])} 个"))
        detail = (
            '<div class="review-right">'
            + (f'<div class="review-head">{toolbar}</div>' if toolbar else "")
            + '<div class="review-detail">'
            + f'<div>{"".join(groups)}</div>'
            + "</div>"
            + (
                '<div class="review-footer">'
                '<div class="review-sum">'
                '<span class="review-sum-main" id="mc-selected-count">已选 0 个</span>'
                f'<span class="review-sum-total">共 {len(apps)} 个应用</span>'
                "</div>"
                '<button class="button primary" type="button" data-bridge-action="uninstall-batch"'
                ' id="mc-uninstall-btn">卸载</button>'
                "</div>"
                if interactive
                else ""
            )
            + "</div>"
        )
        body = '<div class="review-split">' + _rail(rail_items) + detail + "</div>"
    else:
        body = empty_block("check", "没有找到应用", "换一个入口，或稍后再来。")
    return state_page(
        {"message": "", "detail": ""},
        stage="uninstall-list",
        title="软件卸载",
        body="",
        with_header=False,
        actions=body,
        current="uninstall",
    )


def render_uninstall_batch_confirm_html(batch: dict[str, Any], *, interactive: bool = True) -> str:
    """批量卸载的**唯一一次确认**：按应用列残留数量与体积。

    安全口径与单个卸载一致：只移用户域、一律进废纸篓；系统级残留只列出来、不在这里动。
    """
    apps = [item for item in (batch.get("apps") or []) if isinstance(item, dict)]
    total_bytes = int(batch.get("total_bytes", 0) or 0)
    total_items = int(batch.get("total_items", 0) or 0)
    rows = "".join(
        '<div class="row"><div style="min-width:0">'
        f'<strong>{html.escape(str(item.get("name", "")))}</strong>'
        f'<div class="meta">{html.escape(str(item.get("bundle_id", "")))}</div></div>'
        f'<span class="meta value">{int(item.get("count", 0) or 0)} 项 · '
        f'{human_bytes(int(item.get("bytes", 0) or 0))}</span></div>'
        for item in apps
    )
    buttons = (
        _actions(_button("返回列表", "uninstall-list"), _button("移入废纸篓", "uninstall-batch-apply", primary=True))
        if interactive
        else ""
    )
    return state_page(
        {
            "message": f"将卸载 {len(apps)} 个应用，共 {total_items} 项残留（{human_bytes(total_bytes)}）",
            "detail": "全部移入废纸篓，可从废纸篓恢复；系统级残留不在这里处理，需要单独的管理员授权。",
        },
        stage="uninstall-batch-confirm",
        title="确认批量卸载",
        body="",
        actions=rows + buttons,
        current="uninstall",
        subtitle="这一次确认，等于逐个个点【卸载】再确认一遍",
        meta=f"{len(apps)} 个应用",
    )


def render_uninstall_batch_done_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    apps = [item for item in (payload.get("apps") or []) if isinstance(item, dict)]
    moved = sum(int(item.get("moved", 0) or 0) for item in apps)
    bytes_total = sum(int(item.get("bytes", 0) or 0) for item in apps)
    rows = "".join(
        '<div class="row"><div style="min-width:0">'
        f'<strong>{html.escape(str(item.get("name", "")))}</strong>'
        f'<div class="meta">{int(item.get("moved", 0) or 0)} 项已移入废纸篓</div></div>'
        f'<span class="meta value">{human_bytes(int(item.get("bytes", 0) or 0))}</span></div>'
        for item in apps
    )
    buttons = _actions(_button("返回列表", "uninstall-list", primary=True)) if interactive else ""
    return state_page(
        {
            "message": f"已移入废纸篓 {moved} 项，共 {human_bytes(bytes_total)}",
            "detail": "清空废纸篓后才会真正释放空间；后悔了可以从废纸篓拖回来。",
        },
        stage="uninstall-batch-done",
        title="批量卸载完成",
        body="",
        hero=human_bytes(bytes_total),
        actions=rows + buttons,
        current="uninstall",
    )


def render_uninstall_preview_html(
    plan: dict[str, Any], *, interactive: bool = True, notice: str = ""
) -> str:
    """卸载预览：**应用本体必选**；残留按 confidence 分组，名称匹配默认不勾。

    名称匹配（`name-match`）可能命中别的应用的同名目录，所以默认不勾、并写明理由；
    页面只回传 item id，路径永不经过浏览器/调用方。
    """
    items = [item for item in (plan.get("items") or []) if isinstance(item, dict)]
    app = plan.get("app") or {}
    # 系统级残留（requires_admin）单列：root 域进不了你的废纸篓，本工具不处理。
    admin = [item for item in items if item.get("requires_admin")]
    exact = [
        item for item in items
        if item.get("confidence") != "name-match"
        and item.get("kind") != "app-bundle"
        and not item.get("requires_admin")
    ]
    guessed = [
        item for item in items
        if item.get("confidence") == "name-match" and not item.get("requires_admin")
    ]
    bundle = next((item for item in items if item.get("kind") == "app-bundle"), None)

    parts: list[str] = []

    def detail_row(item: dict[str, Any], *, checked: bool, note: str = "", muted: bool = False) -> str:
        """一行一项：图标 + 名称 + 体积，下一行写**它在哪里**（而不是内部 kind 名）。

        之前第二行是 `app-support` 这类内部键——用户看不懂，也判断不了该不该删。
        """
        path = str(item.get("path", ""))
        name = path.rstrip("/").split("/")[-1]
        parent = _display_path(str(Path(path).parent))
        size = human_bytes(int(item.get("allocated_bytes", 0) or 0))
        icon = _kind_icon(str(item.get("kind", "")))
        box = (
            f'<input type="checkbox" data-item-id="{html.escape(str(item.get("id", "")))}"'
            + (" checked" if checked else "")
            + ">"
        ) if not muted else '<span class="pill ghost">管理员</span>'
        return (
            f'<label class="row opt{" readonly" if muted else ""}">{box}'
            f'<div class="row-lead">{icon}<strong>{html.escape(name)}</strong></div>'
            f'<span class="meta">{html.escape(parent)}</span>'
            f'<span class="meta value">{size}</span></label>'
        )

    if bundle:
        parts.append(
            '<div class="row"><div class="row-lead">' + _kind_icon("app-bundle") +
            f'<strong>{html.escape(str(app.get("name", "")))}</strong></div>'
            '<span class="pill">必选</span></div>'
        )
    if exact:
        parts.append('<div class="group-title">确定项<span class="meta">这些路径与 bundle id 对得上</span></div>')
        parts.extend(detail_row(item, checked=True) for item in exact)
    if guessed:
        parts.append('<div class="group-title">按名称匹配<span class="meta">默认不勾 · 可能误伤别的应用</span></div>')
        parts.extend(detail_row(item, checked=False) for item in guessed)
    if admin:
        parts.append(
            '<div class="group-title">系统级残留<span class="meta">root 拥有，本工具不动</span></div>'
        )
        parts.extend(detail_row(item, checked=False, muted=True) for item in admin)

    back = (
        '<div class="review-head">'
        + _button("← 返回列表", "uninstall-back", ghost=True)
        + "</div>"
        if interactive
        else ""
    )
    footer = (
        '<div class="review-footer">'
        '<div class="review-sum">'
        '<span class="review-sum-main" id="mc-preview-count">已选 0 项</span>'
        f'<span class="review-sum-total">共 {len(items)} 项</span>'
        "</div>"
        '<button class="button primary" type="button" data-bridge-action="uninstall-apply"'
        ' id="mc-preview-btn">卸载</button>'
        "</div>"
        if interactive
        else ""
    )

    # cask 装的 app 直接拖废纸篓，`brew list --cask` 仍认为它装着（下次 upgrade 会复活/报错）。
    # 这里给明确提示 + 一键改用 brew 卸载，而不是悄悄替用户决定。
    cask = str(plan.get("cask") or "")
    cask_block = ""
    if cask and interactive:
        cask_block = (
            f'<p class="pill warn" role="status">这个应用由 Homebrew cask 安装（{html.escape(cask)}）：'
            "建议改用 brew 卸载，否则 brew 记录会与磁盘不一致。</p>"
            + _actions(_button("改用 brew 卸载", "uninstall-cask", payload={"token": cask}))
        )
    if notice:
        cask_block = f'<p class="pill warn" role="status">{html.escape(notice)}</p>' + cask_block

    return state_page(
        {
            "message": f"将移入废纸篓 {len(items)} 项，共 "
            f"{human_bytes(int(plan.get('user_total_bytes', 0) or 0))}（可恢复）",
            "detail": "确认后会再核对每个位置；名称匹配项默认不勾，请自行判断。",
        },
        stage="uninstall-preview",
        with_header=False,
        title=f"卸载 {app.get('name', '')}".strip(),
        body="",
        # 返回按钮必须**在滚动区之外**：放到 detail 里滚两屏就找不到了（2026-10-21 截图发现）。
        actions=(
            '<div class="review-right">'
            + back
            + '<div class="review-detail">' + "".join(parts) + cask_block + "</div>"
            + footer
            + "</div>"
        ),
        current="uninstall",
    )


def render_uninstall_cask_result_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """`brew uninstall --cask` 的结果页：成功/失败都给命令输出片段。"""
    data = payload or {}
    token = str(data.get("token") or "")
    ok = str(data.get("status")) == "ok"
    output = str(data.get("output") or "").strip()
    actions = _actions(
        _button("回到应用列表", "uninstall-list"),
        _button("打开废纸篓", "open-trash", ghost=True),
    ) if interactive else ""
    return state_page(
        {
            "message": (
                f"已用 Homebrew 卸载 {token}（brew 记录同步）"
                if ok
                else f"brew 卸载 {token} 失败"
            ),
            "detail": (output[-400:] if output else "（没有输出）"),
        },
        stage="uninstall-cask",
        title="软件卸载",
        body="",
        actions=actions,
        current="uninstall",
    )


def render_uninstall_complete_html(result: dict[str, Any], *, interactive: bool = True) -> str:
    """卸载完成：**只有还剩系统级残留时**才显示管理员按钮。"""
    remaining = result.get("remaining") or {}
    system_count = int(remaining.get("system_count", 0) or 0)
    moved = int(result.get("moved_count", 0) or 0)
    actions = _actions(
        _button("返回", "uninstall-list", primary=not system_count),
        *(
            [_button(f"清除系统级残留（{system_count} 项，需要授权）", "uninstall-system", primary=True)]
            if system_count and interactive
            else []
        ),
    ) if interactive else ""
    return state_page(
        {
            "message": f"已移入废纸篓 {moved} 项（可恢复）",
            "detail": (
                f"仍有 {system_count} 项系统级残留（/Library 或安装收据），需要一次管理员授权才能清除。"
                if system_count
                else "没有剩余的系统级残留。"
            ),
        },
        stage="uninstall-complete",
        title="卸载完成",
        body="卸载完成",
        actions=actions,
        current="uninstall",
    )


# --------------------------------------------------------------------------- 更新


def render_sparkle_result_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """Sparkle 应用"打开之后"的结果页：可以点【检查是否已更新】读回版本对比。

    为什么要有这一步：`open` 只负责把应用拉起来，更新是它自己做的，
    我们无法同步拿到结果；不核对版本就说"已更新"是在骗人。
    """
    data = payload or {}
    name = str(data.get("name") or "应用")
    before = str(data.get("version") or "")
    current = str(data.get("current") or "")
    state = str(data.get("state") or "opened")

    if state == "updated":
        message = f"{name} 已更新：{before} → {current}"
        detail = "版本号已变化，说明它自己完成了更新。"
    elif state == "unchanged":
        message = f"{name} 版本没变（还是 {before or '未知'}）"
        detail = ("它可能没有自动检查更新：在应用菜单里点【检查更新】，"
                  "或回到更新页用 App Store。")
    else:
        message = f"已打开 {name}（当前 {before or '未知版本'}）"
        detail = ("等它自己检查更新；几十秒后点【检查是否已更新】读回版本号。"
                  "如果你的应用没有自动检查，菜单里通常有【检查更新】。")

    actions = _actions(
        _button("检查是否已更新", "sparkle-verify", primary=True),
        _button("回到更新页", "updates-open"),
    ) if interactive else ""
    return state_page(
        {"message": message, "detail": detail},
        stage="sparkle",
        with_header=False,
        title="应用内更新",
        body="",
        actions=actions,
        current="updates",
    )


def render_updates_list_html(
    payload: dict[str, Any], *, interactive: bool = True, notice: str = ""
) -> str:
    """可升级列表，**按来源分组**（2026-10-19 用户反馈"79 项平铺，往下拉太费劲"）。

    分组边界用用户能理解的"来源"（Homebrew formula / cask / App Store / npm…），
    而不是内部字段名——这正是格式塔的相似性：同一来源放在一起才像一个东西。
    """
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]

    labels = {
        ("brew", "formula"): "Homebrew formula",
        ("brew", "cask"): "Homebrew cask",
        ("mas", "app-store"): "App Store",
        ("npm", "npm-global"): "npm 全局包",
        ("pip", "pip"): "Python 包",
        ("gem", "gem"): "Ruby gem",
        ("rustup", "toolchain"): "Rust 工具链",
    }
    order = [
        "Homebrew formula",
        "Homebrew cask",
        "App Store",
        "npm 全局包",
        "Python 包",
        "Ruby gem",
        "Rust 工具链",
    ]
    buckets: dict[str, list[str]] = {}

    for index, item in enumerate(items):
        manager = str(item.get("manager") or "")
        kind = str(item.get("kind") or "")
        label = labels.get((manager, kind), f"{manager}/{kind}".strip("/") or "其它")
        transition = f"{item.get('installed') or '?'} → {item.get('available') or '?'}"
        name = str(item.get("name", ""))
        row = (
            f'<label class="row opt" data-select-row data-sort-text="{html.escape(name.lower())}">'
            f'<input type="checkbox" data-update-id="{index}" checked>'
            '<div style="min-width:0">'
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(transition)}</div></div></label>'
        )
        buckets.setdefault(label, []).append(row)

    groups: list[str] = []
    for label in sorted(buckets, key=lambda key: (order.index(key) if key in order else 99, key)):
        rows = buckets[label]
        group_box = (
            f'<input type="checkbox" data-select-group checked aria-label="全选 {html.escape(label)}">'
            if interactive
            else ""
        )
        groups.append(
            f'<details class="group review" open data-group-key="{html.escape(label)}"><summary>'
            f'<span class="group-name">{html.escape(label)}</span>'
            f'<span class="meta">{len(rows)} 项</span>'
            f"{group_box}</summary>"
            f'<div class="rows">{"".join(rows)}</div></details>'
        )

    # 自带 Sparkle 更新器的应用：**优先**让它们在应用内更新（不需要 App Store 登录、
    # 也不受系统代理影响）；没有 Sparkle 的才需要走 App Store。
    sparkle_rows: list[str] = []
    for app in (payload.get("sparkle") or []):
        if not isinstance(app, dict):
            continue
        path = str(app.get("path") or "")
        feed = str(app.get("feed") or "")
        host = urlparse(feed).hostname if feed else ""
        broken = bool(feed) and (not host or host in {"0.0.0.0", "127.0.0.1", "localhost"})
        hint = "更新源看起来无效（指向本机地址）" if broken else (f"更新源 {host}" if host else "使用内置 Sparkle 框架")
        button = (
            _button("在应用内更新", "open-app", payload={"path": path}, primary=True)
            if interactive
            else ""
        )
        sparkle_rows.append(
            f'<div class="row" data-reveal-path="{html.escape(path)}">'
            + _app_icon(app.get("icon"))
            + '<div style="min-width:0;flex:1">'
            f'<strong>{html.escape(str(app.get("name") or ""))}</strong>'
            f'<div class="meta">{html.escape(str(app.get("version") or ""))} · {html.escape(hint)}</div>'
            "</div>"
            + ('<span class="pill warn">更新源可疑</span>' if broken else "")
            + f'<div class="row-actions">{button}</div></div>'
        )

    notes = "".join(f'<p class="muted">{html.escape(str(note))}</p>' for note in (payload.get("notes") or []))
    if sparkle_rows:
        notes = (
            '<p class="muted">这些应用自带更新器：先点【在应用内更新】；'
            "没有 Sparkle 的应用再用上面的 App Store 更新页。</p>"
            + notes
        )
    toolbar = ""
    if interactive:
        toolbar = (
            '<div class="toolbar-left">'
            '<label class="checkbox-inline"><input type="checkbox" data-select-all-updates checked>'
            "<span>全选</span></label></div>"
            '<div class="toolbar-right">'
            # App Store 应用绕不开 Apple ID：mas 用不了时把更新页打开，让系统自己装。
            # 和【全选】同一行放右侧；不再给【重新检查】——进这一页时已经自动检查过了。
            + (
                _button("App Store 更新页", "open-app-store", ghost=True)
                if any(str(item.get("manager")) == "mas" for item in items)
                else ""
            )
            + "</div>"
        )
        if notice:
            toolbar += f'<p class="pill warn" role="status">{html.escape(notice)}</p>'

    sparkle_block = ""
    if sparkle_rows:
        sparkle_block = (
            '<details class="group review" open data-group-key="sparkle"><summary>'
            '<span class="group-name">自带更新（Sparkle）</span>'
            f'<span class="meta">{len(sparkle_rows)} 个</span></summary>'
            f'<div class="rows">{"".join(sparkle_rows)}</div></details>'
        )
    # Sparkle 组放**最前**：策略是"先应用内更新，不行再 App Store"（2026-10-19 用户要求）。
    body = sparkle_block + ("".join(groups) if groups else empty_block(
        "check", "已经是最新的", "没有发现可升级的第三方软件。"
    ))
    sources: list[tuple[str, str, str, str]] = [("all", "全部", "box", "")]
    if sparkle_rows:
        sources.append(("sparkle", "自带更新", "globe", f"{len(sparkle_rows)} 个"))
    # 分组是**页面内**按 manager/kind 算出来的（报告本身没有 groups 字段），
    # 所以左栏也要从这里取——之前读 payload["groups"] 永远为空，左栏消失、明细被挤成 224px。
    for label in sorted(buckets, key=lambda key: (order.index(key) if key in order else 99, key)):
        sources.append((label, label, "terminal", f"{len(buckets[label])} 项"))

    detail = (
        '<div class="review-right">'
        + (f'<div class="review-head">{toolbar}</div>' if toolbar else "")
        + '<div class="review-detail">'
        + body
        + notes
        + "</div>"
        + (
            '<div class="review-footer">'
            '<div class="review-sum">'
            '<span class="review-sum-main" id="mc-updates-count">已选 0 项</span>'
            f'<span class="review-sum-total">共 {len(items) + len(sparkle_rows)} 项</span>'
            "</div>"
            '<button class="button primary" type="button" data-bridge-action="updates-apply"'
            ' id="mc-updates-btn">更新</button>'
            "</div>"
            if (sparkle_rows or items) and interactive
            else ""
        )
        + "</div>"
    )
    rail = _rail(sources)
    page_body = f'<div class="review-split">{rail}{detail}</div>' if rail else detail

    return state_page(
        {
            "message": "",
            "detail": "",
        },
        stage="updates",
        title="软件更新",
        body="",
        with_header=False,
        actions=page_body,
        current="updates",
    )


def render_updates_result_html(result: dict[str, Any], *, interactive: bool = True) -> str:
    status = str(result.get("status", ""))
    headline = {"applied": "全部更新完成", "partial": "部分更新完成", "failed": "更新失败", "dry-run": "预演"}.get(status, status)
    rows: list[str] = []
    for group in result.get("groups") or []:
        if not isinstance(group, dict):
            continue
        ok = bool(group.get("ok"))
        tail = str(group.get("stderr_tail") or group.get("stdout_tail") or "")
        rows.append(
            '<div class="row"><div><strong>'
            + html.escape(str(group.get("command", "")))
            + '</strong><div class="meta">exit '
            + str(int(group.get("exit_code", 0) or 0))
            + (f" · {html.escape(tail[:160])}" if tail else "")
            + '</div></div><span class="pill '
            + ("ok" if ok else "")
            + '">'
            + ("成功" if ok else "失败")
            + "</span></div>"
        )
    actions = _actions(_button("返回", "updates-open", primary=True)) if interactive else ""
    return state_page(
        {
            "message": headline,
            "detail": f"成功 {int(result.get('ok_count', 0) or 0)}/{int(result.get('total', 0) or 0)} 组",
        },
        stage="updates-result",
        title="更新结果",
        body=headline,
        with_header=False,
        actions=actions + "".join(rows),
        current="updates",
    )


# --------------------------------------------------------------------------- 技能


def render_skills_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """本机可被调用的 Skill 列表（2026-10-19 改）。

    早先这一页只讲 Mac Cleaner 自己（按当时"只展示自己"的要求）；用户后来指出
    **这一页应当显示本设备的全部 skill**——它本来就是"这台机器上 agent 能调什么"的地方。
    现在按来源根分组列出，并把本工具自己标出来。
    """
    data = payload or {}
    skills = [item for item in (data.get("skills") or []) if isinstance(item, dict)]

    def is_mine(skill: dict[str, Any]) -> bool:
        name = str(skill.get("name", "") or "").strip().lower()
        return name in {"mac cleaner", "mac-cleaner", "maccleaner"}

    # 按**来源**分组（真实数据：本工具 / ~/.codebuddy/skills / ~/.codex/skills/.system …）。
    # 与卸载页同一套骨架：左栏分类、右栏分组列表（2026-10-21 用户要求）。
    buckets: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        root = str(skill.get("root", "") or "").strip()
        key = "本工具" if is_mine(skill) or root == "本工具" else (root or "其它来源")
        buckets.setdefault(key, []).append(skill)

    def order(key: str) -> tuple[int, str]:
        if key == "本工具":
            return (0, "")
        return (1, key)

    def rail_label(key: str) -> str:
        # 左栏要窄：去掉 ~/ 前缀，只留有辨识度的部分。
        return key[2:] if key.startswith("~/") else key

    groups: list[str] = []
    for key in sorted(buckets, key=order):
        rows = []
        for skill in buckets[key]:
            name = str(skill.get("name", "") or "")
            description = str(skill.get("description", "") or "")
            path = str(skill.get("path", "") or "")
            pill = '<span class="pill ok">本工具</span>' if is_mine(skill) else '<span class="pill">可调用</span>'
            rows.append(
                # 两行：名称 + 一行说明（超长省略）；完整路径放 title，hover 才看。
                # data-sort-text 给搜索用（名称 / 说明 / 路径都能搜到）。
                f'<div class="row" data-sort-text="{html.escape(f"{name} {description} {path}".lower())}"'
                f' title="{html.escape(_display_path(path))}">'
                f'<div class="row-lead">{_icon("terminal")}'
                '<div class="skill-main">'
                f"<strong>{html.escape(name)}</strong>"
                f'<div class="meta skill-desc">{html.escape(description)}</div>'
                "</div></div>"
                + pill
                + "</div>"
            )
        groups.append(
            f'<details class="group review" open data-group data-group-key="{html.escape(key)}">'
            f'<summary><span class="group-name">{html.escape(rail_label(key))}</span>'
            f'<span class="meta">{len(buckets[key])} 个</span></summary>'
            f'<div class="rows">{"".join(rows)}</div></details>'
        )

    # 本工具自己的细节仍收进折叠块：列表要"全"，但触发词/边界这类说明不该占满屏幕。
    groups.append(
        '<details class="group review" style="margin-top:16px">'
        "<summary>本工具的触发词 / 调用方式 / 边界</summary>"
        '<div class="meta" style="margin-top:8px;line-height:1.9">'
        "<div><b>触发词</b>：mac清理、清理磁盘、清理缓存、清理磁盘空间</div>"
        "<div><b>怎么调用</b>：<code>maccleaner ui</code>（本地界面）/ <code>maccleaner uninstall</code> / MCP 工具</div>"
        "<div><b>边界</b>：扫描只读；清理一律移入废纸篓；系统级残留需要一次管理员授权。</div>"
        "</div></details>"
    )

    rail_items: list[tuple[str, str, str, str]] = [("all", "全部", "doc", f"{len(skills)} 个")]
    for key in sorted(buckets, key=order):
        rail_items.append((key, rail_label(key), "terminal", f"{len(buckets[key])} 个"))

    head = (
        '<div class="review-head">'
        '<input class="search" type="search" data-filter placeholder="搜索 skill 名称 / 说明 / 路径…"'
        ' aria-label="搜索 skill">'
        "</div>"
        if len(skills) >= 10
        else ""
    )
    detail = '<div class="review-detail">' + head + "".join(groups) + "</div>"
    page_body = (
        '<div class="review-split">' + _rail(rail_items) + detail + "</div>"
        if len(rail_items) >= 2
        else detail
    )

    # 这一页不给自己一个【返回】：侧栏一直在，返回按钮既多余、又只能跳"开始扫描"
    # （用户点它不会回到上一页，2026-10-21 反馈"删掉这个功能，skill 没有返回"）。
    return state_page(
        {
            "message": f"本机共 {len(skills)} 个可被调用的 skill",
            "detail": "来自 ~/.codex/skills、~/.codebuddy/skills、~/.claude/skills（可用 MACCLEANER_SKILL_ROOTS 追加）。"
                      "本页只读，不会执行任何 skill。",
        },
        stage="skills",
        title="可调用的 Skill",
        body="",
        with_header=False,
        actions=page_body,
        current="skills",
    )


def _meter(percent: float, *, tone: str = "accent") -> str:
    """一条容量条。`percent` 会被夹到 0–100，避免离谱数据把宽度撑出页面。"""
    width = max(0.0, min(100.0, float(percent or 0)))
    return f'<div class="meter"><span style="width:{width:.1f}%;background:var(--{tone})"></span></div>'



def _treemap_svg(
    entries: list[dict[str, Any]], *, width: int = 1000, height: int = 300, clickable: bool = True
) -> str:
    """把目录条目画成 squarified treemap（Mole `analyze` 那种一眼看懂的样子）。

    只画面积够大的标签：小格子塞文字反而看不清，交给 hover 的 `<title>`。
    """
    positive = [item for item in entries if int(item.get("bytes", 0) or 0) > 0]
    if len(positive) < 2:
        return ""
    positive.sort(key=lambda item: -int(item.get("bytes", 0) or 0))
    total_bytes = sum(int(item.get("bytes", 0) or 0) for item in positive) or 1
    # 面积小于 1% 的项画出来只有亚像素，点不到也看不清 → 聚合成"其它 N 项"。
    # 列表里仍然是完整的一份（treemap 只是入口，不是唯一视图）。
    usable = [item for item in positive if int(item.get("bytes", 0) or 0) / total_bytes >= 0.01][:12]
    rest = positive[len(usable):]
    rest_bytes = sum(int(item.get("bytes", 0) or 0) for item in rest)
    rest_note = ""
    # 余量 >= 2% 才值得画一块；否则画出来是 1px 的线，反而让人以为丢了数据。
    if rest and rest_bytes / total_bytes >= 0.02:
        usable = usable + [{
            "name": f"其它 {len(rest)} 项",
            "path": "",
            "bytes": rest_bytes,
            "is_dir": False,
        }]
    elif rest:
        rest_note = f"另有 {len(rest)} 项合计 {human_bytes(rest_bytes)}（不足 2%），见下方列表。"
    if len(usable) < 2:
        return ""
    rects = treemap_squarify([int(item.get("bytes", 0) or 0) for item in usable], width, height)
    total = sum(int(item.get("bytes", 0) or 0) for item in usable) or 1

    cells: list[str] = []
    for index, (item, (x, y, w, h)) in enumerate(zip(usable, rects)):
        if w <= 0 or h <= 0:
            continue
        path = str(item.get("path", ""))
        is_dir = bool(item.get("is_dir"))
        name = str(item.get("name", ""))
        size = int(item.get("bytes", 0) or 0)
        share = size / total
        fill = "rgba(53,208,161,.18)" if index < 3 else "var(--surface-2)"
        attrs = ""
        cursor = ""
        if is_dir:
            aria = ' aria-label="' + html.escape(f"{name} {human_bytes(size)}") + '"'
            attrs = aria
            if clickable:
                attrs = (
                    f' data-treemap-path="{html.escape(path)}" role="button" tabindex="0"'
                    + aria
                )
                cursor = ' style="cursor:pointer"'
        label = ""
        if w >= 96 and h >= 40:
            # 按宽度算能放几个字（12px 字体 ≈ 7px/字符）：不截断会压到隔壁色块上。
            max_chars = max(4, int((w - 16) / 7))
            shown = name if len(name) <= max_chars else name[: max_chars - 1] + "…"
            label = (
                f'<text x="{x + 8:.1f}" y="{y + 18:.1f}" fill="var(--text)" font-size="12"'
                f' font-weight="600">{html.escape(shown)}</text>'
                f'<text x="{x + 8:.1f}" y="{y + 33:.1f}" fill="var(--muted)" font-size="11">'
                f"{human_bytes(size)} · {share * 100:.0f}%</text>"
                if h >= 46
                else f'<text x="{x + 8:.1f}" y="{y + 18:.1f}" fill="var(--text)" font-size="12"'
                f' font-weight="600">{html.escape(shown)}</text>'
            )
        cells.append(
            f'<g class="tm-cell"{attrs}{cursor}>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4"'
            f' fill="{fill}" stroke="var(--line-strong)" stroke-width="1"/>'
            f"<title>{html.escape(name)} — {human_bytes(size)}（{share * 100:.0f}%）</title>"
            f"{label}</g>"
        )

    return (
        f'<div class="treemap"><svg viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="none" role="img" aria-label="目录体积分布">'
        + "".join(cells)
        + "</svg>"
        + (
            '<p class="meta">面积 = 体积占比；点方块进入。</p></div>'
            if clickable
            else '<p class="meta">面积 = 这些目录之间的占比。</p></div>'
        )
    )


def _orphan_bucket(path: str) -> str:
    """把残留路径归到"藏在哪个目录"，作为分组维度。"""
    parts = [part for part in Path(path).parts if part]
    if "Library" in parts:
        index = parts.index("Library")
        if index + 1 < len(parts):
            name = parts[index + 1]
            return {
                "Saved Application State": "Saved State",
                "Application Support": "Application Support",
            }.get(name, name)
    return "其它"


def render_orphans_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """孤儿残留体检（学 Pearcleaner 的 orphan scan）。

    判定口径写在页面上：名字像 bundle id、没有对应已装应用、且 7 天没动过。
    **默认不勾**，勾了才动，而且只进废纸篓。
    """
    data = payload or {}
    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    total = int(data.get("total", len(items)) or 0)
    total_bytes = int(data.get("bytes", 0) or 0)

    buckets: dict[str, list[str]] = {}
    for item in items:
        path = str(item.get("path", ""))
        size = int(item.get("bytes", 0) or 0)
        name = str(item.get("name", ""))
        # 按"藏在哪个目录"分组：用户判断"能不能删"靠的是这个（缓存可删、容器要小心）。
        bucket = _orphan_bucket(path)
        buckets.setdefault(bucket, []).append(
            f'<div class="row" data-select-row data-sort-text="{html.escape(name.lower())}" data-sort-bytes="{size}"'
            f' data-reveal-path="{html.escape(path)}">'
            '<label class="checkbox-only">'
            f'<input type="checkbox" data-orphan-path="{html.escape(path)}"></label>'
            '<div style="min-width:0;flex:1">'
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(_display_path(path))}'
            + (f" · 最后修改 {html.escape(str(item.get('modified') or ''))}" if item.get("modified") else "")
            + "</div></div>"
            f'<span class="meta value">{human_bytes(size)}</span></div>'
        )

    groups_html = "".join(
        f'<details class="group review" open data-group-key="{html.escape(key)}">'
        f'<summary><span class="group-name">{html.escape(key)}</span>'
        f'<span class="meta">{len(bucket_rows)} 项</span></summary>'
        f'<div class="rows">{"".join(bucket_rows)}</div></details>'
        for key, bucket_rows in buckets.items()
    )

    toolbar = ""
    if interactive and items:
        toolbar = (
            '<div class="toolbar-left">'
            '<label class="checkbox-inline"><input type="checkbox" data-select-all-orphans>'
            "<span>全选</span></label></div>"
        )

    body = (
        groups_html
        if items
        else empty_block(
            "check",
            "没有发现孤儿残留",
            "扫过 Caches / Preferences / Logs / Containers / WebKit / HTTPStorages / Saved State，"
            "每一项都能对上一个已装应用。",
        )
    )
    return state_page(
        {
            "message": "",
            "detail": "",
        },
        stage="orphans",
        title="残留体检",
        body="",
        with_header=False,
        actions=(
            '<div class="review-split">'
            + _rail(
                [("all", "全部", "box", "")]
                + [(key, key, "doc", f"{len(rows)} 项") for key, rows in buckets.items()]
            )
            + '<div class="review-right">'
            + (f'<div class="review-head">{toolbar}</div>' if toolbar else "")
            + '<div class="review-detail">'
            + body
            + "</div>"
            + (
                '<div class="review-footer">'
                '<div class="review-sum">'
                '<span class="review-sum-main" id="mc-orphans-count">已选 0 项</span>'
                f'<span class="review-sum-total">共 {total} 项 · {human_bytes(total_bytes)}</span>'
                "</div>"
                '<button class="button primary" type="button" data-bridge-action="orphans-apply"'
                ' id="mc-orphans-btn">移入废纸篓</button>'
                "</div>"
                if items and interactive
                else ""
            )
            + "</div></div>"
        ),
        current="orphans",
    )


def render_orphans_result_html(result: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    data = result or {}
    moved = [item for item in (data.get("moved") or []) if isinstance(item, dict)]
    failed = [item for item in (data.get("failed") or []) if isinstance(item, dict)]
    total_bytes = int(data.get("bytes", 0) or 0)

    rows = "".join(
        '<div class="row"><div style="min-width:0;flex:1">'
        f'<strong>{html.escape(Path(str(item.get("path", ""))).name)}</strong>'
        f'<div class="meta">{html.escape(_display_path(str(item.get("path", ""))))}</div></div>'
        f'<span class="meta value">{human_bytes(int(item.get("bytes", 0) or 0))}</span></div>'
        for item in moved
    )
    fail_rows = "".join(
        f'<p class="pill warn">{html.escape(str(item.get("path", "")))}：'
        f'{html.escape(str(item.get("reason", "")))}</p>'
        for item in failed
    )
    # 与"大文件结果页"同一个 bug：buttons 算了没接进页面。
    buttons = _actions(_button("打开废纸篓", "open-trash", primary=True)) if interactive else ""
    return state_page(
        {
            "message": f"已移入废纸篓 {len(moved)} 项，共 {human_bytes(total_bytes)}",
            "detail": "想恢复的话，在废纸篓里右键「放回原处」。",
        },
        stage="orphans",
        title="残留体检",
        body="",
        with_header=False,
        actions=(
            (rows + fail_rows) if (rows or fail_rows) else empty_block("check", "没有移动任何文件", "你什么都没勾。")
        ) + buttons,
        current="orphans",
    )


def render_large_files_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """大文件视图：`~/Downloads`、桌面、文稿、影片里超过阈值的文件。

    默认**不勾**；勾了才进废纸篓（可恢复）。列的是"你自己放进去的文件"，
    所以不替用户判断该不该留——只按体积排好队。
    """
    data = payload or {}
    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    total_bytes = int(data.get("bytes", 0) or 0)
    min_mb = int(int(data.get("min_bytes", 0) or 0) / 2**20) or 500

    rows: list[str] = []
    for item in items:
        path = str(item.get("path", ""))
        size = int(item.get("bytes", 0) or 0)
        rows.append(
            f'<div class="row" data-select-row data-sort-text="{html.escape(str(item.get("name", "")).lower())}"'
            f' data-sort-bytes="{size}" data-reveal-path="{html.escape(path)}">'
            '<label class="checkbox-only">'
            f'<input type="checkbox" data-large-path="{html.escape(path)}"></label>'
            '<div style="min-width:0;flex:1">'
            f'<strong>{html.escape(str(item.get("name", "")))}</strong>'
            f'<div class="meta">{html.escape(_display_path(path))}'
            + (f" · {html.escape(str(item.get('modified') or ''))}" if item.get("modified") else "")
            + "</div></div>"
            f'<span class="meta value">{human_bytes(size)}</span></div>'
        )

    toolbar = ""
    if interactive and items:
        # 只留【全选】：进这一页本来就会扫，再给【重新扫描】只是让人怀疑扫没扫。
        toolbar = (
            '<div class="toolbar-left">'
            '<label class="checkbox-inline"><input type="checkbox" data-select-all-large>'
            "<span>全选</span></label></div>"
        )

    body = (
        '<div class="rows" data-sortable>' + "".join(rows) + "</div>"
        if rows
        else empty_block(
            "check",
            "没有发现大文件",
            f"扫过 {', '.join(str(x) for x in (data.get('roots') or [])) or '常用目录'}，"
            f"没有超过 {min_mb} MB 的文件。",
        )
    )
    return state_page(
        {"message": "", "detail": ""},
        stage="large",
        title="大文件",
        body="",
        with_header=False,
        actions=(
            '<div class="review-split">'
            + '<div class="review-right">'
            + (f'<div class="review-head">{toolbar}</div>' if toolbar else "")
            + '<div class="review-detail">' + body + "</div>"
            + (
                '<div class="review-footer">'
                '<div class="review-sum">'
                '<span class="review-sum-main" id="mc-large-count">已选 0 个</span>'
                f'<span class="review-sum-total">共 {len(items)} 个 · {human_bytes(total_bytes)}</span>'
                "</div>"
                '<button class="button primary" type="button" data-bridge-action="large-apply"'
                ' id="mc-large-btn">移入废纸篓</button>'
                "</div>"
                if items and interactive
                else ""
            )
            + "</div></div>"
        ),
        current="large",
    )


def render_large_files_result_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    data = payload or {}
    moved = [item for item in (data.get("moved") or []) if isinstance(item, dict)]
    failed = [item for item in (data.get("failed") or []) if isinstance(item, dict)]
    total_bytes = int(data.get("bytes", 0) or 0)
    rows = "".join(
        '<div class="row"><div style="min-width:0;flex:1">'
        f'<strong>{html.escape(Path(str(item.get("path", ""))).name)}</strong>'
        f'<div class="meta">{html.escape(_display_path(str(item.get("path", ""))))}</div></div>'
        f'<span class="meta value">{human_bytes(int(item.get("bytes", 0) or 0))}</span></div>'
        for item in moved
    )
    fails = "".join(
        f'<p class="pill warn">{html.escape(str(item.get("path", "")))}：'
        f'{html.escape(str(item.get("reason", "")))}</p>'
        for item in failed
    )
    # 之前这里算好了 actions 却**没接进页面**，结果"打开废纸篓"根本不存在——
    # 用户刚移走 2 GB，却找不到去哪儿看（2026-10-21 体检发现）。
    # 也去掉【再扫一次】：侧栏就能重进，页面上不需要再来一个。
    buttons = _actions(_button("打开废纸篓", "open-trash", primary=True)) if interactive else ""
    return state_page(
        {"message": f"已移入废纸篓 {len(moved)} 个文件，共 {human_bytes(total_bytes)}",
         "detail": "在废纸篓里右键「放回原处」即可恢复。"},
        stage="large",
        title="大文件",
        body="",
        with_header=False,
        actions=(
            (rows + fails) if (rows or fails) else empty_block("check", "没有移动任何文件", "你什么都没勾。")
        ) + buttons,
        current="large",
    )


def render_disk_html(
    payload: dict[str, Any] | None = None, *, interactive: bool = True, notice: str = ""
) -> str:
    """磁盘概览（2026-10-19，对齐 Mole 的"磁盘一眼看清"）。

    只读：容量来自 `shutil.disk_usage`，目录体积来自一次 `du -sk`（8 秒超时，拿多少算多少）。
    """
    data = payload or {}
    total = int(data.get("total", 0) or 0)
    used = int(data.get("used", 0) or 0)
    free = int(data.get("free", 0) or 0)
    percent = float(data.get("percent", 0) or 0)
    sections = [item for item in (data.get("sections") or []) if isinstance(item, dict)]
    biggest = max([int(item.get("bytes", 0) or 0) for item in sections] + [1])

    rows: list[str] = []
    for item in sections:
        size = int(item.get("bytes", 0) or 0)
        # 口径只有一种：占**整机**百分比。之前每行是"相对最大项"，同一根条两种含义，
        # 用户会把 Pictures 的满格读成"它占满了磁盘"（2026-10-21）。
        share = (size / total * 100) if total else 0
        share_text = f"{share:.1f}%" if share >= 0.1 else "<0.1%"
        path = str(item.get("path", "") or "")
        # 纯展示行：不可点、无箭头（下钻已删除，2026-10-21）。
        rows.append(
            f'<div class="row" data-sort-text="{html.escape(str(item.get("name", "")).lower())}"'
            f' data-sort-bytes="{size}" data-reveal-path="{html.escape(path)}">'
            f'<div class="row-lead">{_folder_icon(str(item.get("name", "")), path)}'
            f'<strong>{html.escape(str(item.get("name", "")))}</strong></div>'
            f'<span class="meta value">{human_bytes(size)}</span></div>'
        )

    # 系统级目录：root 拥有，不授权读不全（实测 /Library/Caches 会报 0）。
    # **只测量，不删除**——root 域没有"你的废纸篓"，删了不可恢复。
    system = data.get("system") or {}
    sizes = system.get("sizes") or {}
    if sizes:
        def sys_row(path: str, size: Any) -> str:
            # 只有"已授权读到真实体积"时才给勾选框：没读数就不知道搬的是多大一堆。
            box = (
                f'<input type="checkbox" data-system-path="{html.escape(str(path))}">'
                if (interactive and system.get("admin"))
                else '<span class="pill ghost">只读</span>'
            )
            return (
                f'<label class="row opt readonly">{box}<div class="row-lead">' + _icon("lock") +
                f'<strong>{html.escape(str(path))}</strong></div>'
                f'<span class="meta value">{human_bytes(int(size or 0))}</span></label>'
            )

        sys_rows = "".join(sys_row(path, size) for path, size in sizes.items())
        system_block = (
            '<div class="section-readonly">'
            '<div class="group-title">系统级目录'
            + ('<span class="pill ghost">一次性授权</span>' if system.get("admin") else '<span class="pill ghost">只读</span>')
            + "</div>"
            + sys_rows
            + (
                _actions(
                    _button(
                        "重新测量（需管理员授权一次）" if system.get("admin") else "用管理员授权测量一次（只读）",
                        "system-sizes",
                        ghost=True,
                    ),
                    # 仅在"已读到真实体积"时提供搬走：否则用户不知道自己在确认什么。
                    _button("授权并移入废纸篓", "system-trash", primary=True) if system.get("admin") else "",
                )
                if interactive
                else ""
            )
            + (
                '<p class="muted">移入的是<b>你的</b>废纸篓：能拿回来，但文件属主是 root——'
                "清空废纸篓时可能还要授权，Finder 的「放回原处」对它们不可用。</p>"
                if system.get("admin")
                else ""
            )
            + (f'<p class="muted">{html.escape(str(system.get("note") or ""))}</p>' if system.get("note") else "")
            + "</div>"
        )
    else:
        system_block = (
            '<div class="section-readonly">'
            '<div class="group-title">系统级目录<span class="pill ghost">只读</span></div>'
            '<p class="muted">/Library/Caches、/var/log 属于 root：不授权读不到准确体积，本工具不删除它们。</p>'
            + (_button("用管理员授权测量一次（只读）", "system-sizes", ghost=True) if interactive else "")
        )

    return state_page(
        {
            "message": f"已用 {human_bytes(used)}，可用 {human_bytes(free)}（共 {human_bytes(total)}）",
            "detail": "目录体积是当前占用，不是可清理量；要清理请回「Mac 清理」。",
        },
        stage="disk",
        title="磁盘",
        body="",
        hero=f"{percent:.0f}%",
        # 顶部只留一条"整机容量条"：这是唯一代表"总量"的条。
        # treemap 放在总览（2026-10-21 用户要求）：这一页就是"看分布"，不需要下钻。
        actions=(f'<p class="pill warn" role="status">{html.escape(notice)}</p>' if notice else "")
        + _meter(percent, tone="warn")
        + _treemap_svg(sections, clickable=False)
        + f'<div class="rows">{"".join(rows)}</div>'
        + system_block,
        current="disk",
    )


def render_system_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """系统状态：负载 / 内存 / 电池 / 节流 / 进程（只读）。

    电池与节流走 `pmset`/`ioreg`（免 sudo）；**风扇不做**——SMC 私有接口，值也不稳定。
    """
    data = payload or {}
    load = list(data.get("load") or [0, 0, 0])
    cpu_count = int(data.get("cpu_count", 0) or 0)
    mem_total = int(data.get("memory_total", 0) or 0)
    mem_used = int(data.get("memory_used", 0) or 0)
    processes = [item for item in (data.get("processes") or []) if isinstance(item, dict)]
    mem_percent = (mem_used / mem_total * 100) if mem_total else 0.0
    load_percent = (float(load[0] or 0) / max(1, cpu_count) * 100) if cpu_count else 0.0

    power = data.get("power") or {}
    thermal = data.get("thermal") or {}
    percent = power.get("percent")
    state_text = {"charging": "充电中", "discharging": "放电中", "charged": "已充满",
                  "finishing charge": "即将充满", "AC attached": "已接电源"}.get(
        str(power.get("state") or "").lower(), str(power.get("state") or "")
    )
    if percent is not None:
        battery_value = f"{int(percent)}%"
        battery_meta = " · ".join(part for part in (
            str(power.get("source") or ""), state_text,
            (
                f"剩 {power.get('remaining')}"
                if power.get("remaining") and str(power.get("state") or "").lower() == "discharging"
                else ""
            ),
        ) if part)
    else:
        battery_value, battery_meta = "—", "未检测到电池（台式机？）"
    power_block = (
        f'<div class="stat"><div class="k">电池</div><div class="v">{battery_value}</div>'
        f'<div class="meta">{html.escape(battery_meta)}</div></div>'
        + (
            f'<div class="stat"><div class="k">循环 / 健康</div>'
            f'<div class="v">{int(power["cycles"])} / {int(power["health_percent"])}%</div>'
            f'<div class="meta">设计 {int(power["design_mah"] or 0)} mAh</div></div>'
            if power.get("cycles") is not None and power.get("health_percent") is not None
            else ""
        )
        + (
            f'<div class="stat"><div class="k">性能节流</div>'
            f'<div class="v">{int(thermal["speed_limit"])}%</div>'
            f'<div class="meta">CPU 速度上限</div></div>'
            if thermal.get("speed_limit") is not None
            else '<div class="stat"><div class="k">性能节流</div><div class="v">正常</div>'
            '<div class="meta">未触发限制</div></div>'
        )
    )

    # 三格：负载 / 内存 / CPU。每一格都写明"基准"（多少核、占多少 %），
    # 不再在下面另画两条没有刻度的 meter——同一个量只该有一种表达（2026-10-21）。
    stats_head = (
        '<div class="stats">'
        f'<div class="stat"><div class="k">负载（1 / 5 / 15 分钟）</div>'
        f'<div class="v">{" / ".join(str(x) for x in load)}</div>'
        # 负载按"每核倍数"表达：8.55/10 核 = 0.86。写成 86% 会在过载时变成 156%，
        # 反而让人以为计算错了（2026-10-21 截图里就出现过 156%）。
        f'<div class="meta">1 分钟 {float(load[0] if load else 0):.2f} · 每核 {"%.2f" % (float(load[0] if load else 0) / max(1, cpu_count))}</div></div>'
        f'<div class="stat"><div class="k">内存</div>'
        f'<div class="v">{human_bytes(mem_used)} / {human_bytes(mem_total)}</div>'
        f'<div class="meta">已用 {mem_percent:.0f}%</div></div>'
        f'<div class="stat"><div class="k">CPU</div><div class="v">{cpu_count} 核</div></div>'
        "</div>"
    )
    rows = "".join(
        '<div class="row"><div class="row-lead">' + _icon("terminal") +
        f'<strong>{html.escape(str(item.get("name", "")))}</strong></div>'
        f'<span class="meta">{human_bytes(int(item.get("rss", 0) or 0))} 内存</span>'
        f'<span class="meta value">{float(item.get("cpu", 0) or 0):.1f}%</span></div>'
        for item in processes
    )
    return state_page(
        {"message": "", "detail": "只读；电池与节流免 sudo 读取，风扇转速不做（SMC 私有接口，值不稳定）。"},
        stage="system",
        title="系统状态",
        body="",
        with_header=False,
        actions=(
            '<div class="review-detail">'
            + stats_head
            + '<div class="group-title">电池与节流</div>'
            + '<div class="stats">' + power_block + "</div>"
            + (
                '<div class="group-title">占用最高的进程'
                f'<span class="meta">按 CPU 排序 · {len(processes)} 个</span></div>' + rows
                if rows
                else ""
            )
            + "</div>"
        ),
        current="system",
    )




__all__ = [
    "render_large_files_html",
    "render_large_files_result_html",
    "render_sparkle_result_html",
    "render_uninstall_cask_result_html",
    "render_orphans_html",
    "render_orphans_result_html",
    "render_disk_html",
    "render_system_html",
    "human_bytes",
    "render_cancelled_html",
    "render_completion_html",
    "render_confirmation_html",
    "render_landing_html",
    "render_progress_html",
    "render_recovery_html",
    "render_review_html",
    "render_skills_html",
    "render_uninstall_complete_html",
    "render_uninstall_list_html",
    "render_uninstall_preview_html",
    "render_updates_list_html",
    "render_updates_result_html",
]
