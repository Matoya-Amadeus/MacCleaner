"""本地界面会话（2026-10-18 迁入）。

一个会话 = 一张页 + 一个进程 + 一把锁。职责只有三件事：

1. **按阶段发页**：落地页 → 审阅 → 确认 → 完成；侧栏可切到卸载 / 更新 / 技能；
2. **把用户动作变成内核调用**：动作只带 id/名字，路径永远不出现在请求里；
3. **出错可恢复**：任何阶段抛错都发"可以重试"页，**不落 failed**；用户放弃才是 cancelled。

为什么状态要落盘：切走再回来、以及在别的终端里 `--status` 时，都要看得见"会话在哪一阶段"。
为什么要有锁：两个实例同时对同一目录执行清理，是这个工具最危险的使用方式。
"""
from __future__ import annotations

import html
import json
import os
import re
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

# 页面上标记"这个路径可以 reveal"的属性（右键菜单 / 在 Finder 中显示）。
REVEAL_PATH = re.compile(r'data-reveal-path="([^"]+)"')

# 侧栏在任何页面都可见 ⇒ 任何等待都必须能接住它们，否则用户在子流程里点侧栏会"没反应"
# （2026-10-18 真浏览器实测：点了更新页后再点卸载，队列里的动作没人取）。
NAV_ACTIONS: tuple[str, ...] = (
    "home", "uninstall-list", "updates-open", "orphans-open", "skills-open",
    "disk-open", "large-open", "system-open",
)


class SessionBusy(RuntimeError):
    """已有一个会话在跑（单会话锁）。"""


@dataclass
class SessionDeps:
    """会话要用的内核能力。默认真实实现，测试可整体替换（全部是零参/简单参的函数）。"""

    audit: Callable[[], dict[str, Any]]
    plan: Callable[[], dict[str, Any]]
    clean: Callable[[], dict[str, Any]]
    # 带批准 id 的执行入口：界面点过的那批 target id。没有它只能走无参 `clean`（dry-run）。
    clean_approved: Callable[[list[str], list[str]], dict[str, Any]] | None = None
    # 打开废纸篓（完成页的按钮）。默认不做事，真实实现由 deps 注入。
    open_trash: Callable[[], None] | None = None
    # 在 Finder 中显示（右键菜单）。会话负责白名单校验。
    reveal: Callable[[str], None] | None = None
    # 打开 App Store 更新页（mas 不可用时的合法兜底）。
    open_app_store: Callable[[], None] | None = None
    # 打开某个应用，让它的 Sparkle 更新器自己工作。
    open_app: Callable[[str], None] | None = None
    # 自带 Sparkle 更新器的应用列表（随更新结果一起渲染）。
    sparkle_apps: Callable[[], list[dict[str, Any]]] = lambda: []
    # 孤儿残留体检：扫描与清理（清理只允许页面出现过的路径）。
    orphans_scan: Callable[[], dict[str, Any]] | None = None
    orphans_apply: Callable[[list[str]], dict[str, Any]] | None = None
    # 用 Homebrew 卸载 cask（只在预览页显式点击时调用）。
    uninstall_cask: Callable[[str], dict[str, Any]] | None = None
    # 读某个 .app 的版本号（判断 Sparkle 是否真的更新了）。
    app_version: Callable[[str], str] | None = None
    # 已安装浏览器的图标（data URI），给"浏览器缓存"那一行配真实图标。
    browser_icons: Callable[[], dict[str, str]] | None = None
    # 批量取应用图标（卸载列表 / Sparkle 行）。
    app_icons: Callable[[list[str]], dict[str, str]] | None = None
    # 大文件视图：扫描 + 移入废纸篓。
    large_files: Callable[[], dict[str, Any]] | None = None
    trash_paths: Callable[[list[str]], dict[str, Any]] | None = None
    # 系统级目录体积：只测量（第二次可走一次性授权）。
    system_sizes: Callable[[], dict[str, Any]] | None = None
    # 只读缓存（页面加载用）：不发 du、不弹授权。
    system_sizes_cached: Callable[[], dict[str, Any]] | None = None
    system_sizes_admin: Callable[[], dict[str, Any]] | None = None
    # 只读的"看一眼"页面（磁盘/系统）。
    disk: Callable[[], dict[str, Any]] = lambda: {}
    # 磁盘钻取：传目录路径，返回下一级条目。
    disk_browse: Callable[..., dict[str, Any]] | None = None
    system: Callable[[], dict[str, Any]] = lambda: {}
    # 清理历史（读回执文件）。
    history: Callable[[], dict[str, Any]] = lambda: {}
    apps: Callable[[], list[dict[str, Any]]] = lambda: []
    skills: Callable[[], list[dict[str, Any]]] = lambda: []
    uninstall_plan: Callable[..., dict[str, Any]] = lambda **_kwargs: {}
    uninstall_apply: Callable[..., dict[str, Any]] = lambda **_kwargs: {"status": "refused"}
    updates_check: Callable[[], dict[str, Any]] = lambda: {"items": [], "count": 0, "notes": []}
    updates_apply: Callable[..., dict[str, Any]] = lambda **_kwargs: {"status": "refused", "groups": []}
    # 强制重查（绕过 120s 缓存）；不传就退回 updates_check。
    updates_refresh: Callable[[], dict[str, Any]] | None = None
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


