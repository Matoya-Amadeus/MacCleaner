from __future__ import annotations

from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


class ReadmeAssetTests(unittest.TestCase):
    def _glass_panel(self, root: ET.Element) -> ET.Element:
        panel = root.find(".//svg:g[@filter]/svg:rect", SVG_NS)
        self.assertIsNotNone(panel)
        return panel

    def test_header_workflow_cards_fit_inside_the_glass_panel(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        panel = self._glass_panel(root)

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

    def test_header_workflow_has_symmetric_glass_panel_padding(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        panel = self._glass_panel(root)
        workflow = next(
            group
            for group in root.findall("svg:g", SVG_NS)
            if group.get("transform", "").startswith("translate(")
            and "386" in group.get("transform", "")
        )
        cards = [
            group
            for group in workflow.findall("svg:g", SVG_NS)
            if group.find("svg:rect", SVG_NS) is not None
        ]
        workflow_x = float(re.search(r"translate\((\d+)", workflow.attrib["transform"]).group(1))
        card_bounds = []
        for card in cards:
            rect = card.find("svg:rect", SVG_NS)
            offset = re.search(r"translate\((\d+) 0\)", card.get("transform", ""))
            card_x = workflow_x + (float(offset.group(1)) if offset else 0.0)
            card_bounds.append((card_x, card_x + float(rect.attrib["width"])))

        panel_left = float(panel.attrib["x"])
        panel_right = panel_left + float(panel.attrib["width"])
        self.assertEqual(min(left for left, _ in card_bounds) - panel_left,
                         panel_right - max(right for _, right in card_bounds))

    def test_header_has_a_landscape_aspect_ratio_for_readme_rendering(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        view_box = [float(value) for value in root.attrib["viewBox"].split()]
        width = view_box[2]
        height = view_box[3]

        self.assertGreaterEqual(width / height, 1.75)

    def test_header_badge_labels_are_centered_in_consistent_pills(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        badges = next(
            group
            for group in root.findall("svg:g", SVG_NS)
            if group.get("transform", "").startswith("translate(")
            and "568" in group.get("transform", "")
        )
        pills = badges.findall("svg:rect", SVG_NS)
        labels = badges.findall("svg:text", SVG_NS)

        self.assertEqual(3, len(pills))
        self.assertEqual(3, len(labels))
        self.assertEqual({"260"}, {pill.attrib["width"] for pill in pills})
        self.assertEqual("middle", badges.attrib.get("text-anchor"))
        for pill, label in zip(pills, labels):
            center_x = float(pill.attrib.get("x", "0")) + float(pill.attrib["width"]) / 2
            self.assertEqual(center_x, float(label.attrib["x"]))

    def test_header_badge_row_is_centered_in_the_glass_panel(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        panel = self._glass_panel(root)
        badges = next(
            group
            for group in root.findall("svg:g", SVG_NS)
            if group.get("transform", "").startswith("translate(")
            and "568" in group.get("transform", "")
        )
        badges_x = float(re.search(r"translate\((\d+)", badges.attrib["transform"]).group(1))
        pills = badges.findall("svg:rect", SVG_NS)
        left = badges_x + min(float(pill.attrib.get("x", "0")) for pill in pills)
        right = badges_x + max(
            float(pill.attrib.get("x", "0")) + float(pill.attrib["width"])
            for pill in pills
        )
        panel_left = float(panel.attrib["x"])
        panel_right = panel_left + float(panel.attrib["width"])

        self.assertEqual(left - panel_left, panel_right - right)

    def test_header_workflow_cards_use_one_centered_alignment_system(self) -> None:
        root = ET.parse(ROOT / "assets" / "readme-header.svg").getroot()
        workflow = next(
            group
            for group in root.findall("svg:g", SVG_NS)
            if group.get("transform", "").startswith("translate(172 386)")
        )
        cards = [
            group
            for group in workflow.findall("svg:g", SVG_NS)
            if group.find("svg:rect", SVG_NS) is not None
        ]

        self.assertEqual(4, len(cards))
        self.assertEqual(
            {"190"},
            {card.find("svg:rect", SVG_NS).attrib["width"] for card in cards},
        )
        for card in cards:
            rect = card.find("svg:rect", SVG_NS)
            center_x = float(rect.attrib.get("x", "0")) + float(rect.attrib["width"]) / 2
            self.assertEqual("middle", card.attrib.get("text-anchor"))
            for label in card.findall("svg:text", SVG_NS):
                self.assertEqual(center_x, float(label.attrib["x"]))


if __name__ == "__main__":
    unittest.main()
