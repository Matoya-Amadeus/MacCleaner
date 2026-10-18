"""MCP-facing service layer with a one-time, in-memory cleanup plan registry."""

from __future__ import annotations

import hashlib

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from .core import CommandRunner, StorageContext, StorageManager


PLAN_TTL_SECONDS = 15 * 60


class PlanValidationError(ValueError):
    """Raised when an MCP apply request is not bound to a valid plan."""


@dataclass(frozen=True)
class PlanSnapshot:
    plan_id: str
    context: StorageContext
    candidate_target_ids: frozenset[str]
    required_confirmation_ids: frozenset[str]
    expires_at: datetime
    # 计划摘要（2026-10-18）：调用方可以把 `plan_digest` 原样回传，apply 侧比对。
    # 它防的不是"恶意伪造"（调用方本来就可信），而是**错串/误用**：拿 A 会话的计划去执行 B 会话的清单。
    digest: str = ""


def _digest(
    candidates: frozenset[str],
    required: frozenset[str],
    structure: dict[str, Sequence[str]],
    context_key: str = "",
) -> str:
    """计划摘要：目标 id + 需要二次确认的 id + 每个目标的路径清单（排序后）。

    为什么不把"估算字节"算进去：缓存体积随时在变，把它算进摘要会让正常使用频繁被拒
    （"计划变了"），反而逼人去关掉校验。**结构**才是不该变的：删哪些目标、动哪些路径。
    """
    # 上下文也进摘要：同一个目标 id 在不同 home/root 下是**不同的计划**，
    # 否则跨目录/跨机器会得到相同摘要（用例实测到过）。
    parts = [context_key, "|".join(sorted(candidates)), "|".join(sorted(required))]
    for target_id in sorted(structure):
        paths = sorted(str(path) for path in structure[target_id])
        parts.append(target_id + ":" + ",".join(paths))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