def _log_reveal(message: str) -> None:
    """把 reveal 结果写进日志 —— 否则"点了没反应"永远查不到原因。"""
    try:
        log_dir = Path.home() / "Library" / "Logs" / "MacCleaner"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with (log_dir / "reveal.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


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
            pending_payload: dict[str, Any] = {}
            self._review_state: dict[str, Any] | None = None
            while True:
                if pending is None:
                    action = self.bridge.wait_for_action(
                        ("start", "home", "cancel", "uninstall-list", "updates-open", "skills-open",
                         "disk-open", "large-open", "system-open", "orphans-open"),
                        timeout=timeout or self.IDLE_TIMEOUT_SECONDS,
                    )
                    if action is None:
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    pending = action["action"]
                    pending_payload = dict(action.get("payload") or {})

                kind, pending = pending, None
                payload_now, pending_payload = pending_payload, {}
                if kind == "home":
                    # 有上次的审阅结果就**回到那一屏**（"上次从什么状态走，就回到什么状态"）；
                    # 否则回落地页。扫描必须由按钮发起，这里不会偷偷重扫。
                    if self._review_state:
                        outcome = self._run_cleanup(timeout, resume=True)
                        if isinstance(outcome, dict):
                            return outcome
                        if isinstance(outcome, str):
                            pending = outcome
                        continue
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    continue
                if kind == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))

                if kind == "large-open":
                    outcome = self._run_large_files()
                    if outcome:
                        pending = outcome
                    continue
                if kind == "orphans-open":
                    # 点侧栏要交回主循环处理（否则会停在孤儿页，用户以为点不动）。
                    outcome = self._run_orphans()
                    if outcome:
                        pending = outcome
                    continue

                if kind == "disk-open":
                    # 钻取：进入目录后可以继续进入 / 上一级 / 回总览，全程只读。
                    # 这里点侧栏要**交回主循环**（否则会停在落地页，用户以为没反应）。
                    outcome = self._run_disk()
                    if outcome:
                        pending = outcome
                    continue

                if kind == "system-open":
                    self._serve("system", pages.render_system_html(self._safe(self.deps.system, default={})))
                    back = self._wait_or_nav(("cancel",), self.ACTION_TIMEOUT_SECONDS)
                    if back is not None and "nav" in back:
                        pending = back["nav"]
                        continue
                    if back is not None and back["action"] == "cancel":
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    continue

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

    def _attach_icons(self, items: list[dict[str, Any]]) -> None:
        """给带 `path` 的行补 `icon`（取不到就不补，页面退回内置 SVG）。"""
        reader = getattr(self.deps, "app_icons", None)
        if reader is None:
            return
        paths = [str(item.get("path") or "") for item in items if str(item.get("path") or "")]
        if not paths:
            return
        icons = self._safe(lambda: reader(paths), default={}) or {}
        for item in items:
            uri = icons.get(str(item.get("path") or ""))
            if uri:
                item["icon"] = uri

    # ---- 清理链路 ----

    def _run_cleanup(
        self, timeout: float | None, *, resume: bool = False
    ) -> dict[str, Any] | str | None:
        try:
            from .ui.adapter import review_payload

            force = False
            payload: dict[str, Any] | None = None
            if resume:
                payload = (self._review_state or {}).get("payload")
            while True:
                if payload is None:
                    self._serve("scanning", pages.render_progress_html(
                        {"message": "重新扫描中…" if force else "正在扫描，请稍候…"}
                    ))
                    scanner = self.deps.rescan if (force and self.deps.rescan) else self.deps.audit
                    report = scanner()
                    payload = review_payload(report)
                    # 记住这一屏：用户切到别的入口再点「Mac 清理」时，回到同一份结果。
                    self._review_state = {"payload": payload}
                notice = ""
                selected: list[dict[str, Any]] = []
                preselected: list[str] = []
                risky: list[dict[str, Any]] = []
                while True:
                    reader = getattr(self.deps, "system_sizes_cached", None)
                    if reader is not None:
                        payload["system"] = self._safe(reader, default={})
                    # 浏览器缓存那几行配真实图标（读本机 .icns，不引第三方素材）。
                    icons_reader = getattr(self.deps, "browser_icons", None)
                    if icons_reader is not None:
                        icons = self._safe(icons_reader, default={}) or {}
                        for candidate in payload.get("candidates") or []:
                            if str(candidate.get("target_id")) == "browser-caches":
                                candidate["icons"] = list(icons.values())
                    self._serve("review", pages.render_review_html(
                        payload, notice=notice, preselected=preselected,
                    ))
                    action = self._wait_or_nav(
                        ("approval", "rescan", "cancel"), timeout or self.ACTION_TIMEOUT_SECONDS
                    )
                    if action is not None and "nav" in action:
                        target = str(action["nav"])
                        if target == "home":
                            # 审阅页【返回】= 退出这次清理流程，下次进来重新扫。
                            self._review_state = None
                        return target
                    if action is None:
                        return None
                    if action["action"] == "cancel":
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    if action["action"] == "rescan":
                        force = True         # 用户点【重新扫描】→ 必须绕过缓存
                        payload = None
                        break
                    # 只认用户在页面上勾选的那几组：全不勾不等于全部。
                    chosen = {
                        str(value) for value in (action.get("payload") or {}).get("approved_ids") or []
                    }
                    selected = [
                        candidate
                        for candidate in (payload.get("candidates") or [])
                        if str(candidate.get("target_id") or "") in chosen
                    ]
                    if not selected:
                        notice = "至少勾选一组再清理；也可以点【取消】退出"
                        continue

                    # 确认页放在审阅循环里：这样【返回修改】能真的回到审阅页，
                    # 而不是像以前那样 `return None`（页面停在确认页，用户以为按钮坏了）。
                    # 只列**用户真的勾了**的高风险项（没勾就不该出现在确认页）。
                    risky = [
                        candidate for candidate in selected
                        if candidate.get("requires_confirmation")
                    ]
                    # 标题只算"这次一定会清"的低风险项：高风险要等下面再确认一次，
                    # 把它们算进 "共 X GB" 会让人以为不勾也会清（2026-10-20 截图发现）。
                    certain = [c for c in selected if not c.get("requires_confirmation")]
                    self._serve("confirming", pages.render_confirmation_html({
                        "selected_count": len(certain),
                        "selected_bytes": sum(int(item.get("allocated_bytes") or 0) for item in certain),
                        "risk_items": risky,
                    }))
                    decision = self._wait_or_nav(
                        ("confirm", "back", "cancel"), timeout or self.ACTION_TIMEOUT_SECONDS
                    )
                    if decision is not None and "nav" in decision:
                        return None
                    if decision is None or decision["action"] == "cancel":
                        return self._finish("cancelled", pages.render_cancelled_html({}))
                    if decision["action"] == "back":
                        # 回审阅页，**保留刚才勾选的那几组**（否则用户得重新点一遍）。
                        preselected = [str(c.get("target_id") or "") for c in selected]
                        notice = ""
                        continue
                    break                    # confirm → 去清理

                if not selected:
                    continue                 # 重新扫描分支：回到外层重扫
                break                        # 有勾选且已确认 → 结束扫描循环

            self._review_state = None
            self._serve("cleaning", pages.render_progress_html(
                {"title": "正在清理", "body": "正在清理", "message": "正在清理，请不要关闭窗口…",
                 "detail": "文件一律移入废纸篓，可从废纸篓恢复。"},
                stage="cleaning",
            ))
            # 把"用户刚在审阅页看到的那些目标"作为批准清单交给内核；
            # 没有这份清单，内核会按 dry-run 处理并回一份空计划（页面却显示完成）。
            approved_ids = [
                str(candidate.get("target_id") or "")
                for candidate in selected
                if str(candidate.get("target_id") or "")
            ]
            # 高风险项只有在确认页**额外勾了**才放行（内核也要求 confirm_targets）。
            confirmed_risk = bool((decision.get("payload") or {}).get("confirmed_risk"))
            confirm_ids = (
                [str(item.get("target_id") or "") for item in risky]
                if (confirmed_risk and risky)
                else []
            )
            # 去重：高风险项在审阅页已勾选，确认页再确认一次会重复加入批准清单。
            approved_ids = list(dict.fromkeys([*approved_ids, *(i for i in confirm_ids if i)]))
            cleaned = (
                self.deps.clean_approved(approved_ids, confirm_ids)
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
            self._attach_icons(apps)
            self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
            while True:
                action = self._wait_or_nav(
                    ("uninstall-plan", "uninstall-batch", "uninstall-list", "cancel"),
                    self.ACTION_TIMEOUT_SECONDS,
                )
                if action is not None and "nav" in action:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return action["nav"]
                if action is not None and action["action"] == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))
                if action is None or action["action"] in {"start", "uninstall-list"}:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return None
                if action["action"] == "uninstall-batch":
                    outcome = self._run_uninstall_batch(action.get("payload") or {}, apps)
                    if outcome == "reload":
                        self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
                        continue
                    if isinstance(outcome, dict):
                        return outcome          # 终态（cancelled）
                    self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
                    continue

                payload = dict(action.get("payload") or {})
                target_name = str(payload.get("name") or "")
                # 先**立刻**回一屏进度：`uninstall_plan` 本机实测 0.8–1.2s，
                # 这期间页面一动不动，用户会以为"点了没反应"再点一次（2026-10-21 反馈）。
                self._serve("uninstalling", pages.render_progress_html(
                    {"title": "软件卸载",
                     "body": f"正在清点 {target_name} 的残留" if target_name else "正在清点残留",
                     "message": "逐个目录核对，不会删除任何东西…",
                     "detail": "找到后会先给你看清单，勾选确认才移入废纸篓。",
                     "nav": "uninstall", "auto_refresh": False},
                    stage="uninstalling",
                ))
                plan = self.deps.uninstall_plan(
                    app_path=str(payload.get("path", "")),
                    bundle_id=str(payload.get("bundle_id", "")),
                    app_name=target_name,
                )
                # 预览页的决策要**循环等待**：用户可能先空勾一次（被拒绝）、再勾选提交。
                # 曾经把"被拒绝"写成 `continue` 回到外层，外层等的是 `uninstall-plan`，
                # 于是用户第二次点"卸载所选"没人接——真机上表现为"点了没反应"（2026-10-19 验收撞到）。
                notice = ""
                applied: dict[str, Any] | None = None
                while applied is None:
                    self._serve("uninstalling", pages.render_uninstall_preview_html(plan, notice=notice))
                    decision = self._wait_or_nav(
                        ("uninstall-apply", "uninstall-back", "uninstall-cask", "cancel"),
                        self.ACTION_TIMEOUT_SECONDS,
                    )
                    if decision is not None and "nav" in decision:
                        self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                        return decision["nav"]
                    if decision is None or decision["action"] in {"cancel", "uninstall-back"}:
                        self._serve("uninstalling", pages.render_uninstall_list_html({"apps": apps}))
                        break
                    if decision["action"] == "uninstall-cask":
                        # 只接受**当前计划里那个** cask 名，前端伪造别的 token 一律忽略。
                        token = str((decision.get("payload") or {}).get("token") or "")
                        expected = str(plan.get("cask") or "")
                        runner = getattr(self.deps, "uninstall_cask", None)
                        if not token or token != expected or runner is None:
                            notice = "这个应用的 cask 名称与当前计划不一致，已忽略"
                            continue
                        outcome = self._safe(lambda: runner(token), default={"status": "failed", "token": token})
                        self._serve("uninstalling", pages.render_uninstall_cask_result_html(outcome))
                        back = self._wait_or_nav(("uninstall-list", "cancel"), self.ACTION_TIMEOUT_SECONDS)
                        if back is not None and "nav" in back:
                            return str(back["nav"])
                        self._serve("uninstalling", pages.render_uninstall_list_html({"apps": self._safe(self.deps.apps, default=[])}))
                        break

                    selected = [
                        str(value) for value in (decision.get("payload") or {}).get("selected_ids") or []
                    ]
                    result = self.deps.uninstall_apply(plan=plan, ids=selected)
                    if str(result.get("status")) == "refused":
                        notice = "至少选一项再执行（应用本体是必选的）"
                        continue
                    applied = result
                if applied is None:
                    continue          # 用户回列表重新选（外层等 uninstall-plan）
                result = applied
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

    def _run_uninstall_batch(self, payload: dict[str, Any], apps: list[dict[str, Any]]) -> Any:
        """批量卸载：先给**一页确认**，确认后逐个应用执行，最后给汇总。

        为什么不是"选中即执行"：用户选 5 个应用时，真实残留项可能有 20+ 个，
        不给一次总览就执行，等于把 5 次确认压成 0 次（2026-10-19 设计）。
        """
        entries = [item for item in (payload.get("apps") or []) if isinstance(item, dict)]
        if entries:
            # 批量清点是逐个应用跑 uninstall_plan（每个 0.8–1.2s），先给一屏进度，
            # 否则选 5 个应用就是 5 秒白屏（2026-10-21 与单个卸载同一个问题）。
            self._serve("uninstalling", pages.render_progress_html(
                {"title": "批量卸载",
                 "body": f"正在清点 {len(entries)} 个应用的残留",
                 "message": "逐个目录核对，不会删除任何东西…",
                 "detail": "清点完先给你一页汇总，确认后才执行。",
                 "nav": "uninstall", "auto_refresh": False},
                stage="uninstalling",
            ))
        plans: list[dict[str, Any]] = []
        for entry in entries:
            plan = self.deps.uninstall_plan(
                app_path=str(entry.get("path", "")),
                bundle_id=str(entry.get("bundle_id", "")),
                app_name=str(entry.get("name", "")),
            )
            user_items = [item for item in (plan.get("items") or []) if not item.get("requires_admin")]
            plans.append(
                {
                    "name": str(entry.get("name") or (plan.get("app") or {}).get("name") or ""),
                    "bundle_id": str(entry.get("bundle_id") or (plan.get("app") or {}).get("bundle_id") or ""),
                    "plan": plan,
                    "count": len(user_items),
                    "bytes": sum(int(item.get("allocated_bytes", 0) or 0) for item in user_items),
                }
            )
        if not plans:
            return "reload"

        summary = {
            "apps": [
                {"name": item["name"], "bundle_id": item["bundle_id"], "count": item["count"], "bytes": item["bytes"]}
                for item in plans
            ],
            "total_items": sum(item["count"] for item in plans),
            "total_bytes": sum(item["bytes"] for item in plans),
        }
        self._serve("uninstalling", pages.render_uninstall_batch_confirm_html(summary))

        decision = self._wait_or_nav(
            ("uninstall-batch-apply", "uninstall-list", "cancel"), self.ACTION_TIMEOUT_SECONDS
        )
        if decision is not None and "nav" in decision:
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
            return {"stage": "cancelled", "active": False}
        if decision is None or decision["action"] in {"cancel", "uninstall-list"}:
            if decision is not None and decision["action"] == "cancel":
                return self._finish("cancelled", pages.render_cancelled_html({}))
            return "reload"

        results = []
        for item in plans:
            applied = self.deps.uninstall_apply(plan=item["plan"], ids=None)
            moved = int(applied.get("moved_count", 0) or 0)
            results.append({"name": item["name"], "moved": moved, "bytes": item["bytes"] if moved else 0})
        self._serve("uninstalling", pages.render_uninstall_batch_done_html({"apps": results}))

        follow = self._wait_or_nav(("uninstall-list", "cancel"), self.ACTION_TIMEOUT_SECONDS)
        if follow is not None and "nav" in follow:
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
            return {"stage": "cancelled", "active": False}
        if follow is not None and follow["action"] == "cancel":
            return self._finish("cancelled", pages.render_cancelled_html({}))
        return "reload"


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
            notice = ""
            while True:
                self._attach_icons([app for app in (found.get("sparkle") or []) if isinstance(app, dict)])
                self._serve("updates", pages.render_updates_list_html(found, notice=notice))
                action = self._wait_or_nav(
                    ("updates-apply", "updates-refresh", "cancel"), self.ACTION_TIMEOUT_SECONDS
                )
                if action is not None and "nav" in action:
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return action["nav"]
                if action is not None and action["action"] == "cancel":
                    return self._finish("cancelled", pages.render_cancelled_html({}))
                if action is None or action["action"] == "start":
                    self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                    return None
                if action["action"] == "updates-refresh":
                    # 【重新检查】必须绕过缓存（否则点了没反应，用户以为坏了）。
                    refresh = getattr(self.deps, "updates_refresh", None) or self.deps.updates_check
                    found = refresh()
                    notice = ""
                    continue
                ids = [str(value) for value in (action.get("payload") or {}).get("ids") or []]
                if not ids:
                    # 空勾选不是"全部升级"：留在列表页并说明（否则会一口气升掉所有包）。
                    notice = "至少勾选一项再更新"
                    continue
                result = self.deps.updates_apply(ids=ids)
                break
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

    def _run_disk(self) -> str | None:
        """磁盘总览（只读展示）。

        这一页的职责是"看清分布"，不是浏览器：**不做下钻**（2026-10-21 用户要求）。
        """
        while True:
            overview = dict(self._safe(self.deps.disk, default={}))
            reader = getattr(self.deps, "system_sizes_cached", None)
            if reader is not None:
                overview["system"] = self._safe(reader, default={})
            self._serve("disk", pages.render_disk_html(overview))
            action = self._wait_or_nav(("system-sizes", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if action is not None and "nav" in action:
                return str(action["nav"])
            if action is None or action["action"] == "cancel":
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return None
            # 一次性授权（系统标准密码框），只测量不删除；结果写缓存，本次会话不再弹。
            measure = getattr(self.deps, "system_sizes_admin", None)
            self._serve("disk", pages.render_progress_html(
                {"title": "磁盘", "body": "正在测量系统目录",
                 "message": "若弹出授权框，请输入密码（只用来读体积，不会删文件）…",
                 "detail": "同一次会话只需授权一次。", "nav": "disk"},
                stage="disk",
            ))
            if measure is not None:
                self._safe(measure, default={})

    def _run_orphans(self) -> None:
        """孤儿残留体检：扫描 → 勾选 → 移入废纸篓。"""
        scan = getattr(self.deps, "orphans_scan", None)
        apply_ = getattr(self.deps, "orphans_apply", None)
        if scan is None:
            self._serve("orphans", pages.render_orphans_html({}))
            return
        # 要跑 lsregister（4-5 秒）：先出进度页，否则点了像没反应。
        self._serve("orphans", pages.render_progress_html(
            {"title": "残留体检", "body": "正在比对已安装应用",
             "message": "正在读 LaunchServices 注册表（应用装在哪都能认出来）…",
             "detail": "只读，不会动任何文件。", "nav": "orphans"},
            stage="orphans",
        ))
        found = self._safe(scan, default={})
        while True:
            self._serve("orphans", pages.render_orphans_html(found))
            action = self._wait_or_nav(("orphans-apply", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if action is not None and "nav" in action:
                return str(action["nav"])
            if action is None or action["action"] == "cancel":
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return None
            if action["action"] == "orphans-open":
                found = self._safe(scan, default={})
                continue
            wanted = [
                str(value)
                for value in (action.get("payload") or {}).get("paths") or []
                # 只允许清**当前页面出现过的**路径（与会话的 reveal 白名单同源）。
                if str(value) in self._visible_paths
            ]
            if not wanted:
                found = {**found, "message": "先勾选要清理的项"}
                continue
            if apply_ is None:
                found = {**found, "message": "清理不可用"}
                continue
            result = self._safe(lambda: apply_(wanted), default={})
            self._serve("orphans", pages.render_orphans_result_html(result))
            back = self._wait_or_nav(("orphans-open", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if back is not None and "nav" in back:
                return str(back["nav"])
            if back is not None and back["action"] == "orphans-open":
                found = self._safe(scan, default={})
                continue
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
            return None

    def _run_large_files(self) -> str | None:
        """大文件视图：扫描 → 勾选 → 移入废纸篓。"""
        scan = getattr(self.deps, "large_files", None)
        apply_ = getattr(self.deps, "trash_paths", None)
        if scan is None:
            self._serve("large", pages.render_large_files_html({}))
            return None
        found = self._safe(scan, default={})
        while True:
            self._serve("large", pages.render_large_files_html(found))
            action = self._wait_or_nav(("large-apply", "large-open", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if action is not None and "nav" in action:
                return str(action["nav"])
            if action is None or action["action"] == "cancel":
                self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
                return None
            if action["action"] == "large-open":
                found = self._safe(scan, default={})
                continue
            wanted = [
                str(value)
                for value in (action.get("payload") or {}).get("paths") or []
                if str(value) in self._visible_paths      # 只允许页面出现过的路径
            ]
            if not wanted:
                found = {**found, "message": "先勾选要清理的文件"}
                continue
            if apply_ is None:
                found = {**found, "message": "清理不可用"}
                continue
            result = self._safe(lambda: apply_(wanted), default={})
            self._serve("large", pages.render_large_files_result_html(result))
            back = self._wait_or_nav(("large-open", "cancel"), self.ACTION_TIMEOUT_SECONDS)
            if back is not None and "nav" in back:
                return str(back["nav"])
            if back is not None and back["action"] == "large-open":
                found = self._safe(scan, default={})
                continue
            self._serve("idle", pages.render_landing_html({"history": self._safe(self.deps.history)}))
            return None

    # ---- Sparkle 结果确认 ----

    def _await_sparkle(self, target: str, version: str) -> dict[str, Any] | None:
        """打开应用后停在这一页：用户点【检查是否已更新】就重新读版本号对比。

        返回 `{"nav": kind}` 表示用户切走了；返回 `None` 表示结束这段交互、继续原流程。
        """
        reader = getattr(self.deps, "app_version", None)
        name = Path(target).stem
        state = {"kind": "opened", "current": ""}
        while True:
            self._serve("sparkle", pages.render_sparkle_result_html({
                "name": name, "version": version,
                "state": state["kind"], "current": state["current"],
            }))
            action = self.bridge.wait_for_action(
                ("sparkle-verify",) + NAV_ACTIONS + ("reveal", "cancel"),
                timeout=self.ACTION_TIMEOUT_SECONDS,
            )
            if action is None:
                return None
            if action["action"] == "reveal":
                self._reveal(str((action.get("payload") or {}).get("path", "")))
                continue
            if action["action"] in NAV_ACTIONS:
                return {"nav": action["action"]}
            if action["action"] == "cancel":
                return None
            current = ""
            if reader is not None:
                current = str(self._safe(lambda: reader(target), default="") or "")
            state["current"] = current
            state["kind"] = "updated" if (current and current != version) else "unchanged"

    # ---- 公共 ----


    def _wait_or_nav(
        self, kinds: tuple[str, ...], timeout: float
    ) -> dict[str, Any] | None:
        """等指定动作，但**也接住侧栏导航**：返回 `{"nav": "<kind>"}` 表示用户切走了。"""
        # `reveal` 任何页面都可能点：在这里拦下处理，处理完继续等原来的动作。
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            action = self.bridge.wait_for_action(
                tuple(kinds) + NAV_ACTIONS + ("reveal", "open-app", "open-app-store"),
                timeout=remaining,
            )
            if action is None:
                return None
            if action["action"] == "reveal":
                self._reveal(str((action.get("payload") or {}).get("path", "")))
                continue
            if action["action"] == "open-app":
                # 只允许打开**当前页面出现过的**应用路径（与 reveal 同一份白名单）。
                target = str((action.get("payload") or {}).get("path", ""))
                opener = getattr(self.deps, "open_app", None)
                if opener is not None and target and target in self._visible_paths:
                    version = ""
                    reader = getattr(self.deps, "app_version", None)
                    if reader is not None:
                        version = str(self._safe(lambda: reader(target), default="") or "")
                    try:
                        opener(target)
                    except Exception:  # noqa: BLE001
                        pass
                    outcome = self._await_sparkle(target, version)
                    if outcome is not None:
                        return outcome
                continue
            if action["action"] == "open-app-store":
                opener = getattr(self.deps, "open_app_store", None)
                if opener is not None:
                    try:
                        opener()
                    except Exception:  # noqa: BLE001 - 打不开不该把流程变成错误
                        pass
                continue
            break
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
        # 记录本页出现过的路径：`reveal` 只允许打开这些，否则就成了任意路径后门。
        # 必须 `html.unescape`：路径里带 `&`（如 "Foo & Bar.app"）时属性里是 `&amp;`，
        # 浏览器 dataset 给的是解码后的值 —— 不反转义就永远对不上，右键会"点了没反应"。
        self._visible_paths = {
            html.unescape(match.group(1)) for match in REVEAL_PATH.finditer(page)
        }
        self.state.stage = stage
        self.state.updated_at = time.time()
        self.bridge.set_page(page)
        self._write_state()

    def _reveal(self, raw: str) -> bool:
        """在 Finder 中显示某个路径。只接受**当前页面出现过**的路径。"""
        path = str(raw or "").strip()
        if not path or path not in self._visible_paths:
            return False
        opener = self.deps.reveal
        if opener is None:
            return False
        try:
            opener(str(Path(os.path.expanduser(path))))
        except Exception as exc:  # noqa: BLE001 - 打不开不该把流程变成错误
            _log_reveal(f"failed path={path!r} error={type(exc).__name__}: {exc}")
            return False
        _log_reveal(f"ok path={path!r} exists={Path(os.path.expanduser(path)).exists()}")
        return True

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
        self._visible_paths: set[str] = set()

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
