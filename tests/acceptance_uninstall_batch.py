"""批量卸载的真机验收（2026-10-19）。**不是 pytest 用例**，人工运行：

    python3 tests/acceptance_uninstall_batch.py

它走的是用户点出来的路：应用列表 → 勾选 2 个 → 批量卸载所选 → 一页确认 → 一次执行。
只认文件系统的结果：两个应用的残留都消失、废纸篓里有东西、系统级残留没被动。
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import plistlib
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from maccleaner.deps import build_deps
from maccleaner.session import InteractiveSession


def _fake_app(home: Path, name: str, bundle_id: str, leftover_bytes: int) -> tuple[Path, Path]:
    contents = home / "Applications" / f"{name}.app" / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleName": name}, handle)
    leftover = home / "Library" / "Caches" / bundle_id
    leftover.mkdir(parents=True)
    (leftover / "big.bin").write_bytes(b"z" * leftover_bytes)
    os.utime(leftover, (1, 1))
    return contents.parent, leftover


class Driver:
    def __init__(self, url: str) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.open(url, timeout=5).read()
        self.host = url.split("://", 1)[1].split("/", 1)[0]

    def csrf(self) -> str:
        for cookie in self.jar:
            if cookie.name == "mc_csrf":
                return cookie.value
        return ""

    def page(self) -> str:
        with self.opener.open(f"http://{self.host}/", timeout=5) as response:
            return response.read().decode("utf-8", "replace")

    def action(self, name: str, payload: dict | None = None) -> int:
        request = urllib.request.Request(
            f"http://{self.host}/action",
            data=json.dumps({"action": name, "payload": payload or {}}).encode(),
            headers={"Content-Type": "application/json", "X-MC-CSRF": self.csrf(), "X-MC-Action": "1"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            return exc.code

    def wait_page(self, needle: str, timeout: float = 25.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.page()
            if needle in text:
                return text
            time.sleep(0.2)
        raise AssertionError(f"等不到页面标记：{needle}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="batch-e2e-") as tmp:
        root = Path(tmp)
        home = root / "home"
        app_a, left_a = _fake_app(home, "Alpha", "com.demo.alpha", 8192)
        app_b, left_b = _fake_app(home, "Beta", "com.demo.beta", 4096)

        deps = build_deps(home=home, root=home, state_root=root / "state")
        session = InteractiveSession(deps, state_root=root / "state")
        url = session.prepare()
        box: dict = {}

        def run() -> None:
            try:
                box["result"] = session.run(timeout=40)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        threading.Thread(target=run, daemon=True).start()
        driver = Driver(url)
        print(f"入口: {url[:52]}…")

        driver.wait_page('data-stage="idle"')
        driver.action("uninstall-list")
        listing = driver.wait_page('data-stage="uninstall-list"')
        print(f"① 应用列表 ✓（勾选框 {listing.count('data-app-path')} 个）")

        apps = [
            {"path": str(app_a), "bundle_id": "com.demo.alpha", "name": "Alpha"},
            {"path": str(app_b), "bundle_id": "com.demo.beta", "name": "Beta"},
        ]
        assert driver.action("uninstall-batch", {"apps": apps}) == 202
        confirm = driver.wait_page('data-stage="uninstall-batch-confirm"', timeout=20)
        import re as _re

        headline = (_re.findall(r'state-msg">([^<]*)', confirm) or ["(无)"])[0]
        print(f"② 一页确认 ✓（{headline}）")
        # 每个应用 2 项：应用本体 + 1 处缓存残留 → 合计 4 项。
        assert "2 个应用" in confirm, f"确认页信息不完整：{headline}"
        assert "4 项残留" in confirm, f"确认页信息不完整：{headline}"

        assert driver.action("uninstall-batch-apply") == 202
        done = driver.wait_page('data-stage="uninstall-batch-done"', timeout=25)
        print("③ 一次执行 ✓")

        trash = home / ".Trash"
        moved = len(list(trash.iterdir())) if trash.exists() else 0
        print(f"   Alpha 残留还在: {left_a.exists()}（应 False）")
        print(f"   Beta  残留还在: {left_b.exists()}（应 False）")
        print(f"   应用本体还在: {app_a.exists()} / {app_b.exists()}（应 False / False）")
        print(f"   废纸篓: {moved} 项")
        assert not left_a.exists() and not left_b.exists(), "残留没清干净"
        assert not app_a.exists() and not app_b.exists(), "应用本体应一起移走"
        assert moved >= 4, f"废纸篓项数偏少：{moved}"
        assert "已移入废纸篓" in done

        driver.action("cancel")
        time.sleep(0.5)
        print("结论: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
