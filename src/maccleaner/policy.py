from __future__ import annotations

from typing import Any, Sequence

from .core import (
    ExplicitPlanRequiredError,
    HIGH_RISK_VALUES,
    PROFILES,
    PROTECTIONS,
    ROLLBACK_STRATEGIES,
    SOURCE_LAYERS,
    CleanupTarget,
    PlanItem,
    StorageContext,
    TargetScan,
    _effective_cutoff_seconds,
)


def resolve_target_protection(
    protection: str,
    metadata: dict[str, Any] | None,
    requires_confirmation: bool,
) -> str:
    if protection:
        return protection
    effective_metadata = metadata or {}
    if effective_metadata.get('cleanup_requires_approved_plan'):
        return 'approved_plan'
    if requires_confirmation:
        return 'exact_confirm'
    return 'normal'


def resolve_target_rollback(rollback_strategy: str, kind: str) -> str:
    if rollback_strategy:
        return rollback_strategy
    if kind == 'trash_tree':
        return 'trash'
    return 'none'


def target_requires_approved_plan(target: CleanupTarget) -> bool:
    return bool(
        target.metadata.get('cleanup_requires_approved_plan')
        or target.risk in HIGH_RISK_VALUES
        or target.protection == 'approved_plan'
    )


def target_is_confirmed(context: StorageContext, target: CleanupTarget) -> bool:
    if target.target_id in context.confirm_targets:
        return True
    if target.category in context.confirm_targets and target.risk == 'low':
        return True
    if context.yes and target.risk == 'low':
        return True
    return False


def should_back_up_target(target: CleanupTarget) -> bool:
    if target.risk in HIGH_RISK_VALUES:
        return True
    if target.source_layer in {'repo_reference', 'historical_index'}:
        return True
    if target.target_id == 'app-leftovers:' + str(target.metadata.get('app_name', '')):
        return True
    return False


def decide_plan_item(
    context: StorageContext,
    scan: TargetScan,
    *,
    missing_tools: Sequence[str] = (),
    docker_context_local: bool = True,
) -> PlanItem:
    target = scan.target
    reason = ""
    status = "planned"
    estimated = scan.eligible_bytes
    scope_status = "in_scope"
    source_layer = target.source_layer
    protection = target.protection
    protected_notes = [note for note in scan.notes if note.startswith("protected_session=")]
    requires_approved_plan = target_requires_approved_plan(target)

    if protected_notes:
        status = "blocked"
        reason = protected_notes[0].split("=", 1)[1] or "protected session data"
        scope_status = "protected_session"
        source_layer = "protected_session"
        protection = "blocked"
    elif context.enforce_approved_scope and target.target_id not in context.approved_targets:
        status = "blocked"
        reason = "outside approved cleanup plan"
        scope_status = "outside_approved_plan"
        protection = "approved_plan"
    elif target.kind == "command" and not target.paths and target.cwd is None:
        status = "skipped"
        reason = "command target requires explicit scope"
    elif not scan.exists and (target.kind != "command" or bool(target.paths)):
        status = "skipped"
        reason = "target path missing"
    elif missing_tools:
        status = "skipped"
        reason = f"missing tool: {', '.join(missing_tools)}"
    elif target.target_id == "docker-prune" and not docker_context_local:
        status = "skipped"
        reason = "docker context is remote"
    elif requires_approved_plan and not context.approved_targets:
        status = "blocked"
        reason = "approved cleanup plan required before medium/high-risk cleanup"
        scope_status = "outside_approved_plan"
        protection = "approved_plan"
    elif requires_approved_plan and target.target_id not in context.approved_targets:
        status = "blocked"
        reason = "outside approved cleanup plan"
        scope_status = "outside_approved_plan"
        protection = "approved_plan"
    elif any(note.startswith("non_owner_entries=") for note in scan.notes):
        status = "blocked"
        reason = "ownership mismatch; fix owner before cleanup"
    elif target.requires_confirmation and not target_is_confirmed(context, target):
        status = "blocked"
        reason = "explicit confirmation required"
        protection = "exact_confirm"
    elif estimated <= 0 and target.kind != "command":
        status = "empty"
        reason = "nothing eligible to clean"
    elif context.dry_run or not context.apply:
        status = "planned"
        reason = "dry-run"
    else:
        status = "ready"
        reason = "eligible for cleanup"

    return PlanItem(
        target_id=target.target_id,
        name=target.name,
        category=target.category,
        kind=target.kind,
        risk=target.risk,
        status=status,
        reason=reason,
        estimated_bytes=estimated,
        paths=scan.existing_paths,
        requires_confirmation=target.requires_confirmation,
        recoverable=target.recoverable,
        scope_status=scope_status,
        source_layer=source_layer,
        protection=protection if protection in PROTECTIONS else "normal",
        rollback_strategy=target.rollback_strategy,
        validation_patterns=target.validation_patterns,
    )


def evaluate_plan_item(manager, scan: TargetScan) -> PlanItem:
    return manager._evaluate_plan_item_impl(scan)


def discover_targets(manager) -> list[CleanupTarget]:
    return manager._discover_targets_impl()


def plan_targets(manager, scans: Sequence[TargetScan]) -> list[PlanItem]:
    return manager._plan_targets_impl(scans)


def explicit_plan_blockers(manager, plan_items: Sequence[PlanItem]) -> list[PlanItem]:
    return manager._explicit_plan_blockers_impl(plan_items)


__all__ = [
    'ExplicitPlanRequiredError',
    'HIGH_RISK_VALUES',
    'PROFILES',
    'PROTECTIONS',
    'ROLLBACK_STRATEGIES',
    'SOURCE_LAYERS',
    '_effective_cutoff_seconds',
    'decide_plan_item',
    'discover_targets',
    'evaluate_plan_item',
    'explicit_plan_blockers',
    'plan_targets',
    'resolve_target_protection',
    'resolve_target_rollback',
    'should_back_up_target',
    'target_is_confirmed',
    'target_requires_approved_plan',
]
