from __future__ import annotations

from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


class ReadmeAssetTests(unittest.TestCase):
    def test_header_workflow_cards_fit_inside_the_glass_panel(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        panel = root.find(".//svg:g[@filter]/svg:rect", SVG_NS)
        self.assertIsNotNone(panel)

        workflow = next(
            group
            for group in root.findall("svg:g", SVG_NS)
            if group.get("transform", "").startswith("translate(172 386)")
        )
        workflow_x = 172
        panel_left = float(panel.attrib["x"])
        panel_right = panel_left + float(panel.attrib["width"])

        for card in workflow.findall("svg:g", SVG_NS):
            rect = card.find("svg:rect", SVG_NS)
            if rect is None:
                continue
            match = re.fullmatch(r"translate\((\d+) 0\)", card.get("transform", ""))
            offset_x = float(match.group(1)) if match else 0.0
            card_left = workflow_x + offset_x + float(rect.attrib.get("x", "0"))
            card_right = card_left + float(rect.attrib["width"])
            self.assertGreaterEqual(card_left, panel_left)
            self.assertLessEqual(card_right, panel_right)

    def test_header_has_a_landscape_aspect_ratio_for_readme_rendering(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        view_box = [float(value) for value in root.attrib["viewBox"].split()]
        width = view_box[2]
        height = view_box[3]

        self.assertGreaterEqual(width / height, 1.75)


if __name__ == "__main__":
    unittest.main()
