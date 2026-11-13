"""内核协议契约测试（M0，2026-10-22）。

只验协议本身：消息形状、事件顺序、错误码、安全闸（空数组拒绝）。
**不碰真机磁盘**：所有 deps 都是注入的假实现，跑得快且与机器状态无关。
"""

from __future__ import annotations

import io
import json
import time
import unittest

from maccleaner.core_service import PROTOCOL_VERSION, CoreService, serve_stdio
from maccleaner.deps import SessionDeps


def _deps(**overrides) -> SessionDeps:
    base = dict(
        audit=lambda: {"mode": "audit", "plan_items": [
            {"target_id": "home-caches", "name": "Home caches", "paths": ["~/Library/Caches/Demo"],
             "category": "cache", "estimated_bytes": 4096, "recoverable": True, "status": "planned"}]},
        plan=lambda: {"mode": "plan", "plan_items": []},
        clean=lambda: {"mode": "clean", "actual_reclaimed_bytes": 4096, "plan_items": []},
        disk=lambda: {"total": 1000, "used": 250, "free": 750, "percent": 25.0, "sections": []},
        system=lambda: {"load": [1.0, 1.0, 1.0], "cpu_count": 8},
        skills=lambda: [{"name": "mac-cleaner", "path": "/x/SKILL.md", "root": "~/skills"}],
        apps=lambda: [{"name": "Demo", "bundle_id": "com.demo", "path": "/Applications/Demo.app"}],
        uninstall_plan=lambda **kwargs: {"app": {"name": "Demo"}, "items": [
            {"id": "a", "path": "/Applications/Demo.app", "kind": "app-bundle",
             "confidence": "exact", "allocated_bytes": 10}], "user_total_bytes": 10},
        uninstall_apply=lambda **kwargs: {"status": "applied", "moved_count": 1},
        updates_check=lambda: {"items": [{"name": "aom"}], "sparkle": [], "notes": []},
        updates_apply=lambda **kwargs: {"status": "applied", "ok_count": 1},
        clean_approved=lambda approved, selected: {"status": "ok", "approved": list(approved)},
        system_sizes_cached=lambda: {"admin": False, "sizes": {}},
        system_sizes_admin=lambda: {"admin": True, "sizes": {"/Library/Logs": 100}},
        system_trash_paths=lambda paths: {"status": "ok", "moved": list(paths), "failed": []},
        orphans_scan=lambda: {"items": [{"id": "o1"}], "total": 1, "bytes": 10},
        orphans_apply=lambda ids: {"status": "ok", "moved": list(ids)},
    )
    base.update(overrides)
    return SessionDeps(**base)


def _service(**overrides) -> CoreService:
    return CoreService(_deps(**overrides))


def _final(messages: list[dict]) -> dict:
    assert messages, "没有消息"
    return messages[-1]


