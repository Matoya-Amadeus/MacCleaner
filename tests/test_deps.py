"""会话依赖装配（2026-10-18）：把内核、卸载、更新接上，且用临时 home 可验证。

这里测的是"接线对不对"，不是内核算法（那有各自模块的用例）：
每条都断言"数据真的从内核来"，而不是空壳默认值。
"""
from __future__ import annotations

import json
import os
import plistlib
import time
import tempfile
import unittest
from pathlib import Path

from maccleaner.deps import (
    build_deps,
    history_summary,
    list_applications,
    list_skills,
    read_manifest,
)

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
        # maho 的解析器把 entry.bin 当**仓库内相对路径**用，所以它必须是一个真实文件——
        # 写命令名（`maccleaner`）在那边会解析成 <root>/maccleaner 而找不到。
        entry_bin = REPO_ROOT / str(manifest["entry"]["bin"])
        self.assertTrue(entry_bin.is_file(), f"entry.bin 必须是仓库内的真实文件：{entry_bin}")
        self.assertTrue(os.access(entry_bin, os.X_OK), "entry.bin 必须可执行")
        self.assertIn("permissions", manifest)
        self.assertIn("git-tag", json.dumps(manifest), "渠道必须是可复现的 tag，不是浮动分支")

    def test_cli_exposes_the_ui_subcommand(self) -> None:
        from maccleaner.cli import build_parser

        parser = build_parser()
        actions = [action for action in parser._actions if getattr(action, "choices", None)]
        self.assertTrue(any("ui" in (action.choices or {}) for action in actions), "必须有 ui 子命令")


if __name__ == "__main__":
    unittest.main()


