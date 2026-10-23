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


class ExecuteGuardTests(unittest.TestCase):
    """**执行阶段**的闸门：界面过滤挡不住执行，内核自己要拦。

    用户反馈（2026-10-23）：清单里已经没有 Downloads/Desktop，点【清理】却仍连续弹系统授权框——
    因为 `clean` 按 id 重新规划，执行时又碰到了那些目录。
    """

    def test_target_under_protected_folder_is_skipped(self) -> None:
        from maccleaner.core import StorageContext, StorageManager
        from maccleaner.policy import CleanupTarget, PlanItem, TargetScan

        home = Path.home()
        ctx = StorageContext(home=home, root=home, state_root=home / ".state", apply=True)
        manager = StorageManager(ctx)
        manager.skip_protected_paths = (str(home / "Desktop"), str(home / "Downloads"),
                                        str(home / "Documents"))

        target = CleanupTarget(target_id="desktop-test", name="桌面", category="user",
                               kind="trash_tree", paths=(home / "Desktop",))
        item = PlanItem(target_id="desktop-test", name="桌面", category="user", kind="trash_tree",
                        risk="high", status="ready", reason="", estimated_bytes=100,
                        paths=(str(home / "Desktop"),))
        scan = TargetScan(target=target, exists=True, total_bytes=100, eligible_bytes=100,
                          total_files=1, eligible_files=1, newest_mtime=None, oldest_mtime=None)

        manager.execute([scan], [item])

        self.assertEqual(item.status, "skipped")
        self.assertIn("protected", item.reason)

    def test_clean_receives_skip_protected_flag(self) -> None:
        """界面点清理时要显式告诉内核"别碰受保护目录"。"""
        seen: dict[str, object] = {}

        def clean_approved(approved, selected, **kwargs):
            seen.update(kwargs)
            return {"mode": "clean", "plan_items": [], "actual_reclaimed_bytes": 0}

        service = CoreService(
            SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {},
                        clean_approved=clean_approved),
            home=HOME,
        )
        service.dispatch({"id": "1", "cmd": "clean",
                          "args": {"approved_ids": ["a"], "skip_protected": True}})
        self.assertTrue(seen.get("skip_protected"), "内核要收到 skip_protected")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
