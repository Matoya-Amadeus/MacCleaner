"""会话依赖装配（2026-10-18）：把内核、卸载、更新接上，且用临时 home 可验证。

这里测的是"接线对不对"，不是内核算法（那有各自模块的用例）：
每条都断言"数据真的从内核来"，而不是空壳默认值。
"""
from __future__ import annotations

import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from maccleaner.deps import build_deps, history_summary, list_applications, read_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_app(root: Path, *, name: str = "Example App", bundle_id: str = "com.example.app") -> Path:
    app = root / f"{name}.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleName": name}, handle)
    return app


class BuildDepsTests(unittest.TestCase):
    def test_audit_comes_from_the_real_kernel(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-") as tmp:
            home = Path(tmp) / "home"
            cache = home / "Library" / "Caches" / "Demo" / "big.cache"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"z" * 4096)
            import os as _os

            _os.utime(cache, (1, 1))

            report = build_deps(home=home, root=home).audit()
            self.assertIn("plan_items", report, "必须是内核报的形状")
            self.assertTrue(report["plan_items"], "临时 home 里放了一个缓存，应被扫到")

    def test_apps_only_scan_user_and_system_app_dirs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-apps-") as tmp:
            home = Path(tmp) / "home"
            (home / "Applications").mkdir(parents=True)
            _fake_app(home / "Applications")
            apps = list_applications(home=home)
            names = [item["name"] for item in apps]
            self.assertIn("Example App", names)
            self.assertTrue(all(item["path"].endswith(".app") for item in apps))
            self.assertTrue(all("bundle_id" in item for item in apps))

    def test_uninstall_plan_uses_the_shared_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-unin-") as tmp:
            home = Path(tmp) / "home"
            app = _fake_app(home / "Applications")
            (home / "Library" / "Caches" / "com.example.app").mkdir(parents=True)

            plan = build_deps(home=home, root=home).uninstall_plan(app_path=str(app))
            kinds = {item["kind"] for item in plan["items"]}
            self.assertIn("app-bundle", kinds)
            self.assertIn("caches", kinds)
            self.assertTrue(plan["plan_hash"])

    def test_updates_check_reports_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-upd-") as tmp:
            found = build_deps(home=Path(tmp) / "home").updates_check()
            self.assertIn("items", found)
            self.assertIn("macOS system updates are out of scope", found.get("scope", ""))

    def test_dry_run_never_cleans(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-dry-") as tmp:
            home = Path(tmp) / "home"
            cache = home / "Library" / "Caches" / "Demo" / "big.cache"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"z" * 4096)

            report = build_deps(home=home, root=home, dry_run=True).clean()
            self.assertTrue(cache.exists(), "dry_run 下 clean 不得移动任何文件")
            self.assertIn("plan_items", report)


class HistoryTests(unittest.TestCase):
    def test_reads_summary_or_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-hist-") as tmp:
            state = Path(tmp)
            self.assertEqual(history_summary(state_root=state), {}, "缺失时给空，不是报错")
            (state / "history.json").write_text(
                json.dumps({"total_runs": 3, "total_freed_bytes": 4096}), encoding="utf-8"
            )
            self.assertEqual(history_summary(state_root=state)["total_runs"], 3)


class ManifestTests(unittest.TestCase):
    def test_manifest_is_loadable_and_points_at_real_entries(self) -> None:
        manifest = read_manifest(REPO_ROOT)
        self.assertEqual(manifest["id"], "mac-cleaner")
        self.assertEqual(int(manifest["protocol_version"]), 1)
        skill_md = REPO_ROOT / str(manifest["entry"]["skill_md"])
        self.assertTrue(skill_md.is_file(), "manifest 指向的 SKILL.md 必须真的存在")
        self.assertIn("permissions", manifest)
        self.assertIn("git-tag", json.dumps(manifest), "渠道必须是可复现的 tag，不是浮动分支")

    def test_cli_exposes_the_ui_subcommand(self) -> None:
        from maccleaner.cli import build_parser

        parser = build_parser()
        actions = [action for action in parser._actions if getattr(action, "choices", None)]
        self.assertTrue(any("ui" in (action.choices or {}) for action in actions), "必须有 ui 子命令")


if __name__ == "__main__":
    unittest.main()
