"""`maccleaner-core` 入口：给原生界面 / agent 用的内核服务。

    maccleaner-core serve --stdio      # 一行请求一行响应（界面用这个）
    maccleaner-core --list-commands    # 打印可用命令与参数
    maccleaner-core --version

刻意**不**在这里提供 `scan`/`clean` 之类的子命令：那些已经在 `maccleaner` CLI 上，
重复一套只会让两边慢慢分叉（2026-10-22 决定：内核能力只有一个协议出口）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core_service import PROTOCOL_VERSION, CoreService, serve_stdio
from .deps import build_deps

COMMAND_HELP: dict[str, str] = {
    "ping": "连通性检查",
    "disk.summary": "只要容量（statfs，毫秒级，不读受保护目录）",
    "disk": "磁盘总览（含目录体积；需要完全磁盘访问权限）",
    "system": "系统状态（负载/内存/电池/节流/进程）",
    "skills": "本机可调用的 skill 列表",
    "apps": "已安装应用列表",
    "scan": "只读扫描，返回内核原始报告",
    "review.payload": "扫描并返回**分组好的**审阅数据（规则在内核）",
    "updates.list": "检查更新并返回分组好的清单（Sparkle 只留有更新的）",
    "orphans.list": "残留扫描并返回按目录分组的结果",
    "large.list": "大文件扫描并返回按体积排序的清单",
    "files.trash": "把路径移入废纸篓 args: paths[]（空数组拒绝）",
    "app.open": "打开一个 .app（Sparkle 应用内更新用，只接受存在的 .app）",
    "files.reveal": "在 Finder 中显示路径 args: path（必须存在）",
    "trash.open": "打开废纸篓（完成页用）",
    "tools.list": "AI 可调用的 MCP 工具与 stdio 命令清单",
    "clean": "执行清理 args: approved_ids[], selected_ids[]（空勾选会被拒绝）",
    "uninstall.plan": "卸载计划 args: path, bundle_id, name",
    "uninstall.apply": "执行卸载 args: path, item_ids[]（空勾选会被拒绝）",
    "updates.check": "检查更新（brew/npm/pip/gem/rustup/mas + Sparkle）",
    "updates.apply": "执行更新 args: ids[]",
    "orphans.scan": "残留扫描",
    "orphans.apply": "清理残留 args: paths[]（空数组拒绝）",
    "system.measure": "测量系统级目录体积（需一次管理员授权，只读）",
    "system.trash": "把系统级目录移入废纸篓 args: paths[]（需授权）",
}


def _build_deps(args: argparse.Namespace):
    home = Path(args.home).expanduser() if args.home else Path.home()
    root = Path(args.root).expanduser() if args.root else home
    state_root = Path(args.state_root).expanduser() if args.state_root else None
    return build_deps(home=home, root=root, state_root=state_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="maccleaner-core",
        description="Mac Cleaner 内核服务（stdio JSON）",
    )
    parser.add_argument("--home", help="替换家目录（自测用）")
    parser.add_argument("--root", help="扫描根（自测用）")
    parser.add_argument("--state-root", help="状态目录（自测用，避免污染 ~/.maccleaner）")
    parser.add_argument("--version", action="store_true", help="打印版本与协议版本")
    parser.add_argument("--list-commands", action="store_true", help="列出命令")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="起服务")
    serve.add_argument("--stdio", action="store_true", help="用标准输入输出通信（唯一支持的传输）")
    args = parser.parse_args(argv)

    if args.version:
        print(f"maccleaner-core {__version__} (protocol {PROTOCOL_VERSION})")
        return 0
    if args.list_commands:
        print(json.dumps(COMMAND_HELP, ensure_ascii=False, indent=2))
        return 0
    if args.command != "serve" or not args.stdio:
        parser.print_help(sys.stderr)
        return 2

    deps = _build_deps(args)
    return serve_stdio(deps, home=str(args.home) if getattr(args, "home", None) else None)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
