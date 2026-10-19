"""清理目标目录的契约（2026-10-19）。

目前只有一条：Homebrew 的两个目标必须**合并成一个**。

背景：`homebrew-cache`（直接删 `~/Library/Caches/Homebrew`）与 `brew-cleanup`
（跑 `brew cleanup`）指向同一处，同时勾选会做两遍；用户决定只保留 `brew-cleanup`
（交给 Homebrew 自己的清理逻辑）。这条用例防止它被"顺手加回来"。

用**临时 home** 做发现，不碰真实目录：发现过程只在 home 下找路径，空目录足够。
"""
from __future__ import annotations

import tempfile
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


if __name__ == "__main__":
    unittest.main()
