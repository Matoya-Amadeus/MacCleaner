"""适配层（2026-10-18）：用**真实内核报告**验证映射，而不是手写假 dict。

假 dict 只能证明"我按我以为的字段名写了代码"；真报告才能证明"内核给的就是这些字段"。
所以审阅侧的用例直接跑一次 `StorageManager.audit()`。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from maccleaner.core import StorageContext, StorageManager
from maccleaner.ui.adapter import completion_payload, review_payload, updates_payload


class ReviewPayloadTests(unittest.TestCase):
    def test_maps_a_real_audit_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="adapter-") as tmp:
            root = Path(tmp) / "home"
            cache = root / "Library" / "Caches" / "Demo" / "big.cache"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"z" * 4096)
            os.utime(cache, (1, 1))

            report = StorageManager(StorageContext(home=root, root=root)).audit().to_dict()
            payload = review_payload(report)

            self.assertTrue(payload["candidates"], "真实报告里应有候选")
            self.assertTrue(
                all(item["allocated_bytes"] > 0 for item in payload["candidates"]),
                "0 字节条目不该进审阅页",
            )
            self.assertGreater(payload["total_bytes"], 0)
            first = payload["candidates"][0]
            self.assertTrue(first["path"], "候选必须带路径（人要看清单）")
            self.assertIn("recoverable", first)


class CompletionPayloadTests(unittest.TestCase):
    def test_recoverable_and_actual_are_separated(self) -> None:
        report = {
            "mode": "clean",
            "actual_reclaimed_bytes": 0,
            "plan_items": [
                {"paths": ["~/a"], "status": "cleaned", "recoverable": True, "actual_bytes": 4096, "estimated_bytes": 4096},
                {"paths": ["~/b"], "status": "cleaned", "recoverable": False, "actual_bytes": 1024, "estimated_bytes": 1024},
            ],
            "receipt": {"json": "/tmp/receipt.json"},
            "before_free_bytes": 100,
            "after_free_bytes": 200,
        }
        payload = completion_payload(report)
        self.assertEqual(payload["recoverable_bytes"], 4096, "只把 recoverable 项算进可恢复")
        self.assertEqual(payload["actual_freed_bytes"], 0, "走废纸篓时内核的 actual 就是 0")
        self.assertEqual(payload["receipt_path"], "/tmp/receipt.json")
        self.assertEqual(payload["failed_count"], 0)

    def test_skipped_and_failed_are_counted(self) -> None:
        report = {
            "plan_items": [
                {"paths": ["~/a"], "status": "failed", "reason": "locked"},
                {"paths": ["~/b"], "status": "skipped", "reason": "changed since approval"},
            ]
        }
        payload = completion_payload(report)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)
        self.assertEqual(payload["skipped_items"][0]["reason"], "changed since approval")

    def test_receipt_as_plain_string_is_supported(self) -> None:
        payload = completion_payload({"receipt": "/tmp/r.json", "plan_items": []})
        self.assertEqual(payload["receipt_path"], "/tmp/r.json")

    def test_non_problem_skips_are_not_counted(self) -> None:
        """"路径不存在"和"用户没批准"都不是问题，不该显示成跳过。"""
        report = {
            "plan_items": [
                {"paths": ["~/a"], "status": "cleaned", "recoverable": True, "actual_bytes": 10},
                {"paths": ["~/b"], "status": "skipped", "reason": "target path missing"},
                {"paths": ["~/c"], "status": "blocked", "reason": "outside approved cleanup plan"},
                {"paths": ["~/d"], "status": "skipped", "reason": "changed since approval"},
            ]
        }
        payload = completion_payload(report)
        self.assertEqual(payload["skipped_count"], 1, "只有真正的原因才算跳过")
        self.assertEqual(payload["skipped_items"][0]["reason"], "changed since approval")


class UpdatesPayloadTests(unittest.TestCase):
    def test_defaults_are_filled(self) -> None:
        payload = updates_payload({"items": [{"name": "aom"}]})
        self.assertEqual(payload["count"], 0, "count 缺失时补 0，不猜")
        self.assertEqual(payload["notes"], [])
        self.assertEqual(len(payload["items"]), 1)


if __name__ == "__main__":
    unittest.main()
