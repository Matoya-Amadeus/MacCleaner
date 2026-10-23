"""取消时必须交 `remaining`（2026-10-23 验收抓到）。

现象：沙盒里 300 个残留目录，取消后内核回 `moved=26, remaining=0`，
但磁盘上还剩 274 个——界面会因此显示"还剩 0 项未处理"，等于谎报。

`trash_paths` 一直有 remaining，`orphans_clean` 漏了；这条测试同时钉住两者。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maccleaner.deps import orphans_clean, trash_paths


class CancelRemainingTests(unittest.TestCase):
    def test_orphans_clean_reports_remaining(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            paths = []
            for index in range(6):
                folder = home / f"Library/Caches/com.demo{index}"
                folder.mkdir(parents=True)
                paths.append(str(folder))

            calls = {"n": 0}

            def stop() -> bool:
                calls["n"] += 1
                return calls["n"] > 2          # 做完 2 个之后停

            result = orphans_clean(home, paths, should_stop=stop)

            self.assertTrue(result["cancelled"])
            self.assertEqual(len(result["moved"]), 2)
            self.assertEqual(len(result["remaining"]), 4)
            # 账要对得上：移走的 + 剩下的 = 总数
            self.assertEqual(len(result["moved"]) + len(result["remaining"]), len(paths))
            left_on_disk = len(list((home / "Library/Caches").glob("com.demo*")))
            self.assertEqual(left_on_disk, len(result["remaining"]))

    def test_trash_paths_reports_remaining(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            files = []
            for index in range(5):
                path = home / f"big{index}.bin"
                path.write_bytes(b"x" * 1024)
                files.append(str(path))

            calls = {"n": 0}

            def stop() -> bool:
                calls["n"] += 1
                return calls["n"] > 1

            result = trash_paths(home, files, should_stop=stop)
            self.assertTrue(result["cancelled"])
            self.assertEqual(len(result["remaining"]), 4)
            self.assertEqual(len(result["moved"]) + len(result["remaining"]), len(files))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