class RobustnessTests(unittest.TestCase):
    """一个坏文件不能毁掉整页（2026-10-19 用户看到"共 0 个应用"的真因）。"""

    def test_corrupt_info_plist_does_not_empty_the_app_list(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-bad-plist-") as tmp:
            home = Path(tmp) / "home"
            good = home / "Applications" / "Good.app" / "Contents"
            good.mkdir(parents=True)
            with (good / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleIdentifier": "com.example.good", "CFBundleName": "Good"}, handle)
            bad = home / "Applications" / "Broken.app" / "Contents"
            bad.mkdir(parents=True)
            (bad / "Info.plist").write_bytes(b"<?xml version='1.0'?><plist><dict><key>broken")

            apps = list_applications(home=home)
            names = {item["name"] for item in apps}
            self.assertIn("Good", names)
            self.assertIn("Broken", names, "坏 plist 的应用仍应按目录名列出，并带上空 bundle_id")
            broken = next(item for item in apps if item["name"] == "Broken")
            self.assertEqual(broken["bundle_id"], "")


class SkillListingTests(unittest.TestCase):
    """技能页要列**本机全部** skill（2026-10-19 用户要求）。"""

    def _write_skill(self, root: Path, name: str, description: str) -> Path:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")
        return skill_md

    def test_lists_skills_from_every_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skills-") as tmp:
            first, second = Path(tmp) / "root-a", Path(tmp) / "root-b"
            self._write_skill(first, "alpha", "第一个技能")
            self._write_skill(second, "beta", "第二个技能")

            skills = list_skills([str(first), str(second)])
            # 第 0 条永远是"本工具自己"（置顶标注），断言时先排除
            self.assertEqual(skills[0]["root"], "本工具", "本工具应置顶")
            others = [item for item in skills if item["root"] != "本工具"]
            names = {item["name"] for item in others}
            self.assertEqual(names, {"alpha", "beta"})
            self.assertTrue(all(item["path"].endswith("SKILL.md") for item in others))
            self.assertEqual(len({item["root"] for item in others}), 2, "要保留来源根，页面要分组")

    def test_missing_root_is_skipped_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skills-miss-") as tmp:
            existing = Path(tmp) / "root"
            self._write_skill(existing, "only", "仅此一个")
            skills = list_skills([str(Path(tmp) / "nope"), str(existing)])
            names = [item["name"] for item in skills if item["root"] != "本工具"]
            self.assertEqual(names, ["only"], "不存在的根要跳过，而不是整体失败")

    def test_skills_page_renders_rows_and_groups(self) -> None:
        from maccleaner.ui.pages import render_skills_html

        payload = {
            "skills": [
                {"name": "mac-cleaner", "description": "清理磁盘", "path": "/x/SKILL.md", "root": "本工具"},
                {"name": "alpha", "description": "第一个", "path": "/a/SKILL.md", "root": "~/.codex/skills"},
            ]
        }
        page = render_skills_html(payload)
        self.assertIn('data-stage="skills"', page)
        self.assertEqual(page.count('class="row"'), 2)
        self.assertIn("本工具", page, "自己的那条要标注出来")
        self.assertIn("~/.codex/skills", page, "按来源分组")
        self.assertIn("<details", page, "自己的细节仍收进折叠块")


class ListingSpeedTests(unittest.TestCase):
    """列表页不许算体积（2026-10-19：用户看到"正在读取应用列表"卡住 6 秒）。"""

    def test_list_does_not_shell_out_by_default(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="deps-fast-") as tmp:
            home = Path(tmp) / "home"
            (home / "Applications").mkdir(parents=True)
            _fake_app(home / "Applications")
            with patch("maccleaner.deps.subprocess.run", side_effect=AssertionError("列表不该调用 du")):
                apps = list_applications(home=home)
            # 注意：它也会扫真实的 /Applications，所以只断言"假的那个在、且没有体积字段"。
            self.assertIn("Example App", {item["name"] for item in apps})
            self.assertTrue(all("allocated_bytes" not in item for item in apps), "默认不返回体积，页面显示 —")

    def test_explicit_with_sizes_still_works(self) -> None:
        with tempfile.TemporaryDirectory(prefix="deps-sized-") as tmp:
            home = Path(tmp) / "home"
            (home / "Applications").mkdir(parents=True)
            _fake_app(home / "Applications")
            apps = list_applications(home=home, with_sizes=True)
            self.assertIn("allocated_bytes", apps[0])


class ScanCacheTests(unittest.TestCase):
    """扫描缓存（2026-10-19）：命中要真省时间，过期/路径变化要真重扫。"""

    def _home(self, tmp: Path) -> Path:
        home = tmp / "home"
        cache = home / "Library" / "Caches" / "Demo"
        cache.mkdir(parents=True)
        (cache / "a.bin").write_bytes(b"z" * 4096)
        import os as _os

        _os.utime(cache, (1, 1))
        return home

    def test_second_scan_hits_cache_and_reports_the_time(self) -> None:
        from unittest.mock import patch

        from maccleaner.deps import scan_report

        with tempfile.TemporaryDirectory(prefix="scan-cache-") as tmp:
            home = self._home(Path(tmp))
            state = Path(tmp) / "state"
            with patch.object(__import__("maccleaner.deps", fromlist=["StorageManager"]).StorageManager,
                              "audit", autospec=True, side_effect=lambda self: _fake_report()) as spy:
                first = scan_report(home=home, root=home, state_root=state)
                second = scan_report(home=home, root=home, state_root=state)
            self.assertEqual(spy.call_count, 1, "第二次应命中缓存，不再扫")
            self.assertEqual(first.get("scan_cached_at"), 0.0)
            self.assertGreater(second.get("scan_cached_at"), 0, "命中时要带回扫描时间，页面才能标注")
            self.assertEqual(len(second["plan_items"]), len(first["plan_items"]))

    def test_force_bypasses_the_cache(self) -> None:
        from unittest.mock import patch

        from maccleaner.deps import scan_report

        with tempfile.TemporaryDirectory(prefix="scan-force-") as tmp:
            home = self._home(Path(tmp))
            state = Path(tmp) / "state"
            with patch.object(__import__("maccleaner.deps", fromlist=["StorageManager"]).StorageManager,
                              "audit", autospec=True, side_effect=lambda self: _fake_report()) as spy:
                scan_report(home=home, root=home, state_root=state)
                scan_report(home=home, root=home, state_root=state, force=True)
            self.assertEqual(spy.call_count, 2, "force 必须绕过缓存（页面上的【重新扫描】用它）")

    def test_changed_target_invalidates_the_cache(self) -> None:
        from unittest.mock import patch

        from maccleaner.deps import scan_report

        with tempfile.TemporaryDirectory(prefix="scan-invalid-") as tmp:
            home = self._home(Path(tmp))
            state = Path(tmp) / "state"
            watched = home / "Library" / "Caches"
            with patch.object(__import__("maccleaner.deps", fromlist=["StorageManager"]).StorageManager,
                              "audit", autospec=True, side_effect=lambda self: _fake_report()) as spy:
                scan_report(home=home, root=home, state_root=state)
                os.utime(watched, (10_000, 10_000))     # 目标目录变了
                scan_report(home=home, root=home, state_root=state)
            self.assertEqual(spy.call_count, 2, "目标 mtime 变化后必须重扫")


    def test_interrupted_scan_is_retried_once(self) -> None:
        """扫描会遍历整个主目录，系统调用可能被信号打断（实测 Errno 4）。"""
        from unittest.mock import patch

        from maccleaner.deps import scan_report

        with tempfile.TemporaryDirectory(prefix="scan-eintr-") as tmp:
            home = self._home(Path(tmp))
            state = Path(tmp) / "state"
            report = _fake_report()
            with patch.object(__import__("maccleaner.deps", fromlist=["StorageManager"]).StorageManager,
                              "audit", autospec=True,
                              side_effect=[InterruptedError(4, "Interrupted system call"), report]) as spy:
                result = scan_report(home=home, root=home, state_root=state, force=True)
            self.assertEqual(spy.call_count, 2, "被信号打断后应重试一次")
            self.assertTrue(result["plan_items"])

def _fake_report() -> object:
    from pathlib import Path as _Path

    class _Report:
        def to_dict(self) -> dict:
            return {
                "mode": "audit",
                "plan_items": [
                    {
                        "target_id": "home-caches",
                        "name": "Home caches",
                        "category": "cache",
                        "estimated_bytes": 4096,
                        "recoverable": True,
                        "status": "planned",
                        "paths": ["~/Library/Caches"],
                    }
                ],
            }

    return _Report()


class FlutterDiscoveryScopeTests(unittest.TestCase):
    """Flutter 工程发现的范围（2026-10-19 提速）：默认只扫常见工程目录。"""

    def test_default_roots_are_candidate_dirs_not_the_whole_home(self) -> None:
        from maccleaner.core import StorageContext, StorageManager

        manager = StorageManager(StorageContext(home=Path.home(), root=Path.home()))
        roots = manager._flutter_roots()
        self.assertTrue(all(path != Path.home() for path in roots), "不该整个家目录地扫")
        for path in roots:
            self.assertTrue(str(path).startswith(str(Path.home())), "候选目录应在主目录下")

    def test_configured_root_wins(self) -> None:
        from maccleaner.core import StorageContext, StorageManager

        with tempfile.TemporaryDirectory(prefix="flutter-root-") as tmp:
            manager = StorageManager(StorageContext(home=Path(tmp), root=Path(tmp), flutter_search_root=Path(tmp)))
            self.assertEqual(manager._flutter_roots(), [Path(tmp)])

class DiskAndSystemTests(unittest.TestCase):
    """磁盘 / 系统快照（只读，不依赖 psutil）。"""

    def test_disk_report_has_sane_numbers(self) -> None:
        import shutil as _shutil

        from maccleaner.deps import disk_report

        with tempfile.TemporaryDirectory(prefix="disk-") as tmp:
            report = disk_report(home=Path(tmp))
            usage = _shutil.disk_usage(str(Path(tmp)))   # 要在目录还存在时取，否则 statvfs 失败
        self.assertGreater(report["total"], 0)
        self.assertLessEqual(report["used"], report["total"])
        self.assertTrue(0 <= report["percent"] <= 100)
        self.assertIsInstance(report["sections"], list)

    def test_system_report_reads_load_and_memory(self) -> None:
        from maccleaner.deps import system_report

        report = system_report()
        self.assertEqual(len(report["load"]), 3)
        self.assertGreater(report["cpu_count"], 0)
        self.assertGreaterEqual(report["memory_used"], 0)
        self.assertLessEqual(report["memory_used"], report["memory_total"] or report["memory_used"] + 1)

class HistoryReportTests(unittest.TestCase):
    """清理历史直接读回执文件（2026-10-19），不另造状态源。"""

    def _receipt(self, home: Path, name: str, when: str, cleaned: int, freed: int) -> None:
        directory = home / ".mac-storage-manager" / "receipts"
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": when,
            "mode": "clean",
            "dry_run": False,
            "actual_reclaimed_bytes": freed,
            "plan_items": [{"status": "cleaned"} for _ in range(cleaned)],
        }
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_receipts_newest_first(self) -> None:
        from maccleaner.deps import history_report

        with tempfile.TemporaryDirectory(prefix="history-") as tmp:
            home = Path(tmp)
            self._receipt(home, "cleanup-receipt-20261001-100000.json", "2026-10-01T10:00:00", 2, 4096)
            self._receipt(home, "cleanup-receipt-20261002-100000.json", "2026-10-02T10:00:00", 3, 8192)
            report = history_report(home=home)

        self.assertEqual(report["runs"], 2)
        self.assertEqual(report["entries"][0]["created_at"][:10], "2026-10-02", "新的在前")
        self.assertEqual(report["entries"][0]["items"], 3)
        self.assertEqual(report["total_bytes"], 4096 + 8192)
        self.assertEqual(report["total_items"], 5)

    def test_missing_or_broken_receipts_are_skipped(self) -> None:
        from maccleaner.deps import history_report

        with tempfile.TemporaryDirectory(prefix="history-bad-") as tmp:
            home = Path(tmp)
            directory = home / ".mac-storage-manager" / "receipts"
            directory.mkdir(parents=True)
            (directory / "cleanup-receipt-broken.json").write_text("{not json", encoding="utf-8")
            report = history_report(home=home)
        self.assertEqual(report["runs"], 0, "坏文件不能让整页失败")
        self.assertEqual(report["entries"], [])
    def test_other_app_from_same_vendor_suppresses_the_report(self) -> None:
        """同厂商还装着别的应用时，不把它的缓存报成孤儿。

        实测来源（2026-10-20）：`com.epicgames.UnrealEditor` 的缓存对应的是
        `UnrealEditorServices`（装在 ~/Workspace/UEProject/…），bundle id 与缓存目录名不逐字相同，
        前缀匹配抓不到 → 267 MB 被误报成孤儿。改为"同厂商保守排除"。
        """
        from maccleaner.deps import orphan_leftovers

        with tempfile.TemporaryDirectory(prefix="orphans-vendor-") as tmp:
            home = Path(tmp)
            (home / "Applications" / "Epic.app" / "Contents").mkdir(parents=True)
            plistlib.dump(
                {"CFBundleIdentifier": "com.epicgames.Launcher", "CFBundleName": "Epic"},
                (home / "Applications" / "Epic.app" / "Contents" / "Info.plist").open("wb"),
            )
            caches = home / "Library" / "Caches"
            for name in ("com.epicgames.UnrealEditor", "com.gone.app"):
                path = caches / name
                path.mkdir(parents=True)
                (path / "x").write_bytes(b"z" * 512)
                stamp = time.time() - 40 * 86400
                os.utime(path, (stamp, stamp))
            report = orphan_leftovers(home, system=False)
        names = [item["name"] for item in report["items"]]
        self.assertNotIn("com.epicgames.UnrealEditor", names, "同厂商应用还在，不能报成孤儿")
        self.assertIn("com.gone.app", names)
        self.assertGreater(report["skipped_vendor"], 0, "被排除的要计数，页面要说明")


class DiskBrowseTests(unittest.TestCase):
    """磁盘钻取（2026-10-19）：列下一级、按体积降序、不许越出 home。"""

    def _tree(self, home: Path) -> None:
        (home / "big").mkdir(parents=True)
        (home / "big" / "x.bin").write_bytes(b"z" * (2 * 1024 * 1024))
        (home / "small").mkdir()
        (home / "small" / "y.bin").write_bytes(b"z" * (512 * 1024))
        (home / "note.txt").write_bytes(b"z" * 1024)

    def test_lists_children_sorted_by_size(self) -> None:
        from maccleaner.deps import disk_browse

        with tempfile.TemporaryDirectory(prefix="browse-") as tmp:
            home = Path(tmp)
            self._tree(home)
            report = disk_browse(home)

        names = [item["name"] for item in report["entries"]]
        self.assertEqual(names[:2], ["big", "small"], "大的在前")
        self.assertIn("note.txt", names)
        big = next(item for item in report["entries"] if item["name"] == "big")
        self.assertTrue(big["is_dir"])
        self.assertGreaterEqual(big["bytes"], 2 * 1024 * 1024)

    def test_path_outside_home_falls_back_to_home(self) -> None:
        from maccleaner.deps import disk_browse

        with tempfile.TemporaryDirectory(prefix="browse-safe-") as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            self._tree(home)
            report = disk_browse(home, "/etc")

        self.assertEqual(report["path"], str(home.resolve()), "越界路径要退回家目录")

    def test_parent_is_empty_at_home(self) -> None:
        from maccleaner.deps import disk_browse

        with tempfile.TemporaryDirectory(prefix="browse-parent-") as tmp:
            home = Path(tmp)
            self._tree(home)
            self.assertEqual(disk_browse(home)["parent"], "")
            child = disk_browse(home, str(home / "big"))
        self.assertTrue(child["parent"], "进到子目录要能回上一级")

class SparkleDetectionTests(unittest.TestCase):
    """自带 Sparkle 更新器的应用要能被识别（2026-10-19 用户要求"先走应用自带更新"）。"""

    def _app(self, home: Path, name: str, info: dict) -> Path:
        contents = home / "Applications" / f"{name}.app" / "Contents"
        contents.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump(info, handle)
        return contents.parent

    def test_detects_su_feed_url(self) -> None:
        from maccleaner.deps import sparkle_apps

        with tempfile.TemporaryDirectory(prefix="sparkle-") as tmp:
            home = Path(tmp)
            self._app(home, "Feedy", {
                "CFBundleName": "Feedy",
                "CFBundleIdentifier": "com.example.feedy",
                "CFBundleShortVersionString": "1.2.3",
                "SUFeedURL": "https://example.com/appcast.xml",
            })
            apps = sparkle_apps(home, system=False)
        self.assertEqual([app["name"] for app in apps], ["Feedy"])
        self.assertEqual(apps[0]["feed"], "https://example.com/appcast.xml")
        self.assertEqual(apps[0]["version"], "1.2.3")

    def test_detects_sparkle_framework_without_feed(self) -> None:
        from maccleaner.deps import sparkle_apps

        with tempfile.TemporaryDirectory(prefix="sparkle-fw-") as tmp:
            home = Path(tmp)
            bundle = self._app(home, "Framed", {"CFBundleName": "Framed"})
            (bundle / "Contents" / "Frameworks" / "Sparkle.framework").mkdir(parents=True)
            apps = sparkle_apps(home, system=False)
        self.assertEqual([app["name"] for app in apps], ["Framed"])
        self.assertEqual(apps[0]["feed"], "", "只有框架时 feed 为空，页面要说\"使用内置 Sparkle\"")

    def test_plain_app_is_not_listed(self) -> None:
        from maccleaner.deps import sparkle_apps

        with tempfile.TemporaryDirectory(prefix="sparkle-none-") as tmp:
            home = Path(tmp)
            self._app(home, "Plain", {"CFBundleName": "Plain"})
            self.assertEqual(sparkle_apps(home, system=False), [])

class OrphanLeftoverTests(unittest.TestCase):
    """孤儿残留（学 Pearcleaner）：只报"应用不在了但残留还在"，且不能误伤已装应用。"""

    def _home(self, tmp: Path) -> Path:
        home = tmp / "home"
        (home / "Applications" / "Demo.app" / "Contents").mkdir(parents=True)
        plistlib.dump(
            {"CFBundleIdentifier": "com.demo.app", "CFBundleName": "Demo"},
            (home / "Applications" / "Demo.app" / "Contents" / "Info.plist").open("wb"),
        )
        caches = home / "Library" / "Caches"
        caches.mkdir(parents=True)
        return home

    def _dir(self, path: Path, *, days_old: int) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "x.bin").write_bytes(b"z" * 1024)
        stamp = time.time() - days_old * 86400
        os.utime(path, (stamp, stamp))

    def test_reports_only_truly_orphaned_leftovers(self) -> None:
        from maccleaner.deps import orphan_leftovers

        with tempfile.TemporaryDirectory(prefix="orphans-") as tmp:
            home = self._home(Path(tmp))
            caches = home / "Library" / "Caches"
            self._dir(caches / "com.demo.app", days_old=40)          # 已装应用 → 不报
            self._dir(caches / "com.demo.app.ShipIt", days_old=40)   # 前缀属于已装 → 不报
            self._dir(caches / "com.apple.Safari", days_old=40)      # 苹果系统 → 跳过
            self._dir(caches / "com.gone.app", days_old=40)          # 真孤儿 → 报
            self._dir(caches / "com.fresh.app", days_old=0)          # 刚改过 → 先不动
            report = orphan_leftovers(home, system=False)
            names = [item["name"] for item in report["items"]]
            self.assertEqual(names, ["com.gone.app"], f"只该报真孤儿，实际：{names}")
            self.assertGreater(report["bytes"], 0)

    def test_clean_moves_to_trash_and_refuses_outside_home(self) -> None:
        from maccleaner.deps import orphans_clean

        with tempfile.TemporaryDirectory(prefix="orphans-clean-") as tmp:
            home = self._home(Path(tmp))
            target = home / "Library" / "Caches" / "com.gone.app"
            self._dir(target, days_old=40)
            outside = Path(tmp) / "outside.txt"
            outside.write_text("x", encoding="utf-8")

            result = orphans_clean(home, [str(target), str(outside)])
            self.assertEqual(result["count"], 1, f"只该搬一个：{result}")
            self.assertEqual(len(result["failed"]), 1, "越界路径必须被拒")
            self.assertFalse(target.exists(), "目标应已移走")
            self.assertTrue(outside.exists(), "家目录外的文件不能动")
            trashed = list((home / ".Trash").iterdir())
            self.assertEqual(len(trashed), 1)

