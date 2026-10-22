"""取消契约（M3，2026-10-22）。

设计取舍：**协作式取消**，不是杀进程。
- 命令在后台线程执行，`cancel` 只置一个标志；
- 执行循环在**每一项开始前**检查标志，退出时如实返回 `cancelled` + `moved` + `remaining`；
- 已经移走的不会回滚（回滚要把文件搬回来，风险更大），界面据 `remaining` 说"还剩几项"。

杀进程的问题：用户不知道到底删了哪些，也无法解释结果。
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from maccleaner.core_service import CoreService, serve_stdio
from maccleaner.deps import orphans_clean, trash_paths
from maccleaner.session import SessionDeps


class _StopAfter:
    """前 n 次返回 False（继续），之后一直 True（停）。"""

    def __init__(self, n: int) -> None:
        self.remaining = n

    def __call__(self) -> bool:
        if self.remaining > 0:
            self.remaining -= 1
            return False
        return True


class PathLoopCancelTests(unittest.TestCase):
    def test_trash_paths_stops_between_items(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cancel-trash-") as tmp:
            home = Path(tmp)
            files = []
            for index in range(3):
                path = home / f"f{index}.bin"
                path.write_text("x", encoding="utf-8")
                files.append(str(path))

            result = trash_paths(home, files, should_stop=_StopAfter(1))

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(result["moved"]), 1, "只处理了第一项")
        self.assertEqual(result["remaining"], files[1:], "剩下的要如实报告，不能装作没发生")

    def test_trash_paths_without_cancel_processes_all(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cancel-none-") as tmp:
            home = Path(tmp)
            files = []
            for index in range(2):
                path = home / f"f{index}.bin"
                path.write_text("x", encoding="utf-8")
                files.append(str(path))
            result = trash_paths(home, files)
        self.assertEqual(len(result["moved"]), 2)
        self.assertNotIn("cancelled", result)

    def test_orphans_clean_stops_between_items(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cancel-orphans-") as tmp:
            home = Path(tmp)
            caches = home / "Library" / "Caches"
            caches.mkdir(parents=True)
            paths = []
            for index in range(4):
                folder = caches / f"com.demo{index}"
                folder.mkdir()
                paths.append(str(folder))

            result = orphans_clean(home, paths, should_stop=_StopAfter(2))

        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(result["moved"]), 2)


class CancelFlagTests(unittest.TestCase):
    def _service(self) -> CoreService:
        return CoreService(SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {}))

    def test_flag_roundtrip(self) -> None:
        service = self._service()
        self.assertFalse(service.should_stop())
        service.request_cancel()
        self.assertTrue(service.should_stop())
        service.clear_cancel()
        self.assertFalse(service.should_stop())

    def test_cancel_line_is_answered_not_queued(self) -> None:
        """`cancel` 不进任务队列：否则它要等前一个命令跑完才被读到，等于没有。"""
        stdin = io.StringIO('{"id":"c1","cmd":"cancel"}\n')
        stdout = io.StringIO()
        serve_stdio(
            SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {}),
            stdin=stdin,
            stdout=stdout,
        )
        payloads = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["id"], "c1")
        self.assertTrue(payloads[0]["data"]["cancelled"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
