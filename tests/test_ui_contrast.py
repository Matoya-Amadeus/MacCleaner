"""配色的对比度门限（2026-10-19，按美术方案的验收标准）。

为什么要有这条：美术方案里写了"正文 ≥4.5:1、次要 ≥3:1"，但**没算过就等于没验**。
第一次真算时浅色主题有三对不达标（muted 4.14、accent 4.35、on-accent 4.35）——
正是这条用例逼着把浅色的 `muted` 与 `accent` 调深。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STYLE = Path(__file__).resolve().parents[1] / "src" / "maccleaner" / "ui" / "theme.py"


def _style_text() -> str:
    return STYLE.read_text(encoding="utf-8").split('STYLE = """', 1)[1]


def _palette(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})", block))


def _luminance(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


class ContrastTests(unittest.TestCase):
    DARK_MIN = 4.5
    LIGHT_MIN = 4.5

    def _dark(self) -> dict[str, str]:
        return _palette(_style_text().split("@media", 1)[0])

    def _light(self) -> dict[str, str]:
        text = _style_text()
        return _palette(text.split("@media", 1)[1]) if "@media" in text else {}

    def test_dark_theme_meets_wcag_aa(self) -> None:
        palette = self._dark()
        pairs = {
            ("text", "bg"): 7.0,
            ("text-2", "bg"): 4.5,
            ("muted", "bg"): 4.5,
            ("muted", "surface"): 4.5,
            ("on-accent", "accent"): 4.5,
            ("accent", "surface"): 4.5,
            ("danger", "surface"): 4.5,
        }
        for (foreground, background), minimum in pairs.items():
            with self.subTest(pair=f"{foreground}/{background}"):
                value = contrast(palette[foreground], palette[background])
                self.assertGreaterEqual(
                    value, minimum, f"{foreground} 在 {background} 上只有 {value:.2f}:1"
                )

    def test_light_theme_meets_wcag_aa(self) -> None:
        palette = self._light()
        if not palette:
            self.skipTest("没有浅色变体")
        pairs = {
            ("text", "bg"): 7.0,
            ("text-2", "bg"): 4.5,
            ("muted", "bg"): 4.5,
            ("muted", "surface"): 4.5,
            ("on-accent", "accent"): 4.5,
            ("accent", "surface"): 4.5,
            ("danger", "surface"): 4.5,
        }
        for (foreground, background), minimum in pairs.items():
            with self.subTest(pair=f"{foreground}/{background}"):
                value = contrast(palette[foreground], palette[background])
                self.assertGreaterEqual(
                    value, minimum, f"{foreground} 在 {background} 上只有 {value:.2f}:1"
                )

    def test_font_sizes_only_come_from_tokens(self) -> None:
        """字号不许写裸 px：改字阶时漏掉一处，视觉层级就会歪。"""
        offenders = [
            match.group(0)
            for match in re.finditer(r"font-size:\s*\d+(?:\.\d+)?px", _style_text())
        ]
        self.assertEqual(offenders, [], f"这些字号没走 token：{offenders}")


if __name__ == "__main__":
    unittest.main()
