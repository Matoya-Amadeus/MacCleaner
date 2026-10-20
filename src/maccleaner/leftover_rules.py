"""卸载残留的**变体规则**（学 Pearcleaner 的"实测反推"思路）。

怎么来的：跑 `scripts/learn_leftover_rules.py` 在真实机器上采样 50 个已装应用，
统计每种路径模式的命中数，只把**确实命中**的模式写进来。当前样本（2026-10-19）结果：

    prefs.bundle 29 / httpstorages.bundle 22 / support.name 21 / support.bundle 9 /
    cache.bundle 9 / webkit 5 / container 5 / logs.name 3 / shipit 1 / vendor.wide 22*

`*` 厂商级 22 次命中里有**跨应用误伤**（例如 Antigravity 的包里出现 `com.google.GeminiMacOS`），
所以它只能算"按名称匹配"，**默认不勾选**，且要排除已装应用的 bundle id。

规则现在放在 **`data/leftover-rules.json`**（数据），代码里只留兜底。这样
`scripts/learn_leftover_rules.py --emit-rules` 的产出可以直接提交成 PR 来扩语料；
每条规则都必须带 `evidence`（采样数 + 命中的应用），不允许凭猜添加。

诚实结论：现有 `discover_related_paths` 已覆盖绝大多数；本模块只补真正的缺口
（Sparkle 的 `.ShipIt` 更新残留等）。要达到 Pearcleaner 那种"800 应用实测"，
需要持续采样积累，不是靠猜。
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


# 代码里的兜底：`data/leftover-rules.json` 缺失/损坏时仍能工作。
# 数据文件是"可积累的语料"，代码兜底是"坏数据也不能崩"的保险，两者不冲突。
DEFAULT_RULES: tuple[VariantRule, ...] = (
    VariantRule(
        "cache-shipit",
        "Caches",
        "{bundle_id}.ShipIt",
        "cache-shipit",
        "exact",
        "Sparkle 自动更新留下的临时目录",
    ),
    # `{bundle_id}-updater` 曾经写在这里，但本机 50 个应用采样 **0 命中**，
    # 按"每条规则必须有证据"的口径删掉了（2026-10-20）。等采样器真的命中再加回来。
)

RULES_FILE = "data/leftover-rules.json"
SAFE_FOLDERS = frozenset({"Caches", "Preferences", "Logs", "Application Support", "Containers"})
CONFIDENCE = frozenset({"exact", "name-match"})


def _validate(item: dict, index: int) -> VariantRule | None:
    """校验单条规则；任何可疑字段直接丢弃（宁可少一条规则，也不能越出 ~/Library）。"""
    try:
        rule = VariantRule(
            rule_id=str(item["id"]),
            folder=str(item["folder"]),
            template=str(item["template"]),
            kind=str(item["kind"]),
            confidence=str(item["confidence"]),
            note=str(item.get("note") or ""),
        )
    except (KeyError, TypeError):
        return None
    if rule.folder not in SAFE_FOLDERS:
        return None
    if "{bundle_id}" not in rule.template:
        return None
    if "/" in rule.template or ".." in rule.template or rule.template.startswith("."):
        return None
    if rule.confidence not in CONFIDENCE:
        return None
    return rule


def load_rules(text: str | None = None) -> tuple[VariantRule, ...]:
    """从 JSON 文本加载规则；传入 None 时读包内数据文件，读不到就用兜底。

    为什么规则要做成数据（2026-10-20）：Pearcleaner 的 800+ 应用覆盖是靠长期实测攒出来的；
    把规则外置后，`scripts/learn_leftover_rules.py --emit-rules` 的输出可以直接提交成 PR，
    不用改代码。
    """
    if text is None:
        try:
            from importlib.resources import files

            text = files("maccleaner").joinpath(RULES_FILE).read_text(encoding="utf-8")
        except (OSError, ModuleNotFoundError):
            return DEFAULT_RULES
    try:
        import json as _json

        payload = _json.loads(text)
        rules = [
            rule
            for index, item in enumerate(payload.get("rules") or [])
            if isinstance(item, dict) and (rule := _validate(item, index)) is not None
        ]
    except (ValueError, AttributeError):
        return DEFAULT_RULES
    return tuple(rules) or DEFAULT_RULES


RULES: tuple[VariantRule, ...] = load_rules()


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
