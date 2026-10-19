#!/usr/bin/env python3
"""从本机已装应用反推残留规则（只读，不删任何东西）。

为什么要有它：Pearcleaner 的规则库是"800+ 应用实测"堆出来的，我们不该靠猜。
这个脚本做的是**同一件事的起点**：拿本机真实应用，统计每种路径模式命中了多少，
命中最多的模式才值得写进 `leftover_rules.py`。

用法：
    python3 scripts/learn_leftover_rules.py            # 人类可读统计
    python3 scripts/learn_leftover_rules.py --json     # 机器可读（便于积累成规则库）
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maccleaner.deps import list_applications  # noqa: E402
from maccleaner.uninstall import discover_related_paths  # noqa: E402


def candidates(home: Path, bundle_id: str, name: str) -> dict[str, Path]:
    """每种"规则"对应的候选路径（规则名 → 路径）。"""
    library = home / "Library"
    rules: dict[str, Path] = {}
    if bundle_id:
        rules["cache.bundle"] = library / "Caches" / bundle_id
        rules["cache.shipit"] = library / "Caches" / f"{bundle_id}.ShipIt"
        rules["support.bundle"] = library / "Application Support" / bundle_id
        rules["prefs.bundle"] = library / "Preferences" / f"{bundle_id}.plist"
        rules["savedstate.bundle"] = library / "Saved Application State" / f"{bundle_id}.savedState"
        rules["container.bundle"] = library / "Containers" / bundle_id
        rules["groupcontainer.bundle"] = library / "Group Containers" / bundle_id
        rules["webkit.bundle"] = library / "WebKit" / bundle_id
        rules["httpstorages.bundle"] = library / "HTTPStorages" / bundle_id
    if name:
        rules["support.name"] = library / "Application Support" / name
        rules["logs.name"] = library / "Logs" / name
        rules["cache.name"] = library / "Caches" / name
    return rules


def vendor_wide(home: Path, bundle_id: str, known: set[str]) -> list[Path]:
    """厂商级匹配：`com.vendor.*` 且**不是**任何已装应用的 bundle id。

    这类命中很可能是同一厂商的其它工具，所以只能算"按名称匹配"，不能默认勾选。
    """
    if bundle_id.count(".") < 2:
        return []
    vendor = ".".join(bundle_id.split(".")[:2])
    hits: list[Path] = []
    for folder in ("Caches", "Application Support", "Preferences", "Containers"):
        base = home / "Library" / folder
        if not base.is_dir():
            continue
        try:
            entries = base.iterdir()
        except OSError:
            continue
        for entry in entries:
            stem = entry.name.removesuffix(".plist")
            if stem.startswith(vendor + ".") and stem not in known:
                hits.append(entry)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()

    home = Path.home()
    apps = list_applications(home=home, limit=args.limit)
    known = {str(app.get("bundle_id") or "") for app in apps if app.get("bundle_id")}

    hits: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    per_app: list[dict[str, object]] = []
    vendor_hits: list[str] = []

    for app in apps:
        bundle_id = str(app.get("bundle_id") or "")
        name = str(app.get("name") or "")
        matched: list[str] = []
        for rule, path in candidates(home, bundle_id, name).items():
            try:
                exists = path.exists()
            except OSError:
                exists = False
            if exists:
                hits[rule] += 1
                matched.append(rule)
                examples.setdefault(rule, []).append(str(path).replace(str(home), "~"))
        wide = vendor_wide(home, bundle_id, known)
        if wide:
            hits["vendor.wide"] += 1
            vendor_hits.extend(str(p).replace(str(home), "~") for p in wide[:2])
        # 现有实现已经能找到的（用于对比"规则库多找到多少"）
        baseline = {item["path"] for item in discover_related_paths(home=home, bundle_id=bundle_id, app_name=name)}
        extra = [rule for rule in matched if rule in {"cache.shipit", "vendor.wide"}]
        per_app.append(
            {
                "name": name,
                "bundle_id": bundle_id,
                "rules": matched,
                "baseline_count": len(baseline),
                "would_add": extra,
            }
        )

    if args.json:
        print(json.dumps(
            {"apps": len(apps), "rule_hits": dict(hits), "per_app": per_app},
            ensure_ascii=False, indent=2,
        ))
        return 0

    print(f"采样应用: {len(apps)}（home={home}）")
    print("\n每种规则的命中数（命中最多的才值得写进规则库）：")
    for rule, count in hits.most_common():
        sample = (examples.get(rule) or [""])[0]
        print(f"  {rule:26s} {count:3d} 次   e.g. {sample}")
    if vendor_hits:
        print("\n厂商级示例（只能按名称匹配、默认不勾）：")
        for item in vendor_hits[:5]:
            print("  -", item)
    extra_apps = [item for item in per_app if item["would_add"]]
    print(f"\n规则库能**额外**覆盖的应用: {len(extra_apps)} 个")
    for item in extra_apps[:6]:
        print(f"  - {item['name']}: + {item['would_add']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
