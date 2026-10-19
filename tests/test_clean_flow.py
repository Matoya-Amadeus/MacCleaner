"""清理全链路的真机语义（2026-10-19）。

为什么单独有这条：此前"清理"只验证到**页面推进**（review → confirming → complete），
而真机上文件**一个都没动**——因为 `deps.clean()` 用的是默认上下文（`dry_run=True, apply=False`），
内核只回了一份计划，界面却发布了"清理完成"。这条用例直接检查**文件系统**，不看页面。

同时钉住"可恢复"的语义：走废纸篓时 `actual_reclaimed_bytes` 必须是 0（空间还没释放），
但完成页的"可恢复"必须是真实移走的字节数——否则又回到"可恢复 0 B，用户以为没清掉"。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from maccleaner.deps import build_deps
from maccleaner.ui.adapter import completion_payload


def _make_home(tmp: Path) -> tuple[Path, Path]:
    home = tmp / "home"
    demo = home / "Library" / "Caches" / "Demo"
    demo.mkdir(parents=True)
    (demo / "big.cache").write_bytes(b"z" * 8192)
    os.utime(demo / "big.cache", (1, 1))
    os.utime(demo, (1, 1))
    return home, demo


class CleanFlowTests(unittest.TestCase):
    def test_clean_actually_moves_files_to_trash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="clean-flow-") as tmp:
            root = Path(tmp)
            home, demo = _make_home(root)
            deps = build_deps(home=home, root=home, state_root=root / "state")

            report = deps.audit()
            approved = [
                str(item.get("target_id"))
                for item in report.get("plan_items") or []
                if int(item.get("estimated_bytes") or 0) > 0
            ]
            self.assertTrue(approved, "扫描应给出至少一个候选")

            cleaned = deps.clean_approved(approved) if deps.clean_approved else deps.clean()

            self.assertFalse(demo.exists(), "确认之后文件必须真的被移走")
            trash = home / ".Trash"
            self.assertTrue(trash.is_dir() and any(trash.iterdir()), "移走的东西必须进废纸篓")

            payload = completion_payload(cleaned)
            self.assertEqual(payload["actual_freed_bytes"], 0, "走废纸篓时空间还没释放")
            self.assertGreater(payload["recoverable_bytes"], 0, "可恢复字节必须是真实移走的量")

    def test_clean_without_approval_refuses(self) -> None:
        """空批准 ≠ 全部批准：没给 id 时不能清任何东西。"""
        with tempfile.TemporaryDirectory(prefix="clean-refuse-") as tmp:
            root = Path(tmp)
            home, demo = _make_home(root)
            deps = build_deps(home=home, root=home, state_root=root / "state")

            report = deps.clean_approved([]) if deps.clean_approved else deps.clean()
            self.assertTrue(demo.exists(), "没有批准清单时一个字节都不能动")
            self.assertTrue(
                any("refused" in str(note) for note in report.get("notes") or []),
                "要明确说明是被拒绝，而不是静默成功",
            )


if __name__ == "__main__":
    unittest.main()
