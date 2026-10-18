"""`maccleaner ui` 真机启动冒烟（2026-10-18）。

**故意不叫 `*_test.py`**：它会起真实子进程与真实 loopback 桥，按 pytest 收集会污染套件。
人工运行：

    python3 tests/acceptance_ui_smoke.py

它只做三件事：拿到入口 URL → 点【开始扫描】→ 看到审阅页；**不点批准、不点清理**。

起真实子进程（真桥、真内核、临时 home），只做三件事：拿到入口 URL → 点【开始扫描】→ 看到审阅页。
不点批准、不点清理——所以不会动任何文件。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
work = Path(tempfile.mkdtemp(prefix="ui-smoke-"))
home = work / "home"
cache = home / "Library" / "Caches" / "Demo" / "big.cache"
cache.parent.mkdir(parents=True)
cache.write_bytes(b"z" * 8192)
os.utime(cache, (1, 1))
state = work / "state"

env = dict(os.environ)
env.update({"PYTHONPATH": str(REPO / "src"), "no_proxy": "*", "NO_PROXY": "*"})
proc = subprocess.Popen(
    [sys.executable, "-m", "maccleaner", "ui", "--no-open",
     "--home", str(home), "--root", str(home), "--state-root", str(state)],
    cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
)
try:
    deadline = time.time() + 30
    url = ""
    while time.time() < deadline and not url:
        line = proc.stdout.readline().strip()
        if line.startswith("http://"):
            url = line
        elif line == "" and proc.poll() is not None:
            break
    print("入口 URL:", url or "(没拿到)")
    if not url:
        print("stderr:", (proc.stderr.read() or "")[-600:])
        raise SystemExit(1)

    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    with opener.open(url, timeout=5) as response:
        route = response.geturl()
        landing = response.read().decode("utf-8", "ignore")
    print("落地页:", 'data-stage="idle"' in landing, "| 侧栏入口:", landing.count('data-nav-action="'))

    jar = next(h.cookiejar for h in opener.handlers if isinstance(h, HTTPCookieProcessor))
    csrf = next((c.value for c in jar if c.name == "mc_csrf"), "")
    parts = urlsplit(route)
    base = f"{parts.scheme}://{parts.netloc}"
    request = Request(
        f"{base}/action",
        data=json.dumps({"action": "start", "payload": {}}).encode(),
        headers={"Content-Type": "application/json", "X-MC-CSRF": csrf, "X-MC-Action": "1", "Origin": base},
        method="POST",
    )
    with opener.open(request, timeout=5) as response:
        print("点【开始扫描】→", response.status)

    review = ""
    deadline = time.time() + 20
    while time.time() < deadline:
        with opener.open(route, timeout=5) as response:
            page = response.read().decode("utf-8", "ignore")
        if 'data-stage="review"' in page:
            review = page
            break
        time.sleep(0.2)
    print("审阅页:", bool(review), "| 有候选行:", ("Caches" in review) if review else False,
          "| 组数:", review.count('class="row"') if review else 0)
    # 状态文件在 `state/session.json`（本仓布局，不是 maho 那套 analysis/ 目录）。
    state_file = state / "session.json"
    if state_file.is_file():
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        print("状态文件: stage =", payload.get("stage"), "| active =", payload.get("active"))
    print("结论:", "PASS" if review else "FAIL")
    raise SystemExit(0 if review else 1)
finally:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
