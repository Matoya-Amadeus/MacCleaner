"""更新 / 卸载的取消（2026-10-22 补齐）。

两者都是"一条命令 / 一个文件"为单位：**在两项之间**停，不在半途打断——
半途 kill 一条 `brew upgrade` 会留下损坏的包状态，比不停更糟。
"""

from __future__ import annotations

import unittest

from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps
from maccleaner.updates import apply_updates, build_upgrade_plan


def _final(messages: list[dict]) -> dict:
    return messages[-1]


# 注意：同 (manager, kind) 的包会被合并成**一条命令**（brew upgrade a b c），
# 所以"组与组之间取消"要用不同 kind 才能造出两组。
ITEMS = [
    {"name": "a", "manager": "brew", "kind": "formula", "installed": "1", "available": "2"},
    {"name": "b", "manager": "brew", "kind": "cask", "installed": "1", "available": "2"},
]


class StopAfter:
    def __init__(self, n: int) -> None:
        self.remaining = n

    def __call__(self) -> bool:
        if self.remaining > 0:
            self.remaining -= 1
            return False
        return True


class UpdatesCancelTests(unittest.TestCase):
    def test_cancel_between_commands(self) -> None:
        ran: list[str] = []

        def runner(argv, **_kwargs):
            ran.append(" ".join(argv))

            class Result:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return Result()

        plan = build_upgrade_plan(ITEMS, brew="/fake/brew", mas="/fake/mas")
        result = apply_updates(plan, runner=runner, should_stop=StopAfter(1))

        self.assertTrue(result.get("cancelled"))
        self.assertEqual(len(ran), 1, "只跑了一条命令")
        self.assertEqual(len(result["remaining"]), 1, "另一组没跑")
        self.assertEqual(result["ok_count"], 1)

    def test_without_cancel_runs_all(self) -> None:
        def runner(argv, **_kwargs):
            class Result:
                returncode = 0
                stdout = "ok"
                stderr = ""

            return Result()

        plan = build_upgrade_plan(ITEMS, brew="/fake/brew", mas="/fake/mas")
        result = apply_updates(plan, runner=runner)
        self.assertNotIn("cancelled", result)
        self.assertEqual(result["total"], len(ITEMS))


class ForwardingTests(unittest.TestCase):
    def test_uninstall_apply_receives_should_stop(self) -> None:
        seen: dict[str, object] = {}

        def uninstall_apply(**kwargs):
            seen.update(kwargs)
            return {"status": "cancelled", "moved": [], "failed": [], "cancelled": True,
                    "remaining": ["/x/b"]}

        # 现在 `uninstall.apply` 会先取 plan（见 2026-10-23 的入参修复），假实现要一起给。
        service = CoreService(SessionDeps(
            audit=lambda: {}, plan=lambda: {}, clean=lambda: {},
            uninstall_plan=lambda **kwargs: {"items": [{"id": "a", "path": "/x", "kind": "caches",
                                                        "allocated_bytes": 1, "confidence": "exact"}],
                                             "user_total_bytes": 1},
            uninstall_apply=uninstall_apply,
        ))
        data = dict(_final(service.dispatch(
            {"id": "1", "cmd": "uninstall.apply",
             "args": {"path": "/Applications/Demo.app", "item_ids": ["a"]}}
        )))["data"]
        self.assertTrue(callable(seen.get("should_stop")))
        self.assertTrue(data["result"]["cancelled"])

    def test_updates_apply_receives_should_stop(self) -> None:
        seen: dict[str, object] = {}

        def updates_apply(**kwargs):
            seen.update(kwargs)
            return {"status": "cancelled", "results": [{"command": "brew upgrade a", "ok": True}],
                    "cancelled": True, "remaining": ["brew upgrade b"]}

        service = CoreService(SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {},
                                          updates_apply=updates_apply))
        data = dict(_final(service.dispatch(
            {"id": "1", "cmd": "updates.apply", "args": {"ids": ["brew|formula|a"]}}
        )))["data"]
        self.assertTrue(callable(seen.get("should_stop")))
        self.assertTrue(data["result"]["cancelled"])
        self.assertEqual(data["result"]["count"], 1, "只算成功的")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
