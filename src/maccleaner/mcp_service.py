"""MCP-facing service layer with a one-time, in-memory cleanup plan registry."""

from __future__ import annotations

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
        )
        self._plans[snapshot.plan_id] = snapshot
        return snapshot

    def consume(
        self,
        plan_id: str,
        approved_targets: Sequence[str],
        confirm_targets: Sequence[str],
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
        snapshot = self.plans.create(
            context,
            candidate_target_ids=candidates,
            required_confirmation_ids=confirmations,
        )
        report["plan_id"] = snapshot.plan_id
        report["plan_expires_at"] = snapshot.expires_at.isoformat()
        report["applicable_target_ids"] = sorted(snapshot.candidate_target_ids)
        return report

    def trace(self, *, target_path: str | Path, keyword: str, profile: str = "generic") -> dict[str, object]:
        context = self._context(profile=profile)
        return self._manager(context).trace(Path(target_path), keyword).to_dict()

    def apply(
        self,
        *,
        plan_id: str,
        approved_targets: Sequence[str],
        confirm_targets: Sequence[str],
    ) -> dict[str, object]:
        snapshot = self.plans.consume(plan_id, approved_targets, confirm_targets)
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
