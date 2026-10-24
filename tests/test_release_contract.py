from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_packaging_defines_cli_and_mcp_entry_points(self) -> None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('maccleaner = "maccleaner.cli:main"', text)
        self.assertIn('maccleaner-mcp = "maccleaner.mcp_server:main"', text)
        self.assertIn('mcp = ["mcp>=1,<2"]', text)
        self.assertIn('license = { text = "Apache-2.0" }', text)
        self.assertIn('license-files = ["LICENSE"]', text)
        self.assertNotIn("License :: OSI Approved :: MIT License", text)

    def test_docs_and_skill_describe_installable_interfaces(self) -> None:
        for name in ("README.md", "README.en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("pipx install maccleaner", text)
            self.assertIn("git+https://github.com/Matoya-Amadeus/MacCleaner.git", text)
            # MCP 已内嵌进内核（2026-10-24），入口是 maccleaner-core mcp，不再有独立包
            self.assertIn("maccleaner-core mcp", text)
            self.assertIn("plan_id", text)
            self.assertIn("audit_storage", text)
            self.assertIn("apply_storage_plan", text)
            self.assertIn("maccleaner trace", text)
            self.assertIn('"name": "plan_storage"', text)
            self.assertIn('"name": "apply_storage_plan"', text)
            self.assertIn("python3 -m unittest discover -s tests -v", text)

        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("maccleaner audit", skill)
        self.assertIn("maccleaner-mcp", skill)
        self.assertIn("plan_id", skill)
        self.assertTrue((ROOT / "docs" / "mcp.md").is_file())

    def test_readmes_open_with_an_ai_section_then_install(self) -> None:
        """README 的顺序：先给 AI 的短说明 → 安装 → 给人类（截图 + 一句话）。

        2026-10-20 用户明确要求："安装之上的文本都能删掉；安装上加个标题给 AI 看的；
        截图上加个标题给人类看的"。顺序本身就是契约，别再塞回营销文案。
        """
        chinese = (ROOT / "README.md").read_text(encoding="utf-8")
        english = (ROOT / "README.en.md").read_text(encoding="utf-8")

        # 2026-10-20 用户改口：人类那半部分放最前面，AI 段随后，安装在其下。
        self.assertIn("# 给人类看的", chinese)
        self.assertIn("# 给 AI 看的", chinese)
        self.assertLess(chinese.index("# 给人类看的"), chinese.index("assets/screenshot.png"))
        self.assertLess(chinese.index("assets/screenshot.png"), chinese.index("# 给 AI 看的"))
        self.assertLess(chinese.index("# 给 AI 看的"), chinese.index('id="安装"'))

        self.assertIn("# For humans", english)
        self.assertIn("# For AI", english)
        self.assertLess(english.index("# For humans"), english.index("assets/screenshot"))
        self.assertLess(english.index("assets/screenshot"), english.index("# For AI"))
        self.assertLess(english.index("# For AI"), english.index('id="installation"'))

    def test_readmes_carry_one_real_screenshot_and_one_plain_sentence(self) -> None:
        """人类那半部分只要一张真实界面截图 + 一句大白话（用户原话）。"""
        chinese = (ROOT / "README.md").read_text(encoding="utf-8")
        english = (ROOT / "README.en.md").read_text(encoding="utf-8")

        self.assertIn("![Mac Cleaner 审阅页](assets/screenshot.png)", chinese)
        self.assertIn("EMM...就一般清理工具，跟 AI 说用 mac cleaner 清理，能直接调用", chinese)
        self.assertIn("![Mac Cleaner review page](assets/screenshot-en.png)", english)

        # 只留真实截图，不再有 SVG 头图/流程图；中英各一张（各自语言的界面）
        for text in (chinese, english):
            self.assertNotIn(".svg", text)
        self.assertEqual(chinese.count("assets/screenshot.png"), 1)
        self.assertEqual(english.count("assets/screenshot-en.png"), 1)
        self.assertTrue((ROOT / "assets" / "screenshot.png").is_file(), "中文截图必须在仓库里")
        self.assertTrue((ROOT / "assets" / "screenshot-en.png").is_file(), "英文截图必须在仓库里")

    def test_readmes_show_only_their_selected_language_in_the_footer(self) -> None:
        chinese = (ROOT / "README.md").read_text(encoding="utf-8")
        english = (ROOT / "README.en.md").read_text(encoding="utf-8")

        self.assertTrue(chinese.endswith("由 **AI·Maho** 和 **人类·Matoya** 共同维护\n"))
        self.assertNotIn("Maintained jointly by", chinese)
        self.assertTrue(english.endswith("Maintained jointly by **AI·Maho** and **Human·Matoya**\n"))
        self.assertNotIn("由 **AI·Maho** 和 **人类·Matoya** 共同维护", english)

    def test_readmes_link_each_other_for_language_switching(self) -> None:
        """点中文显示中文、点英文显示英文：两页互相链接，且都在最上面。"""
        chinese = (ROOT / "README.md").read_text(encoding="utf-8")
        english = (ROOT / "README.en.md").read_text(encoding="utf-8")

        self.assertIn("[English](README.en.md)", chinese)
        self.assertIn("[中文](README.md)", english)
        # 语言切换要在第一屏（第一行附近），不能埋在页尾
        self.assertLess(chinese.index("[English](README.en.md)"), 120)
        self.assertLess(english.index("[中文](README.md)"), 120)

    def test_ci_and_trusted_publisher_workflows_exist(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        publish = (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text(encoding="utf-8")

        self.assertIn("3.10", ci)
        self.assertIn("3.11", ci)
        self.assertIn("3.12", ci)
        self.assertIn(".[mcp]", ci)
        self.assertIn("python -m unittest discover -s tests -v", ci)
        self.assertIn("python -m build", ci)
        self.assertNotIn("status=$?", ci)
        self.assertIn("id-token: write", publish)
        self.assertIn("pypa/gh-action-pypi-publish", publish)


if __name__ == "__main__":
    unittest.main()