class PlanRegistry:
    """Stores short-lived plans and consumes them before a mutating apply."""

    def __init__(
        self,
        *,
        ttl_seconds: int = PLAN_TTL_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._plans: dict[str, PlanSnapshot] = {}

    def create(
        self,
        context: StorageContext,
        *,
        candidate_target_ids: Sequence[str] | set[str] | frozenset[str],
        required_confirmation_ids: Sequence[str] | set[str] | frozenset[str] = (),
        structure: dict[str, Sequence[str]] | None = None,
    ) -> PlanSnapshot:
        candidates = frozenset(candidate_target_ids)
        required = frozenset(required_confirmation_ids)
        if not required.issubset(candidates):
            raise ValueError("required_confirmation_ids must be a subset of candidate_target_ids")
        snapshot = PlanSnapshot(
            plan_id=str(uuid4()),
            context=context,
            candidate_target_ids=candidates,
            required_confirmation_ids=required,
            expires_at=self._now() + self._ttl,
            digest=_digest(
                candidates,
                required,
                structure or {},
                context_key=f"{getattr(context, 'home', '')}|{getattr(context, 'root', '')}",
            ),
        )
        self._plans[snapshot.plan_id] = snapshot
        return snapshot

    def consume(
        self,
        plan_id: str,
        approved_targets: Sequence[str],
        confirm_targets: Sequence[str],
        expected_digest: str = "",
    ) -> PlanSnapshot:
        snapshot = self._plans.get(plan_id)
        if snapshot is None:
            raise PlanValidationError("plan_id is unknown or already used")
        if self._now() >= snapshot.expires_at:
            self._plans.pop(plan_id, None)
            raise PlanValidationError("plan_id expired; generate a new plan")

        approved = frozenset(target for target in approved_targets if target)
        confirmed = frozenset(target for target in confirm_targets if target)
        if not approved:
            raise PlanValidationError("approved_targets must not be empty")
        outside_plan = sorted(approved - snapshot.candidate_target_ids)
        if outside_plan:
            raise PlanValidationError(f"approved_targets not in plan: {', '.join(outside_plan)}")
        if not confirmed.issubset(approved):
            raise PlanValidationError("confirm_targets must be a subset of approved_targets")
        missing_confirmations = sorted((approved & snapshot.required_confirmation_ids) - confirmed)
        if missing_confirmations:
            raise PlanValidationError(f"confirm_targets required for: {', '.join(missing_confirmations)}")
        # 摘要比对（可选）：传了就**先比再消费**，不匹配直接拒绝——绝不"尽力执行"。
        if expected_digest and snapshot.digest and expected_digest != snapshot.digest:
            raise PlanValidationError(
                "plan_digest mismatch: the plan you approved is not the plan being applied"
            )

        self._plans.pop(plan_id, None)
        return snapshot


class StorageService:
    """Use the canonical storage core without duplicating policy or execution logic."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        root: Path | None = None,
        runner: CommandRunner | None = None,
        plans: PlanRegistry | None = None,
    ) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self.root = (root or self.home).expanduser().resolve()
        self.runner = runner
        self.plans = plans or PlanRegistry()

    @staticmethod
    def _optional_path(value: str | Path | None) -> Path | None:
        if value is None or str(value).strip() == "":
            return None
        return Path(value).expanduser().resolve()

    @staticmethod
    def _targets_from_plan(report: dict[str, object]) -> tuple[frozenset[str], frozenset[str]]:
        candidates: set[str] = set()
        confirmations: set[str] = set()
        for raw_item in report.get("plan_items", []):
            if not isinstance(raw_item, dict):
                continue
            target_id = str(raw_item.get("target_id", ""))
            status = str(raw_item.get("status", ""))
            scope_status = str(raw_item.get("scope_status", ""))
            protection = str(raw_item.get("protection", ""))
            estimated = int(raw_item.get("estimated_bytes", 0))
            if not target_id or estimated <= 0:
                continue
            if status in {"skipped", "empty", "failed"}:
                continue
            if scope_status == "protected_session" or protection == "blocked":
                continue
            candidates.add(target_id)
            if protection == "exact_confirm" or bool(raw_item.get("requires_confirmation", False)):
                confirmations.add(target_id)
        return frozenset(candidates), frozenset(confirmations)

    def _context(
        self,
        *,
        profile: str = "generic",
        days_to_keep: int = 7,
        include_system: bool = False,
        include_hidden_home: bool = False,
        flutter_search_root: str | Path | None = None,
        app_path: str | Path | None = None,
        state_root: str | Path | None = None,
        require_zero_hit: Sequence[str] = (),
    ) -> StorageContext:
        return StorageContext(
            home=self.home,
            root=self.root,
            days_to_keep=days_to_keep,
            dry_run=True,
            apply=False,
            include_system=include_system,
            include_hidden_home=include_hidden_home,
            flutter_search_root=self._optional_path(flutter_search_root),
            app_path=self._optional_path(app_path),
            state_root=self._optional_path(state_root),
            require_zero_hit=tuple(item for item in require_zero_hit if item),
            profile=profile,
        )

    def _manager(self, context: StorageContext) -> StorageManager:
        return StorageManager(context, runner=self.runner)

    def audit(self, **kwargs: object) -> dict[str, object]:
        return self._manager(self._context(**kwargs)).audit().to_dict()

    def plan(self, **kwargs: object) -> dict[str, object]:
        context = self._context(**kwargs)
        report = self._manager(context).plan().to_dict()
        candidates, confirmations = self._targets_from_plan(report)
        structure = {
            str(item.get("target_id")): list(item.get("paths") or [])
            for item in (report.get("plan_items") or [])
            if isinstance(item, dict)
        }
        snapshot = self.plans.create(
            context,
            candidate_target_ids=candidates,
            required_confirmation_ids=confirmations,
            structure=structure,
        )
        report["plan_id"] = snapshot.plan_id
        report["plan_digest"] = snapshot.digest
        report["plan_expires_at"] = snapshot.expires_at.isoformat()
        report["applicable_target_ids"] = sorted(snapshot.candidate_target_ids)
        return report

    def trace(self, *, target_path: str | Path, keyword: str, profile: str = "generic") -> dict[str, object]:
        context = self._context(profile=profile)
        return self._manager(context).trace(Path(target_path), keyword).to_dict()

    # ---- 卸载与更新（2026-10-18 迁入）----
    # 两个能力都**只在这里做编排**：真正的逻辑在 uninstall.py / updates.py，
    # 这样 CLI、MCP、UI 三个入口共用同一套语义，不会各自漂移。

    def uninstall_plan(
        self,
        *,
        app_path: str | Path,
        bundle_id: str = "",
        app_name: str = "",
        home: str | Path | None = None,
    ) -> dict[str, object]:
        """列出某个应用的残留（只读）。不传 bundle-id/名称时从 Info.plist 自动读取。

        `home` 只给测试与多用户场景用（默认当前用户主目录）——否则用例会去扫真实的 `~/Library`。
        """
        from .uninstall import build_plan, read_app_identity, summarize

        identity = read_app_identity(app_path)
        plan = build_plan(
            {
                "path": str(app_path),
                "bundle_id": bundle_id or identity.get("bundle_id", ""),
                "name": app_name or identity.get("name", ""),
                "home": str(home) if home is not None else "",
            },
            home=home,
        )
        return {**summarize(plan), "items": plan["items"], "system_items": plan["system_items"]}

    def uninstall_apply(
        self,
        *,
        app_path: str | Path,
        bundle_id: str = "",
        app_name: str = "",
        ids: Sequence[str] = (),
        home: str | Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        """执行卸载：只移勾选项、只移用户域、一律进废纸篓（可恢复）。

        `ids` 为空表示"计划里的全部用户域项"；传了就只认这些 id（调用方换不掉路径）。
        """
        from .uninstall import apply_plan, build_plan, read_app_identity

        identity = read_app_identity(app_path)
        plan = build_plan(
            {
                "path": str(app_path),
                "bundle_id": bundle_id or identity.get("bundle_id", ""),
                "name": app_name or identity.get("name", ""),
            },
            home=home,
        )
        return apply_plan(plan, home=home, selected_ids=list(ids) or None, dry_run=dry_run)

    def updates_check(self) -> dict[str, object]:
        """第三方软件更新（只读）：Homebrew + App Store，不含 macOS 系统更新。"""
        from .updates import discover_updates

        return discover_updates()

    def updates_apply(self, *, names: Sequence[str] = ()) -> dict[str, object]:
        """按名称代装第三方更新（不传则全部）；返回逐组结果。"""
        from .updates import apply_updates, build_upgrade_plan, discover_updates

        found = discover_updates()
        wanted = {str(name) for name in names}
        selected = [
            item
            for item in found["items"]
            if not wanted or str(item.get("name")) in wanted or str(item.get("app_id")) in wanted
        ]
        plan = build_upgrade_plan(selected)
        return apply_updates(plan, dry_run=False)

    def apply(
        self,
        *,
        plan_id: str,
        approved_targets: Sequence[str],
        confirm_targets: Sequence[str],
        plan_digest: str = "",
    ) -> dict[str, object]:
        snapshot = self.plans.consume(plan_id, approved_targets, confirm_targets, expected_digest=plan_digest)
        context = replace(
            snapshot.context,
            dry_run=False,
            apply=True,
            yes=True,
            approved_targets=frozenset(approved_targets),
            confirm_targets=frozenset(confirm_targets),
            require_explicit_plan=True,
            enforce_approved_scope=True,
        )
        return self._manager(context).clean().to_dict()


__all__ = [
    "PLAN_TTL_SECONDS",
    "PlanRegistry",
    "PlanSnapshot",
    "PlanValidationError",
    "StorageService",
]
