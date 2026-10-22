"""`files.trash` 契约（大文件页用）。

单独一个文件而不是塞回 test_protocol.py：那条命令是 M2 才加的，
放这儿能一眼看出"后来补的"，也避免再动一个已经很长的手写文件。
"""

from __future__ import annotations

import unittest

from maccleaner.core_service import CoreService
from maccleaner.session import SessionDeps


def _service(**overrides) -> CoreService:
    base = dict(
        audit=lambda: {"plan_items": []},
        plan=lambda: {},
        clean=lambda: {},
    )
    base.update(overrides)
    return CoreService(SessionDeps(**base))


def _final(messages: list[dict]) -> dict:
    assert messages, "没有消息"
    return messages[-1]


class FilesTrashTests(unittest.TestCase):
    def test_empty_paths_is_rejected(self) -> None:
        """空数组必须拒绝：否则一次误调用可能"移走全部大文件"。"""
        final = _final(_service().dispatch({"id": "1", "cmd": "files.trash", "args": {"paths": []}}))
        self.assertFalse(final["ok"])
        self.assertEqual(final["error"]["code"], "bad_args")
        self.assertIn("paths", final["error"]["message"])

    def test_moves_given_paths_and_emits_started(self) -> None:
        calls: list[list[str]] = []

        def trash(paths, **_kwargs):
            calls.append(list(paths))
            return {"moved": list(paths), "failed": []}

        service = _service(trash_paths=trash)
        messages = service.dispatch(
            {"id": "1", "cmd": "files.trash", "args": {"paths": ["/Users/x/Downloads/big.bin"]}}
        )
        self.assertEqual(messages[0]["event"], "started")
        self.assertEqual(messages[0]["op"], "files.trash")
        self.assertEqual(calls, [["/Users/x/Downloads/big.bin"]])
        self.assertEqual(len(_final(messages)["data"]["moved"]), 1)

    def test_missing_capability_is_reported(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "files.trash", "args": {"paths": ["/x"]}}))
        self.assertEqual(final["error"]["code"], "bad_args")
        self.assertIn("不支持", final["error"]["message"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
