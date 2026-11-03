"""TCC 拒绝时只跳过该目标，不炸掉整批清理（2026-11-03）。

现场：用户点清理，界面弹
`PermissionError: [Errno 1] Operation not permitted: '~/Library/Caches/com.apple.Safari'`，
整批任务变成 `internal_error`，前面已经移走的也不出现在报告里。

原因有两层：
1. `~/Library/Caches/com.apple.Safari` 属于 Apple 应用数据，受 TCC 保护，没有
   「完全磁盘访问权限」时 rename / readdir 返回 **EPERM**（不是 EACCES）；
2. 内核在 `_cleanup_tree` 里裸调 `move_to_trash`，任何一个目录拒绝就把异常抛到
   `core_service.dispatch`，在那里统一变成 `internal_error`。

修法：单目标失败降级为 `skipped` + 可执行的原因（去开全盘访问），其余目标照常执行。
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maccleaner.core import StorageContext, StorageManager, _denied_reason
from maccleaner.policy import CleanupTarget, PlanItem, TargetScan


def _scan(target: CleanupTarget) -> TargetScan:
    return TargetScan(
        target=target,
        exists=True,
        total_bytes=100,
        eligible_bytes=100,
        total_files=1,
        eligible_files=1,
        newest_mtime=None,
        oldest_mtime=None,
    )


def _item(target: CleanupTarget) -> PlanItem:
    return PlanItem(
        target_id=target.target_id,
        name=target.name,
        category=target.category,
        kind=target.kind,
        risk=target.risk,
        status="ready",
        reason="",
        estimated_bytes=100,
        paths=tuple(str(path) for path in target.paths),
    )


class DeniedReasonTests(unittest.TestCase):
    def test_eperm_points_at_full_disk_access(self) -> None:
        exc = PermissionError(errno.EPERM, "Operation not permitted")
        self.assertIn("full disk access", _denied_reason(exc))

    def test_other_oserror_keeps_its_message(self) -> None:
        exc = OSError(errno.ENOSPC, "No space left on device")
        self.assertIn("No space left", _denied_reason(exc))


class DeniedRootIsSkippedTests(unittest.TestCase):
    def test_move_eperm_does_not_abort_the_batch(self) -> None:
        """一半目标被 TCC 拒、另一半正常：正常的必须照清，报告里标出被跳过的。"""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            denied = home / "Library" / "Caches" / "com.apple.Safari"
            ok = home / "Library" / "Caches" / "Firefox"
            for path in (denied, ok):
                path.mkdir(parents=True)
                (path / "blob.bin").write_bytes(b"x" * 32)

            ctx = StorageContext(home=home, root=home, apply=True, dry_run=False, prefer_trash=True)
            manager = StorageManager(ctx)

            real_move = shutil.move

            def fake_move(src, dst, *args, **kwargs):
                if str(src).startswith(str(denied)):
                    raise PermissionError(errno.EPERM, "Operation not permitted", str(src))
                return real_move(src, dst, *args, **kwargs)

            target = CleanupTarget(
                target_id="browser-caches",
                name="浏览器缓存",
                category="browser",
                kind="purge_tree",
                paths=(denied, ok),
                risk="low",
                metadata={"move_whole_paths": True},
            )
            item = _item(target)

            with mock.patch("maccleaner.core.move_to_trash", side_effect=_trash_with(fake_move, home)):
                manager.execute([_scan(target)], [item])

            self.assertFalse(ok.exists(), "能动的目录必须被清掉")
            self.assertTrue(denied.exists(), "被拒的目录不许伪造成功")
            self.assertEqual(item.status, "cleaned", "整批不该因为一个目录而失败")
            self.assertIn("skipped", item.reason)
            self.assertIn("full disk access", item.reason)
            self.assertIn("com.apple.Safari", item.reason)

    def test_unreadable_root_is_never_touched(self) -> None:
        """读都读不动的目录：连 rename 都不尝试，直接标 skipped。"""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            blocked = home / "Library" / "Caches" / "com.apple.Safari"
            blocked.mkdir(parents=True)
            (blocked / "blob.bin").write_bytes(b"x" * 8)

            ctx = StorageContext(home=home, root=home, apply=True, dry_run=False, prefer_trash=True)
            manager = StorageManager(ctx)
            target = CleanupTarget(
                target_id="browser-caches",
                name="浏览器缓存",
                category="browser",
                kind="purge_tree",
                paths=(blocked,),
                risk="low",
                metadata={"move_whole_paths": True},
            )
            item = _item(target)
            denied = PermissionError(errno.EPERM, "Operation not permitted", str(blocked))

            with mock.patch("maccleaner.core._access_blocker", return_value=_denied_reason(denied)):
                manager.execute([_scan(target)], [item])

            self.assertTrue(blocked.exists())
            self.assertEqual(item.status, "skipped")
            self.assertIn("full disk access", item.reason)


class MixedResultTests(unittest.TestCase):
    def test_partial_success_reports_cleaned_with_skip_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            denied = home / "Library" / "Caches" / "com.apple.Safari"
            ok = home / "Library" / "Caches" / "Chrome"
            for path in (denied, ok):
                path.mkdir(parents=True)
                (path / "blob.bin").write_bytes(b"x" * 8)

            ctx = StorageContext(home=home, root=home, apply=True, dry_run=False, prefer_trash=True)
            manager = StorageManager(ctx)
            target = CleanupTarget(
                target_id="browser-caches",
                name="浏览器缓存",
                category="browser",
                kind="purge_tree",
                paths=(denied, ok),
                risk="low",
                min_age_days=0,   # 刚建的测试文件不该被"7 天保留期"挡掉
            )
            item = _item(target)
            denied_exc = PermissionError(errno.EPERM, "Operation not permitted", str(denied))

            # 逐文件分支：Firefox/Chrome 走这里；模拟 Chrome 里有个文件被拒。
            def fake_move_file(src, home_arg):
                if str(src).startswith(str(denied)):
                    raise denied_exc
                destination = home_arg / ".Trash" / Path(src).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(destination))
                return destination

            with mock.patch("maccleaner.core.move_to_trash", side_effect=fake_move_file), \
                 mock.patch("maccleaner.core._access_blocker", return_value=None):
                manager.execute([_scan(target)], [item])

            self.assertFalse((ok / "blob.bin").exists(), "可清理的文件必须真的被移走")
            self.assertTrue((denied / "blob.bin").exists(), "被拒的文件不许伪造成功")
            self.assertEqual(item.status, "cleaned")
            self.assertIn("skipped", item.reason)


class EmptyTrashTests(unittest.TestCase):
    def test_trash_target_deletes_instead_of_moving_into_itself(self) -> None:
        """「清空废纸篓」必须真删：以前是把 ~/.Trash 的每个文件 move 到 ~/.Trash 里。"""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            trash = home / ".Trash"
            trash.mkdir()
            old = trash / "old.dmg"
            old.write_bytes(b"x" * 16)
            os.utime(old, (0, 0))   # 早于保留期

            ctx = StorageContext(home=home, root=home, apply=True, dry_run=False, prefer_trash=True)
            manager = StorageManager(ctx)
            target = CleanupTarget(
                target_id="trash",
                name="Trash",
                category="user-files",
                kind="trash_tree",
                paths=(trash,),
                risk="medium",
                requires_confirmation=True,
            )
            item = _item(target)
            manager.execute([_scan(target)], [item])

            self.assertTrue(trash.is_dir(), "废纸篓目录本身要留着")
            self.assertEqual(list(trash.iterdir()), [], "废纸篓内容要被真正删掉")
            self.assertEqual(item.status, "cleaned")


class ReviewFlagTests(unittest.TestCase):
    """审阅页要**提前**标出"这项需要授权"，而不是等清理跑完才报错。"""

    def test_flags_only_the_unreadable_targets(self) -> None:
        from maccleaner.view_models import review_candidates

        report = {
            "plan_items": [
                {"target_id": "browser-caches", "name": "浏览器缓存", "category": "browser",
                 "paths": ["/private/var/root"], "estimated_bytes": 100,
                 "risk": "low", "recoverable": True},
                {"target_id": "home-caches", "name": "用户缓存", "category": "cache",
                 "paths": [tempfile.gettempdir()], "estimated_bytes": 100,
                 "risk": "low", "recoverable": True},
            ]
        }
        items = {item["target_id"]: item for item in review_candidates(report)}
        self.assertTrue(items["browser-caches"]["needs_full_disk_access"])
        self.assertFalse(items["home-caches"]["needs_full_disk_access"])


def _trash_with(mover, home: Path):
    def _move(source, _home):
        destination = home / ".Trash" / Path(source).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        return mover(str(source), str(destination))
    return _move


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