class PowerParsingTests(unittest.TestCase):
    """电池与节流解析（2026-10-20）：免 sudo，数据来自 pmset / ioreg。"""

    def test_parse_pmset_batt(self) -> None:
        from maccleaner.deps import parse_pmset_batt

        text = (
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0 (id=22151267)\t79%; discharging; 3:04 remaining present: true\n"
        )
        data = parse_pmset_batt(text)
        self.assertEqual(data["percent"], 79)
        self.assertEqual(data["source"], "电池")
        self.assertEqual(data["state"], "discharging")
        self.assertEqual(data["remaining"], "3:04")

    def test_parse_battery_ioreg_uses_full_charge_capacity(self) -> None:
        """健康度必须用 FullChargeCapacity/DesignCapacity。

        本机 `MaxCapacity=100` 只是百分比；拿它算健康度会永远显示 100%（错的）。
        """
        from maccleaner.deps import parse_battery_ioreg

        text = (
            '  |   "MaxCapacity" = 100\n'
            '  |   "CycleCount" = 986\n'
            '  |   "BatteryData" = {"FullChargeCapacity"=6918,"DesignCapacity"=8694}\n'
        )
        data = parse_battery_ioreg(text)
        self.assertEqual(data["cycles"], 986)
        self.assertEqual(data["health_percent"], 80)
        self.assertEqual(data["design_mah"], 8694)

    def test_parse_thermal_reports_no_throttle_when_absent(self) -> None:
        from maccleaner.deps import parse_thermal

        idle = parse_thermal("Note: No thermal warning level has been recorded\n")
        self.assertFalse(idle["throttled"])
        self.assertIsNone(idle["speed_limit"])

        hot = parse_thermal("CPU_Speed_Limit = 70\nCPU_Scheduler_Limit = 80\n")
        self.assertTrue(hot["throttled"])
        self.assertEqual(hot["speed_limit"], 70)

