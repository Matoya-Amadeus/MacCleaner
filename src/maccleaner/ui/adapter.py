"""内核报告 → 页面数据（2026-10-18 迁入）。

为什么要这一层：页面只吃 dict，而内核报告是**另一种** dict（`plan_items` 里带
`estimated_bytes` / `actual_bytes` / `recoverable` / `status`，顶层有 `actual_reclaimed_bytes`
与 `receipt`）。把映射写在一处，页面就不会各自猜字段名——这是"两支合流"里最容易腐化的接缝。

口径忠实于内核，不做美化：

- 审阅页只列**有实际体量**的条目（`estimated_bytes > 0`），避免一屏 0 字节噪声；
- 完成页的"可恢复"取自 `recoverable=True` 条目的 `actual_bytes`；"实际释放"用内核的
  `actual_reclaimed_bytes`（走废纸篓时它本来就是 0，页面据此显示"清空废纸篓后释放"）。
"""
from __future__ import annotations

from typing import Any, Iterable

_CLEANED_STATES = {"cleaned", "applied", "done", "moved"}


def _items(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in (report.get("plan_items") or []) if isinstance(item, dict)]


def _first_path(item: dict[str, Any]) -> str:
    paths = item.get("paths") or []
    if isinstance(paths, str):
        return paths
    return str(paths[0]) if paths else ""


def review_payload(report: dict[str, Any]) -> dict[str, Any]:
    """审阅页数据：只保留有体量的条目，并带上是否可恢复。"""
    candidates: list[dict[str, Any]] = []
    for item in _items(report):
        estimated = int(item.get("estimated_bytes") or 0)
        if estimated <= 0:
            continue
        candidates.append(
            {
                "path": _first_path(item),
                # target 的**名字**要带上：页面以前拿路径末级名当标题，于是
                # `homebrew-cache` 与 `brew-cleanup` 都显示成 "Homebrew"，看着像重复项。
                "name": str(item.get("name") or ""),
                "kind": str(item.get("category") or item.get("kind") or ""),
                "allocated_bytes": estimated,
                "recoverable": bool(item.get("recoverable")),
                "status": str(item.get("status") or ""),
                "target_id": str(item.get("target_id") or ""),
            }
        )
    return {
        "candidates": candidates,
        "count": len(candidates),
        "total_bytes": sum(int(candidate["allocated_bytes"]) for candidate in candidates),
        "mode": str(report.get("mode") or ""),
        "dry_run": bool(report.get("dry_run")),
        "scan_cached_at": float(report.get("scan_cached_at") or 0),
    }


def _actual_bytes(item: dict[str, Any]) -> int:
    actual = int(item.get("actual_bytes") or 0)
    if actual:
        return actual
    status = str(item.get("status") or "")
    return int(item.get("estimated_bytes") or 0) if status in _CLEANED_STATES else 0


def completion_payload(report: dict[str, Any]) -> dict[str, Any]:
    """完成页数据：可恢复字节优先，实际释放量取内核的 `actual_reclaimed_bytes`。"""
    items = _items(report)
    recoverable = sum(_actual_bytes(item) for item in items if item.get("recoverable"))
    failed = sum(1 for item in items if str(item.get("status")) == "failed")
    # 这两类都不是"出问题"，不该计进"跳过"：
    # - `target path missing`：目标是空的/不存在（扫到 0 字节的目标很常见）；
    # - `outside approved cleanup plan`：用户**没勾**的目标，被内核按范围外标记。
    # 把它们算成跳过，完成页会显示"跳过 19"，看着像清理失败了（2026-10-19 截图里就是这样）。
    IGNORED = ("target path missing", "outside approved cleanup plan")
    skipped = [
        {"path": _first_path(item), "reason": str(item.get("reason") or "")}
        for item in items
        if str(item.get("status")) in {"skipped", "blocked", "protected"}
        and not any(marker in str(item.get("reason") or "") for marker in IGNORED)
    ]
    receipt = report.get("receipt")
    receipt_path = ""
    if isinstance(receipt, dict):
        receipt_path = str(receipt.get("json") or receipt.get("path") or "")
    elif receipt:
        receipt_path = str(receipt)
    return {
        "recoverable_bytes": recoverable,
        "actual_freed_bytes": int(report.get("actual_reclaimed_bytes") or 0),
        "failed_count": failed,
        "skipped_count": len(skipped),
        "skipped_items": skipped,
        "receipt_path": receipt_path,
        "before_free_bytes": int(report.get("before_free_bytes") or 0),
        "after_free_bytes": int(report.get("after_free_bytes") or 0),
    }


def updates_payload(found: dict[str, Any]) -> dict[str, Any]:
    """更新页数据：发现结果本身就是页面要的形状，这里只补缺省值。"""
    items: Iterable[dict[str, Any]] = (item for item in (found.get("items") or []) if isinstance(item, dict))
    return {
        "items": list(items),
        "count": int(found.get("count") or 0),
        "notes": [str(note) for note in (found.get("notes") or [])],
        "scope": str(found.get("scope") or ""),
    }


__all__ = ["completion_payload", "review_payload", "updates_payload"]
