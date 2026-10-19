"""本地界面与程序之间的 loopback 桥（2026-10-18 迁入）。

为什么要有桥：界面是浏览器里的一张页，而"批准/确认/取消"这类动作必须回到**同一个进程**里执行，
并且**不能让页面直接决定删什么**。桥只做三件事：发页、收动作、报在场。

安全口径（每条都对应一次真实事故或多年前的教训）：

1. **只听 127.0.0.1**：不绑 `0.0.0.0`，避免同网段的人连上来；
2. **一次性入口**：`/bootstrap/<secret>` 换 cookie 后立即作废，之后一律走 `/`；
   页面拿不到第二个入口，就不会出现"链接被转发给别人还能用"；
3. **双重凭据**：cookie（`mc_csrf`）+ 请求头（`X-MC-CSRF`）必须一致，且要求 `X-MC-Action` 头
   ——后者会强制跨域预检，普通表单无法伪造；
4. **动作白名单**：不在 `ACTIONS` 里的动作一律 400，桥不会替调用方"猜"；
5. **动作入队**：页面早发的动作不会丢（会话还在准备时就点了按钮，也能收到）；
6. **在场检测**：页面关掉后 `presence_expired()` 为真，会话据此收尾（而不是一直挂着）。
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

ACTIONS = frozenset(
    {
        "start",
        "cancel",
        "rescan",
        "approval",
        "confirm",
        "back",
        "open-trash",
        "uninstall-list",
        "uninstall-plan",     # 点某一行的"卸载" → 生成残留计划（2026-10-19 发现漏了，按钮会 400）
        "uninstall-back",
        "uninstall-apply",
        "uninstall-system",
        "updates-open",
        "updates-apply",
        "updates-refresh",
        "skills-open",
    }
)

PRESENCE_HEARTBEAT_SECONDS = 15.0
PRESENCE_TIMEOUT_SECONDS = 45.0


class LoopbackBridge:
    """一张页 + 一个动作队列 + 在场检测；线程安全，可被同一进程的会话反复使用。"""

    ACTIONS = ACTIONS
    PRESENCE_HEARTBEAT_SECONDS = PRESENCE_HEARTBEAT_SECONDS

    def __init__(self, *, host: str = "127.0.0.1") -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("bridge must listen on loopback only")
        self.host = host
        self._secret = secrets.token_urlsafe(24)
        self._csrf = secrets.token_urlsafe(18)
        self._page = "<!doctype html><title>starting</title>"
        self._actions: list[dict[str, Any]] = []
        self._condition = threading.Condition()
        self._last_seen = 0.0
        self._page_served = threading.Condition()
        self._bootstrap_used = False
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- 生命周期 ----

    @property
    def port(self) -> int:
        return int(self._server.server_address[1]) if self._server else 0

    @property
    def bootstrap_url(self) -> str:
        return f"http://{self.host}:{self.port}/bootstrap/{self._secret}"

    def start(self) -> None:
        if self._server is not None:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args, **_kwargs):  # noqa: ANN002, ANN003 - 静音
                return

            def _cookies(self) -> dict[str, str]:
                raw = self.headers.get("Cookie", "") or ""
                pairs = {}
                for chunk in raw.split(";"):
                    if "=" in chunk:
                        key, _, value = chunk.partition("=")
                        pairs[key.strip()] = value.strip()
                return pairs

            def _send(self, status: int, body: str, *, content_type: str = "text/html; charset=utf-8") -> None:
                payload = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):  # noqa: N802 - http.server 约定
                path = urlsplit(self.path).path
                if path.startswith("/bootstrap/"):
                    if bridge._bootstrap_used:
                        self._send(410, "bootstrap already used")
                        return
                    secret = path[len("/bootstrap/"):]
                    if not secrets.compare_digest(secret, bridge._secret):
                        self._send(403, "bad secret")
                        return
                    bridge._bootstrap_used = True
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", f"mc_session=1; Path=/; SameSite=Strict; HttpOnly")
                    self.send_header("Set-Cookie", f"mc_csrf={bridge._csrf}; Path=/; SameSite=Strict")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if path == "/ready":
                    bridge._touch()
                    self._send(200, "ok", content_type="text/plain")
                    return
                if path == "/closed":
                    bridge._last_seen = 0.0
                    self._send(200, "ok", content_type="text/plain")
                    return
                if path == "/":
                    if self._cookies().get("mc_session") != "1":
                        self._send(401, "no session")
                        return
                    bridge._touch()
                    with bridge._page_served:
                        page = bridge._page
                        bridge._page_served.notify_all()
                    self._send(200, page)
                    return
                self._send(404, "not found")

            def do_POST(self):  # noqa: N802 - http.server 约定
                if urlsplit(self.path).path != "/action":
                    self._send(404, "not found")
                    return
                cookies = self._cookies()
                if cookies.get("mc_session") != "1":
                    self._send(401, "no session")
                    return
                if not secrets.compare_digest(cookies.get("mc_csrf", ""), bridge._csrf):
                    self._send(403, "bad csrf cookie")
                    return
                if not secrets.compare_digest(self.headers.get("X-MC-CSRF", ""), bridge._csrf):
                    self._send(403, "bad csrf header")
                    return
                if self.headers.get("X-MC-Action", "") != "1":
                    self._send(403, "missing action header")
                    return
                origin = self.headers.get("Origin", "")
                if origin and urlsplit(origin).netloc != f"{bridge.host}:{bridge.port}":
                    self._send(403, "bad origin")
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0 or length > 65536:
                    self._send(400, "bad length")
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._send(400, "bad json")
                    return
                if not isinstance(payload, dict) or str(payload.get("action", "")) not in bridge.ACTIONS:
                    self._send(400, "unknown action")
                    return
                bridge._enqueue(str(payload["action"]), payload.get("payload") or {})
                bridge._touch()
                self._send(202, json.dumps({"accepted": True}), content_type="application/json")

        self._server = ThreadingHTTPServer((self.host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="maccleaner-bridge")
        self._thread.start()
        self._touch()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---- 页面与动作 ----

    def set_page(self, page: str) -> None:
        with self._page_served:
            self._page = str(page)
            self._page_served.notify_all()

    def wait_for_page(self, timeout: float = 10.0) -> bool:
        """等页面被真的取走一次（否则失败页/终页永远送不到用户眼前）。"""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._page_served:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._page_served.wait(min(remaining, 0.2))
                if self._last_seen > 0:
                    return True

    def _enqueue(self, action: str, payload: dict[str, Any]) -> None:
        with self._condition:
            self._actions.append({"action": action, "payload": payload})
            self._condition.notify_all()

    def wait_for_action(self, kinds: tuple[str, ...], timeout: float = 60.0) -> dict[str, Any] | None:
        """等一个指定类型的动作；**早发的动作不会丢**（入队后按类型筛选）。"""
        allowed = tuple(kinds)
        if not allowed:
            raise ValueError("allowed actions must not be empty")
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                for index, item in enumerate(self._actions):
                    if item["action"] in allowed:
                        return self._actions.pop(index)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(min(remaining, 0.2))

    def _touch(self) -> None:
        self._last_seen = time.monotonic()

    def presence_expired(self, *, timeout: float = PRESENCE_TIMEOUT_SECONDS) -> bool:
        return self._last_seen <= 0 or (time.monotonic() - self._last_seen) > timeout


__all__ = ["ACTIONS", "LoopbackBridge", "PRESENCE_HEARTBEAT_SECONDS", "PRESENCE_TIMEOUT_SECONDS"]
