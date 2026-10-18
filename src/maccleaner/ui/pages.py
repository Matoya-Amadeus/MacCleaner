"""页面渲染（2026-10-18 迁入）。

**只吃 dict**：页面不碰文件系统、不碰 core，因此可以用示例数据单测。
真数据由会话层/服务层提供（下一步）。
"""
from __future__ import annotations

import html
from typing import Any

from .shell import state_page


def _human_bytes(value: int) -> str:
    number = float(max(0, int(value or 0)))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if number < 1024 or unit == "TiB":
            return f"{int(number)} B" if unit == "B" else f"{number:.2f} {unit}"
        number /= 1024
    return f"{number:.2f} TiB"


def render_landing_html(payload: dict[str, Any], *, interactive: bool = True) -> str:
    """落地页：**打开不扫**，点【开始扫描】才扫。

    为什么要有这一页：扫描是**动作**而不是窗口的副作用。此前"打开即扫"会在用户还没看屏幕时
    就读磁盘，而且"扫描耗时"里混进了他发呆的时间。
    """
    history = payload.get("history") or {}
    total = int(history.get("total_freed_bytes") or 0)
    runs = int(history.get("total_runs") or 0)
    if total or runs:
        summary = f"上次共清理 {runs} 次，可恢复 {_human_bytes(total)}（清空废纸篓后才真正释放）"
    else:
        summary = "还没有清理记录"

    actions = ""
    if interactive:
        actions = (
            '<div class="actions" style="justify-content:center">'
            '<button class="button round primary" type="button" id="start-scan" '
            'data-bridge-action="start">开始扫描</button></div>'
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


__all__ = ["render_landing_html"]
