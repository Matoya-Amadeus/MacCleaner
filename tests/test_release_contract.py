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
        self.assertIn('license = "MIT"', text)
        self.assertIn('license-files = ["LICENSE"]', text)
        self.assertNotIn("License :: OSI Approved :: MIT License", text)

    def test_docs_and_skill_describe_installable_interfaces(self) -> None:
        for name in ("README.md", "README.en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("pipx install maccleaner", text)
            self.assertIn('pipx install "maccleaner[mcp]"', text)
            self.assertIn("git+https://github.com/Matoya-Amadeus/MacCleaner.git", text)
            self.assertIn("maccleaner-mcp", text)
            self.assertIn("plan_id", text)
            self.assertIn("python3 -m unittest discover -s tests -v", text)

        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("maccleaner audit", skill)
        self.assertIn("maccleaner-mcp", skill)
        self.assertIn("plan_id", skill)
        self.assertTrue((ROOT / "docs" / "mcp.md").is_file())

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
