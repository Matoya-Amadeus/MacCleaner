"""本地界面会话（2026-10-18 迁入）：真实 HTTP 驱动，内核用假实现。

为什么内核用假的：这里要验的是**阶段推进与动作处理**，不是清理逻辑（那有各自模块的用例）。
假实现让"整条链路"几秒跑完且完全确定；真机验收另做。
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import HTTPCookieProcessor, ProxyHandler, build_opener

from maccleaner.session import InteractiveSession, SessionBusy, SessionDeps


def _deps(**overrides) -> SessionDeps:
    base = dict(
        audit=lambda: {"mode": "audit", "plan_items": [
            {"paths": ["~/Library/Caches/Demo"], "category": "cache", "estimated_bytes": 4096,
             "recoverable": True, "status": "planned"}]},
        plan=lambda: {"mode": "plan", "plan_items": []},
        clean=lambda: {"mode": "clean", "actual_reclaimed_bytes": 0, "plan_items": [
            {"paths": ["~/Library/Caches/Demo"], "status": "cleaned", "recoverable": True,
             "actual_bytes": 4096}], "receipt": {"json": "/tmp/receipt.json"}},
        history=lambda: {"total_runs": 1, "total_freed_bytes": 4096},
        apps=lambda: [{"name": "Example", "bundle_id": "com.example.app", "path": "/Applications/Example.app"}],
        uninstall_plan=lambda **_kwargs: {"app": {"name": "Example"}, "items": [
            {"id": "aaa", "path": "/Applications/Example.app", "kind": "app-bundle", "confidence": "exact",
             "allocated_bytes": 10}], "user_total_bytes": 10, "system_items": []},
        uninstall_apply=lambda **_kwargs: {"status": "applied", "moved_count": 1, "moved": [], "skipped": []},
        updates_check=lambda: {"items": [{"name": "aom", "manager": "brew", "kind": "formula",
                                          "installed": "1", "available": "2"}], "count": 1, "notes": []},
        updates_apply=lambda **_kwargs: {"status": "applied", "ok_count": 1, "total": 1,
                                         "groups": [{"command": "brew upgrade aom", "exit_code": 0, "ok": True}]},
    )
    base.update(overrides)
    return SessionDeps(**base)


class _Driver:
    """管一个会话线程 + 一个带 cookie 的 HTTP 客户端。"""

    def __init__(self, deps: SessionDeps, tmp: Path) -> None:
        self.session = InteractiveSession(deps, state_root=tmp / "state")
        self.box: dict[str, object] = {}
        self.thread = threading.Thread(target=self._target, daemon=True)
        self.thread.start()
        self._wait_port()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.base = f"http://{self.session.bridge.host}:{self.session.bridge.port}"

    def _target(self) -> None:
        try:
            self.box["result"] = self.session.run(timeout=10)
        except BaseException as exc:  # noqa: BLE001 - 失败要在主线程里断言
            self.box["error"] = exc

    def _wait_port(self) -> None:
        for _ in range(300):
            if self.session.bridge.port:
                return
            time.sleep(0.02)
        raise AssertionError("bridge 没起来")

    def bootstrap(self) -> None:
        with self.opener.open(self.session.bridge.bootstrap_url, timeout=5) as response:
            response.read()

    def page(self) -> str:
        with self.opener.open(f"{self.base}/", timeout=5) as response:
            return response.read().decode("utf-8", "ignore")

    def wait_page(self, marker: str, timeout: float = 8.0) -> str:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            last = self.page()
            if marker in last:
                return last
            time.sleep(0.05)
        raise AssertionError(f"等不到 {marker!r}，最后页面片段: {last[:200]!r}")

    def action(self, name: str, payload: dict | None = None) -> int:
        jar = next(handler.cookiejar for handler in self.opener.handlers if isinstance(handler, HTTPCookieProcessor))
        csrf = next((cookie.value for cookie in jar if cookie.name == "mc_csrf"), "")
        request = urllib.request.Request(
            f"{self.base}/action",
            data=json.dumps({"action": name, "payload": payload or {}}).encode(),
            headers={"Content-Type": "application/json", "X-MC-CSRF": csrf, "X-MC-Action": "1",
                     "Origin": self.base},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def join(self, timeout: float = 10.0) -> dict:
        self.thread.join(timeout=timeout)
        if "error" in self.box:
            raise self.box["error"]  # type: ignore[misc]
        return self.box.get("result", {})  # type: ignore[return-value]


class CleanupFlowTests(unittest.TestCase):
    def test_start_to_complete(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-") as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("start"), 202)
            review = driver.wait_page('data-stage="review"')
            self.assertIn("Demo", review, "审阅页要列出候选")

            self.assertEqual(driver.action("approval"), 202)
            driver.wait_page('data-stage="confirming"')

            self.assertEqual(driver.action("confirm"), 202)
            complete = driver.wait_page('data-stage="complete"')
            self.assertIn("4.00 KiB", complete, "完成页头条是可恢复字节")

            result = driver.join()
            self.assertEqual(result["stage"], "complete")
            self.assertFalse(result["active"])
            state = json.loads((Path(tmp) / "state" / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(state["stage"], "complete")

    def test_cancel_from_landing_ends_as_cancelled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-cancel-") as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("cancel")
            driver.wait_page('data-stage="cancelled"')
            self.assertEqual(driver.join()["stage"], "cancelled")

    def test_error_shows_recovery_page_and_retry_reruns_the_step(self) -> None:
        """重试必须**重跑刚才那一段**，而不是退回落地页让用户再点一次。

        2026-10-18 真机冒烟发现：原来重试只回落地页，按钮写着"重试"却要两次点击才等效一次重试。
        """
        attempts = {"n": 0}

        def flaky() -> dict:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ValueError("scan exploded")
            return {"mode": "audit", "plan_items": [
                {"paths": ["~/Library/Caches/Demo"], "category": "cache", "estimated_bytes": 4096,
                 "recoverable": True, "status": "planned"}]}

        with tempfile.TemporaryDirectory(prefix="session-error-") as tmp:
            driver = _Driver(_deps(audit=flaky), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("start")
            error_page = driver.wait_page('data-stage="error"')
            self.assertIn("没有删除任何东西", error_page)
            self.assertEqual(attempts["n"], 1)

            driver.action("start")           # 重试 → 应直接重跑扫描
            review = driver.wait_page('data-stage="review"')
            self.assertEqual(attempts["n"], 2, "重试要真的重跑，而不是回到落地页等下一次点击")
            # 页面行显示的是**末级目录名**（这里是 Demo），不是完整路径——别拿路径去断言。
            self.assertIn("Demo", review)
            self.assertEqual(review.count('class="row"'), 1, "应恰好一行候选")

            driver.action("cancel")
            result = driver.join()
            self.assertEqual(result["stage"], "cancelled", "出错不该落 failed，用户放弃才是 cancelled")


class NavigationTests(unittest.TestCase):
    def test_uninstall_entry_lists_apps(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-unin-") as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            self.assertEqual(driver.action("uninstall-list"), 202)
            page = driver.wait_page('data-stage="uninstall-list"')
            self.assertIn("Example", page)
            driver.action("cancel")
            driver.join()

    def test_updates_entry_lists_packages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-upd-") as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            self.assertEqual(driver.action("updates-open"), 202)
            page = driver.wait_page('data-stage="updates"')
            self.assertIn("aom", page)
            self.assertIn("macOS 系统更新不在此列", page)
            driver.action("cancel")
            driver.join()

    def test_skills_entry_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-skills-") as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("skills-open")
            page = driver.wait_page('data-stage="skills"')
            self.assertIn("<details", page)
            driver.action("cancel")
            driver.join()


class LockTests(unittest.TestCase):
    def test_second_session_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="session-lock-") as tmp:
            first = _Driver(_deps(), Path(tmp))
            first.bootstrap()
            first.wait_page('data-stage="idle"')
            second = InteractiveSession(_deps(), state_root=Path(tmp) / "state")
            with self.assertRaises(SessionBusy):
                second.run(timeout=1)
            first.session.bridge.stop()
            first.join()


if __name__ == "__main__":
    unittest.main()
