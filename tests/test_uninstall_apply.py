"""卸载执行（2026-10-18 迁入）：勾选子集、受保护路径、废纸篓、系统级代跑。

这一组用例守的是**不可逆动作**的边界，所以每条都断言"不该动的没动"，而不只是"该动的动了"。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maccleaner.uninstall import (
    apply_plan,
    apply_system_leftovers,
    build_admin_command,
    build_plan,
    item_id,
)


def _touch(path: Path, payload: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _plan(root: Path) -> tuple[dict, Path, Path, Path]:
    app = root / "Applications" / "Example.app"
    (app / "Contents").mkdir(parents=True)
    _touch(app / "Contents" / "Info.plist", b"<plist/>")
    cache = _touch(root / "home" / "Library" / "Caches" / "com.example.app", b"c")
    logs = _touch(root / "home" / "Library" / "Logs" / "Example App", b"l")
    plan = build_plan(
        {"path": str(app), "bundle_id": "com.example.app", "name": "Example App", "home": str(root / "home")},
        home=root / "home",
        library_root=root / "Library",
        receipts_root=root / "receipts",
    )
    return plan, app, cache, logs


class ApplyPlanTests(unittest.TestCase):
    def test_only_selected_items_move_and_everything_goes_to_trash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-") as tmp:
            root = Path(tmp)
            plan, app, cache, logs = _plan(root)
            chosen = next(item for item in plan["items"] if item["path"] == str(cache))

            result = apply_plan(plan, home=root / "home", selected_ids=[chosen["id"]])
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["moved_count"], 1)
            self.assertFalse(cache.exists(), "勾选的残留应被移走")
            self.assertTrue(logs.exists(), "未勾选的残留必须原样保留")
            self.assertTrue(app.exists(), "未勾选的应用本体必须保留")
            trash_path = Path(result["moved"][0]["trash_path"])
            self.assertTrue(trash_path.exists(), "移动目标必须在废纸篓里（可恢复）")
            self.assertIn(".Trash", str(trash_path))

    def test_empty_selection_refuses_and_moves_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-empty-") as tmp:
            root = Path(tmp)
            plan, app, cache, logs = _plan(root)
            result = apply_plan(plan, home=root / "home", selected_ids=[])
            self.assertEqual(result["status"], "refused")
            for path in (app, cache, logs):
                self.assertTrue(path.exists(), "拒绝时不得移动任何东西")

    def test_forged_ids_cannot_reach_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-forged-") as tmp:
            root = Path(tmp)
            plan, _app, cache, _logs = _plan(root)
            result = apply_plan(plan, home=root / "home", selected_ids=["deadbeefcafe", str(cache)])
            self.assertEqual(result["status"], "refused", "传路径字符串也换不到任何计划项")
            self.assertTrue(cache.exists())

    def test_protected_paths_are_skipped_with_a_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-protected-") as tmp:
            root = Path(tmp)
            secret = _touch(root / "home" / ".ssh" / "id_rsa", b"KEY")
            plan = {
                "app": {"home": str(root / "home")},
                "items": [
                    {"id": item_id(str(secret)), "path": str(secret), "kind": "ssh", "confidence": "exact",
                     "requires_admin": False},
                ],
            }
            result = apply_plan(plan, home=root / "home")
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["moved_count"], 0)
            self.assertTrue(secret.exists(), "受保护路径绝不能被移动")
            self.assertIn("protected", result["skipped"][0]["reason"])

    def test_dry_run_moves_nothing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-dry-") as tmp:
            root = Path(tmp)
            plan, _app, cache, _logs = _plan(root)
            result = apply_plan(plan, home=root / "home", dry_run=True)
            self.assertEqual(result["status"], "dry-run")
            self.assertTrue(result["would_move"])
            self.assertTrue(cache.exists(), "dry-run 不得移动文件")

    def test_system_items_are_never_moved_by_apply_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-sys-") as tmp:
            root = Path(tmp)
            system_file = _touch(root / "Library" / "LaunchAgents" / "com.example.app.helper.plist", b"{}")
            plan = {
                "app": {"home": str(root / "home")},
                "items": [
                    {"id": item_id(str(system_file)), "path": str(system_file), "kind": "launch-agent-system",
                     "confidence": "exact", "requires_admin": True},
                ],
            }
            result = apply_plan(plan, home=root / "home")
            self.assertEqual(result["status"], "refused", "没有可动的用户域项时拒绝")
            self.assertTrue(system_file.exists(), "系统级项必须留给代跑路径")

    def test_trash_collision_gets_unique_names(self) -> None:
        from maccleaner.uninstall import _move_to_trash

        with tempfile.TemporaryDirectory(prefix="apply-collide-") as tmp:
            root = Path(tmp)
            trash = root / ".Trash"
            first = _touch(root / "a" / "same.txt", b"1")
            second = _touch(root / "b" / "same.txt", b"2")
            one = _move_to_trash(first, trash)
            two = _move_to_trash(second, trash)
            self.assertNotEqual(one, two, "同名文件不能互相覆盖")
            self.assertEqual(one.read_bytes(), b"1")
            self.assertEqual(two.read_bytes(), b"2")


class SystemApplyTests(unittest.TestCase):
    def test_command_asks_for_admin_and_quotes_spaces(self) -> None:
        command = build_admin_command(["/Library/Application Support/Example App"])
        self.assertEqual(command[0], "/usr/bin/osascript")
        self.assertIn("with administrator privileges", command[-1])
        self.assertIn("'/Library/Application Support/Example App'", command[-1])

    def test_guards_refuse_dangerous_paths(self) -> None:
        for paths, reason in (
            (["/"], "refusing to remove /"),
            (["/Library/../../etc"], "parent traversal"),
            (["relative/x"], "relative path"),
            ([], "nothing selected"),
        ):
            result = apply_system_leftovers(paths)
            self.assertEqual(result["status"], "refused", paths)
            self.assertIn(reason, result["reason"])

    def test_dry_run_never_executes(self) -> None:
        calls: list[list[str]] = []
        result = apply_system_leftovers(["/Library/x"], runner=lambda *a, **k: calls.append(list(a[0])), dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(calls, [])

    def test_counts_only_pre_existing_items(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apply-count-") as tmp:
            victim = Path(tmp) / "probe"
            victim.write_bytes(b"x")

            def runner(argv, **_kwargs):
                if victim.exists():
                    victim.unlink()
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            result = apply_system_leftovers([str(victim)], runner=runner)
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["pre_existing_count"], 1)
            self.assertEqual(result["removed_count"], 1, "真删掉了就要记 1")

    def test_failure_is_recorded(self) -> None:
        class _Failed:
            returncode = 1
            stderr = "sudo: a password is required"

        result = apply_system_leftovers(["/nonexistent-mc-probe"], runner=lambda *a, **k: _Failed())
        self.assertEqual(result["status"], "failed")
        self.assertIn("password is required", result["error"])
        self.assertEqual(result["removed_count"], 0)


if __name__ == "__main__":
    unittest.main()
