"""完成页契约：`clean` 的返回值必须带完成页口径。

旧界面那张"释放了多少 / 可恢复多少 / 跳过几项"的收尾屏，口径在这里：
- 走废纸篓 → `actual_freed_bytes = 0`（空间要清空废纸篓才释放）；
- 可恢复 = 真正移走的字节；
- "目标为空"和"用户没勾"**不算跳过**（否则完成页会说"跳过 19 项"，像失败了）。
"""

from __future__ import annotations

import unittest

from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps


def _report(items):
    return {"mode": "clean", "plan_items": items, "actual_reclaimed_bytes": 0,
            "receipt": {"json": "/tmp/receipt.json"}}


ITEMS = [
    {"target_id": "a", "name": "A", "paths": ["/x/a"], "status": "cleaned",
     "actual_bytes": 1000, "estimated_bytes": 1000, "recoverable": True},
    {"target_id": "b", "name": "B", "paths": ["/x/b"], "status": "skipped",
     "reason": "target path missing"},
    {"target_id": "c", "name": "C", "paths": ["/x/c"], "status": "blocked",
     "reason": "outside approved cleanup plan"},
    {"target_id": "d", "name": "D", "paths": ["/x/d"], "status": "skipped",
     "reason": "permission denied"},
]


def _service(**overrides) -> CoreService:
    base = dict(
        audit=lambda: {"plan_items": []},
        plan=lambda: {},
        clean=lambda: _report(ITEMS),
        clean_approved=lambda approved, selected: _report(ITEMS),
    )
    base.update(overrides)
    return CoreService(SessionDeps(**base))


class CleanCompletionTests(unittest.TestCase):
    def test_clean_returns_completion_payload(self) -> None:
        data = dict(_final(_service().dispatch(
            {"id": "1", "cmd": "clean", "args": {"approved_ids": ["a"], "selected_ids": ["a"]}}
        )))["data"]
        completion = data["completion"]
        self.assertEqual(completion["recoverable_bytes"], 1000)
        self.assertEqual(completion["actual_freed_bytes"], 0, "走废纸篓时空间还没释放")
        self.assertEqual(data["moved_count"], 1)

    def test_only_real_skips_are_counted(self) -> None:
        """`target path missing` / `outside approved plan` 不算跳过。"""
        data = dict(_final(_service().dispatch(
            {"id": "1", "cmd": "clean", "args": {"approved_ids": ["a"], "selected_ids": ["a"]}}
        )))["data"]
        skipped = data["completion"]["skipped_items"]
        self.assertEqual([item["reason"] for item in skipped], ["permission denied"])

    def test_receipt_path_surfaces(self) -> None:
        data = dict(_final(_service().dispatch(
            {"id": "1", "cmd": "clean", "args": {"approved_ids": ["a"], "selected_ids": ["a"]}}
        )))["data"]
        self.assertEqual(data["completion"]["receipt_path"], "/tmp/receipt.json")


class TrashOpenTests(unittest.TestCase):
    def test_opens_trash(self) -> None:
        called: list[bool] = []
        service = _service(open_trash=lambda: called.append(True))
        final = _final(service.dispatch({"id": "1", "cmd": "trash.open"}))
        self.assertTrue(final["ok"])
        self.assertEqual(called, [True])

    def test_reports_missing_capability(self) -> None:
        # 默认 deps 里 open_trash 是 None
        final = _final(_service(open_trash=None).dispatch({"id": "1", "cmd": "trash.open"}))
        self.assertEqual(final["error"]["code"], "bad_args")
        self.assertIn("不支持", final["error"]["message"])


def _final(messages: list[dict]) -> dict:
    return messages[-1]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
