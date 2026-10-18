"""本地界面（2026-10-18 迁入）。

定位：MacCleaner 的**人面入口**。与 CLI / MCP 并列，三者共用 `uninstall` / `updates` / core 的同一套语义。

当前状态：外壳 + 落地页已就位；审阅/确认/完成/卸载/更新页随后按同样方式迁入。
会话与 loopback 桥（浏览器交互）需要先有 core 适配层，故排在页面之后。
"""
from __future__ import annotations

from .pages import render_landing_html

__all__ = ["render_landing_html"]
