"""清理目标目录的契约（2026-10-19）。

目前只有一条：Homebrew 的两个目标必须**合并成一个**。

背景：`homebrew-cache`（直接删 `~/Library/Caches/Homebrew`）与 `brew-cleanup`
（跑 `brew cleanup`）指向同一处，同时勾选会做两遍；用户决定只保留 `brew-cleanup`
（交给 Homebrew 自己的清理逻辑）。这条用例防止它被"顺手加回来"。

用**临时 home** 做发现，不碰真实目录：发现过程只在 home 下找路径，空目录足够。
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from maccleaner.core import StorageContext, StorageManager
from maccleaner.policy import discover_targets


class TargetCatalogTests(unittest.TestCase):
    def test_homebrew_targets_are_merged_into_one(self) -> None:
        with tempfile.TemporaryDirectory(prefix="targets-") as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            manager = StorageManager(StorageContext(home=home, root=home))
            ids = [target.target_id for target in discover_targets(manager) if "brew" in target.target_id]
        self.assertEqual(ids, ["brew-cleanup"], "Homebrew 只允许留一条（brew cleanup）")

    def test_no_target_id_is_duplicated(self) -> None:
        """同一 target_id 出现两次会让页面出现两个一模一样的行。"""
        with tempfile.TemporaryDirectory(prefix="targets-dup-") as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            manager = StorageManager(StorageContext(home=home, root=home))
            ids = [target.target_id for target in discover_targets(manager)]
        self.assertEqual(len(ids), len(set(ids)), f"重复的 target_id：{ids}")

    def _age(self, path: Path, days: int) -> None:
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))

    def test_installers_target_only_matches_installer_files(self) -> None:
        """`~/Downloads` 里只清 .dmg/.pkg/.iso，且必须超过 30 天；文档一律不动。"""
        with tempfile.TemporaryDirectory(prefix="targets-installers-") as tmp:
            home = Path(tmp)
            downloads = home / "Downloads"
            downloads.mkdir(parents=True)
            for name, days in (("old.dmg", 60), ("setup.pkg", 60), ("new.dmg", 1), ("note.txt", 60)):
                path = downloads / name
                path.write_bytes(b"z" * 1024)
                self._age(path, days)

            manager = StorageManager(StorageContext(home=home, root=home, state_root=None))
            targets = {target.target_id: target for target in discover_targets(manager)}
            self.assertIn("installers", targets, "安装包目标必须存在")
            scan = manager.scan_targets([targets["installers"]])[0]
            self.assertEqual(scan.eligible_bytes, 2048, "只该算 old.dmg + setup.pkg")
            self.assertEqual(scan.eligible_files, 2)

            ctx = StorageContext(
                home=home, root=home, apply=True, dry_run=False,
                approved_targets=frozenset({"installers"}), confirm_targets=frozenset({"installers"}),
                require_explicit_plan=False, enforce_approved_scope=True,
                prefer_trash=True, state_root=None,
            )
            StorageManager(ctx).clean()
            self.assertEqual(sorted(path.name for path in downloads.iterdir()), ["new.dmg", "note.txt"])

    def test_ios_backups_target_moves_whole_backup_dirs_only(self) -> None:
        """iOS 备份以"每个子目录一份"为单位整块搬走；最近还在写的那份不动。"""
        with tempfile.TemporaryDirectory(prefix="targets-ios-") as tmp:
            home = Path(tmp)
            backup = home / "Library" / "Application Support" / "MobileSync" / "Backup"
            old_dir = backup / "00008110-old"
            new_dir = backup / "00008110-new"
            old_dir.mkdir(parents=True)
            new_dir.mkdir()
            (old_dir / "Manifest.db").write_bytes(b"z" * 2048)
            (new_dir / "Manifest.db").write_bytes(b"z" * 512)
            self._age(old_dir, 60)
            self._age(new_dir, 0)

            manager = StorageManager(StorageContext(home=home, root=home, state_root=None))
            targets = {target.target_id: target for target in discover_targets(manager)}
            self.assertIn("ios-backups", targets)
            scan = manager.scan_targets([targets["ios-backups"]])[0]
            self.assertEqual(scan.eligible_bytes, 2048, "只算旧备份")

            ctx = StorageContext(
                home=home, root=home, apply=True, dry_run=False,
                approved_targets=frozenset({"ios-backups"}), confirm_targets=frozenset({"ios-backups"}),
                require_explicit_plan=False, enforce_approved_scope=True,
                prefer_trash=True, state_root=None,
            )
            StorageManager(ctx).clean()
            self.assertFalse(old_dir.exists(), "旧备份应整块移走")
            self.assertTrue(new_dir.exists(), "新备份不能动")


if __name__ == "__main__":
    unittest.main()
