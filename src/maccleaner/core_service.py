"""内核对外协议（stdio JSON Lines）。

为什么需要它（2026-10-22）：界面要从 WKWebView 换成 SwiftUI，界面与内核之间不能再走
"HTTP + 整页 HTML"，否则又回到"刷新当导航"的老毛病。这里定义一个**只谈数据**的协议：

    请求（一行 JSON）  {"id":"1","cmd":"scan","args":{}}
    事件（零到多行）    {"id":"1","event":"started","op":"scan"}
    终态（恰好一行）    {"id":"1","ok":true,"data":{...}}
                       {"id":"1","ok":false,"error":{"code":"...","message":"..."}}

设计约束（不满足就不要加命令）：
1. **只返回内核自己的数据**，不在这一层做 HTML/文案加工；
2. 任何可能超过 0.3s 的操作，先发一条 `started` 事件——界面靠它显示进度，
   而不是轮询（轮询 + 整页刷新正是四类 UI bug 的根源）；
3. 参数只接受**标识符与白名单路径**，路径在执行侧再校验一次（不信任调用方）。
"""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, Callable, Iterable

from .view_models import (
    apps_view,
    large_view,
    orphans_view,
    review_view,
    updates_view,
)

PROTOCOL_VERSION = 1

# 错误码：界面按 code 做分支，message 只给人看（可能变）。
ERROR_CODES = {
    "bad_json": "这一行不是合法 JSON",
    "bad_request": "请求缺少 cmd 或 id",
    "unknown_command": "不认识的命令",
    "bad_args": "参数不合法",
    "internal_error": "内核执行出错",
}


