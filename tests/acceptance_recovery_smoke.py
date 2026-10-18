"""真机"出错 → 恢复页 → 重试 → 走通"冒烟（2026-10-18）。

**故意不叫 `*_test.py`**：它起真实子进程与真桥，人工运行：

    python3 tests/acceptance_recovery_smoke.py

制造故障的方式真实且可瞬修：把 `--home` 先建成**一个文件**（内核会抛
`FileNotFoundError: root is not a directory`），看到恢复页后再把文件换成目录 → 点重试 → 应当走通。

它验的是我此前只敢说"在桩上验过"的那条路径：**失败不是终点**。
"""
from __future__ import annotations

import json
import os
import shutil
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
work = Path(tempfile.mkdtemp(prefix="recovery-smoke-"))
home = work / "home"          # 先当文件用（制造真实异常），之后换成目录
state = work / "state"
home.write_bytes(b"not a directory\n")

env = dict(os.environ)
env.update({"PYTHONPATH": str(REPO / "src"), "no_proxy": "*", "NO_PROXY": "*"})
proc = subprocess.Popen(
    [sys.executable, "-m", "maccleaner", "ui", "--no-open",
     "--home", str(home), "--root", str(home), "--state-root", str(state)],
    cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
)


def read_page(opener, url: str) -> str:
    with opener.open(url, timeout=10) as response:
        return response.read().decode("utf-8", "ignore")


def wait_stage(opener, url: str, stage: str, timeout: float = 25.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = read_page(opener, url)
        if f'data-stage="{stage}"' in last:
            return last
        time.sleep(0.2)
    raise AssertionError(f"等不到 stage={stage}；最后页面片段: {last[:200]!r}")


def click(opener, route: str, action: str) -> int:
    jar = next(h.cookiejar for h in opener.handlers if isinstance(h, HTTPCookieProcessor))
    csrf = next((cookie.value for cookie in jar if cookie.name == "mc_csrf"), "")
    parts = urlsplit(route)
    base = f"{parts.scheme}://{parts.netloc}"
    request = Request(
        f"{base}/action",
        data=json.dumps({"action": action, "payload": {}}).encode(),
        headers={"Content-Type": "application/json", "X-MC-CSRF": csrf, "X-MC-Action": "1", "Origin": base},
        method="POST",
    )
    with opener.open(request, timeout=10) as response:
        return response.status


try:
    deadline = time.time() + 30
    url = ""
    while time.time() < deadline and not url:
        line = proc.stdout.readline().strip()
        if line.startswith("http://"):
            url = line
        elif line == "" and proc.poll() is not None:
            break
    if not url:
        print("拿不到入口 URL:", (proc.stderr.read() or "")[-500:])
        raise SystemExit(1)
    print("入口 URL:", url)

    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    with opener.open(url, timeout=10) as response:
        route = response.geturl()
        landing = response.read().decode("utf-8", "ignore")
    print("① 落地页:", 'data-stage="idle"' in landing)

    print("② 点【开始扫描】（此时 home 是个文件，内核必然报错）→", click(opener, route, "start"))
    error_page = wait_stage(opener, route, "error")
    print("③ 恢复页出现:", "data-stage=\"error\"" in error_page,
          "| 写明未删除:", "没有删除任何东西" in error_page,
          "| 有重试按钮:", 'data-bridge-action="start"' in error_page)
    reason = "root is not a directory" in error_page
    print("   原因已展示:", reason)

    # ④ 把故障修掉（文件 → 目录，并放一个缓存），模拟"用户处理了问题"
    home.unlink()
    (home / "Library" / "Caches" / "Demo").mkdir(parents=True)
    (home / "Library" / "Caches" / "Demo" / "big.cache").write_bytes(b"z" * 8192)
    os.utime(home / "Library" / "Caches" / "Demo" / "big.cache", (1, 1))
    print("④ 故障已修复（home 变成目录 + 放入 1 个缓存）")

    print("⑤ 点【重试】→", click(opener, route, "start"))
    review = wait_stage(opener, route, "review")
    print("⑥ 走通了:", 'data-stage="review"' in review, "| 候选行数:", review.count('class="row"'))

    state_file = state / "session.json"
    if state_file.is_file():
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        print("状态文件: stage =", payload.get("stage"), "| active =", payload.get("active"))

    ok = all(('data-stage="error"' in error_page, "没有删除任何东西" in error_page, reason,
              'data-stage="review"' in review))
    print("结论:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)
finally:
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(work, ignore_errors=True)