class EnvelopeTests(unittest.TestCase):
    def test_success_envelope_has_version_and_id(self) -> None:
        final = _final(_service().dispatch({"id": "7", "cmd": "ping"}))
        self.assertTrue(final["ok"])
        self.assertEqual(final["id"], "7")
        self.assertEqual(final["v"], PROTOCOL_VERSION)
        self.assertTrue(final["data"]["pong"])

    def test_unknown_command_lists_available_ones(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "delete.everything"}))
        self.assertFalse(final["ok"])
        self.assertEqual(final["error"]["code"], "unknown_command")
        self.assertIn("scan", final["error"]["hint"], "要告诉调用方有哪些命令")

    def test_missing_cmd_is_bad_request(self) -> None:
        final = _final(_service().dispatch({"id": "1"}))
        self.assertEqual(final["error"]["code"], "bad_request")

    def test_bad_json_line_reports_bad_json(self) -> None:
        lines = list(_service().serve_lines(["not json"]))
        payload = json.loads(lines[0])
        self.assertEqual(payload["error"]["code"], "bad_json")

    def test_blank_lines_are_ignored(self) -> None:
        self.assertEqual(list(_service().serve_lines(["", "   "])), [])

    def test_stdio_eof_waits_for_slow_command_terminal_message(self) -> None:
        """stdin 关闭后，慢命令的**终态**必须写完再退出。

        回归：原来 `thread.join(timeout=5)` 会把还在跑的 daemon 线程一起带走，
        调用方只收到 started 事件，没有结果（system.detail 实测 12.8s 必现）。
        """
        import threading

        from maccleaner.core_service import SHUTDOWN_WAIT_SECONDS

        released = threading.Event()

        def slow_detail() -> dict:
            released.set()
            time.sleep(0.3)
            return {"processes": [{"cpu_instant": 12.5}]}

        deps = _deps(system_detail=slow_detail)
        stdin = io.StringIO('{"id":"slow","cmd":"system.detail"}\n')
        stdout = io.StringIO()
        serve_stdio(deps, stdin=stdin, stdout=stdout)
        self.assertTrue(released.wait(timeout=1), "慢命令必须真的执行过")
        messages = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual([item.get("event") for item in messages], ["started", None])
        self.assertTrue(messages[-1]["ok"])
        self.assertEqual(messages[-1]["data"]["processes"][0]["cpu_instant"], 12.5)
        self.assertGreater(SHUTDOWN_WAIT_SECONDS, 5.0, "等待上限必须覆盖慢的只读诊断命令")


    def test_disk_summary_is_fast_and_permission_free(self) -> None:
        """`disk.summary` 只做 statfs：不读受保护目录，也不跑 du。

        为什么要这条：`disk` 会对 ~/Documents、~/Desktop 跑 du，没有「完全磁盘访问权限」时
        macOS 会连环弹授权框（真机撞到）。首屏必须有一个不需要权限的容量来源。
        """
        data = _final(_service().dispatch({"id": "1", "cmd": "disk.summary"}))["data"]
        self.assertGreater(data["total"], 0)
        self.assertLessEqual(data["percent"], 100.0)
        self.assertNotIn("sections", data, "summary 不该顺手扫目录")