class CoreService:
    """把内核能力暴露成命令。一个实例对应一个调用方（stdio 会话）。"""

    def __init__(self, deps: Any, *, emit: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.deps = deps
        self._emit = emit or (lambda message: None)
        # 协作式取消：命令是同步执行的，所以靠一个标志让执行循环自己收手，
        # 而不是杀进程（杀进程会留下"不知道删了哪些"的半成品）。
        self._cancel = threading.Event()

    # ---------- 取消 ----------

    def request_cancel(self) -> None:
        self._cancel.set()

    def clear_cancel(self) -> None:
        self._cancel.clear()

    def should_stop(self) -> bool:
        return self._cancel.is_set()

    # ---------- 对外入口 ----------

    def dispatch(self, request: Any, *, message_id: str = "") -> list[dict[str, Any]]:
        """处理一个请求，返回要发出去的消息列表（事件 + 终态）。

        返回列表而不是直接写流：单元测试可以不碰 IO 就把协议验完。
        """
        messages: list[dict[str, Any]] = []

        def emit(payload: dict[str, Any]) -> None:
            messages.append(payload)
            self._emit(payload)

        if not isinstance(request, dict):
            emit(self._error(message_id, "bad_request", ERROR_CODES["bad_request"]))
            return messages

        request_id = str(request.get("id") or message_id or "")
        cmd = str(request.get("cmd") or "").strip()
        args = request.get("args") if isinstance(request.get("args"), dict) else {}
        if not cmd:
            emit(self._error(request_id, "bad_request", "缺少 cmd"))
            return messages

        self.clear_cancel()
        handler = self._handlers().get(cmd)
        if handler is None:
            emit(self._error(
                request_id, "unknown_command",
                f"{ERROR_CODES['unknown_command']}: {cmd}",
                hint=sorted(self._handlers()),
            ))
            return messages

        try:
            data = handler(request_id, args, emit)
        except KeyError as exc:                      # 参数缺失
            emit(self._error(request_id, "bad_args", f"缺少参数: {exc}"))
            return messages
        except (TypeError, ValueError) as exc:       # 参数类型/取值不对
            emit(self._error(request_id, "bad_args", str(exc)))
            return messages
        except Exception as exc:  # noqa: BLE001 - 任何异常都要变成可读的终态，不能让调用方干等
            print(f"[core] {cmd} failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            emit(self._error(request_id, "internal_error", f"{type(exc).__name__}: {exc}"))
            return messages

        emit({"id": request_id, "ok": True, "data": data, "v": PROTOCOL_VERSION})
        return messages

    def serve_lines(self, lines: Iterable[str]) -> Iterable[str]:
        """把输入的每一行请求变成输出的若干行（供 stdio 循环与测试共用）。"""
        for raw in lines:
            text = raw.strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except json.JSONDecodeError as exc:
                yield self._dumps(self._error("", "bad_json", f"{ERROR_CODES['bad_json']}: {exc.msg}"))
                continue
            for message in self.dispatch(request):
                yield self._dumps(message)

    # ---------- 命令表 ----------

    def _handlers(self) -> dict[str, Callable[[str, dict[str, Any], Callable[[dict[str, Any]], None]], Any]]:
        return {
            # 只读
            "ping": self._ping,
            "disk": self._disk,
            "disk.summary": self._disk_summary,
            "large.list": self._large_list,
            "files.trash": self._files_trash,
            "app.open": self._app_open,
            "system": self._system,
            "skills": self._skills,
            "apps": self._apps,
            "scan": self._scan,
            "review.payload": self._review_payload,
            # 清理
            "clean": self._clean,
            # 卸载
            "uninstall.plan": self._uninstall_plan,
            "uninstall.apply": self._uninstall_apply,
            # 更新
            "updates.check": self._updates_check,
            "updates.list": self._updates_list,
            "updates.apply": self._updates_apply,
            # 残留
            "orphans.scan": self._orphans_scan,
            "orphans.list": self._orphans_list,
            "orphans.apply": self._orphans_apply,
            # 系统级目录（需授权）
            "system.measure": self._system_measure,
            "system.trash": self._system_trash,
        }

    # ---------- 只读 ----------

    def _ping(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        return {"pong": True, "v": PROTOCOL_VERSION}

    def _disk_summary(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """只要容量（statfs，毫秒级、不读任何受保护目录）。

        为什么单独一条（2026-10-22 真机撞到）：`disk` 会对 ~/Documents、~/Desktop 等目录跑 `du`，
        没有「完全磁盘访问权限」时 macOS 会**连环弹授权框**，界面还会卡住。
        先出容量、再按权限决定要不要读目录——这样首屏永远有东西看。
        """
        import shutil

        usage = shutil.disk_usage("/")
        total = int(usage.total or 0)
        used = int(usage.used or 0)
        free = int(usage.free or 0)
        percent = (used / total * 100) if total else 0.0
        return {"total": total, "used": used, "free": free, "percent": round(percent, 1)}

    def _disk(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        report = dict(self._call("disk", default={}) or {})
        cached = getattr(self.deps, "system_sizes_cached", None)
        if cached is not None:
            report["system"] = self._call("system_sizes_cached", default={}) or {}
        return report

    def _system(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        return self._call("system", default={}) or {}

    def _skills(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        return {"skills": self._call("skills", default=[]) or []}

    def _apps(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """已安装应用 + **已分好的分类组**（规则的唯一来源在内核，界面不复制）。"""
        return apps_view(self._call("apps", default=[]) or [])

    def _scan(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """只读扫描。返回内核原始报告；分组/展示留给上层（M1 会把分组也收到内核）。"""
        emit({"id": request_id, "event": "started", "op": "scan"})
        return {"report": self._call("audit", default={}) or {}}

    def _review_payload(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """扫一遍并**直接给出分组好的审阅数据**（界面不用知道分类规则）。"""
        emit({"id": request_id, "event": "started", "op": "review.payload"})
        report = self._call("audit", default={}) or {}
        return review_view(report)

    def _large_list(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        emit({"id": request_id, "event": "started", "op": "large.list"})
        runner = getattr(self.deps, "large_files", None)
        if runner is None:
            raise ValueError("这个构建不支持大文件扫描")
        return large_view(self._call("large_files", default={}) or {})

    def _files_trash(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """把给定路径移进废纸篓（大文件页用）。空数组拒绝。"""
        paths = [str(value) for value in (args.get("paths") or [])]
        if not paths:
            raise ValueError("paths 不能为空")
        emit({"id": request_id, "event": "started", "op": "files.trash", "count": len(paths)})
        runner = getattr(self.deps, "trash_paths", None)
        if runner is None:
            raise ValueError("这个构建不支持移入废纸篓")
        return self._call("trash_paths", paths, should_stop=self.should_stop, default={}) or {}

    def _app_open(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """打开一个 .app（自带更新器的「在应用内更新」用它）。

        只接受**存在且以 .app 结尾**的路径：这条命令会把控制权交给别的程序，
        不能让它变成"打开任意路径"。
        """
        from pathlib import Path

        raw = str(args.get("path") or "").strip()
        if not raw:
            raise ValueError("path 不能为空")
        target = Path(raw)
        if target.suffix != ".app" or not target.exists():
            raise ValueError("只允许打开存在的 .app")
        opener = getattr(self.deps, "open_app", None)
        if opener is None:
            raise ValueError("这个构建不支持打开应用")
        opener(str(target))
        return {"opened": str(target)}

    # ---------- 清理 ----------

    def _clean(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """执行清理。**空勾选必须拒绝**（与界面同一条安全规则）。"""
        approved = [str(value) for value in (args.get("approved_ids") or [])]
        selected = [str(value) for value in (args.get("selected_ids") or [])]
        if not approved:
            raise ValueError("approved_ids 不能为空：空勾选不等于全部")
        emit({"id": request_id, "event": "started", "op": "clean", "count": len(approved)})
        runner = getattr(self.deps, "clean_approved", None)
        if runner is not None:
            return self._call("clean_approved", approved, selected, default={}) or {}
        return self._call("clean", default={}) or {}

    # ---------- 卸载 ----------

    def _uninstall_plan(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        path = str(args.get("path") or "").strip()
        if not path:
            raise ValueError("path 不能为空")
        emit({"id": request_id, "event": "started", "op": "uninstall.plan"})
        return self._call(
            "uninstall_plan",
            app_path=path,
            bundle_id=str(args.get("bundle_id") or ""),
            app_name=str(args.get("name") or ""),
            default={},
        ) or {}

    def _uninstall_apply(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """卸载。**空勾选必须拒绝**：否则等于"把整个应用连同残留全删"。"""
        items = [str(value) for value in (args.get("item_ids") or [])]
        if not items:
            raise ValueError("item_ids 不能为空")
        emit({"id": request_id, "event": "started", "op": "uninstall.apply", "count": len(items)})
        return self._call(
            "uninstall_apply",
            app_path=str(args.get("path") or ""),
            item_ids=items,
            default={},
        ) or {}

    def _updates_list(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """检查并给出**分组好的更新清单**（Sparkle 只保留确认有更新的）。"""
        emit({"id": request_id, "event": "started", "op": "updates.list"})
        return updates_view(self._call("updates_check", default={}) or {})

    # ---------- 更新 ----------

    def _updates_check(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        emit({"id": request_id, "event": "started", "op": "updates.check"})
        return self._call("updates_check", default={}) or {}

    def _updates_apply(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        ids = [str(value) for value in (args.get("ids") or [])]
        if not ids:
            raise ValueError("ids 不能为空")
        emit({"id": request_id, "event": "started", "op": "updates.apply", "count": len(ids)})
        return self._call("updates_apply", ids=ids, default={}) or {}

    # ---------- 残留 ----------

    def _orphans_scan(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        emit({"id": request_id, "event": "started", "op": "orphans.scan"})
        runner = getattr(self.deps, "orphans_scan", None)
        if runner is None:
            raise ValueError("这个构建不支持残留扫描")
        return self._call("orphans_scan", default={}) or {}

    def _orphans_apply(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """按**路径**清残留：内核那层就是 `orphans_clean(home, paths)`。

        参数名必须是 `paths`：之前写成 `ids` 再把它当路径传下去，只是名字骗自己
        （2026-10-22 对齐原生界面时发现）。
        """
        paths = [str(value) for value in (args.get("paths") or [])]
        if not paths:
            raise ValueError("paths 不能为空")
        emit({"id": request_id, "event": "started", "op": "orphans.apply", "count": len(paths)})
        return self._call("orphans_apply", paths, should_stop=self.should_stop, default={}) or {}

    def _orphans_list(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        emit({"id": request_id, "event": "started", "op": "orphans.list"})
        runner = getattr(self.deps, "orphans_scan", None)
        if runner is None:
            raise ValueError("这个构建不支持残留扫描")
        return orphans_view(self._call("orphans_scan", default={}) or {})

    # ---------- 系统级目录 ----------

    def _system_measure(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        """测量 root 域体积（会弹一次管理员授权，**只读**）。"""
        emit({"id": request_id, "event": "started", "op": "system.measure"})
        runner = getattr(self.deps, "system_sizes_admin", None)
        if runner is None:
            raise ValueError("这个构建不支持系统目录测量")
        return self._call("system_sizes_admin", default={}) or {}

    def _system_trash(self, request_id: str, args: dict[str, Any], emit: Callable[..., None]) -> dict[str, Any]:
        paths = [str(value) for value in (args.get("paths") or [])]
        if not paths:
            raise ValueError("paths 不能为空")
        emit({"id": request_id, "event": "started", "op": "system.trash", "count": len(paths)})
        runner = getattr(self.deps, "system_trash_paths", None)
        if runner is None:
            raise ValueError("这个构建不支持移走系统目录")
        return self._call("system_trash_paths", paths, default={}) or {}

    # ---------- 内部 ----------

    def _call(self, name: str, *args: Any, default: Any = None, **kwargs: Any) -> Any:
        fn = getattr(self.deps, name, None)
        if fn is None:
            return default
        return fn(*args, **kwargs)

    @staticmethod
    def _error(request_id: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
        payload = {"code": code, "message": message, "v": PROTOCOL_VERSION}
        payload.update(extra)
        return {"id": request_id, "ok": False, "error": payload}

    @staticmethod
    def _dumps(message: dict[str, Any]) -> str:
        return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def serve_stdio(deps: Any, stdin=None, stdout=None) -> int:
    """stdio 循环：读请求、**在后台线程执行**、逐行写消息。

    为什么要分线程（2026-10-22 加取消）：命令是同步阻塞的（一次清理可能几十秒），
    如果读和做在同一个线程里，`cancel` 只能排在队尾——等它能被读到，活早干完了。
    现在读线程只负责收消息，`cancel` 立刻置标志，执行循环在下一项开始前看到它。
    """
    import queue

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    service = CoreService(deps)
    write_lock = threading.Lock()

    def write(payload: dict[str, Any]) -> None:
        with write_lock:
            stdout.write(CoreService._dumps(payload) + "\n")
            stdout.flush()

    service._emit = write  # noqa: SLF001 - 同一个实例，避免再复制状态
    jobs: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def worker() -> None:
        while True:
            request = jobs.get()
            if request is None:
                return
            service.dispatch(request)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        for line in stdin:
            text = line.strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except json.JSONDecodeError as exc:
                write(CoreService._error("", "bad_json", f"{ERROR_CODES['bad_json']}: {exc.msg}"))
                continue
            if isinstance(request, dict) and str(request.get("cmd") or "") == "cancel":
                service.request_cancel()
                write({"id": str(request.get("id") or ""), "ok": True,
                       "data": {"cancelled": True}, "v": PROTOCOL_VERSION})
                continue
            jobs.put(request)
    finally:
        jobs.put(None)
        thread.join(timeout=5)
    return 0
