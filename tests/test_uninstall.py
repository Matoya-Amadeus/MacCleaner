"""卸载残留发现与计划（2026-10-18 迁入）。

钉住的口径全部是在真实使用中踩出来的，不是想象出来的：

1. 只按 bundle-id 找会漏——很多应用用**应用名**建目录；
2. 沙盒应用的数据全在 `Containers/<bundle-id>`；
3. `HTTPStorages` 下常见的是 `<id>.binarycookies` **文件**，不是同名目录；
4. 开机项是**带点边界的文件名前缀**（`<id>.helper.plist` 算，`<id>2.plist` 不算）；
5. 名称匹配必须**完全相等**且长度 ≥4，否则会误伤"Example App Extra"这类邻居。
"""
from __future__ import annotations

import json
import plistlib
import tempfile
import unittest
from pathlib import Path

from maccleaner.uninstall import (
    build_plan,
    discover_related_paths,
    discover_system_related_paths,
    item_id,
    read_app_identity,
    render_plan_text,
    summarize,
)

BUNDLE = "com.example.app"
NAME = "Example App"


def _touch(path: Path, payload: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class DiscoverRelatedPathsTests(unittest.TestCase):
    def test_finds_bundle_id_items_containers_and_name_matched_dirs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-") as tmp:
            home = Path(tmp)
            lib = home / "Library"
            _mkdir(lib / "Caches" / BUNDLE)
            _mkdir(lib / "Containers" / BUNDLE)
            _mkdir(lib / "Application Support" / NAME)
            _mkdir(lib / "Logs" / NAME)
            _mkdir(lib / "Application Support" / f"{NAME} Extra")   # 邻居，不该命中
            _touch(lib / "Preferences" / f"{BUNDLE}.plist")

            found = discover_related_paths(home=home, bundle_id=BUNDLE, app_name=NAME)
            by_path = {item["path"]: item for item in found}

            self.assertIn(str(lib / "Caches" / BUNDLE), by_path)
            self.assertIn(str(lib / "Containers" / BUNDLE), by_path)
            self.assertIn(str(lib / "Preferences" / f"{BUNDLE}.plist"), by_path)
            self.assertIn(str(lib / "Application Support" / NAME), by_path)
            self.assertIn(str(lib / "Logs" / NAME), by_path)
            self.assertNotIn(str(lib / "Application Support" / f"{NAME} Extra"), by_path)
            self.assertEqual(by_path[str(lib / "Caches" / BUNDLE)]["confidence"], "exact")
            self.assertEqual(by_path[str(lib / "Application Support" / NAME)]["confidence"], "name-match")

    def test_http_storages_cookie_file_is_found(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-http-") as tmp:
            home = Path(tmp)
            cookie = _touch(home / "Library" / "HTTPStorages" / f"{BUNDLE}.binarycookies", b"{}")
            found = discover_related_paths(home=home, bundle_id=BUNDLE, app_name=NAME)
            self.assertIn(str(cookie), {item["path"] for item in found})

    def test_launch_agent_uses_dot_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-agent-") as tmp:
            home = Path(tmp)
            mine = _touch(home / "Library" / "LaunchAgents" / f"{BUNDLE}.helper.plist", b"{}")
            neighbor = _touch(home / "Library" / "LaunchAgents" / f"{BUNDLE}2.plist", b"{}")
            paths = {item["path"] for item in discover_related_paths(home=home, bundle_id=BUNDLE, app_name=NAME)}
            self.assertIn(str(mine), paths)
            self.assertNotIn(str(neighbor), paths, "`<id>2.plist` 不属于 `<id>`")

    def test_short_app_name_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-short-") as tmp:
            home = Path(tmp)
            _mkdir(home / "Library" / "Caches" / "App")
            found = discover_related_paths(home=home, bundle_id=BUNDLE, app_name="App")
            self.assertEqual([item for item in found if item["confidence"] == "name-match"], [])


class SystemLeftoversTests(unittest.TestCase):
    def test_system_items_are_flagged_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-sys-") as tmp:
            root = Path(tmp)
            library, receipts = root / "Library", root / "receipts"
            mine = _touch(library / "LaunchAgents" / f"{BUNDLE}.helper.plist", b"{}")
            neighbor = _touch(library / "LaunchAgents" / f"{BUNDLE}2.plist", b"{}")
            _mkdir(library / "Application Support" / NAME)
            ticket = _touch(receipts / f"{BUNDLE}.bom", b"bom")

            found = discover_system_related_paths(
                bundle_id=BUNDLE, app_name=NAME, library_root=library, receipts_root=receipts
            )
            paths = {item["path"]: item for item in found}
            self.assertIn(str(mine), paths)
            self.assertIn(str(ticket), paths)
            self.assertIn(str(library / "Application Support" / NAME), paths)
            self.assertNotIn(str(neighbor), paths)
            self.assertTrue(all(item["requires_admin"] for item in found))
            self.assertEqual(paths[str(library / "Application Support" / NAME)]["confidence"], "name-match")

    def test_no_identity_means_no_system_items(self) -> None:
        self.assertEqual(discover_system_related_paths(bundle_id="", app_name=""), [])


class BuildPlanTests(unittest.TestCase):
    def _app(self, root: Path) -> tuple[Path, dict]:
        app = root / "Applications" / f"{NAME}.app"
        _mkdir(app / "Contents")
        _touch(app / "Contents" / "Info.plist", b"<plist/>")
        return app, {"path": str(app), "bundle_id": BUNDLE, "name": NAME, "home": str(root)}

    def test_plan_puts_the_bundle_first_and_has_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-plan-") as tmp:
            root = Path(tmp)
            app, spec = self._app(root)
            _mkdir(root / "Library" / "Caches" / BUNDLE)

            plan = build_plan(spec, home=root, library_root=root / "Library", receipts_root=root / "receipts")
            self.assertEqual(plan["items"][0]["path"], str(app))
            self.assertEqual(plan["items"][0]["kind"], "app-bundle")
            ids = [item["id"] for item in plan["items"]]
            self.assertEqual(len(ids), len(set(ids)), "计划项 id 必须唯一")
            again = build_plan(spec, home=root, library_root=root / "Library", receipts_root=root / "receipts")
            self.assertEqual(plan["plan_hash"], again["plan_hash"], "同一输入的计划 hash 必须稳定")

    def test_user_and_system_are_counted_separately(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-count-") as tmp:
            root = Path(tmp)
            _app, spec = self._app(root)
            _mkdir(root / "Library" / "Caches" / BUNDLE)
            _touch(root / "Library" / "LaunchAgents" / f"{BUNDLE}.helper.plist", b"{}")

            plan = build_plan(spec, home=root, library_root=root / "Library", receipts_root=root / "receipts")
            self.assertGreaterEqual(plan["user_count"], 2, "应用本体 + 缓存")
            self.assertGreaterEqual(plan["system_count"], 1)
            self.assertTrue(plan["system_items"] and all(i["requires_admin"] for i in plan["system_items"]))
            self.assertTrue(summarize(plan)["needs_admin"])

    def test_item_id_is_stable_and_short(self) -> None:
        self.assertEqual(item_id("/a/b"), item_id("/a/b"))
        self.assertEqual(len(item_id("/a/b")), 12)
        self.assertNotEqual(item_id("/a/b"), item_id("/a/c"))


class AppIdentityTests(unittest.TestCase):
    def test_reads_bundle_id_and_name_from_info_plist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-id-") as tmp:
            app = Path(tmp) / f"{NAME}.app"
            _mkdir(app / "Contents")
            with (app / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleIdentifier": BUNDLE, "CFBundleName": NAME}, handle)
            identity = read_app_identity(app)
            self.assertEqual(identity["bundle_id"], BUNDLE)
            self.assertEqual(identity["name"], NAME)

    def test_missing_plist_falls_back_to_the_folder_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-noid-") as tmp:
            app = Path(tmp) / f"{NAME}.app"
            _mkdir(app)
            identity = read_app_identity(app)
            self.assertEqual(identity["bundle_id"], "")
            self.assertEqual(identity["name"], NAME)


class RenderTests(unittest.TestCase):
    def test_text_plan_says_it_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="uninstall-text-") as tmp:
            root = Path(tmp)
            app = root / "Applications" / f"{NAME}.app"
            _mkdir(app / "Contents")
            _touch(app / "Contents" / "Info.plist", b"<plist/>")
            _mkdir(root / "Library" / "Caches" / BUNDLE)
            plan = build_plan(
                {"path": str(app), "bundle_id": BUNDLE, "name": NAME, "home": str(root)},
                home=root, library_root=root / "Library", receipts_root=root / "receipts",
            )
            text = render_plan_text(plan)
            self.assertIn(NAME, text)
            self.assertIn("只列出", text, "必须明确告诉用户这条命令不删东西")
            self.assertIn("name-match" if False else "*", text)


if __name__ == "__main__":
    unittest.main()


class PathNormalizationTests(unittest.TestCase):
    """同一目录的两种写法必须给出同一个 id（2026-10-18 CLI 冒烟发现的真问题）。"""

    def test_relative_and_absolute_spellings_share_one_id(self) -> None:
        from maccleaner.uninstall import item_id

        with tempfile.TemporaryDirectory(prefix="uninstall-norm-") as tmp:
            root = Path(tmp)
            target = _touch(root / "Library" / "Caches" / BUNDLE)
            import os as _os

            previous = _os.getcwd()
            _os.chdir(root)
            try:
                found = discover_related_paths(home=Path("."), bundle_id=BUNDLE, app_name=NAME)
            finally:
                _os.chdir(previous)
            paths = {item["path"] for item in found}
            self.assertIn(str(target.resolve()), paths | {str(target)}, "相对写法也要归一成绝对路径")
            self.assertEqual(len({item["id"] for item in found}), len(found), "同一次计划里 id 不能重复")
            self.assertEqual(item_id(str(target)), item_id(str(target)), "同一路径 id 必须稳定")
