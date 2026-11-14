"""SwiftUI 侧的源码契约测试（2026-11-13）。

SwiftUI 没有 XCTest target，CI 以前也不编译 Swift，结果界面接线断了没人拦得住。
这里不建 UI 测试工程，而是用**源码契约**守住最关键的三条线：
协议版本分支、慢命令进度事件、诊断区块的解析字段。CI 另跑 `swiftc -typecheck`
保证语法可编译（见 .github/workflows/ci.yml）。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "native" / "Sources"


def swift(name: str) -> str:
    return (SOURCES / name).read_text(encoding="utf-8")


class NativeContractTests(unittest.TestCase):
    def test_protocol_version_is_checked_on_terminal_message(self) -> None:
        """契约要求界面按 `v` 做分支，不能拿到新版本内核还按旧结构硬解。"""
        text = swift("CoreClient.swift")
        self.assertIn("supportedProtocolVersion", text)
        self.assertIn("protocol_mismatch", text)
        self.assertRegex(text, r'object\["v"\]\?\.intValue')

    def test_slow_command_progress_event_reaches_the_view(self) -> None:
        text = swift("SystemView.swift")
        self.assertIn("request(\"system.detail\")", text)
        self.assertIn(".mcDiagnosticProgress", text)
        self.assertIn("detailStage", text)
        self.assertIn("Notification.Name", swift("App.swift"))
        self.assertIn("mcDiagnosticProgress", swift("App.swift"))

    def test_system_page_labels_lifetime_cpu_and_offers_a_limit(self) -> None:
        """累计均值不能冒充瞬时值；进程条数必须可配。"""
        text = swift("SystemView.swift")
        self.assertIn("累计平均 CPU（ps %cpu）", text)
        self.assertIn("cpu_instant", text)
        self.assertIn('"limit": .int(processLimit)', text)
        self.assertIn("loadSystem()", text)

    def test_diagnostic_parse_keys_all_exist_in_kernel_payload(self) -> None:
        """Swift 解析用到的 key 必须在内核返回的字段集合里，否则界面会静默显示 —。"""
        body = swift("SystemView.swift").split("private static func parseDetail", 1)[1]
        keys = set(re.findall(r'\["([a-z_]+)"\]', body))
        payload = {
            "sampled_at", "sample_interval_ms", "cpu_idle_percent", "cpu_count",
            "processes", "limitations", "filevault", "load", "launchctl",
            "cpu_instant", "cpu_lifetime", "name", "rss", "volume", "count", "available",
            "memory", "disk", "hardware", "startup", "thermal", "power", "displays",
            "free_percentage", "swap_used_bytes", "compressor_pages", "pageins",
            "smart_status", "free", "snapshots", "chip", "cores", "os_version",
            "os_build", "model_name", "looks_like", "main", "resolution",
            "enabled_count", "run_at_load", "periodic", "boot_to_powerd_seconds",
            "boot_time", "speed_limit", "scheduler_limit", "design_mah", "full_mah",
            "volumes", "indexing",
        }
        self.assertTrue(keys, "没解析到任何 key，提取逻辑可能失效")
        missing = sorted(keys - payload)
        self.assertEqual(missing, [], f"Swift 读了内核没有的字段：{missing}")

    def test_unmeasured_items_are_never_rendered(self) -> None:
        """系统页不画「测不到的项目」，也不写「—」占位。

        数据层 `limitations[]` 仍保留给 agent（MCP/stdio），
        但界面按用户要求只显示真的测到的值，测不到的整块省略。
        """
        text = swift("SystemView.swift")
        self.assertNotIn("测不到的项目", text)
        self.assertNotIn("BTM 未测到", text)
        self.assertNotIn('?? "—"', text)
        self.assertNotIn('"limitations"', text, "界面不该再解析/渲染 limitations")
        self.assertIn("SystemSectionHeader", text, "相关内容要按格式塔分组")

    def test_both_cpu_metrics_share_one_section(self) -> None:
        """两种 CPU 口径必须挨在一起，用分段器切换，不许拆成两个长列表。"""
        text = swift("SystemView.swift")
        self.assertIn("processMetric", text)
        self.assertIn("processSection", text)
        self.assertIn("累计平均 CPU（ps %cpu）", text)
        self.assertIn("SystemProcessRow", text)
        self.assertNotIn("瞬时 CPU 占用最高的进程", text)

    def test_ci_compiles_swift_sources(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: macos-latest", ci)
        self.assertIn("swiftc", ci)
        self.assertIn("-typecheck", ci)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