class EventTests(unittest.TestCase):
    def test_slow_command_emits_started_before_result(self) -> None:
        """慢命令必须先发 started —— 界面靠它显示进度，不靠轮询。"""
        messages = _service().dispatch({"id": "1", "cmd": "uninstall.plan", "args": {"path": "/Applications/Demo.app"}})
        self.assertEqual(messages[0]["event"], "started")
        self.assertEqual(messages[0]["op"], "uninstall.plan")
        self.assertTrue(messages[-1]["ok"])
        self.assertEqual(len(messages), 2, "一个事件 + 一个终态")

    def test_fast_reads_do_not_emit_events(self) -> None:
        messages = _service().dispatch({"id": "1", "cmd": "disk"})
        self.assertEqual(len(messages), 1, "只读快命令不该有多余事件")
        self.assertIn("total", messages[0]["data"])

    def test_system_stays_fast_and_lifetime_based(self) -> None:
        """旧 `system` 不许被诊断命令带慢，也不许悄悄换成瞬时口径。"""
        messages = _service().dispatch({"id": "1", "cmd": "system"})
        self.assertEqual(len(messages), 1)
        self.assertIn("load", messages[0]["data"])

    def test_system_limit_only_changes_process_count(self) -> None:
        """`limit` 只改条数：不改字段语义，也不发事件。"""
        captured: dict[str, object] = {}

        def fake_system(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"load": [1.0, 1.0, 1.0], "processes": []}

        messages = _service(system=fake_system).dispatch(
            {"id": "1", "cmd": "system", "args": {"limit": 12}})
        self.assertEqual(captured, {"limit": 12})
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0]["ok"])

    def test_system_detail_emits_started_and_returns_new_fields(self) -> None:
        messages = _service(system_detail=lambda: {
            "sample_interval_ms": 1000,
            "processes": [{"pid": 1, "name": "demo", "cpu_instant": 42.0,
                           "cpu_lifetime": 9.0, "rss": 1024}],
        }).dispatch({"id": "1", "cmd": "system.detail"})
        self.assertEqual(len(messages), 2, "一个 started 事件 + 一个终态")
        self.assertEqual(messages[0]["event"], "started")
        self.assertEqual(messages[0]["op"], "system.detail")
        self.assertTrue(messages[-1]["ok"])
        data = messages[-1]["data"]
        self.assertEqual(data["sample_interval_ms"], 1000)
        self.assertEqual(data["processes"][0]["cpu_instant"], 42.0)

    def test_system_detail_btm_is_opt_in(self) -> None:
        """默认不碰会卡死的后台任务管理守护进程；显式请求才传 include_btm。"""
        captured: dict[str, object] = {}

        def fake_detail(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"processes": []}

        service = _service(system_detail=fake_detail)
        service.dispatch({"id": "1", "cmd": "system.detail"})
        self.assertEqual(captured, {}, "默认调用不许带 include_btm")
        service.dispatch({"id": "2", "cmd": "system.detail", "args": {"include_btm": True}})
        self.assertEqual(captured, {"include_btm": True})

    def test_disk_merges_cached_system_sizes(self) -> None:
        data = _final(_service().dispatch({"id": "1", "cmd": "disk"}))["data"]
        self.assertIn("system", data)
        self.assertFalse(data["system"]["admin"])


    def test_review_payload_returns_ready_groups(self) -> None:
        """界面不该自己分组：`review.payload` 直接给好 groups（规则在内核）。"""
        messages = _service().dispatch({"id": "1", "cmd": "review.payload"})
        self.assertEqual(messages[0]["event"], "started")
        data = messages[-1]["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual([group["key"] for group in data["groups"]], ["app"])
        self.assertEqual(data["groups"][0]["bytes"], 4096)

    def test_updates_list_splits_sparkle(self) -> None:
        def check():
            return {"items": [], "sparkle": [
                {"name": "Has", "update_available": True},
                {"name": "None", "update_available": False}], "notes": []}

        data = _final(_service(updates_check=check).dispatch({"id": "1", "cmd": "updates.list"}))["data"]
        self.assertEqual([item["name"] for item in data["sparkle_updates"]], ["Has"])
        self.assertEqual([item["name"] for item in data["sparkle_rest"]], ["None"])

    def test_apps_include_category_groups(self) -> None:
        apps = lambda: [
            {"name": "A", "category": "开发工具"},
            {"name": "B", "category": "浏览器"},
        ]
        data = _final(_service(apps=apps).dispatch({"id": "1", "cmd": "apps"}))["data"]
        self.assertEqual([group["label"] for group in data["groups"]], ["浏览器", "开发工具"])

class SafetyGateTests(unittest.TestCase):
    def test_clean_rejects_empty_approval(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "clean", "args": {"approved_ids": []}}))
        self.assertEqual(final["error"]["code"], "bad_args")
        self.assertIn("空勾选", final["error"]["message"])

    def test_uninstall_rejects_empty_items(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "uninstall.apply", "args": {"path": "/Applications/Demo.app"}}))
        self.assertEqual(final["error"]["code"], "bad_args")

    def test_uninstall_plan_requires_path(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "uninstall.plan"}))
        self.assertEqual(final["error"]["code"], "bad_args")

    def test_system_trash_requires_paths(self) -> None:
        final = _final(_service().dispatch({"id": "1", "cmd": "system.trash", "args": {"paths": []}}))
        self.assertEqual(final["error"]["code"], "bad_args")

    def test_internal_error_does_not_crash_service(self) -> None:
        def boom(**kwargs):
            raise RuntimeError("磁盘炸了")

        service = _service(uninstall_plan=boom)
        final = _final(service.dispatch({"id": "1", "cmd": "uninstall.plan", "args": {"path": "/x.app"}}))
        self.assertEqual(final["error"]["code"], "internal_error")
        self.assertIn("磁盘炸了", final["error"]["message"])
        # 出错之后服务还能继续用
        self.assertTrue(_final(service.dispatch({"id": "2", "cmd": "ping"}))["ok"])


class StdioTests(unittest.TestCase):
    def test_stdio_streams_messages_in_order(self) -> None:
        import io

        stdin = io.StringIO('{"id":"1","cmd":"disk"}\n{"id":"2","cmd":"nope"}\n')
        stdout = io.StringIO()
        serve_stdio(_deps(), stdin=stdin, stdout=stdout)
        payloads = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([p["id"] for p in payloads], ["1", "2"])
        self.assertTrue(payloads[0]["ok"])
        self.assertFalse(payloads[1]["ok"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
