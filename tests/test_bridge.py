"""loopback 桥（2026-10-18 迁入）：真实 HTTP，不用 mock。

桥是"页面能不能点到程序"的唯一通道，所以这里逐条验安全口径：

- 只绑 loopback；一次性 bootstrap；双重凭据（cookie + 头）；动作白名单；
- 早发动作不丢；按类型筛选；页面关掉后在场判定过期。
"""
from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, build_opener

from maccleaner.bridge import LoopbackBridge


def _opener() -> urllib.request.OpenerDirector:
    # 显式禁用代理：本机若有 http_proxy，访问 127.0.0.1 会被它劫持。
    return build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))


def _get(opener, url: str) -> tuple[int, str]:
    try:
        with opener.open(url, timeout=5) as response:
            return response.status, response.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")


class LifecycleTests(unittest.TestCase):
    def test_refuses_non_loopback_hosts(self) -> None:
        with self.assertRaises(ValueError):
            LoopbackBridge(host="0.0.0.0")

    def test_bootstrap_is_single_use(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            status, _ = _get(opener, bridge.bootstrap_url)
            self.assertIn(status, (200, 302), "第一次 bootstrap 应成功")
            again = _get(_opener(), bridge.bootstrap_url)
            self.assertEqual(again[0], 410, "入口只能换一次 cookie")
        finally:
            bridge.stop()

    def test_wrong_secret_is_rejected(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            status, _ = _get(_opener(), f"http://{bridge.host}:{bridge.port}/bootstrap/not-the-secret")
            self.assertEqual(status, 403)
        finally:
            bridge.stop()


class PageTests(unittest.TestCase):
    def test_page_requires_the_session_cookie(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            self.assertEqual(_get(_opener(), f"http://{bridge.host}:{bridge.port}/")[0], 401)
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            status, body = _get(opener, f"http://{bridge.host}:{bridge.port}/")
            self.assertEqual(status, 200)
            self.assertIn("starting", body)
        finally:
            bridge.stop()

    def test_set_page_reaches_the_client_and_wait_for_page_returns(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            bridge.set_page('<html data-stage="idle">hi</html>')
            status, body = _get(opener, f"http://{bridge.host}:{bridge.port}/")
            self.assertEqual(status, 200)
            self.assertIn('data-stage="idle"', body)
            self.assertTrue(bridge.wait_for_page(timeout=5.0))
        finally:
            bridge.stop()


class ActionTests(unittest.TestCase):
    def _post(self, opener, bridge: LoopbackBridge, payload: dict, *, headers: dict | None = None):
        path = f"http://{bridge.host}:{bridge.port}/action"
        jar = next(handler.cookiejar for handler in opener.handlers if isinstance(handler, HTTPCookieProcessor))
        csrf = next((cookie.value for cookie in jar if cookie.name == "mc_csrf"), "")
        merged = {
            "Content-Type": "application/json",
            "X-MC-CSRF": csrf,
            "X-MC-Action": "1",
            "Origin": f"http://{bridge.host}:{bridge.port}",
        }
        if headers:
            merged.update(headers)
        request = urllib.request.Request(path, data=json.dumps(payload).encode(), headers=merged, method="POST")
        try:
            with opener.open(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_valid_action_is_accepted_and_queued(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self.assertEqual(self._post(opener, bridge, {"action": "start", "payload": {}}), 202)
            received = bridge.wait_for_action(("start",), timeout=2.0)
            self.assertIsNotNone(received)
            self.assertEqual(received["action"], "start")
        finally:
            bridge.stop()

    def test_missing_or_wrong_credentials_are_rejected(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self.assertEqual(self._post(opener, bridge, {"action": "start"}, headers={"X-MC-CSRF": "wrong"}), 403)
            self.assertEqual(self._post(opener, bridge, {"action": "start"}, headers={"X-MC-Action": ""}), 403)
            self.assertEqual(
                self._post(opener, bridge, {"action": "start"}, headers={"Origin": "http://evil.example"}), 403
            )
            self.assertEqual(_post_without_cookie(bridge, {"action": "start"}), 401)
        finally:
            bridge.stop()

    def test_unknown_action_is_rejected_by_the_whitelist(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self.assertEqual(self._post(opener, bridge, {"action": "rm-rf-everything"}), 400)
        finally:
            bridge.stop()

    def test_early_actions_are_not_lost(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self.assertEqual(self._post(opener, bridge, {"action": "approval", "payload": {"items": ["a"]}}), 202)
            received = bridge.wait_for_action(("approval",), timeout=2.0)
            self.assertEqual(received["payload"], {"items": ["a"]}, "按钮先被点、等待后发生，也不能丢")
        finally:
            bridge.stop()

    def test_wait_filters_by_kind_and_keeps_others_queued(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self._post(opener, bridge, {"action": "cancel"})
            self.assertIsNone(bridge.wait_for_action(("start",), timeout=0.3), "不是自己等的类型就别拿走")
            self.assertEqual(bridge.wait_for_action(("cancel",), timeout=1.0)["action"], "cancel")
        finally:
            bridge.stop()


class PresenceTests(unittest.TestCase):
    def test_presence_expires_after_the_page_is_closed(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self.assertFalse(bridge.presence_expired())
            _get(opener, f"http://{bridge.host}:{bridge.port}/closed")
            self.assertTrue(bridge.presence_expired(), "页面关掉后会话要能收尾，而不是一直挂着")
        finally:
            bridge.stop()

    def test_ready_heartbeat_keeps_presence_alive(self) -> None:
        bridge = LoopbackBridge()
        bridge.start()
        try:
            opener = _opener()
            _get(opener, bridge.bootstrap_url)
            self.assertEqual(_get(opener, f"http://{bridge.host}:{bridge.port}/ready")[0], 200)
            self.assertFalse(bridge.presence_expired())
        finally:
            bridge.stop()


def _post_without_cookie(bridge: LoopbackBridge, payload: dict) -> int:
    path = f"http://{bridge.host}:{bridge.port}/action"
    request = urllib.request.Request(
        path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-MC-CSRF": "x", "X-MC-Action": "1"},
        method="POST",
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


if __name__ == "__main__":
    unittest.main()
