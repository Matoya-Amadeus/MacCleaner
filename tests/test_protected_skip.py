"""没给「完全磁盘访问权限」时，整块跳过受保护目录（2026-10-23）。

背景：macOS 会对 `~/Downloads`、`~/Desktop`、`~/Documents` **各弹一次**授权框，
用户点得很累。做法是"没授权就根本不去碰它们"，由界面用一条全局提示说明
"授权一次即可全部读到"。

踩过的坑：报告里的路径是 `~/Downloads` 波浪线形式，直接跟绝对路径比永远匹配不上。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps

HOME = str(Path.home())


def _report(*paths_per_item: list[str]) -> dict:
    return {
        "mode": "audit",
        "plan_items": [
            {"target_id": f"t{index}", "name": f"T{index}", "paths": paths,
             "estimated_bytes": 100, "category": "cache", "risk": "low", "recoverable": True}
            for index, paths in enumerate(paths_per_item)
        ],
    }


def _service(report: dict) -> CoreService:
    return CoreService(
        SessionDeps(audit=lambda: report, plan=lambda: {}, clean=lambda: {}),
        home=HOME,
    )


class DropProtectedTests(unittest.TestCase):
    def test_drops_items_inside_protected_folders(self) -> None:
        service = _service(_report(["~/Downloads"], ["~/Library/Caches"]))
        out = service.drop_protected(_report(["~/Downloads"], ["~/Library/Caches"]))
        self.assertEqual([item["target_id"] for item in out["plan_items"]], ["t1"])
        self.assertEqual(out["skipped_protected"], 1)
        self.assertTrue(any("protected" in note for note in out["notes"]))

    def test_keeps_items_outside(self) -> None:
        report = _report(["~/Library/Caches/Firefox"], ["~/Library/Containers/com.docker"])
        out = _service(report).drop_protected(report)
        self.assertEqual(len(out["plan_items"]), 2)
        self.assertNotIn("skipped_protected", out)

    def test_partial_paths_are_kept(self) -> None:
        """一个条目里只要有一条路径不在受保护目录，就保留——宁可多扫，不要漏删。"""
        report = _report(["~/Downloads", "~/Library/Caches"])
        out = _service(report).drop_protected(report)
        self.assertEqual(len(out["plan_items"]), 1)


class ReviewPayloadArgsTests(unittest.TestCase):
    def test_skip_protected_reported(self) -> None:
        report = _report(["~/Desktop"], ["~/Library/Caches"])
        service = _service(report)
        messages = service.dispatch({"id": "1", "cmd": "review.payload",
                                     "args": {"skip_protected": True}})
        data = messages[-1]["data"]   # dispatch 返回"事件 + 终态"的消息列表
        self.assertEqual(data["skipped_protected"], 1)
        kinds = [group["key"] for group in data["groups"]]
        self.assertNotIn("user", kinds)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
