"""卸载全链路的真机验收（2026-10-19）。

**不是 pytest 用例**（要起真实 loopback 桥 + 真实内核 + 真实文件操作），人工运行：

    python3 tests/acceptance_uninstall_smoke.py

它走的是用户点出来的同一条路：
    应用列表 → 点"卸载" → 残留预览 → 勾选 → 移入废纸篓

并且**只认文件系统的结果**：残留目录消失、$HOME/.Trash 里出现东西。
为什么必须这样：此前清理链路就栽在"页面到了完成、文件一个没动"，光看页面会重复那个错。
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

REPO = Path(__file__).resolve().parents[1]


def _make_home(root: Path) -> tuple[Path, Path, Path]:
    home = root / "home"
    app = home / "Applications" / "Demo.app" / "Contents"
    app.mkdir(parents=True)
    with (app / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {"CFBundleIdentifier": "com.demo.app", "CFBundleName": "Demo", "CFBundleShortVersionString": "1.0"},
            handle,
        )
    leftover = home / "Library" / "Caches" / "com.demo.app"
    leftover.mkdir(parents=True)
    (leftover / "big.bin").write_bytes(b"z" * 8192)
    os.utime(leftover / "big.bin", (1, 1))
    os.utime(leftover, (1, 1))
    return home, app.parent.parent, leftover


class Driver:
    def __init__(self, url: str) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.open(url, timeout=5).read()

    def csrf(self) -> str:
        for cookie in self.jar:
            if cookie.name == "mc_csrf":
                return cookie.value
        return ""

    def page(self) -> str:
        with self.opener.open("http://" + self.host + "/", timeout=5) as response:
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

    def wait_page(self, needle: str, timeout: float = 20.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.page()
            if needle in text:
                return text
            time.sleep(0.2)
        raise AssertionError(f"等不到页面标记：{needle}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="unin-e2e-") as tmp:
        root = Path(tmp)
        home, app, leftover = _make_home(root)
        deps = build_deps(home=home, root=home, state_root=root / "state")
        session = InteractiveSession(deps, state_root=root / "state")

        url = session.prepare()
        box: dict = {}

        def run() -> None:
            try:
                box["result"] = session.run(timeout=30)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        driver = Driver(url)
        driver.host = url.split("://", 1)[1].split("/", 1)[0]
        print(f"入口: {url[:56]}…")

        driver.wait_page('data-stage="idle"')
        print("① 落地页 ✓")

        assert driver.action("uninstall-list") == 202
        listing = driver.wait_page("data-stage=\"uninstall-list\"", timeout=10)
        rows = listing.count('class="row"')
        print(f"② 应用列表 ✓（行数={rows}）")

        status = driver.action("uninstall-plan", {"bundle_id": "com.demo.app", "path": str(app)})
        assert status == 202, f"uninstall-plan 被拒：HTTP {status}"
        preview = driver.wait_page("data-stage=\"uninstall-preview\"", timeout=15)
        ids = [
            chunk.split('"', 1)[0]
            for chunk in preview.split('data-item-id="')[1:]
        ]
        print(f"③ 残留预览 ✓（可勾选 {len(ids)} 项）")
        assert ids, "预览页没有任何可勾选项"

        # 先试"一个都不勾"：必须被拒绝，文件不能动。
        assert driver.action("uninstall-apply", {"selected_ids": []}) == 202
        time.sleep(1.5)
        assert leftover.exists(), "空勾选居然动了文件"

        status = driver.action("uninstall-apply", {"selected_ids": ids})
        print(f"   勾选 {ids} 后 apply → HTTP {status}")
        try:
            done = driver.wait_page("data-stage=\"uninstall-complete\"", timeout=20)
        except AssertionError:
            current = driver.page()
            stage = (current.split('data-stage="', 1)[1].split('"', 1)[0]) if 'data-stage="' in current else "?"
            print(f"   ⛔ 卡在 stage={stage}")
            print(f"   ⛔ 预览页提示: {'至少选一项' in current}")
            state = root / "state" / "session.json"
            if state.is_file():
                print("   ⛔ 状态文件:", state.read_text(encoding="utf-8")[:200])
            raise
        print("④ 卸载完成 ✓")

        trash = home / ".Trash"
        moved = len(list(trash.iterdir())) if trash.exists() else 0
        print(f"   残留目录还在吗: {leftover.exists()}（应为 False）")
        print(f"   废纸篓: {moved} 项（应 >0）")
        assert not leftover.exists(), "残留目录仍在：卸载没有真的发生"
        assert moved > 0, "废纸篓是空的：文件没有移进去"
        assert "已移入" in done or "废纸篓" in done, "完成页没有说明可恢复"

        driver.action("cancel")
        thread.join(timeout=10)
        print(f"⑤ 会话收尾 ✓（stage={(box.get('result') or {}).get('stage')}）")
        print("结论: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
