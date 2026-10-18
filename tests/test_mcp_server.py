from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from maccleaner.mcp_server import build_mcp_server
from maccleaner.mcp_service import StorageService

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ModuleNotFoundError:
    MCP_AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]


class McpEntryPointTests(unittest.TestCase):
    @unittest.skipIf(MCP_AVAILABLE, "checks the optional-dependency path only")
    def test_mcp_entrypoint_explains_missing_optional_dependency(self) -> None:
        env = dict(os.environ)
        source_root = str(ROOT / "src")
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "maccleaner.mcp_server"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn('pipx install "maccleaner[mcp]"', result.stderr)


@unittest.skipUnless(MCP_AVAILABLE, "install the mcp extra to exercise the transport")
class McpTransportTests(unittest.TestCase):
    def test_stdio_server_advertises_only_the_public_tool_contract(self) -> None:
        async def check() -> list[str]:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "maccleaner.mcp_server"],
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return [tool.name for tool in tools.tools]

        # 2026-10-18：卸载与更新也成了一等 agent 入口，公开面从 4 个变 7 个。
        self.assertEqual(
            set(asyncio.run(check())),
            {
                "apply_storage_plan",
                "audit_storage",
                "plan_storage",
                "trace_storage",
                "uninstall_plan",
                "updates_check",
                "updates_apply",
            },
        )

    def test_tool_adapter_applies_only_the_selected_plan_target(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="maccleaner-mcp-transport-"))
        approved_file = root / "Library" / "Caches" / "approved" / "cache.bin"
        blocked_file = root / "Library" / "Logs" / "blocked" / "log.txt"
        approved_file.parent.mkdir(parents=True)
        blocked_file.parent.mkdir(parents=True)
        approved_file.write_bytes(b"cache")
        blocked_file.write_bytes(b"log")
        old = time.time() - 9 * 24 * 60 * 60
        os.utime(approved_file, (old, old))
        os.utime(blocked_file, (old, old))
        server = build_mcp_server(StorageService(home=root, root=root))

        async def apply_plan() -> tuple[dict[str, object], dict[str, object]]:
            tools = await server.list_tools()
            # 2026-10-18：新增卸载与更新入口（uninstall_plan / updates_check / updates_apply），
            # 工具集合从 4 个变 7 个——这条断言要跟着产品面走，不是放宽。
            self.assertEqual(
                {tool.name for tool in tools},
                {
                    "audit_storage",
                    "plan_storage",
                    "trace_storage",
                    "apply_storage_plan",
                    "uninstall_plan",
                    "updates_check",
                    "updates_apply",
                },
            )
            apply_tool = next(tool for tool in tools if tool.name == "apply_storage_plan")
            self.assertEqual(
                set(apply_tool.inputSchema["properties"]),
                # plan_digest：回传计划摘要，用来证明"执行的就是给人看的那份计划"。
                {"plan_id", "approved_targets", "confirm_targets", "plan_digest"},
            )
            _plan_content, plan = await server.call_tool("plan_storage", {})
            _apply_content, applied = await server.call_tool(
                "apply_storage_plan",
                {"plan_id": plan["plan_id"], "approved_targets": ["home-caches"]},
            )
            return plan, applied

        plan, applied = asyncio.run(apply_plan())

        self.assertIn("home-caches", plan["applicable_target_ids"])
        self.assertFalse(approved_file.exists())
        self.assertTrue(blocked_file.exists())
        statuses = {item["target_id"]: item["status"] for item in applied["plan_items"]}
        self.assertEqual(statuses["home-caches"], "cleaned")
        self.assertEqual(statuses["home-logs"], "blocked")


if __name__ == "__main__":
    unittest.main()
