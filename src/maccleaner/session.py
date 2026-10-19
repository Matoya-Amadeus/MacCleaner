"""本地界面会话（2026-10-18 迁入）。

一个会话 = 一张页 + 一个进程 + 一把锁。职责只有三件事：

1. **按阶段发页**：落地页 → 审阅 → 确认 → 完成；侧栏可切到卸载 / 更新 / 技能；
2. **把用户动作变成内核调用**：动作只带 id/名字，路径永远不出现在请求里；
3. **出错可恢复**：任何阶段抛错都发"可以重试"页，**不落 failed**；用户放弃才是 cancelled。

为什么状态要落盘：切走再回来、以及在别的终端里 `--status` 时，都要看得见"会话在哪一阶段"。
为什么要有锁：两个实例同时对同一目录执行清理，是这个工具最危险的使用方式。
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .bridge import LoopbackBridge
from .ui import pages

try:  # 仅 macOS 有 fcntl；其它平台退化为"无锁但可用"（CI 上跑测试用）
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

ACTIVE_STAGES = frozenset({"idle", "scanning", "review", "confirming", "cleaning", "uninstalling",
                           "updates", "skills", "error"})
TERMINAL_STAGES = frozenset({"complete", "cancelled"})

# 侧栏在任何页面都可见 ⇒ 任何等待都必须能接住它们，否则用户在子流程里点侧栏会"没反应"
# （2026-10-18 真浏览器实测：点了更新页后再点卸载，队列里的动作没人取）。
NAV_ACTIONS: tuple[str, ...] = ("start", "uninstall-list", "updates-open", "skills-open")


class SessionBusy(RuntimeError):
    """已有一个会话在跑（单会话锁）。"""


@dataclass
class SessionDeps:
    """会话要用的内核能力。默认真实实现，测试可整体替换（全部是零参/简单参的函数）。"""

    audit: Callable[[], dict[str, Any]]
    plan: Callable[[], dict[str, Any]]
    clean: Callable[[], dict[str, Any]]
    # 带批准 id 的执行入口：界面点过的那批 target id。没有它只能走无参 `clean`（dry-run）。
    clean_approved: Callable[[list[str]], dict[str, Any]] | None = None
    # 打开废纸篓（完成页的按钮）。默认不做事，真实实现由 deps 注入。
    open_trash: Callable[[], None] | None = None
    history: Callable[[], dict[str, Any]] = lambda: {}
    apps: Callable[[], list[dict[str, Any]]] = lambda: []
    skills: Callable[[], list[dict[str, Any]]] = lambda: []
    uninstall_plan: Callable[..., dict[str, Any]] = lambda **_kwargs: {}
    uninstall_apply: Callable[..., dict[str, Any]] = lambda **_kwargs: {"status": "refused"}
    updates_check: Callable[[], dict[str, Any]] = lambda: {"items": [], "count": 0, "notes": []}
    updates_apply: Callable[..., dict[str, Any]] = lambda **_kwargs: {"status": "refused", "groups": []}
    # 扫描可能很慢（实测全盘 24.7s），所以有缓存；`rescan` 必须能**绕过缓存**强制重扫。
    rescan: Callable[[], dict[str, Any]] | None = None


@dataclass
class SessionState:
    session_id: str
    stage: str = "idle"
    active: bool = True
    owner_pid: int = 0
    url: str = ""
    error: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "stage": self.stage,
            "active": self.active,
            "owner_pid": self.owner_pid,
            "url": self.url,
            "error": self.error,
            "updated_at": self.updated_at,
        }


class InteractiveSession:
    """跑一张页，直到用户完成或离开。"""

    IDLE_TIMEOUT_SECONDS = 1800.0
    ACTION_TIMEOUT_SECONDS = 600.0

    def __init__(
        self,
        deps: SessionDeps,
        *,
        state_root: Path | None = None,
        bridge: LoopbackBridge | None = None,
    ) -> None:
        self.deps = deps
        self.state_root = Path(state_root) if state_root is not None else Path.home() / ".maccleaner" / "state"
        self.bridge = bridge or LoopbackBridge()
        self.state = SessionState(session_id=secrets.token_hex(8), owner_pid=os.getpid())
        self._lock_handle: Any = None

    # ---- 对外 ----

    def prepare(self) -> str:
        """拿锁 + 起桥，返回入口 URL。

        顺序很关键（2026-10-18 用户遇到"Could not connect"）：
        先拿锁再起桥，否则**第二个实例会先打印一个 URL**、随后因会话锁直接退出，
        调用方（原生外壳）拿着这个地址去连，只能得到"连接失败"——而真正的原因是"已有会话在运行"。
        """
        self._acquire_lock()
        self.bridge.start()
        self.state.url = self.bridge.bootstrap_url
        self._install_signal_handlers()
        self._watch_parent()
        return self.bridge.bootstrap_url

    def _install_signal_handlers(self) -> None:
        """SIGTERM/SIGINT 要能走 `finally`，否则状态文件会停留在 active=True。

        2026-10-19 实测：外壳 quit 时 `backend.terminate()` 发 SIGTERM，Python 默认直接死掉，
        既不写终态也不标记非活动——下一个读状态的地方（另一个实例、诊断命令）会以为会话还活着，
        表现就是"关闭 app 后功能没关干净"。
        """

        def _stop(_signum: int, _frame: Any) -> None:
            raise SystemExit(0)

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(sig, _stop)
            except (ValueError, OSError):   # 非主线程 / 平台不支持：忽略
                continue

    def _watch_parent(self) -> None:
        """父进程死了就退出（避免孤儿后端一直占着会话锁）。

        为什么要这个：外壳被 SIGTERM/强杀时跑不到 `applicationWillTerminate`，
        子进程会留下来；下次双击就撞上"已有会话在运行"，而用户看不到任何窗口。
        父进程变成 1（被 init 收养）就是孤儿信号。
        """
        expected = os.environ.get("MACCLEANER_PARENT_PID", "")
        if not expected.isdigit():
            return
        parent = int(expected)

        def _loop() -> None:
            while True:
                time.sleep(2.0)
                if os.getppid() != parent:
                    os._exit(0)

        threading.Thread(target=_loop, daemon=True, name="maccleaner-parent-watch").start()

    def run(self, *, timeout: float | None = None) -> dict[str, Any]:
        """跑完整个会话，返回终态 dict（`stage` 为 complete / cancelled）。"""
        if self._lock_handle is None:
            self._acquire_lock()
        try:
            self.bridge.start()
            self.state.url = self.bridge.bootstrap_url
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))

            pending: str | None = None
            while True:
                if pending is None:
                    action = self.bridge.wait_for_action(
                        ("start", "cancel", "uninstall-list", "updates-open", "skills-open"),
                        timeout=timeout or self.IDLE_TIMEOUT_SECONDS,
                    )
                    if action is None:
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    pending = action["action"]

                kind, pending = pending, None
                if kind == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))

                if kind == "skills-open":
                    self._serve("skills", pages.render_skills_html(
                        {"skills": self._safe(self.deps.skills, default=[])},
                    ))
                    back = self._wait_or_nav(("cancel",), self.ACTION_TIMEOUT_SECONDS)
                    # **先判 nav 再取 action**：`_wait_or_nav` 在用户点侧栏时返回 {"nav": …}，
                    # 没有 "action" 键——顺序写反会 KeyError 把会话打崩（2026-10-18 真机复现）。
                    if back is not None and "nav" in back:
                        pending = back["nav"]      # 从技能页直接切走，不必先回落地页
                        continue
                    if back is not None and back["action"] == "cancel":
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    continue

                if kind == "updates-open":
                    outcome = self._run_updates()
                elif kind == "uninstall-list":
                    outcome = self._run_uninstall()
                else:
                    outcome = self._run_cleanup(timeout)

                if isinstance(outcome, dict):
                    return outcome            # 终态（complete / cancelled）
                if isinstance(outcome, str):
                    pending = outcome         # 用户在子流程里点了别的侧栏入口
        finally:
            self._release_lock()

    # ---- 清理链路 ----

    def _run_cleanup(self, timeout: float | None) -> dict[str, Any] | None:
        try:
            from .ui.adapter import review_payload

            force = False
            while True:
                self._serve("scanning", pages.render_progress_html(
                    {"message": "重新扫描中…" if force else "正在扫描，请稍候…"}
                ))
                scanner = self.deps.rescan if (force and self.deps.rescan) else self.deps.audit
                report = scanner()
                payload = review_payload(report)
                self._serve("review", pages.render_review_html(payload))

                action = self._wait_or_nav(("approval", "rescan", "cancel"), timeout or self.ACTION_TIMEOUT_SECONDS)
                if action is not None and "nav" in action:
                    return None          # 用户切到别的入口，交回主循环
                if action is None:
                    return None
                if action["action"] == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))
                if action["action"] == "rescan":
                    force = True         # 用户点【重新扫描】→ 必须绕过缓存
                    continue
                break

            self._serve("confirming", pages.render_confirmation_html({
                "selected_count": payload.get("count", 0),
                "selected_bytes": payload.get("total_bytes", 0),
            }))
            decision = self._wait_or_nav(("confirm", "back", "cancel"), timeout or self.ACTION_TIMEOUT_SECONDS)
            if decision is not None and "nav" in decision:
                return None
            if decision is None or decision["action"] == "cancel":
                return self._finish("cancelled", pages.render_cancelled_html({}))
            if decision["action"] == "back":
                return None

            self._serve("cleaning", pages.render_progress_html(
                {"title": "正在清理", "body": "正在清理", "message": "正在清理，请不要关闭窗口…",
                 "detail": "文件一律移入废纸篓，可从废纸篓恢复。"},
                stage="cleaning",
            ))
            # 把"用户刚在审阅页看到的那些目标"作为批准清单交给内核；
            # 没有这份清单，内核会按 dry-run 处理并回一份空计划（页面却显示完成）。
            approved_ids = [
                str(candidate.get("target_id") or "")
                for candidate in (payload.get("candidates") or [])
                if str(candidate.get("target_id") or "")
            ]
            cleaned = (
                self.deps.clean_approved(approved_ids)
                if self.deps.clean_approved is not None
                else self.deps.clean()
            )
            from .ui.adapter import completion_payload

            done = completion_payload(cleaned)
            # 完成页**不能立刻结束会话**：否则【打开废纸篓】这个按钮点了没人接，
            # 白名单里有、界面上有，实际是死的（2026-10-19 真机走查发现）。
            while True:
                self._serve("complete", pages.render_completion_html(done))
                action = self._wait_or_nav(
                    ("open-trash", "rescan", "cancel"), timeout or self.ACTION_TIMEOUT_SECONDS
                )
                if action is None or "nav" in action or action["action"] == "cancel":
                    # 工作已经完成：此时关窗/取消**不该**把终态降级成 cancelled
                    # （用户清完了，只是把窗口关了）。
                    break
                if action["action"] == "rescan":
                    return None          # 回落地页重新开始
                self._open_trash()        # 打开后仍停在完成页
            return self._finish("complete", pages.render_completion_html(done))
        except Exception as exc:  # noqa: BLE001 - 运行期任何异常都走"可重试"，不落 failed
            terminal = self._recover(exc, timeout)
            if terminal is not None:
                return terminal
            return self._run_cleanup(timeout)   # 重试 = 重跑这一段（不是回落地页）


    def _open_trash(self) -> None:
        """打开废纸篓。测试可注入 `deps.open_trash` 记录调用，不打真实 Finder。"""
        opener = getattr(self.deps, "open_trash", None)
        if opener is None:
            return
        try:
            opener()
        except Exception:  # noqa: BLE001 - 打不开废纸篓不该把"已完成"变成"出错"
            return

    # ---- 卸载 ----

    def _run_uninstall(self) -> dict[str, Any] | None:
        try:
            self._serve("uninstalling", pages.render_progress_html(
                {"title": "软件卸载", "body": "正在读取应用列表", "message": "扫描 /Applications 与 ~/Applications…",
                 "detail": "只读目录，不会改动任何应用。", "nav": "uninstall"},
                stage="uninstalling",
            ))
            apps = self._safe(self.deps.apps, default=[])
            self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
            while True:
                action = self._wait_or_nav(("uninstall-plan", "uninstall-list", "cancel"), self.ACTION_TIMEOUT_SECONDS)
                if action is not None and "nav" in action:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return action["nav"]
                if action is not None and action["action"] == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))
                if action is None or action["action"] in {"start", "uninstall-list"}:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return None
                payload = dict(action.get("payload") or {})
                plan = self.deps.uninstall_plan(
                    app_path=str(payload.get("path", "")),
                    bundle_id=str(payload.get("bundle_id", "")),
                    app_name=str(payload.get("name", "")),
                )
                self._serve("uninstalling", pages.render_uninstall_preview_html(plan))
                decision = self._wait_or_nav(("uninstall-apply", "uninstall-back", "cancel"), self.ACTION_TIMEOUT_SECONDS)
                if decision is not None and "nav" in decision:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return decision["nav"]
                if decision is None or decision["action"] in {"cancel", "uninstall-back"}:
                    self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
                    continue
                selected = [str(value) for value in (decision.get("payload") or {}).get("selected_ids") or []]
                result = self.deps.uninstall_apply(plan=plan, ids=selected)
                remaining = self._remaining_for(plan)
                self._serve("uninstalling", pages.render_uninstall_complete_html({
                    "moved_count": int(result.get("moved_count", 0) or 0),
                    "remaining": remaining,
                }))
                follow = self._wait_or_nav(("uninstall-system", "uninstall-list", "cancel"), self.ACTION_TIMEOUT_SECONDS)
                if follow is not None and "nav" in follow:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return follow["nav"]
                if follow is not None and follow["action"] == "uninstall-system":
                    from .uninstall import apply_system_leftovers

                    apply_system_leftovers([item["path"] for item in (plan.get("system_items") or [])])
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return None
        except Exception as exc:  # noqa: BLE001
            terminal = self._recover(exc, None)
            if terminal is not None:
                return terminal
            return self._run_uninstall()

    def _remaining_for(self, plan: dict[str, Any]) -> dict[str, Any]:
        """卸载后重扫：**只有还剩系统级项**时才让界面显示管理员按钮。"""
        from .uninstall import discover_system_related_paths

        app = plan.get("app") or {}
        system_left = discover_system_related_paths(
            bundle_id=str(app.get("bundle_id", "") or ""), app_name=str(app.get("name", "") or "")
        )
        return {"system_count": len(system_left), "system_items": system_left}

    # ---- 更新 ----

    def _run_updates(self) -> dict[str, Any] | None:
        try:
            # 先发进度页：`brew outdated` 在包多时要几秒，期间什么都看不到等于"点了没反应"。
            self._serve("updates", pages.render_progress_html(
                {"title": "软件更新", "body": "正在检查更新", "message": "正在检查 Homebrew 与 App Store…",
                 "detail": "这一步只读，不会安装或升级任何东西。", "nav": "updates"},
                stage="updates",
            ))
            found = self.deps.updates_check()
            self._serve("updates", pages.render_updates_list_html(found))
            action = self._wait_or_nav(("updates-apply", "updates-refresh", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if action is not None and "nav" in action:
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return action["nav"]
            if action is not None and action["action"] == "cancel":
                return self._finish("cancelled", pages.render_cancelled_html({}))
            if action is None or action["action"] == "start":
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return None
            if action["action"] == "updates-refresh":
                found = self.deps.updates_check()
                self._serve("updates", pages.render_updates_list_html(found))
                return None
            ids = [str(value) for value in (action.get("payload") or {}).get("ids") or []]
            result = self.deps.updates_apply(ids=ids)
            self._serve("updates", pages.render_updates_result_html(result))
            follow = self._wait_or_nav(("updates-refresh", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if follow is not None and "nav" in follow:
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return follow["nav"]
            if follow is not None and follow["action"] == "cancel":
                return self._finish("cancelled", pages.render_cancelled_html({}))
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
            return None
        except Exception as exc:  # noqa: BLE001
            terminal = self._recover(exc, None)
            if terminal is not None:
                return terminal
            return self._run_updates()

    # ---- 公共 ----

    def _wait_or_nav(
        self, kinds: tuple[str, ...], timeout: float
    ) -> dict[str, Any] | None:
        """等指定动作，但**也接住侧栏导航**：返回 `{"nav": "<kind>"}` 表示用户切走了。"""
        action = self.bridge.wait_for_action(tuple(kinds) + NAV_ACTIONS, timeout=timeout)
        if action is None:
            return None
        if action["action"] in NAV_ACTIONS and action["action"] not in kinds:
            return {"nav": action["action"]}
        return action

    def _recover(self, exc: BaseException, timeout: float | None) -> dict[str, Any] | None:
        """出错：说明原因 + 可重试。

        返回值语义：`None` = 用户点了【重试】（调用方应**直接重跑刚才那一段**）；
        非 `None` = 会话终态（用户退出/超时 → cancelled）。

        为什么重试不回落地页：按钮写着"重试"，若只是退回落地页，用户得**再点一次**才开始，
        两次点击才等效一次重试——那是文案在骗人（2026-10-18 真机冒烟发现的）。
        """
        self._serve("error", pages.render_recovery_html({"detail": f"{type(exc).__name__}: {exc}"}))
        action = self.bridge.wait_for_action(("start", "cancel"), timeout=timeout or self.ACTION_TIMEOUT_SECONDS)
        if action is not None and action["action"] == "start":
            return None
        return self._finish("cancelled", pages.render_cancelled_html({}))

    def _serve(self, stage: str, page: str) -> None:
        self.state.stage = stage
        self.state.updated_at = time.time()
        self.bridge.set_page(page)
        self._write_state()

    def _finish(self, stage: str, page: str) -> dict[str, Any]:
        self.state.stage = stage
        self.state.active = False
        self.state.updated_at = time.time()
        self.bridge.set_page(page)
        self._write_state()
        self.bridge.wait_for_page(timeout=3.0)
        return self.state.to_dict()

    def _write_state(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        path = self.state_root / "session.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _acquire_lock(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        handle = (self.state_root / "session.lock").open("a+")
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise SessionBusy("已有一个会话在运行（单会话锁）") from exc
        self._lock_handle = handle

    def _release_lock(self) -> None:
        self.bridge.stop()
        self.state.active = False
        # 用户关掉窗口/退出时，把阶段收尾成 cancelled（而不是停在 idle/updates 之类的中间态）。
        if self.state.stage not in TERMINAL_STAGES:
            self.state.stage = "cancelled"
        try:
            self._write_state()
        except OSError:
            pass
        if self._lock_handle is not None:
            if fcntl is not None:
                try:
                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            self._lock_handle.close()
            self._lock_handle = None

    @staticmethod
    def _safe(call: Callable[[], Any], default: Any = None) -> Any:
        """装饰性信息读失败不该拖垮会话——但要返回**调用方期望的类型**。

        早先固定返回 `{}`：`apps()` 失败时列表页就变成"共 0 个应用"，
        看起来像功能没做，实际是错误被吞了（2026-10-19 排查到的）。
        """
        try:
            return call()
        except Exception:  # noqa: BLE001
            return {} if default is None else default


__all__ = ["ACTIVE_STAGES", "TERMINAL_STAGES", "InteractiveSession", "SessionBusy", "SessionDeps", "SessionState"]
