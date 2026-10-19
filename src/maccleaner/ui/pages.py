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
from typing import Any, Iterable, Sequence

from .shell import state_page


def human_bytes(value: int | float) -> str:
    number = float(max(0, int(value or 0)))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or unit == "TiB":
            return f"{int(number)} B" if unit == "B" else f"{number:.2f} {unit}"
        number /= 1024
    return f"{number:.2f} TiB"


def _button(
    label: str,
    action: str,
    *,
    primary: bool = False,
    element_id: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    """按钮只携带**动作名 + 数据**；参数走 data-bridge-payload。

    为什么参数不拼进动作名（`uninstall-plan:<id>`）：桥的动作白名单是按**裸动作名**匹配的，
    拼字符串会被 400 拒掉；把参数放进 payload，白名单与校验逻辑就能保持单一来源。
    """
    import json as _json

    cls = "button primary" if primary else "button"
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


def _rows(items: Iterable[dict[str, Any]], *, note_key: str = "reason") -> str:
    rows: list[str] = []
    for item in items:
        path = str(item.get("path", "") or "")
        name = path.rstrip("/").split("/")[-1] or path
        kind = str(item.get("kind", "") or item.get("status", "") or "")
        note = str(item.get(note_key, "") or "")
        size = human_bytes(int(item.get("allocated_bytes", 0) or item.get("bytes", 0) or 0))
        rows.append(
            '<div class="row"><div>'
            f"<strong>{html.escape(name)}</strong>"
            f'<div class="meta">{html.escape(kind)}{" · " + html.escape(note) if note else ""}</div>'
            f"</div><span class=\"meta\">{size}</span></div>"
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
    summary = (
        f"上次共清理 {runs} 次，可恢复 {human_bytes(total)}（清空废纸篓后才真正释放）"
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
            "<script>setTimeout(function(){location.reload()}, 1500)</script>"
            if data.get("auto_refresh", True)
            else ""
        ),
        current=str(data.get("nav") or "clean"),
    )


def render_review_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """审阅页：列出候选，**用户可以逐条不选**；没有候选时明确说"没找到"。

    这一页的核心承诺是"先看清单再决定删什么"——所以候选必须逐条可见（名称、类型、大小），
    而不是只给一个总数。
    """
    candidates = [item for item in (payload.get("candidates") or []) if isinstance(item, dict)]
    total = sum(int(item.get("allocated_bytes", 0) or 0) for item in candidates)
    # 空结果时不写 state-head/state-msg：结论交给下面的 empty 块，否则同一句话说三遍
    # （2026-10-19 截图里一眼看到三处重复）。
    body = "找到可清理的内容" if candidates else ""
    detail = (
        f"共 {len(candidates)} 组候选，可恢复 {human_bytes(total)}；"
        "点【开始清理】前会再让你确认一次，文件一律移入废纸篓（可恢复）。"
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
    return state_page(
        {"message": "逐组核对下面的清单，确认无误再开始清理" if candidates else "", "detail": detail},
        stage="review",
        title="审阅清单",
        body=body,
        actions=empty + _rows(candidates) + actions,
        current="clean",
        subtitle="只读预览：点【开始清理】之前不会动任何文件" if candidates else "",
        meta=f"{len(candidates)} 组 · {human_bytes(total)}" if candidates else "",
    )


def render_confirmation_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """确认页：再拦一次（这是"删除"前的最后一道门）。"""
    count = int(payload.get("selected_count", 0) or 0)
    size = human_bytes(int(payload.get("selected_bytes", 0) or 0))
    actions = _actions(
        _button("返回修改", "back"),
        _button("确认清理", "confirm", primary=True),
    ) if interactive else ""
    return state_page(
        {
            "message": f"将移入废纸篓：{count} 组，共 {size}",
            "detail": "点【确认清理】立即执行；文件仍可从废纸篓恢复。",
        },
        stage="confirming",
        title="确认清理",
        body="确认清理",
        actions=actions,
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
    """应用列表（只列 `/Applications` 与用户应用目录里的 `.app`）。"""
    apps = [item for item in (payload.get("apps") or []) if isinstance(item, dict)]
    # 每个应用一行，**卸载按钮就放在行尾**：之前把按钮单独堆成一块（只前 6 个、还会换行），
    # 用户看到的是"一排按钮 + 一堆 0 B"（2026-10-19 看真机快照发现）。
    rows = []
    for app in apps:
        size = int(app.get("allocated_bytes") or 0)
        # 体积未知时**整段不渲染**：50 行都挂一个 "—" 是纯噪声（列表页默认不算体积）。
        size_text = f'<span class="meta value">{human_bytes(size)}</span>' if size else ""
        button = (
            _button(
                "卸载",
                "uninstall-plan",
                payload={"bundle_id": app.get("bundle_id", ""), "path": app.get("path", "")},
            )
            if interactive
            else ""
        )
        rows.append(
            '<div class="row"><div style="min-width:0">'
            f'<strong>{html.escape(str(app.get("name", "")))}</strong>'
            f'<div class="meta">{html.escape(str(app.get("bundle_id", "")))}</div>'
            f'</div><div style="display:flex;align-items:center;gap:10px;flex:none">'
            f"{size_text}{button}</div></div>"
        )
    actions = ""
    return state_page(
        {
            "message": "点右侧【卸载】查看它留下的文件，确认后才移入废纸篓",
            "detail": "系统级残留需要一次管理员授权；体积在点开应用后计算。",
        },
        stage="uninstall-list",
        title="软件卸载（彻底）",
        body="选择一个应用",
        actions="".join(rows),
        current="uninstall",
        subtitle="先看残留清单，确认后才移入废纸篓（可恢复）",
        meta=f"{len(apps)} 个应用" if apps else "",
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
    return state_page(
        {
            "message": f"将移入废纸篓 {len(items)} 项，共 {human_bytes(int(plan.get('user_total_bytes', 0) or 0))}（可恢复）",
            "detail": "确认后会再核对每个位置；名称匹配项默认不勾，请自行判断。",
        },
        stage="uninstall-preview",
        title=f"卸载 {app.get('name', '')}".strip(),
        body="确认要清理的内容",
        actions=actions + "".join(parts),
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


def render_updates_list_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    rows: list[str] = []
    for index, item in enumerate(items):
        transition = f"{item.get('installed') or '?'} → {item.get('available') or '?'}"
        rows.append(
            '<label class="row opt"><input type="checkbox" data-update-id="'
            + str(index)
            + '" checked><div><strong>'
            + html.escape(str(item.get("name", "")))
            + '</strong><div class="meta">'
            + html.escape(f"{item.get('manager')}/{item.get('kind')} · {transition}")
            + '</div></div></label>'
        )
    notes = "".join(f'<p class="muted">{html.escape(str(note))}</p>' for note in (payload.get("notes") or []))
    actions = _actions(_button("重新检查", "updates-refresh"), _button("更新所选", "updates-apply", primary=True)) if interactive else ""
    return state_page(
        {
            "message": f"可升级 {len(items)} 项（只处理第三方：Homebrew / App Store）",
            "detail": "macOS 系统更新不在此列——它有自己的机制。升级不可逆，确认后逐组执行并记录输出。",
        },
        stage="updates",
        title="软件更新",
        body="可升级的第三方软件",
        actions=actions + "".join(rows) + notes,
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


__all__ = [
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
