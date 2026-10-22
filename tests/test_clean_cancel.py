"""清理的取消（M3 补齐，2026-10-22）。

清理是最长的操作，之前**没有**取消按钮（只有残留/大文件有）——不一致。
现在 `clean` 也接协作式取消：每处理一个 target 前检查一次标志。

真机验证（本机，第一个检查点即取消，不动任何文件）：
    候选 8 → cancelled=True，remaining=6（另 2 项本来就不是 ready/planned）
"""

from __future__ import annotations

import unittest

from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps


def _final(messages: list[dict]) -> dict:
    return messages[-1]


class CleanCancelPlumbingTests(unittest.TestCase):
    def test_should_stop_is_forwarded_and_cancelled_surfaced(self) -> None:
        seen: dict[str, object] = {}

        def clean_approved(approved, selected, **kwargs):
            seen["should_stop"] = kwargs.get("should_stop")
            # 内核在取消时会把 cancelled/remaining 带回来
            return {
                "mode": "clean",
                "plan_items": [
                    {"target_id": "a", "name": "A", "paths": ["/x/a"], "status": "cleaned",
                     "actual_bytes": 10, "recoverable": True},
                    {"target_id": "b", "name": "B", "paths": ["/x/b"], "status": "planned"},
                ],
                "actual_reclaimed_bytes": 0,
                "cancelled": True,
                "remaining": ["b"],
            }

        service = CoreService(SessionDeps(
            audit=lambda: {"plan_items": []}, plan=lambda: {}, clean=lambda: {},
            clean_approved=clean_approved,
        ))
        data = dict(_final(service.dispatch(
            {"id": "1", "cmd": "clean", "args": {"approved_ids": ["a", "b"]}}
        )))["data"]

        self.assertTrue(callable(seen["should_stop"]), "内核要把取消标志传进清理")
        self.assertTrue(data["cancelled"])
        self.assertEqual(data["remaining"], ["b"])
        self.assertEqual(data["moved_count"], 1, "只算真正移走的")
        self.assertEqual(data["completion"]["recoverable_bytes"], 10)

    def test_result_envelope_reports_cancelled(self) -> None:
        """结果页也要能显示"已取消（部分完成）"。"""
        service = CoreService(SessionDeps(
            audit=lambda: {}, plan=lambda: {}, clean=lambda: {},
            clean_approved=lambda approved, selected, **kwargs: {
                "mode": "clean",
                "plan_items": [{"target_id": "a", "paths": ["/x"], "status": "cleaned",
                                "actual_bytes": 5, "recoverable": True}],
                "cancelled": True,
            },
        ))
        result = dict(_final(service.dispatch(
            {"id": "1", "cmd": "clean", "args": {"approved_ids": ["a"]}}
        )))["data"]["result"]
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["count"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
