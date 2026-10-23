#!/usr/bin/env bash
# 把内核打成**不依赖系统 python** 的二进制，供 SwiftUI App 内嵌。
#
#   bash scripts/build_core.sh              # onedir（默认，启动 ~105ms，16 MB）
#   bash scripts/build_core.sh --onefile    # 单文件（分发方便，但每次启动解压 ~1.2s）
#
# 为什么默认 onedir（2026-10-22 实测）：
#   启动：onedir 105 ms / onefile 1204 ms（onefile 每次都要解压到临时目录）
#   App 冷启动目标 < 0.4 s，onefile 一个人就吃掉 1.2 s。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MODE="onedir"
if [[ "${1:-}" == "--onefile" ]]; then MODE="onefile"; fi

PY="${PYTHON:-python3}"
VENV="${MACCLEANER_BUILD_VENV:-/tmp/maccleaner-build-venv}"
if [[ ! -x "$VENV/bin/pyinstaller" ]]; then
  echo "准备构建环境：$VENV"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --disable-pip-version-check pyinstaller
fi

# MCP 要**打进安装包**，不能让用户再 `pipx install "maccleaner[mcp]"`（2026-10-23 用户要求）。
if ! "$VENV/bin/python" -c "import mcp" >/dev/null 2>&1; then
  echo "安装 MCP 依赖（打进包体）"
  "$VENV/bin/pip" install -q --disable-pip-version-check "mcp>=1,<2"
fi

# 只清自己的产物：`build/native` 是 build_native.sh 的目录，以前这里 `rm -rf build`
# 会把它一起删掉（2026-10-22 踩到：打完内核，原生 app 不见了）。
rm -rf build/pyinstaller dist maccleaner-core.spec
"$VENV/bin/pyinstaller" "--$MODE" \
  --name maccleaner-core \
  --paths src \
  --noupx \
  --workpath build/pyinstaller \
  --collect-submodules mcp.server \
  --collect-submodules mcp.shared \
  --collect-data mcp \
  --copy-metadata mcp \
  --hidden-import mcp \
  --hidden-import mcp.server.fastmcp \
  --hidden-import maccleaner.mcp_server \
  --log-level WARN \
  scripts/core_entry.py

BIN="dist/maccleaner-core/maccleaner-core"
[[ "$MODE" == "onefile" ]] && BIN="dist/maccleaner-core"

# 冒烟：必须在**干净环境**下能跑（没有 PATH/PYTHONPATH，证明不依赖系统 python）
echo "— 干净环境自检 —"
env -i "$REPO/$BIN" --version
echo '{"id":"1","cmd":"ping"}' | env -i "$REPO/$BIN" serve --stdio

echo "构建完成：$BIN ($(du -sh "dist/maccleaner-core" | cut -f1))"
