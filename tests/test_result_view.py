"""结果页口径：四种执行结果收敛成同一张表的字段。

三种内核返回形状不同：`moved/count/bytes`、`results[].ok`、`plan_items[].status`。
界面不该逐个适配——这里钉住归一化后的语义。
"""

from __future__ import annotations

import unittest

from maccleaner.view_models import result_view


class OrphansResultTests(unittest.TestCase):
    def test_counts_and_failures(self) -> None:
        view = result_view("orphans", {
            "moved": [{"path": "/x/a", "bytes": 10}, {"path": "/x/b", "bytes": 5}],
            "failed": [{"path": "/x/c", "reason": "permission denied"}],
            "count": 2,
            "bytes": 15,
        })
        self.assertEqual(view["title"], "残留清理完成")
        self.assertEqual(view["count"], 2)
        self.assertEqual(view["bytes"], 15)
        self.assertEqual(view["failed_count"], 1)
        self.assertEqual(view["failures"][0]["reason"], "permission denied")

    def test_cancelled_is_flagged(self) -> None:
        view = result_view("orphans", {"moved": [{"path": "/x/a"}], "cancelled": True, "count": 1})
        self.assertTrue(view["cancelled"])


class UpdatesResultTests(unittest.TestCase):
    def test_counts_only_successful_commands(self) -> None:
        view = result_view("updates", {
            "status": "partial",
            "results": [
                {"command": "brew upgrade a", "ok": True},
                {"command": "brew upgrade b", "ok": True},
                {"command": "brew upgrade c", "ok": False, "stdout_tail": "Error: cask conflict"},
            ],
        })
        self.assertEqual(view["count"], 2, "只有成功的算完成")
        self.assertEqual(view["failed_count"], 1)
        self.assertIn("cask conflict", view["failures"][0]["reason"])


class UninstallResultTests(unittest.TestCase):
    def test_moved_count_falls_back_to_len(self) -> None:
        view = result_view("uninstall", {"status": "applied", "moved": [{"path": "/a"}, {"path": "/b"}]})
        self.assertEqual(view["title"], "卸载完成")
        self.assertEqual(view["count"], 2, "没有 count 就用 moved 的长度")


class FailureCapTests(unittest.TestCase):
    def test_failures_are_capped_at_20(self) -> None:
        failed = [{"path": f"/x/{i}", "reason": "boom"} for i in range(50)]
        view = result_view("orphans", {"moved": [], "failed": failed, "count": 0})
        self.assertEqual(view["failed_count"], 50, "总数要如实给")
        self.assertEqual(len(view["failures"]), 20, "明细最多 20 条（界面只显示前 5）")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
