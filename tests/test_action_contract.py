"""页面上的每个动作，桥都必须认得（2026-10-19）。

为什么单独立一条：这已经是第二次栽在同一类问题上——

1. 【打开废纸篓】的 `open-trash` 在白名单里，但**会话不处理**，点了没反应；
2. 【卸载 Demo】的 `uninstall-plan` **根本不在白名单**，点了 HTTP 400。

两次都是"页面上有按钮、后端不认"，而单元测试各自只测自己那半边。
这条用例把两边对齐：把每个页面渲染出来，抽出全部 `data-bridge-action` /
`data-nav-action`，逐个断言存在于 `bridge.ACTIONS`。
"""
from __future__ import annotations

import re
import unittest

from maccleaner.bridge import ACTIONS
from maccleaner.ui import pages

ACTION_PATTERN = re.compile(r'data-(?:bridge|nav)-action="([^"]+)"')


def _all_pages() -> dict[str, str]:
    plan = {
        "app": {"name": "Demo", "bundle_id": "com.demo.app"},
        "items": [
            {"id": "aaa", "path": "/Applications/Demo.app", "kind": "app-bundle", "confidence": "exact",
             "allocated_bytes": 10},
            {"id": "bbb", "path": "~/Library/Caches/com.demo.app", "kind": "caches", "confidence": "exact",
             "allocated_bytes": 20},
            {"id": "ccc", "path": "~/Library/Logs/Demo", "kind": "log-name", "confidence": "name-match",
             "allocated_bytes": 30},
        ],
        "user_total_bytes": 60,
        "system_items": [],
    }
    return {
        "landing": pages.render_landing_html({}),
        "progress": pages.render_progress_html(),
        "review": pages.render_review_html({"candidates": [
            {"path": "~/Library/Caches/Demo", "kind": "cache", "allocated_bytes": 4096, "target_id": "home-caches"},
        ]}),
        "review-empty": pages.render_review_html({"candidates": []}),
        "confirmation": pages.render_confirmation_html({"selected_count": 1, "selected_bytes": 4096}),
        "completion": pages.render_completion_html({"recoverable_bytes": 4096, "actual_freed_bytes": 0}),
        "cancelled": pages.render_cancelled_html({}),
        "recovery": pages.render_recovery_html({"detail": "boom"}),
        "skills": pages.render_skills_html({"skills": []}),
        "uninstall-list": pages.render_uninstall_list_html({"apps": [
            {"name": "Demo", "bundle_id": "com.demo.app", "path": "/Applications/Demo.app"},
        ]}),
        "uninstall-preview": pages.render_uninstall_preview_html(plan),
        "uninstall-preview-notice": pages.render_uninstall_preview_html(plan, notice="至少选一项"),
        "uninstall-complete": pages.render_uninstall_complete_html(
            {"moved_count": 1, "remaining": {"system_count": 0}}
        ),
        "updates": pages.render_updates_list_html({"items": [
            {"name": "aom", "manager": "brew", "kind": "formula", "installed": "1", "available": "2"},
        ], "notes": []}),
        "updates-result": pages.render_updates_result_html({"status": "applied", "ok_count": 1, "total": 1,
                                                            "groups": []}),
    }


class ActionContractTests(unittest.TestCase):
    def test_every_rendered_action_is_whitelisted(self) -> None:
        missing: dict[str, list[str]] = {}
        for name, page in _all_pages().items():
            for action in ACTION_PATTERN.findall(page):
                if action not in ACTIONS:
                    missing.setdefault(action, []).append(name)
        self.assertEqual(missing, {}, f"这些动作页面上有、桥不认（点了会 400）：{missing}")

    def test_each_page_uses_at_least_one_action_or_is_pure_text(self) -> None:
        """防止正则失效导致上一条永远通过（空集合断言不出来）。"""
        total = sum(len(ACTION_PATTERN.findall(page)) for page in _all_pages().values())
        self.assertGreater(total, 15, "抽到的动作太少，正则或页面结构可能变了")


if __name__ == "__main__":
    unittest.main()
