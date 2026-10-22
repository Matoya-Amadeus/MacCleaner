"""`files.reveal` 契约（右键菜单「在 Finder 中显示」用）。

这条命令会让**另一个程序**（Finder）接管，所以只接受存在的路径，
不能让界面拿它当"随便传个字符串试试"的通道。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps


def _service(**overrides) -> CoreService:
    base = dict(audit=lambda: {"plan_items": []}, plan=lambda: {}, clean=lambda: {})
    base.update(overrides)
    return CoreService(SessionDeps(**base))


def _final(messages: list[dict]) -> dict:
    return messages[-1]


class RevealTests(unittest.TestCase):
    def test_rejects_missing_path_argument(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "files.reveal", "args": {}}))
        self.assertEqual(final["error"]["code"], "bad_args")

    def test_rejects_nonexistent_path(self) -> None:
        final = _final(_service().dispatch(
            {"id": "1", "cmd": "files.reveal", "args": {"path": "/definitely/not/here"}}
        ))
        self.assertEqual(final["error"]["code"], "bad_args")
        self.assertIn("不存在", final["error"]["message"])

    def test_reveals_existing_path(self) -> None:
        revealed: list[str] = []
        with tempfile.TemporaryDirectory(prefix="reveal-") as tmp:
            target = Path(tmp) / "Demo.app"
            target.mkdir()
            service = _service(reveal=lambda path: revealed.append(path))
            data = _final(service.dispatch(
                {"id": "1", "cmd": "files.reveal", "args": {"path": str(target)}}
            ))["data"]
        self.assertEqual(revealed, [str(target)])
        self.assertEqual(data["revealed"], str(target))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
