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


class SessionBusy(RuntimeError):
    """已有一个会话在跑（单会话锁）。"""


@dataclass
class SessionDeps:
    """会话要用的内核能力。默认真实实现，测试可整体替换（全部是零参/简单参的函数）。"""

    audit: Callable[[], dict[str, Any]]
    plan: Callable[[], dict[str, Any]]
    clean: Callable[[], dict[str, Any]]
    history: Callable[[], dict[str, Any]] = lambda: {}
    apps: Callable[[], list[dict[str, Any]]] = lambda: []
    uninstall_plan: Callable[..., dict[str, Any]] = lambda **_kwargs: {}
    uninstall_apply: Callable[..., dict[str, Any]] = lambda **_kwargs: {"status": "refused"}
    updates_check: Callable[[], dict[str, Any]] = lambda: {"items": [], "count": 0, "notes": []}
    updates_apply: Callable[..., dict[str, Any]] = lambda **_kwargs: {"status": "refused", "groups": []}


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

    def run(self, *, timeout: float | None = None) -> dict[str, Any]:
        """跑完整个会话，返回终态 dict（`stage` 为 complete / cancelled）。"""
        self._acquire_lock()
        try:
            self.bridge.start()
            self.state.url = self.bridge.bootstrap_url
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))

            while True:
                action = self.bridge.wait_for_action(
                    ("start", "cancel", "uninstall-list", "updates-open", "skills-open"),
                    timeout=timeout or self.IDLE_TIMEOUT_SECONDS,
                )
                if action is None:
                    return self._finish("cancelled", pages.render_cancelled_html({}))

                kind = action["action"]
                if kind == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))
                if kind == "skills-open":
                    self._serve("skills", pages.render_skills_html())
                    back = self.bridge.wait_for_action(
                        ("start", "cancel"), timeout=self.ACTION_TIMEOUT_SECONDS
                    )
                    # `cancel` 在任何页面都必须**结束会话**：只回落地页会让用户以为退出了、
                    # 而进程还挂着（用例里表现为"取消后 join 等不到结束"）。
                    if back is not None and back["action"] == "cancel":
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    continue
                if kind == "updates-open":
                    terminal = self._run_updates()
                    if terminal is not None:
                        return terminal
                    continue
                if kind == "uninstall-list":
                    terminal = self._run_uninstall()
                    if terminal is not None:
                        return terminal
                    continue

                outcome = self._run_cleanup(timeout)
                if outcome is not None:
                    return outcome
        finally:
            self._release_lock()

    # ---- 清理链路 ----

    def _run_cleanup(self, timeout: float | None) -> dict[str, Any] | None:
        try:
            self._serve("scanning", pages.render_progress_html())
            report = self.deps.audit()
            from .ui.adapter import review_payload

            payload = review_payload(report)
            self._serve("review", pages.render_review_html(payload))

            action = self.bridge.wait_for_action(
                ("approval", "rescan", "cancel"), timeout=timeout or self.ACTION_TIMEOUT_SECONDS
            )
            if action is None or action["action"] in {"cancel", "rescan"}:
                if action is not None and action["action"] == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))
                return None

            self._serve("confirming", pages.render_confirmation_html({
                "selected_count": payload.get("count", 0),
                "selected_bytes": payload.get("total_bytes", 0),
            }))
            decision = self.bridge.wait_for_action(
                ("confirm", "back", "cancel"), timeout=timeout or self.ACTION_TIMEOUT_SECONDS
            )
            if decision is None or decision["action"] == "cancel":
                return self._finish("cancelled", pages.render_cancelled_html({}))
            if decision["action"] == "back":
                return None

            self._serve("cleaning", pages.render_progress_html(
                {"title": "正在清理", "body": "正在清理", "message": "正在清理，请不要关闭窗口…",
                 "detail": "文件一律移入废纸篓，可从废纸篓恢复。"},
                stage="cleaning",
            ))
            cleaned = self.deps.clean()
            from .ui.adapter import completion_payload

            return self._finish("complete", pages.render_completion_html(completion_payload(cleaned)))
        except Exception as exc:  # noqa: BLE001 - 运行期任何异常都走"可重试"，不落 failed
            terminal = self._recover(exc, timeout)
            if terminal is not None:
                return terminal
            return self._run_cleanup(timeout)   # 重试 = 重跑这一段（不是回落地页）

    # ---- 卸载 ----

    def _run_uninstall(self) -> dict[str, Any] | None:
        try:
            apps = self._safe(self.deps.apps)
            self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
            while True:
                action = self.bridge.wait_for_action(
                    ("uninstall-plan", "uninstall-list", "cancel", "start"),
                    timeout=self.ACTION_TIMEOUT_SECONDS,
                )
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
                decision = self.bridge.wait_for_action(
                    ("uninstall-apply", "uninstall-back", "cancel"),
                    timeout=self.ACTION_TIMEOUT_SECONDS,
                )
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
                follow = self.bridge.wait_for_action(
                    ("uninstall-system", "uninstall-list", "cancel"), timeout=self.ACTION_TIMEOUT_SECONDS
                )
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
            found = self.deps.updates_check()
            self._serve("updates", pages.render_updates_list_html(found))
            action = self.bridge.wait_for_action(
                ("updates-apply", "updates-refresh", "cancel", "start"),
                timeout=self.ACTION_TIMEOUT_SECONDS,
            )
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
            follow = self.bridge.wait_for_action(
                ("updates-open", "start", "cancel"), timeout=self.ACTION_TIMEOUT_SECONDS
            )
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
    def _safe(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except Exception:  # noqa: BLE001 - 摘要类信息失败不该拖垮会话
            return {}


__all__ = ["ACTIVE_STAGES", "TERMINAL_STAGES", "InteractiveSession", "SessionBusy", "SessionDeps", "SessionState"]
