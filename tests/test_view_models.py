"""视图模型（分组规则）契约测试。

这些规则以前长在 `ui/pages.py`（HTML 层）。搬进内核的原因：SwiftUI 版如果自己再写一份，
两份规则早晚分叉——"哪些类别算开发工具""更新按来源怎么分组""残留按哪个目录分桶"必须只有一处。

所以下面每条断言，都是**界面能正确分组的前提**。
"""

from __future__ import annotations

import unittest

from maccleaner.view_models import (
    APP_CATEGORY_ORDER,
    apps_view,
    large_view,
    orphan_bucket,
    orphans_view,
    review_group_for,
    review_view,
    update_group_label,
    updates_view,
)


def _report(*items):
    return {"mode": "audit", "plan_items": list(items)}


def _item(target_id, category, estimated, **extra):
    return {
        "target_id": target_id,
        "name": target_id,
        "paths": [f"/tmp/{target_id}"],
        "category": category,
        "estimated_bytes": estimated,
        **extra,
    }


class ReviewGroupTests(unittest.TestCase):
    def test_categories_map_to_expected_groups(self) -> None:
        cases = {
            "browser": "browser",
            "cache": "app",
            "logs": "app",
            "xcode": "dev",
            "package-cache": "dev",
            "docker": "containers",
            "user-files": "user",
            "没见过的类别": "app",  # 兜底：不能凭空消失
        }
        for category, expected in cases.items():
            self.assertEqual(review_group_for({"kind": category}), expected, category)

    def test_trash_target_wins_over_category(self) -> None:
        self.assertEqual(review_group_for({"target_id": "trash", "kind": "cache"}), "trash")

    def test_zero_byte_candidates_are_dropped(self) -> None:
        view = review_view(_report(_item("empty", "cache", 0), _item("real", "cache", 10)))
        self.assertEqual([c["target_id"] for c in view["candidates"]], ["real"])

    def test_groups_are_ordered_and_carry_totals(self) -> None:
        view = review_view(_report(
            _item("dev1", "xcode", 300),
            _item("dev2", "homebrew", 100),
            _item("br", "browser", 50),
        ))
        self.assertEqual([group["key"] for group in view["groups"]], ["browser", "dev"])
        dev = next(group for group in view["groups"] if group["key"] == "dev")
        self.assertEqual(dev["count"], 2)
        self.assertEqual(dev["bytes"], 400)
        self.assertEqual([item["target_id"] for item in dev["items"]], ["dev1", "dev2"], "组内保持内核顺序")


class AppsViewTests(unittest.TestCase):
    def test_groups_follow_macos_category_order(self) -> None:
        apps = [
            {"name": "A", "category": "其它"},
            {"name": "B", "category": "开发工具"},
            {"name": "C", "category": "浏览器"},
        ]
        view = apps_view(apps)
        self.assertEqual([group["label"] for group in view["groups"]], ["浏览器", "开发工具", "其它"])
        self.assertEqual(view["count"], 3)
        self.assertEqual(APP_CATEGORY_ORDER[0], "浏览器", "浏览器排第一（最常清理）")

    def test_missing_category_falls_back_to_other(self) -> None:
        view = apps_view([{"name": "A"}])
        self.assertEqual(view["groups"][0]["label"], "其它")


class UpdatesViewTests(unittest.TestCase):
    def test_source_labels_and_order(self) -> None:
        self.assertEqual(update_group_label({"manager": "brew", "kind": "cask"}), "Homebrew cask")
        self.assertEqual(update_group_label({"manager": "quirky", "kind": "thing"}), "quirky/thing")
        view = updates_view({"items": [
            {"name": "npm1", "manager": "npm", "kind": "npm-global"},
            {"name": "brew1", "manager": "brew", "kind": "formula"},
        ]})
        self.assertEqual([group["label"] for group in view["groups"]], ["Homebrew formula", "npm 全局包"])

    def test_sparkle_split_only_keeps_confirmed_updates(self) -> None:
        view = updates_view({
            "items": [],
            "sparkle": [
                {"name": "Has", "update_available": True, "latest": "2"},
                {"name": "UpToDate", "update_available": False, "status": "ok"},
                {"name": "Unknown", "update_available": False, "status": "unknown"},
            ],
        })
        self.assertEqual([item["name"] for item in view["sparkle_updates"]], ["Has"])
        self.assertEqual([item["name"] for item in view["sparkle_rest"]], ["UpToDate", "Unknown"])


class OrphansViewTests(unittest.TestCase):
    def test_bucket_uses_library_subdir(self) -> None:
        self.assertEqual(orphan_bucket("/Users/x/Library/Caches/com.a"), "Caches")
        self.assertEqual(orphan_bucket("/Users/x/Library/Saved Application State/com.a"), "Saved State")
        self.assertEqual(orphan_bucket("/opt/homebrew/lib/thing"), "其它")

    def test_groups_sorted_by_count_desc(self) -> None:
        view = orphans_view({"items": [
            {"path": "/Users/x/Library/Logs/a", "bytes": 1},
            {"path": "/Users/x/Library/Caches/b", "bytes": 2},
            {"path": "/Users/x/Library/Caches/c", "bytes": 3},
        ]})
        self.assertEqual([group["label"] for group in view["groups"]], ["Caches", "Logs"])
        caches = view["groups"][0]
        self.assertEqual(caches["bytes"], 5)
        self.assertEqual(view["total_bytes"], 6)


class LargeViewTests(unittest.TestCase):
    def test_items_sorted_by_size_desc(self) -> None:
        view = large_view({"items": [
            {"name": "small", "bytes": 1},
            {"name": "big", "bytes": 100},
        ], "roots": ["~/Downloads"], "min_bytes": 500})
        self.assertEqual([item["name"] for item in view["items"]], ["big", "small"])
        self.assertEqual(view["total_bytes"], 101)
        self.assertEqual(view["min_bytes"], 500)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
