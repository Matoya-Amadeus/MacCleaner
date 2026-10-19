"""卸载残留的**变体规则**（学 Pearcleaner 的"实测反推"思路）。

怎么来的：跑 `scripts/learn_leftover_rules.py` 在真实机器上采样 50 个已装应用，
统计每种路径模式的命中数，只把**确实命中**的模式写进来。当前样本（2026-10-19）结果：

    prefs.bundle 29 / httpstorages.bundle 22 / support.name 21 / support.bundle 9 /
    cache.bundle 9 / webkit 5 / container 5 / logs.name 3 / shipit 1 / vendor.wide 22*

`*` 厂商级 22 次命中里有**跨应用误伤**（例如 Antigravity 的包里出现 `com.google.GeminiMacOS`），
所以它只能算"按名称匹配"，**默认不勾选**，且要排除已装应用的 bundle id。

诚实结论：现有 `discover_related_paths` 已覆盖绝大多数；本模块只补真正的缺口
（Sparkle 的 `.ShipIt` 更新残留等）。要达到 Pearcleaner 那种"800 应用实测"，
需要持续把 `learn_leftover_rules.py --json` 的产出积累成语料，不是靠猜。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 受保护路径：规则命中了也不能碰（宁可漏，不可错删）。
PROTECTED_PARTS = frozenset(
    {
        ".ssh",
        ".gnupg",
        "Keychains",
        "Cookies",
        "Safari",
        "com.apple.Safari",
        "MobileSync",
        "Mail",
        "Messages",
    }
)


@dataclass(frozen=True)
class VariantRule:
    """一条变体规则：给出相对 `~/Library` 的路径模板与置信度。"""

    rule_id: str
    folder: str
    template: str
    kind: str
    confidence: str          # exact = 可默认勾选；name-match = 需用户确认
    note: str = ""


RULES: tuple[VariantRule, ...] = (
    VariantRule(
        "cache-shipit",
        "Caches",
        "{bundle_id}.ShipIt",
        "cache-shipit",
        "exact",
        "Sparkle 自动更新留下的临时目录",
    ),
    VariantRule(
        "cache-updater",
        "Caches",
        "{bundle_id}-updater",
        "cache-updater",
        "exact",
        "应用自带更新器留下的缓存",
    ),
)


def _is_protected(path: Path) -> bool:
    return any(part in PROTECTED_PARTS for part in path.parts)


def rule_candidates(home: Path, bundle_id: str) -> list[dict[str, str]]:
    """按变体规则给出**存在**的残留路径（不判权限、不判大小）。

    返回项与 `discover_related_paths` 的条目形状一致（path/kind/confidence），
    由调用方统一做去重与 `_entry()` 包装。
    """
    hits: list[dict[str, str]] = []
    if not bundle_id or bundle_id.count(".") < 1:
        return hits
    library = Path(home) / "Library"
    for rule in RULES:
        candidate = library / rule.folder / rule.template.format(bundle_id=bundle_id)
        if _is_protected(candidate):
            continue
        try:
            exists = candidate.exists()
        except OSError:
            exists = False
        if exists:
            hits.append(
                {
                    "path": str(candidate),
                    "kind": rule.kind,
                    "confidence": rule.confidence,
                    "note": rule.note,
                }
            )
    return hits
