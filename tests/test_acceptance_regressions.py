"""端到端验收（2026-10-23）抓到的两个真 bug 的回归测试。

这两个都没被单测抓到，因为单测的**假 deps 签名比真 deps 宽松**：

1. `uninstall.apply` 把 `app_path` / `item_ids` 传给 `deps.uninstall_apply`，
   而它要的是 `plan` / `ids` —— 结果命令永远 internal_error，界面上等于**卸载不可用**；
2. 完成页把"处理掉的字节"当"已释放"，走废纸篓也报出 100 KB 已释放。

所以这里的断言刻意贴近**真 deps 的签名**（严格关键字），而不是 `**kwargs` 一把收。
"""

from __future__ import annotations

import unittest

from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps
from maccleaner.view_models import completion_view


def _final(messages: list[dict]) -> dict:
    return messages[-1]


PLAN = {
    "app": {"name": "Demo", "path": "/Applications/Demo.app", "bundle_id": "com.demo.app"},
    "items": [
        {"id": "a", "path": "/Users/x/Library/Caches/com.demo.app", "kind": "caches",
         "allocated_bytes": 100, "confidence": "exact", "requires_admin": False},
    ],
    "user_total_bytes": 100,
}


class UninstallApplySignatureTests(unittest.TestCase):
    def test_apply_receives_a_plan_not_a_path(self) -> None:
        seen: dict[str, object] = {}

        def uninstall_apply(*, plan, ids, should_stop=None):   # 与真 deps 同签名
            seen["plan"] = plan
            seen["ids"] = ids
            return {"status": "applied", "moved": [{"path": "/x"}], "failed": [],
                    "moved_count": 1, "count": 1}

        service = CoreService(SessionDeps(
            audit=lambda: {}, plan=lambda: {}, clean=lambda: {},
            uninstall_plan=lambda **kwargs: PLAN,
            uninstall_apply=uninstall_apply,
        ))
        data = dict(_final(service.dispatch(
            {"id": "1", "cmd": "uninstall.apply",
             "args": {"path": "/Applications/Demo.app", "item_ids": ["a"]}}
        )))["data"]

        self.assertEqual(seen["plan"], PLAN, "要把冻结的 plan 传下去")
        self.assertEqual(seen["ids"], ["a"])
        self.assertEqual(data["moved_count"], 1)
        self.assertEqual(data["result"]["count"], 1)

    def test_empty_item_ids_still_rejected(self) -> None:
        service = CoreService(SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {},
                                          uninstall_plan=lambda **kwargs: PLAN))
        final = _final(service.dispatch(
            {"id": "1", "cmd": "uninstall.apply", "args": {"path": "/Applications/Demo.app", "item_ids": []}}
        ))
        self.assertEqual(final["error"]["code"], "bad_args")


class CompletionFreedTests(unittest.TestCase):
    def _report(self, reclaimed: int, recoverable_items: list[dict]) -> dict:
        return {"mode": "clean", "actual_reclaimed_bytes": reclaimed, "plan_items": recoverable_items}

    def test_trash_bytes_are_not_counted_as_freed(self) -> None:
        report = self._report(100_000, [
            {"target_id": "installers", "paths": ["/x/a.dmg"], "status": "cleaned",
             "actual_bytes": 100_000, "recoverable": True},
        ])
        view = completion_view(report)
        self.assertEqual(view["recoverable_bytes"], 100_000)
        self.assertEqual(view["actual_freed_bytes"], 0, "移进废纸篓的东西还占着磁盘")

    def test_permanent_delete_still_counts(self) -> None:
        report = self._report(50_000, [
            {"target_id": "docker-prune", "paths": ["docker"], "status": "cleaned",
             "actual_bytes": 50_000, "recoverable": False},
        ])
        view = completion_view(report)
        self.assertEqual(view["recoverable_bytes"], 0)
        self.assertEqual(view["actual_freed_bytes"], 50_000)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
