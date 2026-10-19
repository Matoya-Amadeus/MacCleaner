"""第三方软件更新（2026-10-18 迁入）。

钉住的都是"真机上会咬人"的点：

1. 两个来源（brew / mas）**互相独立**——一个失败不该让另一个消失；
2. runner 有**两种形态**（可调用对象 / 带 `.run()` 的对象）；在 maho 里就因此把整个会话打成过失败；
3. 执行按**组**跑，一组失败不拖累其它组；
4. `dry_run` 只回命令、**不执行**（CLI 默认就是它）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maccleaner.updates import (
    SCOPE_NOTE,
    apply_updates,
    build_upgrade_plan,
    discover_updates,
    parse_brew_outdated,
    parse_gem_outdated,
    parse_mas_outdated,
    parse_npm_outdated,
    parse_pip_outdated,
    parse_rustup_check,
    select_updates,
)

BREW_JSON = """
{
  "formulae": [
    {"name": "ffmpeg", "installed_versions": ["6.0"], "current_version": "7.1"},
    {"name": "jq", "installed_versions": "1.7.1", "current_version": "1.7.1"}
  ],
  "casks": [
    {"token": "raycast", "installed_versions": "1.50.0", "current_version": "1.60.0"}
  ]
}
"""

MAS_TEXT = """497799835 Xcode (15.0)
409183694 Keynote (13.2)
"""


class _Runner:
    """按命令片段返回预置结果，并记录调用。"""

    def __init__(self, answers: dict[str, tuple[int, str, str]]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_kwargs):  # noqa: ANN001, ANN003
        self.calls.append(list(argv))
        joined = " ".join(str(part) for part in argv)
        for key, (code, out, err) in self.answers.items():
            if key in joined:
                return type("R", (), {"returncode": code, "stdout": out, "stderr": err})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def _with_fake_managers(runner):
    """把两个 CLI 都当成"存在"，否则用例会依赖本机是否装了 brew/mas。"""
    import maccleaner.updates as mod

    original = mod._resolve
    mod._resolve = lambda name: f"/fake/{name}"  # type: ignore[assignment]
    try:
        return mod.discover_updates(runner=runner)
    finally:
        mod._resolve = original  # type: ignore[assignment]


class ParseTests(unittest.TestCase):
    def test_brew_json_covers_formula_and_cask(self) -> None:
        by_name = {item["name"]: item for item in parse_brew_outdated(BREW_JSON)}
        self.assertEqual(by_name["ffmpeg"]["installed"], "6.0")
        self.assertEqual(by_name["ffmpeg"]["available"], "7.1")
        self.assertEqual(by_name["raycast"]["kind"], "cask")
        self.assertEqual(by_name["raycast"]["installed"], "1.50.0", "installed_versions 是字符串时也要能解析")

    def test_mas_text(self) -> None:
        items = parse_mas_outdated(MAS_TEXT)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["app_id"], "497799835")
        self.assertEqual(items[0]["available"], "15.0")

    def test_garbage_yields_empty_not_exception(self) -> None:
        self.assertEqual(parse_brew_outdated("not json"), [])
        self.assertEqual(parse_mas_outdated("garbage line without id"), [])


class DiscoverTests(unittest.TestCase):
    def test_merges_both_sources_and_states_scope(self) -> None:
        runner = _Runner({"outdated --json=v2": (0, BREW_JSON, ""), "outdated": (0, MAS_TEXT, "")})
        result = _with_fake_managers(runner)
        names = [item["name"] for item in result["items"]]
        self.assertIn("ffmpeg", names)
        self.assertIn("Xcode", names)
        self.assertEqual(result["count"], 5, "brew 3 项 + mas 2 项")
        self.assertIn("macOS system updates are out of scope", result["scope"])
        self.assertEqual(result["notes"], [])

    def test_missing_cli_degrades_to_note(self) -> None:
        import maccleaner.updates as mod

        original = mod._resolve
        mod._resolve = lambda name: ""  # type: ignore[assignment]
        try:
            result = mod.discover_updates(runner=_Runner({}))
        finally:
            mod._resolve = original  # type: ignore[assignment]
        self.assertEqual(result["items"], [])
        self.assertGreaterEqual(len(result["notes"]), 2, "每个缺工具的源各一条，源变多了不要写死条数")
        self.assertTrue(all("未安装" in note for note in result["notes"]))

    def test_one_source_failing_keeps_the_other(self) -> None:
        runner = _Runner({"outdated --json=v2": (1, "", "boom"), "outdated": (0, MAS_TEXT, "")})
        result = _with_fake_managers(runner)
        self.assertTrue(any("Homebrew 查询失败" in note for note in result["notes"]))
        self.assertIn("Xcode", [item["name"] for item in result["items"]])

    def test_scope_note_is_explicit(self) -> None:
        self.assertIn("third-party only", SCOPE_NOTE)


class UpgradePlanTests(unittest.TestCase):
    ITEMS = [
        {"manager": "brew", "kind": "formula", "name": "aom"},
        {"manager": "brew", "kind": "formula", "name": "cmake"},
        {"manager": "brew", "kind": "cask", "name": "devin-desktop"},
        {"manager": "mas", "kind": "app-store", "name": "Xcode", "app_id": "497799835"},
        {"manager": "unknown", "kind": "x", "name": "nope"},
    ]

    def test_groups_by_manager_and_kind(self) -> None:
        plan = build_upgrade_plan(self.ITEMS, brew="/fake/brew", mas="/fake/mas")
        self.assertEqual(len(plan["groups"]), 3)
        self.assertEqual(plan["count"], 4)
        self.assertEqual(plan["ignored"], ["nope"])
        commands = [group["command"] for group in plan["groups"]]
        self.assertIn("brew upgrade aom cmake", commands)
        self.assertIn("brew upgrade --cask devin-desktop", commands, "cask 必须带 --cask")
        self.assertIn("mas upgrade 497799835", commands)

    def test_empty_selection_is_refused(self) -> None:
        result = apply_updates(build_upgrade_plan([]))
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["reason"], "nothing selected")

    def test_dry_run_returns_commands_without_executing(self) -> None:
        calls: list[list[str]] = []
        plan = build_upgrade_plan(self.ITEMS, brew="/fake/brew", mas="/fake/mas")
        result = apply_updates(plan, dry_run=True, runner=lambda *a, **k: calls.append(list(a[0])))
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(len(result["commands"]), 3)
        self.assertEqual(calls, [], "dry-run 不得调用 runner")

    def test_partial_failure_does_not_stop_other_groups(self) -> None:
        def runner(argv, **_kwargs):
            code = 1 if "aom" in argv else 0
            return type("R", (), {
                "returncode": code,
                "stdout": "ok" if code == 0 else "",
                "stderr": "" if code == 0 else "boom",
            })()

        result = apply_updates(build_upgrade_plan(self.ITEMS, brew="/fake/brew", mas="/fake/mas"), runner=runner)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["ok_count"], 2)
        failed = [group for group in result["groups"] if not group["ok"]]
        self.assertEqual(len(failed), 1)
        self.assertIn("boom", failed[0]["stderr_tail"], "失败要留下 stderr")

    def test_all_failed(self) -> None:
        def runner(argv, **_kwargs):
            return type("R", (), {"returncode": 2, "stdout": "", "stderr": "nope"})()

        result = apply_updates(build_upgrade_plan(self.ITEMS, brew="/fake/brew", mas="/fake/mas"), runner=runner)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["ok_count"], 0)


class RunnerShapeTests(unittest.TestCase):
    """两种 runner 形态都要能用（maho 里就因 `CommandRunner` 不可调用把会话打成过失败）。"""

    def test_runnable_object_is_supported(self) -> None:
        class _Obj:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def run(self, argv, **_kwargs):
                self.calls.append(list(argv))
                return type("R", (), {"returncode": 0, "stdout": BREW_JSON, "stderr": ""})()

        obj = _Obj()
        result = _with_fake_managers(obj)
        self.assertTrue(obj.calls)
        self.assertEqual(result["count"], 3)

    def test_apply_accepts_runnable_object(self) -> None:
        class _Obj:
            def run(self, argv, **_kwargs):
                return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        plan = build_upgrade_plan([{"manager": "brew", "kind": "formula", "name": "aom"}], brew="/fake/brew")
        self.assertEqual(apply_updates(plan, runner=_Obj())["status"], "applied")


if __name__ == "__main__":
    unittest.main()


class MasParsingTests(unittest.TestCase):
    """mas 输出解析（2026-10-19 真机 bug）：名字可以含空格，版本要拆成 installed/available。"""

    def test_name_with_spaces_is_kept_whole(self) -> None:
        items = parse_mas_outdated("634148309  Logic Pro  (11.2 -> 12.4)")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Logic Pro", "不能被空格截成 Logic")
        self.assertEqual(items[0]["installed"], "11.2")
        self.assertEqual(items[0]["available"], "12.4")

    def test_line_without_version_parentheses_is_still_listed(self) -> None:
        items = parse_mas_outdated("497799835  Xcode")
        self.assertEqual(items[0]["name"], "Xcode")
        self.assertEqual(items[0]["available"], "")

    def test_noise_lines_are_ignored(self) -> None:
        items = parse_mas_outdated("Warning: something happened\n\n634148309  Logic Pro  (11.2 -> 12.4)")
        self.assertEqual([item["name"] for item in items], ["Logic Pro"])


class SelectionTests(unittest.TestCase):
    """`--only` 的匹配规则（CLI 与 MCP 共用同一份）。"""

    def _items(self) -> list[dict]:
        return [
            {"name": "Logic Pro", "app_id": "634148309"},
            {"name": "aom", "app_id": ""},
        ]

    def test_select_by_name_with_space(self) -> None:
        self.assertEqual([i["name"] for i in select_updates(self._items(), {"Logic Pro"})], ["Logic Pro"])

    def test_select_by_app_id(self) -> None:
        self.assertEqual([i["name"] for i in select_updates(self._items(), {"634148309"})], ["Logic Pro"])

    def test_empty_wanted_means_all(self) -> None:
        self.assertEqual(len(select_updates(self._items(), set())), 2)

    def test_unknown_name_selects_nothing(self) -> None:
        self.assertEqual(select_updates(self._items(), {"nope"}), [])

class ExtraSourceParsingTests(unittest.TestCase):
    """额外更新源（npm/pip/gem/rustup）的解析（2026-10-19 对齐 Topgrade 的思路）。"""

    def test_npm_outdated_json(self) -> None:
        items = parse_npm_outdated('{"typescript": {"current": "5.3.0", "latest": "5.6.3"}}')
        self.assertEqual(items[0]["manager"], "npm")
        self.assertEqual(items[0]["name"], "typescript")
        self.assertEqual(items[0]["available"], "5.6.3")

    def test_npm_ignores_non_object_values(self) -> None:
        self.assertEqual(parse_npm_outdated('{"x": "junk"}'), [])
        self.assertEqual(parse_npm_outdated("not json"), [])

    def test_pip_outdated_json(self) -> None:
        items = parse_pip_outdated('[{"name": "requests", "version": "2.28.0", "latest_version": "2.32.0"}]')
        self.assertEqual([(i["name"], i["installed"], i["available"]) for i in items],
                         [("requests", "2.28.0", "2.32.0")])

    def test_gem_outdated_text(self) -> None:
        items = parse_gem_outdated("rails (7.0.1 < 7.1.3)\nrake (13.0.6)")
        self.assertEqual(items[0]["name"], "rails")
        self.assertEqual(items[0]["available"], "7.1.3")
        self.assertEqual(items[1]["available"], "")

    def test_rustup_check_only_update_lines(self) -> None:
        payload = (
            "stable-aarch64-apple-darwin - Up to date : 1.90.0\n"
            "nightly-aarch64-apple-darwin - Update available : 1.92.0-nightly -> 1.93.0-nightly\n"
        )
        items = parse_rustup_check(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["installed"], "1.92.0-nightly")
        self.assertEqual(items[0]["available"], "1.93.0-nightly")


class ExtraSourcePlanTests(unittest.TestCase):
    def test_each_manager_gets_its_own_command(self) -> None:
        plan = build_upgrade_plan([
            {"manager": "npm", "kind": "npm-global", "name": "typescript"},
            {"manager": "pip", "kind": "pip", "name": "requests"},
            {"manager": "gem", "kind": "gem", "name": "rails"},
            {"manager": "rustup", "kind": "toolchain", "name": "stable-aarch64-apple-darwin"},
        ])
        commands = {group["manager"]: group["command"] for group in plan["groups"]}
        self.assertIn("npm install -g typescript@latest", commands["npm"])
        self.assertIn("pip3 install --upgrade requests", commands["pip"])
        self.assertIn("gem update rails", commands["gem"])
        self.assertEqual(commands["rustup"], "rustup update")

    def test_unknown_manager_is_ignored_not_executed(self) -> None:
        plan = build_upgrade_plan([{"manager": "weird", "kind": "x", "name": "thing"}])
        self.assertEqual(plan["groups"], [])
        self.assertEqual(plan["ignored"], ["thing"])


class SourceSelectionTests(unittest.TestCase):
    """pip/gem 要联网（实测 20s+），默认关闭；可用环境变量显式打开。"""

    def test_slow_sources_are_off_by_default(self) -> None:
        from unittest.mock import patch

        from maccleaner.updates import _enabled_sources

        with patch.dict("os.environ", {}, clear=True):
            tools = [source["tool"] for source in _enabled_sources()]
        self.assertIn("brew", tools)
        self.assertIn("npm", tools)
        self.assertNotIn("pip3", tools)
        self.assertNotIn("gem", tools)

    def test_env_can_enable_them(self) -> None:
        from unittest.mock import patch

        from maccleaner.updates import _enabled_sources

        with patch.dict("os.environ", {"MACCLEANER_UPDATE_SOURCES": "brew,pip,gem"}, clear=True):
            tools = [source["tool"] for source in _enabled_sources()]
        self.assertIn("pip3", tools, "pip 是别名，要能选中 pip3")
        self.assertIn("gem", tools)
        self.assertNotIn("npm", tools)

class UpdatesCacheTests(unittest.TestCase):
    """更新检查缓存（2026-10-19）：命中要真省时间，强制要真重查。"""

    def _report(self):
        return {"items": [{"name": "aom", "manager": "brew", "kind": "formula"}], "count": 1, "notes": []}

    def test_second_call_hits_cache_and_reports_time(self) -> None:
        from unittest.mock import patch

        from maccleaner.updates import updates_report

        with tempfile.TemporaryDirectory(prefix="upd-cache-") as tmp:
            with patch("maccleaner.updates.discover_updates", return_value=self._report()) as spy:
                first = updates_report(state_root=Path(tmp))
                second = updates_report(state_root=Path(tmp))
        self.assertEqual(spy.call_count, 1, "第二次应命中缓存")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertGreater(second["checked_at"], 0, "要带回检查时间，页面才能标注")

    def test_force_bypasses_cache(self) -> None:
        from unittest.mock import patch

        from maccleaner.updates import updates_report

        with tempfile.TemporaryDirectory(prefix="upd-force-") as tmp:
            with patch("maccleaner.updates.discover_updates", return_value=self._report()) as spy:
                updates_report(state_root=Path(tmp))
                forced = updates_report(state_root=Path(tmp), force=True)
        self.assertEqual(spy.call_count, 2, "【重新检查】必须绕过缓存")
        self.assertFalse(forced["cached"])

    def test_tool_env_adds_tool_dirs_and_disables_brew_autoupdate(self) -> None:
        """npm 是 `#!/usr/bin/env node`：PATH 里没有 node 所在目录就跑不起来（实测 exit 127）。"""
        from maccleaner.updates import _tool_env

        env = _tool_env()
        self.assertEqual(env.get("HOMEBREW_NO_AUTO_UPDATE"), "1")
        self.assertIn(str(Path.home() / ".local" / "bin"), env["PATH"])

class AppStoreFallbackTests(unittest.TestCase):
    """App Store：代理诊断 + 不依赖 mas 联网的公开查询兜底（2026-10-19 实测驱动）。"""

    def test_parse_mas_list(self) -> None:
        from maccleaner.updates import parse_mas_list

        items = parse_mas_list(" 682658836  库乐队      (10.4.14)\n1247341465 同花顺      (5.3.5)")
        self.assertEqual([i["app_id"] for i in items], ["682658836", "1247341465"])
        self.assertEqual(items[0]["name"], "库乐队")
        self.assertEqual(items[0]["installed"], "10.4.14")

    def test_version_compare_handles_numbers(self) -> None:
        from maccleaner.updates import _version_tuple

        self.assertGreater(_version_tuple("12.4"), _version_tuple("11.2"))
        self.assertGreater(_version_tuple("5.10"), _version_tuple("5.9"))
        self.assertEqual(_version_tuple("1.0"), _version_tuple("1"))

    def test_proxy_hint_names_the_socks_proxy(self) -> None:
        """mas 连不上时的真凶常常是"系统代理开着但代理没运行"，提示里要写出地址。"""
        from unittest.mock import patch

        from maccleaner.updates import _proxy_hint

        fake = "SOCKSEnable : 1\nSOCKSPort : 7892\nSOCKSProxy : 127.0.0.1"
        with patch("maccleaner.updates._system_proxy_state",
                   return_value={"SOCKSEnable": "1", "SOCKSPort": "7892", "SOCKSProxy": "127.0.0.1"}):
            hint = _proxy_hint()
        self.assertIn("127.0.0.1:7892", hint)
        self.assertIn("连不上", hint)

    def test_lookup_fallback_lists_updates_without_mas_network(self) -> None:
        """mas 的 URLSession 走系统代理，代理坏了就整条断；公开查询能绕过它。"""
        import io
        import json as _json
        from unittest.mock import patch

        from maccleaner.updates import app_store_outdated_via_lookup

        def fake_run(argv, **kwargs):
            if "list" in argv:
                return 0, " 682658836  库乐队      (10.4.14)", ""
            return 0, "store ▁▁ CN", ""

        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class FakeOpener:
            def open(self, url, timeout=None):
                payload = {"results": [{"version": "10.4.16", "trackName": "库乐队"}]}
                return FakeResponse(_json.dumps(payload).encode())

        with patch("maccleaner.updates._run", side_effect=fake_run), \
                patch("urllib.request.build_opener", return_value=FakeOpener()):
            items = app_store_outdated_via_lookup()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["installed"], "10.4.14")
        self.assertEqual(items[0]["available"], "10.4.16")
        self.assertEqual(items[0]["source"], "itunes-lookup")

