"""AI 可调用清单（`tools.list`）的契约。

这一页是给人和 agent 看的"能力目录"，最容易出的问题是**目录与实现脱节**：
加了命令却没写说明，或者 MCP 工具加了却不在清单里。
所以这里不只是断言形状，还要比对两边数量。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from maccleaner.core_cli import COMMAND_HELP
from maccleaner.core_service import CoreService
from maccleaner.deps import SessionDeps

REPO_ROOT = Path(__file__).resolve().parents[1]


def _final(messages: list[dict]) -> dict:
    return messages[-1]


def _service() -> CoreService:
    return CoreService(SessionDeps(audit=lambda: {}, plan=lambda: {}, clean=lambda: {}))


class ToolsListTests(unittest.TestCase):
    def test_lists_mcp_tools_and_commands(self) -> None:
        data = _final(_service().dispatch({"id": "1", "cmd": "tools.list"}))["data"]
        self.assertGreaterEqual(len(data["mcp"]), 5)
        self.assertGreaterEqual(len(data["commands"]), 15)
        self.assertIn("serve --stdio", data["example"])
        for entry in data["mcp"] + data["commands"]:
            self.assertTrue(entry["name"], entry)
            self.assertTrue(entry["summary"], f"{entry['name']} 没有说明")

    def test_every_handler_has_a_summary(self) -> None:
        """有处理器就必须有说明——否则界面上会出现一条空白的"可调用项"。"""
        handlers = set(_service()._handlers())          # noqa: SLF001 - 故意的：契约测试要看全表
        missing = sorted(handlers - set(COMMAND_HELP))
        self.assertEqual(missing, [], f"这些命令没有写说明：{missing}")

    def test_mcp_catalog_matches_server(self) -> None:
        """MCP 工具清单必须和 `mcp_server.py` 里的 `@mcp.tool()` 数量一致。"""
        source = (REPO_ROOT / "src" / "maccleaner" / "mcp_server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        tools = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(isinstance(d, ast.Call) for d in node.decorator_list)
        ]
        data = _final(_service().dispatch({"id": "1", "cmd": "tools.list"}))["data"]
        listed = [entry["name"] for entry in data["mcp"]]
        self.assertEqual(sorted(listed), sorted(tools), "MCP 清单与实现不同步")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
