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


def _rows(
    items: Iterable[dict[str, Any]], *, note_key: str = "reason", selectable: bool = False
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
        body = (
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(meta)}</div>'
        )
        if selectable:
            target_id = html.escape(str(item.get("target_id", "") or ""))
            risky = bool(item.get("requires_confirmation"))
            # 默认**不勾**；高风险项连勾选框都不给（要在确认页单独确认）。
            box = (
                '<input type="checkbox" disabled data-risk="1">'
                if risky
                else f'<input type="checkbox" data-target-id="{target_id}">'
            )
            risk_note = (
                '<span class="pill risk">高风险 · 确认页单独确认</span>' if risky else ""
            )
            rows.append(
                f'<label class="row opt"{sort_attrs}{reveal_attr}>{box}<div>{body}{risk_note}</div>'
                f'<span class="meta value">{size}</span></label>'
            )
        else:
            rows.append(
                f'<div class="row"{sort_attrs}{reveal_attr}><div>{body}</div><span class="meta value">{size}</span></div>'
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
    page = state_page(
        {
            "message": "将扫描启动盘上的缓存、日志、废纸篓等推荐类型。",
            "detail": "扫描只读取文件大小与修改时间，不会改动或删除任何内容。",
        },
        stage="idle",
        title="开始一次清理",
        body="扫描你的 Mac，先看清单再决定删什么",
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
    ("browser", "浏览器", "浏览器留下的缓存（不含 Cookies / 登录数据）；默认不勾", ("browser",)),
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
            f'<span class="group-name">{label}</span>'
            f'<span class="meta">{len(items)} 项 · {human_bytes(size)}</span>'
            "</summary>"
            f'<p class="group-hint meta">{hint}</p>'
            f'<div class="rows">{"".join(_rows(items, selectable=interactive))}</div>'
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


def render_review_html(
    payload: dict[str, Any], *, interactive: bool = True, notice: str = ""
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
    actions = (
        _actions(
            _button("取消", "cancel"),
            _button("重新扫描", "rescan"),
            _button("开始清理", "approval", primary=True),
        )
        if (interactive and candidates)
        else _actions(_button("退出", "cancel"), _button("重新扫描", "rescan", primary=interactive))
    )
    empty = (
        empty_block("check", "没有找到可清理的内容", "你的 Mac 现在挺干净。可以稍后再扫一次，或先去看看卸载残留。")
        if not candidates
        else ""
    )
    # 头部固定（2026-10-20 用户要求：滚列表时这半部分一直在）。
    # 标题区与"找到可清理的内容…"整块已删——它只是重复下面的数字。
    head = (
        (f'<p class="pill warn" role="status">{html.escape(notice)}</p>' if notice else "")
        + (
            '<label class="row opt select-all"><input type="checkbox" data-select-all>'
            '<div><strong>全选（不含浏览器 / 系统数据）</strong>'
            '<div class="meta">默认不勾；高风险项在确认页单独确认</div></div>'
            '<span class="meta value" id="mc-picked-bytes">已选 0 B</span></label>'
            if candidates and interactive
            else ""
        )
        + _review_filter_bar(_present_review_groups(candidates, payload.get("system")))
    )
    return state_page(
        {"message": "", "detail": ""},
        stage="review",
        title="审阅清单",
        body="",
        with_header=False,
        actions=(
            empty
            + (f'<div class="review-head">{head}</div>' if head else "")
            + _review_groups_html(
                candidates,
                interactive=interactive and bool(candidates),
                system=payload.get("system"),
            )
            + actions
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
        _actions(_button("再看一眼", "rescan"), _button("打开废纸篓", "open-trash", primary=True))
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
            "detail": (f"回执：{receipt}" if receipt else "")
            + " · 失败/跳过：%d" % int(payload.get("failed_count", 0) or 0),
        },
        stage="complete",
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
        body="这次没有完成",
        actions=block + buttons,
        current="clean",
        subtitle="失败不是终点：重试会从这一步重新开始",
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
            '<div style="min-width:0;flex:1">'
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(bundle)}</div>'
            "</div>"
            f'<div class="row-actions">{size_text}{button}</div></div>'
        )
        initial = name.strip()[:1].upper()
        key = initial if (initial.isascii() and initial.isalpha()) else "#"
        buckets.setdefault(key, []).append(row)

    groups: list[str] = []
    for key in sorted(buckets, key=lambda item: (item == "#", item)):
        rows = buckets[key]
        groups.append(
            f'<details class="group" open data-group data-letter="{html.escape(key)}">'
            f'<summary><span class="group-name">{key}</span>'
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
            '<span class="meta" id="mc-selected-count"></span></div>'
            '<div class="toolbar-right">'
            + sort_bar()
            + _button("批量卸载所选", "uninstall-batch", primary=True)
            + "</div>"
        )

    if groups:
        index = "".join(
            f'<button type="button" data-jump="{html.escape(key)}" aria-label="跳到 {html.escape(key)}">'
            f"{html.escape(key)}</button>"
            for key in sorted(buckets, key=lambda item: (item == "#", item))
        )
        body = (
            '<div class="list-with-index">'
            f'<div class="groups">{"".join(groups)}</div>'
            f'<nav class="alpha" aria-label="字母索引">{index}</nav></div>'
        )
    else:
        body = empty_block("check", "没有找到应用", "换一个入口，或稍后再来。")
    return state_page(
        {
            "message": "点行尾【卸载】看它留下的文件；勾选多个可以批量处理",
            "detail": "系统级残留需要一次管理员授权；体积在点开应用后计算。",
        },
        stage="uninstall-list",
        title="软件卸载",
        body="选择一个应用",
        toolbar=toolbar,
        actions=body,
        current="uninstall",
        subtitle="先看残留清单，确认后才移入废纸篓（可恢复）",
        meta=f"{len(apps)} 个应用" if apps else "",
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
    exact = [item for item in items if item.get("confidence") != "name-match" and item.get("kind") != "app-bundle"]
    guessed = [item for item in items if item.get("confidence") == "name-match"]
    bundle = next((item for item in items if item.get("kind") == "app-bundle"), None)

    parts: list[str] = []
    if bundle:
        parts.append(
            '<div class="row"><div><strong>'
            + html.escape(str(app.get("name", "")))
            + '</strong><div class="meta">应用本体 · 始终包含</div></div>'
            '<span class="pill">必选</span></div>'
        )
    if exact:
        parts.append('<p class="group-title">确定项</p>')
        for item in exact:
            parts.append(
                '<label class="row opt"><input type="checkbox" data-item-id="'
                + html.escape(str(item.get("id", "")))
                + '" checked><div><strong>'
                + html.escape(str(item.get("path", "")).rstrip("/").split("/")[-1])
                + '</strong><div class="meta">'
                + html.escape(str(item.get("kind", "")))
                + "</div></div><span class=\"meta\">"
                + human_bytes(int(item.get("allocated_bytes", 0) or 0))
                + "</span></label>"
            )
    if guessed:
        parts.append('<p class="group-title">按名称匹配（默认不勾）</p>')
        for item in guessed:
            parts.append(
                '<label class="row opt"><input type="checkbox" data-item-id="'
                + html.escape(str(item.get("id", "")))
                + '"><div><strong>'
                + html.escape(str(item.get("path", "")).rstrip("/").split("/")[-1])
                + '</strong><div class="meta">可能是别的应用 · '
                + html.escape(str(item.get("kind", "")))
                + "</div></div><span class=\"meta\">"
                + human_bytes(int(item.get("allocated_bytes", 0) or 0))
                + "</span></label>"
            )

    actions = (
        _actions(_button("返回列表", "uninstall-back"), _button("卸载所选", "uninstall-apply", primary=True))
        if interactive
        else ""
    )
    if notice:
        # 提示放在按钮**上方**，否则它会挤在动作条里、看起来像另一个按钮。
        actions = f'<p class="pill warn" role="status">{html.escape(notice)}</p>' + actions

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

    return state_page(
        {
            "message": f"将移入废纸篓 {len(items)} 项，共 {human_bytes(int(plan.get('user_total_bytes', 0) or 0))}（可恢复）",
            "detail": "确认后会再核对每个位置；名称匹配项默认不勾，请自行判断。",
        },
        stage="uninstall-preview",
        title=f"卸载 {app.get('name', '')}".strip(),
        body="确认要清理的内容",
        actions=cask_block + actions + "".join(parts),
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
            '<details class="group" open><summary>'
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
            '<div style="min-width:0;flex:1">'
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
            "<span>全选</span></label>"
            '<span class="meta" id="mc-updates-count"></span></div>'
            '<div class="toolbar-right">'
            + _button("重新检查", "updates-refresh")
            # App Store 应用绕不开 Apple ID：mas 用不了时把更新页打开，让系统自己装。
            + (
                _button("打开 App Store 更新页", "open-app-store", ghost=True)
                if any(str(item.get("manager")) == "mas" for item in items)
                else ""
            )
            + _button("更新所选", "updates-apply", primary=True)
            + "</div>"
        )
        if notice:
            toolbar += f'<p class="pill warn" role="status">{html.escape(notice)}</p>'

    sparkle_block = ""
    if sparkle_rows:
        sparkle_block = (
            '<details class="group" open><summary>'
            '<span class="group-name">自带更新（Sparkle）</span>'
            f'<span class="meta">{len(sparkle_rows)} 个</span></summary>'
            f'<div class="rows">{"".join(sparkle_rows)}</div></details>'
        )
    # Sparkle 组放**最前**：策略是"先应用内更新，不行再 App Store"（2026-10-19 用户要求）。
    body = sparkle_block + ("".join(groups) if groups else empty_block(
        "check", "已经是最新的", "没有发现可升级的第三方软件。"
    ))
    return state_page(
        {
            "message": f"可升级 {len(items)} 项，按来源分了 {len(groups)} 组"
            + (f"，另有 {len(sparkle_rows)} 个应用可自带更新" if sparkle_rows else "")
            + (
                f'（数据来自 {time.strftime("%H:%M", time.localtime(float(payload.get("checked_at"))))}'
                + ("，缓存" if payload.get("cached") else "")
                + "）"
                if payload.get("checked_at")
                else ""
            ),
            "detail": "只处理第三方来源；macOS 系统更新不在此列。升级不可逆，确认后逐组执行并记录输出。",
        },
        stage="updates",
        title="软件更新",
        body="可升级的第三方软件",
        toolbar=toolbar,
        actions=body + notes,
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
    rows: list[str] = []

    current_root = ""
    for skill in skills:
        root = str(skill.get("root", "") or "")
        if root != current_root:
            current_root = root
            rows.append(f'<p class="group-title">{html.escape(root or "(未知来源)")}</p>')
        name = str(skill.get("name", "") or "")
        description = str(skill.get("description", "") or "")
        path = str(skill.get("path", "") or "")
        mine = name.strip().lower() in {"mac cleaner", "mac-cleaner", "maccleaner"}
        rows.append(
            '<div class="row"><div style="min-width:0">'
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(description[:120])}</div>'
            f'<div class="meta">{html.escape(path)}</div>'
            "</div>"
            + ('<span class="pill ok">本工具</span>' if mine else '<span class="pill">可调用</span>')
            + "</div>"
        )

    body = "".join(rows) or '<p class="muted">没有在常见 skill 根下找到 SKILL.md。</p>'
    # 本工具自己的细节仍收进折叠块：列表要"全"，但触发词/边界这类说明不该占满屏幕。
    body += (
        "<details style=\"margin-top:16px\"><summary>本工具的触发词 / 调用方式 / 边界</summary>"
        '<div class="meta" style="margin-top:8px;line-height:1.9">'
        "<div><b>触发词</b>：mac清理、清理磁盘、清理缓存、清理磁盘空间</div>"
        "<div><b>怎么调用</b>：<code>maccleaner ui</code>（本地界面）/ <code>maccleaner uninstall</code> / MCP 工具</div>"
        "<div><b>边界</b>：扫描只读；清理一律移入废纸篓；系统级残留需要一次管理员授权。</div>"
        "</div></details>"
    )
    actions = _actions(_button("返回", "start", primary=True)) if interactive else ""
    return state_page(
        {
            "message": f"本机共 {len(skills)} 个可被调用的 skill",
            "detail": "来自 ~/.codex/skills、~/.codebuddy/skills、~/.claude/skills（可用 MACCLEANER_SKILL_ROOTS 追加）。"
                      "本页只读，不会执行任何 skill。",
        },
        stage="skills",
        title="可调用的 Skill",
        body="本机全部 skill",
        actions=actions + body,
        current="skills",
    )


def _meter(percent: float, *, tone: str = "accent") -> str:
    """一条容量条。`percent` 会被夹到 0–100，避免离谱数据把宽度撑出页面。"""
    width = max(0.0, min(100.0, float(percent or 0)))
    return f'<div class="meter"><span style="width:{width:.1f}%;background:var(--{tone})"></span></div>'



def sort_bar(*, default: str = "bytes") -> str:
    """排序条：按体积（默认，降序）/ 按名称（升序）。

    为什么放前端：排序是纯展示，不该为一次点击重新扫盘或重发页面。
    """
    return (
        '<div class="sortbar"><span class="meta">排序</span>'
        f'<button type="button" class="sortbtn{" is-on" if default == "bytes" else ""}" '
        'data-sort="bytes" data-dir="desc">体积</button>'
        f'<button type="button" class="sortbtn{" is-on" if default == "text" else ""}" '
        'data-sort="text" data-dir="asc">名称</button></div>'
    )
def _treemap_svg(entries: list[dict[str, Any]], *, width: int = 1000, height: int = 300) -> str:
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
        attrs = (
            f' data-treemap-path="{html.escape(path)}" role="button" tabindex="0"'
            ' aria-label="' + html.escape(f"{name} {human_bytes(size)}") + '"'
            if is_dir
            else ""
        )
        cursor = ' style="cursor:pointer"' if is_dir else ""
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
        + '<p class="meta">点方块进入该目录；面积 = 体积占比。'
        + html.escape(rest_note)
        + "</p></div>"
    )


def render_disk_browse_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """磁盘钻取：一个目录的下一级，按体积降序；目录可以再点进去。"""
    data = payload or {}
    entries = [item for item in (data.get("entries") or []) if isinstance(item, dict)]
    display = str(data.get("display") or data.get("path") or "")
    parent = str(data.get("parent") or "")
    total = int(data.get("total", 0) or 0)
    biggest = max([int(item.get("bytes", 0) or 0) for item in entries] + [1])

    rows: list[str] = []
    for item in entries:
        size = int(item.get("bytes", 0) or 0)
        share = size / biggest * 100 if biggest else 0
        name = str(item.get("name", ""))
        path = str(item.get("path", ""))
        is_dir = bool(item.get("is_dir"))
        open_button = (
            _button("进入", "disk-open", payload={"path": path}) if (interactive and is_dir) else ""
        )
        rows.append(
            f'<div class="row" data-sort-text="{html.escape(name.lower())}"'
            f' data-sort-bytes="{size}" data-reveal-path="{html.escape(path)}">'
            '<div style="min-width:0;flex:1">'
            f"<strong>{html.escape(name)}{'/' if is_dir else ''}</strong>"
            f'<div class="meta">{_meter(share)}</div></div>'
            f'<span class="meta value">{human_bytes(size)}</span>{open_button}</div>'
        )

    buttons = []
    if interactive:
        if parent:
            buttons.append(_button("上一级", "disk-back"))
        buttons.append(_button("回到总览", "disk-open", payload={}))
    body = (
        _treemap_svg(entries)
        + sort_bar()
        + '<div class="rows" data-sortable>' + "".join(rows) + "</div>"
        if rows
        else empty_block("check", "这个目录是空的", "换一个目录，或回到磁盘总览。")
    )
    return state_page(
        {
            "message": f"{display} 下一级共 {human_bytes(total)}",
            "detail": "点【进入】看下一级；体积是当前占用，不是“可清理”的量。",
        },
        stage="disk",
        title="磁盘",
        body="",
        actions=body + _actions(*buttons),
        current="disk",
        subtitle="逐层看谁最占地方",
        meta=f"{len(entries)} 项",
    )


def render_orphans_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """孤儿残留体检（学 Pearcleaner 的 orphan scan）。

    判定口径写在页面上：名字像 bundle id、没有对应已装应用、且 7 天没动过。
    **默认不勾**，勾了才动，而且只进废纸篓。
    """
    data = payload or {}
    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    total = int(data.get("total", len(items)) or 0)
    total_bytes = int(data.get("bytes", 0) or 0)

    rows: list[str] = []
    for item in items:
        path = str(item.get("path", ""))
        size = int(item.get("bytes", 0) or 0)
        name = str(item.get("name", ""))
        rows.append(
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

    toolbar = ""
    if interactive and items:
        toolbar = (
            '<div class="toolbar-left">'
            '<label class="checkbox-inline"><input type="checkbox" data-select-all-orphans>'
            "<span>全选</span></label>"
            '<span class="meta" id="mc-orphans-count"></span></div>'
            '<div class="toolbar-right">'
            + _button("重新扫描", "orphans-open")
            + _button("移入废纸篓", "orphans-apply", primary=True)
            + "</div>"
        )

    body = (
        '<div class="rows" data-sortable>' + "".join(rows) + "</div>"
        if rows
        else empty_block(
            "check",
            "没有发现孤儿残留",
            "扫过 Caches / Preferences / Logs / Containers / WebKit / HTTPStorages / Saved State，"
            "每一项都能对上一个已装应用。",
        )
    )
    return state_page(
        {
            "message": (
                f"疑似残留 {total} 项，共 {human_bytes(total_bytes)}"
                + (f"（页面列出前 {len(items)} 项）" if total > len(items) else "")
                if items
                else "没有发现孤儿残留"
            ),
            "detail": "判定：名字像 bundle id、对不上任何已装应用、且 7 天没被改动过。"
            "默认不勾；勾了才移入废纸篓（可恢复）。"
            + (
                f" 另有 {int(data.get('skipped_vendor', 0) or 0)} 项同厂商组件被保守排除"
                "（同厂商别的应用还装着，先不动）。"
                if int(data.get("skipped_vendor", 0) or 0)
                else ""
            ),
        },
        stage="orphans",
        title="残留体检",
        body="",
        toolbar=toolbar,
        actions=body,
        current="orphans",
        subtitle="应用删了，残留还在？这里找那些没人认领的",
        meta=f"已装 {int(data.get('installed', 0) or 0)} 个应用",
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
    actions = _actions(
        _button("再扫一次", "orphans-open"),
        _button("打开废纸篓", "open-trash", ghost=True) if interactive else "",
    ) if interactive else ""
    return state_page(
        {
            "message": f"已移入废纸篓 {len(moved)} 项，共 {human_bytes(total_bytes)}",
            "detail": "想恢复的话，在废纸篓里右键「放回原处」。",
        },
        stage="orphans",
        title="残留体检",
        body="",
        actions=(rows + fail_rows) if (rows or fail_rows) else empty_block("check", "没有移动任何文件", "你什么都没勾。"),
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
        toolbar = (
            '<div class="toolbar-left">'
            '<label class="checkbox-inline"><input type="checkbox" data-select-all-large>'
            "<span>全选</span></label>"
            '<span class="meta" id="mc-large-count"></span></div>'
            '<div class="toolbar-right">'
            + _button("重新扫描", "large-open")
            + _button("移入废纸篓", "large-apply", primary=True)
            + "</div>"
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
    truncated = "（扫描超时或结果过多，只列了前一部分）" if data.get("truncated") else ""
    return state_page(
        {
            "message": (
                f"{len(items)} 个大文件，共 {human_bytes(total_bytes)}"
                if items
                else "没有发现大文件"
            ),
            "detail": f"阈值 {min_mb} MB；默认不勾，勾了才移入废纸篓（可恢复）。{truncated}",
        },
        stage="large",
        title="大文件",
        body="",
        toolbar=toolbar,
        actions=body,
        current="large",
        subtitle="按体积排队，不替你判断该不该留",
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
    actions = _actions(
        _button("再扫一次", "large-open"),
        _button("打开废纸篓", "open-trash", ghost=True),
    ) if interactive else ""
    return state_page(
        {"message": f"已移入废纸篓 {len(moved)} 个文件，共 {human_bytes(total_bytes)}",
         "detail": "在废纸篓里右键「放回原处」即可恢复。"},
        stage="large",
        title="大文件",
        body="",
        actions=(rows + fails) if (rows or fails) else empty_block("check", "没有移动任何文件", "你什么都没勾。"),
        current="large",
    )


def render_history_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
    """清理历史：直接读回执文件（时间/模式/条目/字节），只读。"""
    data = payload or {}
    entries = [item for item in (data.get("entries") or []) if isinstance(item, dict)]
    runs = int(data.get("runs", len(entries)) or 0)
    total_bytes = int(data.get("total_bytes", 0) or 0)
    total_items = int(data.get("total_items", 0) or 0)

    rows = []
    for item in entries:
        created = str(item.get("created_at") or "").replace("T", " ")[:16]
        mode = "清理" if item.get("mode") == "clean" else str(item.get("mode") or "")
        if item.get("dry_run"):
            mode += " · 预演"
        moved = int(item.get("items", 0) or 0)
        freed = int(item.get("bytes", 0) or 0)
        estimated = int(item.get("estimated", 0) or 0)
        # 走废纸篓的记录"实际释放"是 0（空间还在废纸篓里），这时显示可恢复量——
        # 否则历史页每条都是 "—"，看着像什么都没清（2026-10-19 截图发现）。
        if freed:
            size_text = human_bytes(freed)
        elif estimated:
            size_text = "可恢复 " + human_bytes(estimated)
        else:
            size_text = "—"
        rows.append(
            '<div class="row"><div style="min-width:0">'
            f"<strong>{html.escape(created or '(无时间)')}</strong>"
            f'<div class="meta">{html.escape(mode)} · {moved} 项</div></div>'
            f'<span class="meta value">{size_text}</span></div>'
        )

    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="k">清理次数</div><div class="v">{runs}</div></div>'
        f'<div class="stat"><div class="k">最近释放</div><div class="v">{human_bytes(total_bytes)}</div></div>'
        f'<div class="stat"><div class="k">条目</div><div class="v">{total_items}</div></div>'
        "</div>"
    )
    body = "".join(rows) or empty_block("check", "还没有清理记录", "第一次清理完成后，这里会出现可核对的时间、条目与字节。")
    return state_page(
        {
            "message": "每次清理都会留下回执文件；这里只读它们，不做任何修改。",
            "detail": "走废纸篓的记录`实际释放`为 0，字节数在移入时记的是可恢复量。",
        },
        stage="history",
        title="清理历史",
        body="",
        actions=stats + '<div class="rows">' + body + "</div>"
        + (_actions(_button("刷新", "history-open")) if interactive else ""),
        current="history",
        subtitle="来自回执文件（~/.mac-storage-manager/receipts）",
        meta=f"最近 {len(entries)} 条" if entries else "",
    )

def render_disk_html(payload: dict[str, Any] | None = None, *, interactive: bool = True) -> str:
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
        share = size / biggest * 100 if biggest else 0
        path = str(item.get("path", "") or "")
        enter = (
            _button("进入", "disk-open", payload={"path": path}) if (interactive and path) else ""
        )
        rows.append(
            f'<div class="row" data-sort-text="{html.escape(str(item.get("name", "")).lower())}"'
            f' data-sort-bytes="{size}" data-reveal-path="{html.escape(path)}">'
            '<div style="min-width:0;flex:1">'
            f'<strong>{html.escape(str(item.get("name", "")))}</strong>'
            f'<div class="meta">{_meter(share)}</div></div>'
            f'<span class="meta value">{human_bytes(size)}</span>{enter}</div>'
        )

    # 系统级目录：root 拥有，不授权读不全（实测 /Library/Caches 会报 0）。
    # **只测量，不删除**——root 域没有"你的废纸篓"，删了不可恢复。
    system = data.get("system") or {}
    sizes = system.get("sizes") or {}
    if sizes:
        sys_rows = "".join(
            '<div class="row"><div style="min-width:0;flex:1">'
            f'<strong>{html.escape(str(path))}</strong>'
            f'<div class="meta">{"已授权读取（只测量）" if system.get("admin") else "未授权：可能读不全"}</div></div>'
            f'<span class="meta value">{human_bytes(int(size or 0))}</span></div>'
            for path, size in sizes.items()
        )
        system_block = (
            '<div class="group-title">系统级目录（只测量，不删除）</div>'
            + sys_rows
            + (
                _button(
                    "重新测量（需管理员授权一次）" if system.get("admin") else "用管理员授权测量一次（只读）",
                    "system-sizes",
                )
                if interactive
                else ""
            )
            + (f'<p class="muted">{html.escape(str(system.get("note") or ""))}</p>' if system.get("note") else "")
        )
    else:
        system_block = (
            '<div class="group-title">系统级目录（只测量，不删除）</div>'
            '<p class="muted">/Library/Caches、/var/log 属于 root：不授权读不到准确体积。</p>'
            + (_button("用管理员授权测量一次（只读）", "system-sizes", ghost=True) if interactive else "")
        )

    return state_page(
        {
            "message": f"已用 {human_bytes(used)}，可用 {human_bytes(free)}",
            "detail": "目录体积是当前占用（不是“可清理”的量）；清理请回「Mac 清理」看候选。",
        },
        stage="disk",
        title="磁盘",
        body="",
        hero=f"{percent:.0f}%",
        actions=_meter(percent, tone="warn") + sort_bar()
        + f'<div class="rows" data-sortable>{"".join(rows)}</div>'
        + system_block
        + (_actions(_button("刷新", "disk-open")) if interactive else ""),
        current="disk",
        subtitle="整机容量与常用目录占用（只读）",
        meta=f"{human_bytes(total)} 总容量",
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
            (f"剩 {power.get('remaining')}" if power.get("remaining") else ""),
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

    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="k">1/5/15 分钟负载</div>'
        f'<div class="v">{" / ".join(str(x) for x in load)}</div></div>'
        f'<div class="stat"><div class="k">内存</div>'
        f'<div class="v">{human_bytes(mem_used)} / {human_bytes(mem_total)}</div></div>'
        f'<div class="stat"><div class="k">CPU 核数</div><div class="v">{cpu_count}</div></div>'
        + power_block
        + "</div>"
    )
    rows = "".join(
        '<div class="row"><div style="min-width:0">'
        f'<strong>{html.escape(str(item.get("name", "")))}</strong>'
        f'<div class="meta">{human_bytes(int(item.get("rss", 0) or 0))} 内存</div></div>'
        f'<span class="meta value">{float(item.get("cpu", 0) or 0):.1f}%</span></div>'
        for item in processes
    )
    return state_page(
        {
            "message": f"内存占用 {mem_percent:.0f}%，1 分钟负载 {load[0] if load else 0}",
            "detail": "电池与节流免 sudo 读取；风扇转速不做（SMC 私有接口，值也不稳定）。进程按 CPU 排序。",
        },
        stage="system",
        title="系统状态",
        body="",
        actions=stats + '<div class="group-title">负载</div>' + _meter(load_percent, tone="warn")
        + '<div class="group-title">内存</div>' + _meter(mem_percent)
        + '<div class="group-title">占用最高的进程</div>' + rows
        + (_actions(_button("刷新", "system-open")) if interactive else ""),
        current="system",
        subtitle="负载 / 内存 / 电池 / 进程（只读）",
        meta="",
    )


__all__ = [
    "render_disk_browse_html",
    "render_large_files_html",
    "render_large_files_result_html",
    "render_sparkle_result_html",
    "render_uninstall_cask_result_html",
    "render_orphans_html",
    "render_orphans_result_html",
    "render_disk_html",
    "render_history_html",
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
