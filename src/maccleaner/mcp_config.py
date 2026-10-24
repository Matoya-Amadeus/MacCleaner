"""给 Claude Code / Codex 生成与安装 MCP 配置。

**为什么需要**：MCP 工具列表是客户端在**会话启动时**拉取的，服务端无法把自己"塞进"
正在运行的会话。所以 agent 能做的只有：写配置 + 提示用户重启会话。

**安全边界**（都是硬要求）：
- 默认只**打印**，不写任何文件；写盘必须显式 `--install` + `--yes`；
- 写之前备份原文件（`.bak-YYYYmmdd-HHMMSS`）；
- 幂等：已经配过就跳过，不重复追加；
- 只增 `mac-cleaner` 一个条目，**不碰**其他 server。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SERVER_NAME = "mac-cleaner"


def detect_command() -> str:
    """给客户端用的启动命令。

    优先用 PATH 里的 `maccleaner-core`；没有就退回 App 内的绝对路径
    （用户装完 App 但没装 CLI 时，这条是唯一能用的）。
    """
    found = shutil.which("maccleaner-core")
    if found:
        return found
    bundled = Path("/Applications/MacCleaner.app/Contents/Resources/core/maccleaner-core")
    if bundled.exists():
        return str(bundled)
    return "maccleaner-core"


def claude_entry(command: str | None = None) -> dict[str, object]:
    return {"type": "stdio", "command": command or detect_command(), "args": ["mcp"], "env": {}}


def claude_snippet(command: str | None = None) -> str:
    return json.dumps({"mcpServers": {SERVER_NAME: claude_entry(command)}}, ensure_ascii=False, indent=2)


def codex_snippet(command: str | None = None) -> str:
    cmd = command or detect_command()
    return (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f'command = "{cmd}"\n'
        f'args = ["mcp"]\n'
    )


def print_config(client: str, command: str | None = None) -> str:
    """只读：返回该客户端要加的配置片段。"""
    target = (client or "claude").lower()
    if target.startswith("codex"):
        return codex_snippet(command)
    return claude_snippet(command)


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    return backup


def install_claude(command: str | None = None) -> dict[str, object]:
    """写 Claude Code 配置。

    如果 `claude` CLI 在，用它的官方命令（最稳）；否则编辑 `~/.claude.json`。
    """
    cmd = command or detect_command()

    if shutil.which("claude"):
        done = subprocess.run(
            ["claude", "mcp", "add", SERVER_NAME, "--", cmd, "mcp"],
            capture_output=True,
            text=True,
        )
        if done.returncode == 0:
            return {"client": "claude", "written": True, "how": "claude mcp add", "path": ""}
        # 失败就落回文件编辑，不直接报错——不同版本 CLI 参数不同。

    config_path = Path.home() / ".claude.json"
    data: dict[str, object] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {"client": "claude", "written": False, "reason": "配置不是合法 JSON，未改动"}

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    if SERVER_NAME in servers:
        return {"client": "claude", "written": False, "reason": "已经配置过", "path": str(config_path)}

    servers[SERVER_NAME] = claude_entry(cmd)
    data["mcpServers"] = servers

    backup = _backup(config_path)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "client": "claude",
        "written": True,
        "how": "编辑 ~/.claude.json",
        "path": str(config_path),
        "backup": str(backup) if backup else "",
    }


def install_codex(command: str | None = None) -> dict[str, object]:
    """在 `~/.codex/config.toml` 末尾追加一段。

    用**文本追加**而不是解析重写：TOML 解析回来会丢掉用户的注释与顺序，
    而这里只需要加一个表。
    """
    cmd = command or detect_command()
    config_path = Path.home() / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if f"[mcp_servers.{SERVER_NAME}]" in existing:
        return {"client": "codex", "written": False, "reason": "已经配置过", "path": str(config_path)}

    backup = _backup(config_path)
    block = ("\n" if existing and not existing.endswith("\n") else "") + "\n" + codex_snippet(cmd)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(block)
    return {
        "client": "codex",
        "written": True,
        "how": "追加 ~/.codex/config.toml",
        "path": str(config_path),
        "backup": str(backup) if backup else "",
    }


def install(client: str, command: str | None = None) -> dict[str, object]:
    target = (client or "auto").lower()
    if target == "auto":
        # 两个目录都存在就都装；都没有就按 claude 处理（更常见）。
        results = []
        if (Path.home() / ".codex").exists():
            results.append(install_codex(command))
        if (Path.home() / ".claude.json").exists() or shutil.which("claude"):
            results.append(install_claude(command))
        if not results:
            results.append(install_claude(command))
        return {"client": "auto", "results": results}
    if target.startswith("codex"):
        return install_codex(command)
    return install_claude(command)
