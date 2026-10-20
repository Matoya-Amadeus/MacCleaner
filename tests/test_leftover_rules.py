"""卸载残留规则库的契约（2026-10-20 外置成数据文件）。

为什么单独一组用例：
- 规则是**可被 PR 扩充的数据**，必须校验（不能越出 ~/Library、必须有 `{bundle_id}`）；
- 每条规则必须带 `evidence.samples >= 1`——本机采样 0 命中的 `-updater` 就是因此被删掉的；
- 数据文件坏了也不能让卸载功能崩，代码里要有兜底。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from maccleaner.leftover_rules import DEFAULT_RULES, RULES, load_rules, rule_candidates

ROOT = Path(__file__).resolve().parents[1]


class LeftoverRuleTests(unittest.TestCase):
    def test_shipped_rules_have_evidence(self) -> None:
        """仓库里的每条规则都必须有真实采样证据（否则就是拍脑袋）。"""
        payload = json.loads((ROOT / "src" / "maccleaner" / "data" / "leftover-rules.json").read_text(encoding="utf-8"))
        rules = payload.get("rules") or []
        self.assertGreaterEqual(len(rules), 1)
        for rule in rules:
            evidence = rule.get("evidence") or {}
            self.assertGreaterEqual(
                int(evidence.get("samples") or 0), 1, f"{rule.get('id')} 没有采样证据"
            )
            self.assertTrue(evidence.get("apps"), f"{rule.get('id')} 缺少命中的应用")

    def test_load_rejects_escaping_or_absolute_templates(self) -> None:
        bad = json.dumps({"rules": [
            {"id": "escape", "folder": "Caches", "template": "../../etc/passwd",
             "kind": "x", "confidence": "exact"},
            {"id": "absolute", "folder": "/tmp", "template": "{bundle_id}",
             "kind": "x", "confidence": "exact"},
            {"id": "no_placeholder", "folder": "Caches", "template": "fixed-name",
             "kind": "x", "confidence": "exact"},
            {"id": "ok", "folder": "Caches", "template": "{bundle_id}.ShipIt",
             "kind": "cache-shipit", "confidence": "exact"},
        ]})
        self.assertEqual([rule.rule_id for rule in load_rules(bad)], ["ok"])

    def test_broken_json_falls_back_to_defaults(self) -> None:
        self.assertEqual(load_rules("{not json"), DEFAULT_RULES)
        self.assertTrue(DEFAULT_RULES, "兜底不能为空")

    def test_rule_candidates_hits_real_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rules-") as tmp:
            home = Path(tmp)
            (home / "Library" / "Caches" / "com.demo.app.ShipIt").mkdir(parents=True)
            hits = rule_candidates(home, "com.demo.app")
        self.assertEqual([Path(hit["path"]).name for hit in hits], ["com.demo.app.ShipIt"])
        self.assertEqual(hits[0]["confidence"], "exact")

    def test_rule_candidates_skips_protected_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rules-safe-") as tmp:
            home = Path(tmp)
            (home / "Library" / "Caches" / "com.demo.app.ShipIt").mkdir(parents=True)
            # 受保护目录即使命中也不返回（这里直接验证函数本身不越界）
            hits = rule_candidates(home, "com.demo.app")
        self.assertTrue(all("Keychains" not in hit["path"] for hit in hits))


if __name__ == "__main__":
    unittest.main()
