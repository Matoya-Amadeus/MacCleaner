"""执行类命令的契约：更新的 id 语义、打开应用、残留按路径。

这三条都是"界面把参数传回内核"的边界，出错的表现都是**静默做错事**（升错包 / 打开错东西 /
删错目录），所以单独钉住。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maccleaner.core_service import CoreService
from maccleaner.deps import _update_key, select_updates
from maccleaner.session import SessionDeps
from maccleaner.view_models import updates_view


def _service(**overrides) -> CoreService:
    base = dict(audit=lambda: {"plan_items": []}, plan=lambda: {}, clean=lambda: {})
    base.update(overrides)
    return CoreService(SessionDeps(**base))


def _final(messages: list[dict]) -> dict:
    return messages[-1]


class UpdateSelectionTests(unittest.TestCase):
    ITEMS = [
        {"manager": "brew", "kind": "formula", "name": "aom"},
        {"manager": "npm", "kind": "npm-global", "name": "pnpm"},
    ]

    def test_stable_key_format(self) -> None:
        self.assertEqual(_update_key(self.ITEMS[0]), "brew|formula|aom")

    def test_select_by_stable_key(self) -> None:
        """原生界面按分组渲染后回传的是稳定键——不能按索引理解。"""
        picked = select_updates(self.ITEMS, ["npm|npm-global|pnpm"])
        self.assertEqual([item["name"] for item in picked], ["pnpm"])

    def test_select_by_index_still_works_for_old_ui(self) -> None:
        picked = select_updates(self.ITEMS, ["0"])
        self.assertEqual([item["name"] for item in picked], ["aom"])

    def test_unknown_ids_select_nothing(self) -> None:
        self.assertEqual(select_updates(self.ITEMS, ["brew|formula|不存在"]), [])

    def test_view_items_carry_stable_id(self) -> None:
        view = updates_view({"items": self.ITEMS})
        ids = [item["id"] for group in view["groups"] for item in group["items"]]
        self.assertEqual(sorted(ids), ["brew|formula|aom", "npm|npm-global|pnpm"])


class AppOpenTests(unittest.TestCase):
    def test_rejects_non_app_paths(self) -> None:
        """这条命令会把控制权交给别的程序：只接受存在的 .app。"""
        final = _final(_service().dispatch({"id": "1", "cmd": "app.open", "args": {"path": "/etc/passwd"}}))
        self.assertEqual(final["error"]["code"], "bad_args")

    def test_rejects_missing_path_argument(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "app.open", "args": {}}))
        self.assertEqual(final["error"]["code"], "bad_args")

    def test_opens_existing_app(self) -> None:
        opened: list[str] = []
        with tempfile.TemporaryDirectory(prefix="app-open-") as tmp:
            app = Path(tmp) / "Demo.app"
            app.mkdir()
            service = _service(open_app=lambda path: opened.append(path))
            data = _final(service.dispatch({"id": "1", "cmd": "app.open", "args": {"path": str(app)}}))["data"]
        self.assertEqual(opened, [str(app)])
        self.assertEqual(len(data["opened"]), len(str(app)))


class OrphansApplyTests(unittest.TestCase):
    def test_passes_paths_not_ids(self) -> None:
        """内核那层是 `orphans_clean(home, paths)`：参数名必须叫 paths。"""
        seen: list[list[str]] = []

        def apply(paths):
            seen.append(list(paths))
            return {"moved": list(paths), "failed": []}

        service = _service(orphans_apply=apply)
        messages = service.dispatch(
            {"id": "1", "cmd": "orphans.apply", "args": {"paths": ["/Users/x/Library/Caches/com.gone"]}}
        )
        self.assertEqual(messages[0]["event"], "started")
        self.assertEqual(seen, [["/Users/x/Library/Caches/com.gone"]])
        self.assertTrue(_final(messages)["ok"])

    def test_empty_paths_rejected(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "orphans.apply", "args": {"paths": []}}))
        self.assertEqual(final["error"]["code"], "bad_args")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
