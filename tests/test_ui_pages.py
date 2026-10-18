"""本地界面（2026-10-18 迁入）：外壳契约与落地页。

界面测试只断言**可核对的契约**（stage、动作、插槽、无硬编码色值、无假入口），
不断言像素或具体文案措辞——否则改个措辞就红，久而久之没人再看它。
"""
from __future__ import annotations

import unittest

from maccleaner.ui.pages import render_landing_html
from maccleaner.ui.shell import ACTIONS_SLOT, NAV_SLOT, NAV_GROUPS, render_nav, state_page


class LandingPageTests(unittest.TestCase):
    def test_landing_is_idle_and_offers_one_big_button(self) -> None:
        page = render_landing_html({"history": {"total_runs": 2, "total_freed_bytes": 2048}})
        self.assertIn('data-stage="idle"', page)
        self.assertIn('data-bridge-action="start"', page, "唯一主按钮要发 start 动作")
        self.assertIn('class="button round primary"', page, "圆形主按钮")
        self.assertIn("不会改动或删除", page, "必须说清扫描只读")

    def test_landing_shows_history_summary(self) -> None:
        page = render_landing_html({"history": {"total_runs": 3, "total_freed_bytes": 1024 * 1024}})
        self.assertIn("上次共清理 3 次", page)
        self.assertIn("清空废纸篓后才真正释放", page, "回收量口径必须与清理侧一致")

    def test_landing_without_history_says_so(self) -> None:
        page = render_landing_html({})
        self.assertIn("还没有清理记录", page)

    def test_static_preview_has_no_action_button(self) -> None:
        page = render_landing_html({}, interactive=False)
        self.assertNotIn("data-bridge-action", page)


class ShellTests(unittest.TestCase):
    def test_nav_lists_only_real_entries(self) -> None:
        nav = render_nav("clean")
        self.assertEqual(nav.count('data-nav-action="'), 4, "四个真实入口")
        self.assertNotIn("待实现", nav, "四项都已实现，不该再有待实现徽标")
        self.assertNotIn("Protection", nav, "不出现我们没有的分类")
        self.assertIn('class="side-item is-current"', nav, "当前项要有选中态")
        self.assertIn('aria-current="page"', nav)

    def test_nav_groups_are_explicit(self) -> None:
        titles = [group.title for group in NAV_GROUPS]
        self.assertEqual(titles, ["清理", "应用", "技能"])

    def test_state_page_replaces_both_slots(self) -> None:
        page = state_page(
            {"message": "m", "detail": "d"},
            stage="review",
            title="审阅",
            body="清单",
            actions='<button id="x">X</button>',
            current="uninstall",
        )
        self.assertNotIn(NAV_SLOT, page, "导航插槽必须被替换")
        self.assertNotIn(ACTIONS_SLOT, page, "动作插槽必须被替换")
        self.assertIn('data-stage="review"', page)
        self.assertIn('id="x"', page)

    def test_no_hardcoded_colors_outside_the_style_block(self) -> None:
        """色值只允许出现在 `<style>`（也就是 theme.py 的单一来源）里。

        上一版界面曾在某个 *页面* 的样式覆盖里硬编码深紫色，导致"调品牌色时那一页不跟着变"。
        所以规则是：**样式块之外**不许出现色值，页面里一律 `var(--…)`。
        """
        page = render_landing_html({"history": {}})
        body = page.split("</style>", 1)[-1]
        for literal in ("#181530", "#2a2350", "#0e8a62", "#ffffff"):
            self.assertNotIn(literal, body, f"样式块之外不许出现硬编码色值 {literal}")
        self.assertIn('class="button round primary"', body, "页面主体结构仍在")


if __name__ == "__main__":
    unittest.main()
