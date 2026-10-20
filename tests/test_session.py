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
            {"target_id": "home-caches", "name": "Home caches", "paths": ["~/Library/Caches/Demo"],
             "category": "cache", "estimated_bytes": 4096,
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

            self.assertEqual(driver.action("approval", {"approved_ids": ["home-caches"]}), 202)
            driver.wait_page('data-stage="confirming"')

            self.assertEqual(driver.action("confirm"), 202)
            complete = driver.wait_page('data-stage="complete"')
            self.assertIn("4.10 KB", complete, "完成页头条是可恢复字节")

            # 完成页是可交互的（打开废纸篓/再看一眼），会话不会立刻结束；
            # 这里发一个 cancel 等价"关窗"，终态必须仍是 complete。
            driver.action("cancel")

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
                {"target_id": "home-caches", "name": "Home caches", "paths": ["~/Library/Caches/Demo"],
                 "category": "cache", "estimated_bytes": 4096,
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
            # 行标题现在用 target 的 **name**（"Home caches"），副标题才是路径；
            # 勾选行是 `label.row opt`（不是 `div.row`），所以按勾选框计数。
            self.assertIn("Home caches", review)
            self.assertEqual(review.count('data-target-id="home-caches"'), 1, "应恰好一行候选")

            driver.action("cancel")
            result = driver.join()
            self.assertEqual(result["stage"], "cancelled", "出错不该落 failed，用户放弃才是 cancelled")

    def test_complete_page_open_trash_actually_opens(self) -> None:
        """完成页的【打开废纸篓】曾经是死按钮：白名单里有、会话不处理（2026-10-19 走查发现）。"""
        opened: list[int] = []
        with tempfile.TemporaryDirectory(prefix="session-trash-") as tmp:
            driver = _Driver(_deps(open_trash=lambda: opened.append(1)), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            self.assertEqual(driver.action("start"), 202)
            driver.wait_page('data-stage="review"')
            self.assertEqual(driver.action("approval", {"approved_ids": ["home-caches"]}), 202)
            driver.wait_page('data-stage="confirming"')
            self.assertEqual(driver.action("confirm"), 202)
            driver.wait_page('data-stage="complete"')

            self.assertEqual(driver.action("open-trash"), 202)
            deadline = time.time() + 5
            while time.time() < deadline and not opened:
                time.sleep(0.05)
            self.assertEqual(opened, [1], "点了就必须真的调用打开废纸篓")

            # 打开后仍停在完成页，且终态是 complete
            driver.wait_page('data-stage="complete"')
            driver.action("cancel")
            self.assertEqual(driver.join()["stage"], "complete")


    def test_uninstall_empty_selection_stays_on_preview_then_applies(self) -> None:
        """一个都不勾时必须**停在预览页**并提示，而不是冒充"卸载完成 0 项"。

        2026-10-19 真机 HTTP 验收撞到：空勾选会把会话推进到完成页，用户再勾选提交就没人接了
        （外层等的是 uninstall-plan）。这里钉住"拒绝 → 重等 → 再提交 → 成功"。
        """
        calls: list[list[str]] = []

        def apply(**kwargs):
            ids = list(kwargs.get("ids") or [])
            calls.append(ids)
            if not ids:
                return {"status": "refused", "reason": "nothing selected", "moved": [], "skipped": []}
            return {"status": "applied", "moved_count": 1, "moved": [], "skipped": []}

        # 会话线程可能仍在写 state/，清理临时目录会撞上 "Directory not empty"，所以忽略清理错误
        with tempfile.TemporaryDirectory(prefix="session-unin-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(uninstall_apply=apply), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("uninstall-list"), 202)
            driver.wait_page('data-stage="uninstall-list"')
            self.assertEqual(
                driver.action("uninstall-plan", {"bundle_id": "com.example.app", "path": "/Applications/Example.app"}),
                202,
            )
            driver.wait_page('data-stage="uninstall-preview"')

            self.assertEqual(driver.action("uninstall-apply", {"selected_ids": []}), 202)
            notice = driver.wait_page("至少选一项", timeout=5)
            self.assertIn('data-stage="uninstall-preview"', notice, "被拒绝后应留在预览页")

            self.assertEqual(driver.action("uninstall-apply", {"selected_ids": ["aaa"]}), 202)
            done = driver.wait_page('data-stage="uninstall-complete"', timeout=5)
            self.assertIn("卸载", done)
            self.assertEqual(calls, [[], ["aaa"]], "拒绝一次后必须还能再提交")

            driver.action("cancel")
            driver.join()

class UpdatesFlowTests(unittest.TestCase):
    """更新链路的接线（2026-10-19 补）：勾选 → 执行 → 结果页。

    此前完全没有会话级用例，于是"空勾选 = 全部升级 79 个包"这种问题没人拦。
    """

    def _items(self):
        return [
            {"name": "aom", "manager": "brew", "kind": "formula", "installed": "1", "available": "2"},
            {"name": "cmake", "manager": "brew", "kind": "formula", "installed": "3", "available": "4"},
        ]

    def test_apply_sends_only_the_ticked_ids(self) -> None:
        calls: list[list[str]] = []

        def apply(**kwargs):
            calls.append(list(kwargs.get("ids") or []))
            return {"status": "applied", "ok_count": 1, "total": 1,
                    "groups": [{"command": "brew upgrade aom", "exit_code": 0, "ok": True}]}

        with tempfile.TemporaryDirectory(prefix="session-upd-") as tmp:
            driver = _Driver(
                _deps(updates_check=lambda: {"items": self._items(), "count": 2, "notes": []}, updates_apply=apply),
                Path(tmp),
            )
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("updates-open"), 202)
            driver.wait_page("data-update-id=", timeout=10)
            self.assertEqual(driver.action("updates-apply", {"ids": ["1"]}), 202)
            result = driver.wait_page('data-stage="updates-result"', timeout=10)
            self.assertIn("brew upgrade aom", result)
            self.assertEqual(calls, [["1"]], "只能把勾选的那一项交出去")

            driver.action("cancel")
            driver.join()

    def test_empty_selection_refuses_instead_of_upgrading_everything(self) -> None:
        """一个都不勾 ≈ 升级全部 79 个包 —— 必须拦住（2026-10-19 复查发现）。"""
        calls: list[list[str]] = []

        def apply(**kwargs):
            calls.append(list(kwargs.get("ids") or []))
            return {"status": "applied", "ok_count": 0, "total": 0, "groups": []}

        with tempfile.TemporaryDirectory(prefix="session-upd0-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(
                _deps(updates_check=lambda: {"items": self._items(), "count": 2, "notes": []}, updates_apply=apply),
                Path(tmp),
            )
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("updates-open"), 202)
            driver.wait_page("data-update-id=", timeout=10)
            self.assertEqual(driver.action("updates-apply", {"ids": []}), 202)
            page = driver.wait_page("至少勾选一项", timeout=5)
            self.assertIn('data-stage="updates"', page, "被拒绝后应留在列表页")
            self.assertEqual(calls, [], "空勾选绝不能触发执行")

            driver.action("cancel")
            driver.join()



    def test_sidebar_home_returns_to_landing_without_scanning(self) -> None:
        """点侧栏"Mac 清理"只回落地页，**不能**触发扫描（2026-10-19 用户报的 bug）。"""
        scans = {"n": 0}

        def audit():
            scans["n"] += 1
            return {"mode": "audit", "plan_items": []}

        with tempfile.TemporaryDirectory(prefix="session-home-") as tmp:
            driver = _Driver(_deps(audit=audit), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            self.assertEqual(driver.action("home"), 202)
            page = driver.wait_page('data-stage="idle"', timeout=5)
            self.assertIn("开始扫描", page)
            self.assertEqual(scans["n"], 0, "切页签不该触发扫描")
            driver.action("cancel")
            driver.join()

    def test_approval_without_selection_stays_on_review(self) -> None:
        """默认不勾后，"一组都不勾就点开始清理"必须留在审阅页并提示。"""
        with tempfile.TemporaryDirectory(prefix="session-noSel-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("start")
            driver.wait_page('data-stage="review"')
            self.assertEqual(driver.action("approval", {"approved_ids": []}), 202)
            page = driver.wait_page("至少勾选一组", timeout=5)
            self.assertIn('data-stage="review"', page)
            driver.action("cancel")
            driver.join()



    def test_batch_uninstall_confirms_once_then_applies_each_app(self) -> None:
        """批量卸载：一页确认 → 逐个应用执行（2026-10-19 补的原生批量操作缺口）。"""
        applied: list[object] = []

        def plan(**kwargs):
            return {
                "app": {"name": kwargs.get("app_name", ""), "bundle_id": kwargs.get("bundle_id", "")},
                "items": [
                    {"id": "i1", "path": "/tmp/x", "kind": "caches", "confidence": "exact",
                     "allocated_bytes": 100},
                ],
                "system_items": [],
            }

        def apply(**kwargs):
            applied.append(kwargs.get("ids"))
            return {"status": "applied", "moved_count": 1, "moved": [], "skipped": []}

        with tempfile.TemporaryDirectory(prefix="session-batch-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(uninstall_plan=plan, uninstall_apply=apply), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("uninstall-list"), 202)
            driver.wait_page('data-stage="uninstall-list"')
            apps = [
                {"path": "/Applications/A.app", "bundle_id": "com.a", "name": "A"},
                {"path": "/Applications/B.app", "bundle_id": "com.b", "name": "B"},
            ]
            self.assertEqual(driver.action("uninstall-batch", {"apps": apps}), 202)
            confirm = driver.wait_page('data-stage="uninstall-batch-confirm"')
            self.assertIn("2 个应用", confirm)
            self.assertIn("2 项残留", confirm, "确认页要给出总项数")

            self.assertEqual(driver.action("uninstall-batch-apply"), 202)
            done = driver.wait_page('data-stage="uninstall-batch-done"')
            self.assertIn("已移入废纸篓", done)
            self.assertEqual(applied, [None, None], "两个应用各执行一次，且都是\"全部用户域\"")

            driver.action("cancel")
            driver.join()


    def test_reveal_only_accepts_paths_shown_on_the_current_page(self) -> None:
        """右键"在 Finder 中显示"必须受限：只允许本页出现过的路径（否则是任意路径后门）。"""
        revealed: list[str] = []
        with tempfile.TemporaryDirectory(prefix="session-reveal-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(reveal=revealed.append), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("start")
            driver.wait_page('data-stage="review"')

            # 页面上有的路径 → 允许
            self.assertEqual(driver.action("reveal", {"path": "~/Library/Caches/Demo"}), 202)
            # 页面上没有的路径 → 忽略
            self.assertEqual(driver.action("reveal", {"path": "/etc/passwd"}), 202)
            deadline = time.time() + 4
            while time.time() < deadline and not revealed:
                time.sleep(0.05)
            time.sleep(0.3)
            self.assertEqual(len(revealed), 1, f"只应打开页面上的那条，实际：{revealed}")
            self.assertIn("Caches/Demo", revealed[0])

            driver.action("cancel")
            driver.join()


    def test_disk_drill_down_walks_into_directory_and_back(self) -> None:
        """磁盘钻取：进入子目录 → 上一级；并且从磁盘页点侧栏能去系统页（不能被吞掉）。"""
        targets: list[str] = []

        def browse(target=None):
            targets.append(str(target or ""))
            return {
                "path": "/home/Downloads", "display": "~/Downloads", "parent": "/home",
                "total": 10,
                "entries": [{"name": "big", "path": "/home/Downloads/big", "bytes": 10, "is_dir": True}],
            }

        with tempfile.TemporaryDirectory(prefix="session-drill-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(disk_browse=browse), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("disk-open"), 202)
            driver.wait_page('data-stage="disk"', timeout=5)
            self.assertEqual(targets, [], "首次进磁盘只渲染总览，不该去钻目录")

            self.assertEqual(driver.action("disk-open", {"path": "/home/Downloads"}), 202)
            page = driver.wait_page("~/Downloads", timeout=5)
            self.assertIn("/home/Downloads", targets[-1])

            before = len(targets)
            self.assertEqual(driver.action("disk-back"), 202)
            driver.wait_page('data-stage="disk"', timeout=5)
            self.assertEqual(len(targets), before, "上一级回总览，不该再钻目录")

            # 关键回归：钻取页点侧栏"系统状态"必须真的切过去
            self.assertEqual(driver.action("system-open"), 202)
            driver.wait_page('data-stage="system"', timeout=5)

            driver.action("cancel")
            driver.join()


    def test_orphans_flow_scans_then_trashes_selected(self) -> None:
        """残留体检：进页 → 勾选 → 移入废纸篓；只允许页面出现过的路径。"""
        applied: list[list[str]] = []

        def scan():
            return {
                "items": [{"name": "com.gone.app", "path": "/home/Library/Caches/com.gone.app",
                           "bytes": 1024, "modified": "2026-09-01"}],
                "total": 1, "bytes": 1024, "installed": 12,
            }

        def apply_(paths):
            applied.append(list(paths))
            return {"moved": [{"path": paths[0], "bytes": 1024}], "failed": [], "count": 1, "bytes": 1024}

        with tempfile.TemporaryDirectory(prefix="session-orphans-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(orphans_scan=scan, orphans_apply=apply_), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            self.assertEqual(driver.action("orphans-open"), 202)
            page = driver.wait_page('data-stage="orphans"', timeout=5)
            self.assertIn("data-orphan-path", page)

            self.assertEqual(driver.action("orphans-apply", {"paths": ["/home/Library/Caches/com.gone.app"]}), 202)
            driver.wait_page("已移入废纸篓", timeout=5)
            self.assertEqual(applied, [["/home/Library/Caches/com.gone.app"]])

            driver.action("cancel")
            driver.join()

    def test_orphans_refuses_paths_that_were_not_on_the_page(self) -> None:
        """白名单：页面没出现过的路径，即使前端伪造也不执行。"""
        applied: list[list[str]] = []

        def scan():
            return {"items": [{"name": "com.visible.app", "path": "/home/Library/Caches/com.visible.app",
                               "bytes": 1, "modified": ""}], "total": 1, "bytes": 1, "installed": 1}

        def apply_(paths):
            applied.append(list(paths))
            return {"moved": [], "failed": [], "count": 0, "bytes": 0}

        with tempfile.TemporaryDirectory(prefix="session-orphans-guard-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(orphans_scan=scan, orphans_apply=apply_), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("orphans-open")
            driver.wait_page('data-stage="orphans"', timeout=5)
            driver.action("orphans-apply", {"paths": ["/home/Library/Caches/com.evil.app"]})
            page = driver.wait_page("先勾选要清理的项", timeout=5)
            self.assertIn('data-stage="orphans"', page)
            self.assertEqual(applied, [], "伪造路径必须被白名单拦下")
            driver.action("cancel")
            driver.join()


    def test_uninstall_cask_runs_brew_and_rejects_wrong_token(self) -> None:
        """cask 卸载：只接受计划里的 token；伪造的 token 不执行。"""
        calls: list[str] = []

        def plan(**kwargs):
            return {"app": {"path": "/Applications/Ollama.app", "name": "Ollama"},
                    "cask": "ollama-app", "items": [], "user_total_bytes": 0}

        def apply_cask(token):
            calls.append(token)
            return {"status": "ok", "token": token, "output": "Uninstalling ollama-app"}

        with tempfile.TemporaryDirectory(prefix="session-cask-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(uninstall_plan=plan, uninstall_cask=apply_cask), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            driver.action("uninstall-list")
            driver.wait_page('data-stage="uninstall-list"', timeout=5)
            driver.action("uninstall-plan", {"path": "/Applications/Ollama.app"})
            page = driver.wait_page('data-stage="uninstall-preview"', timeout=5)
            self.assertIn("uninstall-cask", page)

            # 伪造 token：必须被忽略，且不能执行
            driver.action("uninstall-cask", {"token": "evil-cask"})
            driver.wait_page("与当前计划不一致", timeout=5)
            self.assertEqual(calls, [], "伪造 token 不该执行 brew")

            driver.action("uninstall-cask", {"token": "ollama-app"})
            driver.wait_page("已用 Homebrew 卸载", timeout=5)
            self.assertEqual(calls, ["ollama-app"])

            driver.action("cancel")
            driver.join()


    def test_sparkle_update_is_verified_by_reading_version_back(self) -> None:
        """点【在应用内更新】后要能核对版本：变了→已更新，没变→提示它没自动检查。

        为什么不能"打开就当更新了"：Sparkle 更新是应用自己完成的，我们同步拿不到结果。
        """
        opened: list[str] = []
        versions = iter(["1.0", "2.0"])

        def updates_check():
            return {"items": [], "count": 0, "notes": [], "sparkle": [
                {"name": "Demo", "path": "/Applications/Demo.app", "version": "1.0",
                 "feed": "https://example.com/appcast.xml"}]}

        def app_version(_path):
            return next(versions, "2.0")

        with tempfile.TemporaryDirectory(prefix="session-sparkle-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(
                _deps(updates_check=updates_check, open_app=opened.append, app_version=app_version),
                Path(tmp),
            )
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            driver.action("updates-open")
            driver.wait_page('data-stage="updates"', timeout=5)
            driver.action("open-app", {"path": "/Applications/Demo.app"})
            page = driver.wait_page('data-stage="sparkle"', timeout=5)
            self.assertIn("已打开 Demo", page)
            self.assertEqual(opened, ["/Applications/Demo.app"])

            driver.action("sparkle-verify")
            page = driver.wait_page("已更新：1.0 → 2.0", timeout=5)
            self.assertIn("已更新", page)

            driver.action("cancel")
            driver.join()

    def test_sparkle_verify_reports_when_version_did_not_change(self) -> None:
        def updates_check():
            return {"items": [], "count": 0, "notes": [], "sparkle": [
                {"name": "Demo", "path": "/Applications/Demo.app", "version": "1.0", "feed": ""}]}

        with tempfile.TemporaryDirectory(prefix="session-sparkle-same-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(
                _deps(updates_check=updates_check, open_app=lambda _p: None, app_version=lambda _p: "1.0"),
                Path(tmp),
            )
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("updates-open")
            driver.wait_page('data-stage="updates"', timeout=5)
            driver.action("open-app", {"path": "/Applications/Demo.app"})
            driver.wait_page('data-stage="sparkle"', timeout=5)
            driver.action("sparkle-verify")
            page = driver.wait_page("版本没变", timeout=5)
            self.assertIn("检查更新", page, "要告诉用户去应用菜单里手动检查")
            driver.action("cancel")
            driver.join()


    def test_large_files_flow_trashes_selected_and_rejects_forged_paths(self) -> None:
        applied: list[list[str]] = []

        def scan():
            return {"items": [{"name": "big.bin", "path": "/home/Downloads/big.bin",
                               "bytes": 2 * 2**20, "modified": "2026-10-01"}],
                    "bytes": 2 * 2**20, "roots": ["~/Downloads"], "min_bytes": 1}

        def trash(paths):
            applied.append(list(paths))
            return {"moved": [{"path": paths[0], "bytes": 2 * 2**20}], "failed": [], "count": 1,
                    "bytes": 2 * 2**20}

        with tempfile.TemporaryDirectory(prefix="session-large-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(large_files=scan, trash_paths=trash), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')

            driver.action("large-open")
            page = driver.wait_page('data-stage="large"', timeout=5)
            self.assertIn("data-large-path", page)

            # 伪造路径必须被白名单拦下
            driver.action("large-apply", {"paths": ["/home/Downloads/evil.bin"]})
            driver.wait_page("先勾选要清理的文件", timeout=5)
            self.assertEqual(applied, [])

            driver.action("large-apply", {"paths": ["/home/Downloads/big.bin"]})
            driver.wait_page("已移入废纸篓", timeout=5)
            self.assertEqual(applied, [["/home/Downloads/big.bin"]])

            driver.action("cancel")
            driver.join()


    def test_back_from_confirmation_returns_to_review_with_selection(self) -> None:
        """确认页【返回修改】要真的回到审阅页，并保留刚才的勾选。

        之前实现是 `return None`：页面停在确认页不动，用户以为按钮坏了（2026-10-20 真机反馈）。
        """
        with tempfile.TemporaryDirectory(prefix="session-back-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("start")
            driver.wait_page('data-stage="review"')
            driver.action("approval", {"approved_ids": ["home-caches"]})
            driver.wait_page('data-stage="confirming"')

            driver.action("back")
            page = driver.wait_page('data-stage="review"', timeout=5)
            self.assertIn('data-target-id="home-caches" checked', page, "返回后要保留勾选")

            driver.action("cancel")
            driver.join()


    def test_risky_target_requires_selection_then_confirmation(self) -> None:
        """高风险项：审阅页勾选 → 确认页列出 → 勾"我确认"才作为 confirm 传给内核。"""
        calls: list[tuple[list[str], list[str]]] = []

        def audit():
            return {"mode": "audit", "plan_items": [
                {"target_id": "home-caches", "name": "Home caches", "paths": ["~/Library/Caches/Demo"],
                 "category": "cache", "estimated_bytes": 4096, "recoverable": True, "status": "planned"},
                {"target_id": "docker-prune", "name": "Docker prune", "paths": ["~/Library/Containers/com.docker.docker"],
                 "category": "docker", "estimated_bytes": 8192, "recoverable": False,
                 "requires_confirmation": True, "risk": "high", "status": "planned"},
            ]}

        def clean(approved, confirm):
            calls.append((list(approved), list(confirm)))
            return {"mode": "clean", "actual_reclaimed_bytes": 0, "plan_items": [], "receipt": {}}

        with tempfile.TemporaryDirectory(prefix="session-risky-", ignore_cleanup_errors=True) as tmp:
            driver = _Driver(_deps(audit=audit, clean_approved=clean), Path(tmp))
            driver.bootstrap()
            driver.wait_page('data-stage="idle"')
            driver.action("start")
            page = driver.wait_page('data-stage="review"')
            self.assertIn('data-target-id="docker-prune"', page, "高风险项必须可勾")

            driver.action("approval", {"approved_ids": ["home-caches", "docker-prune"]})
            page = driver.wait_page('data-stage="confirming"')
            self.assertIn("高风险项", page)
            self.assertIn("data-confirm-risk", page)

            driver.action("confirm", {"confirmed_risk": True})
            driver.wait_page('data-stage="complete"', timeout=20)
            self.assertEqual(calls, [(["home-caches", "docker-prune"], ["docker-prune"])])

            driver.action("cancel")
            driver.join()

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
            # 注意：先出的是**进度页**（stage 同样是 updates），要等列表独有的标记 `data-update-id`。
            page = driver.wait_page("data-update-id=")
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


class ShutdownStateTests(unittest.TestCase):
    """关闭会话时必须把状态收尾（2026-10-19 用户反馈"关闭后没关干净"）。"""

    def test_release_marks_stage_cancelled_and_inactive(self) -> None:
        import json

        from maccleaner.session import InteractiveSession, SessionDeps

        with tempfile.TemporaryDirectory(prefix="shutdown-") as tmp:
            session = InteractiveSession(
                SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {}),
                state_root=Path(tmp),
            )
            session.state.stage = "updates"      # 停在中间态
            session._write_state()
            session._release_lock()               # 相当于收到 SIGTERM 后的 finally

            payload = json.loads((Path(tmp) / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "cancelled", "退出时不能停在中间态")
            self.assertFalse(payload["active"], "退出后不得再声称会话活动")

