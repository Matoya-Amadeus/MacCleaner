"""会话依赖装配（2026-10-18）：把内核、卸载、更新接上，且用临时 home 可验证。

这里测的是"接线对不对"，不是内核算法（那有各自模块的用例）：
每条都断言"数据真的从内核来"，而不是空壳默认值。
"""
from __future__ import annotations

import json
import os
import plistlib
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
