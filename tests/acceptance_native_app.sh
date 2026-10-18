#!/usr/bin/env bash
# 原生 .app 验收（2026-10-18）。
#
# **不是 pytest 用例**（要起 GUI 进程），人工运行：
#
#     bash tests/acceptance_native_app.sh
#
# 为什么必须有它：用户遇到过"双击后黑屏"，而我当时只验证了"进程在跑、session.json 生成了"——
# 进程活着不等于页面渲染了。外壳现在会把加载结果写进
# `~/Library/Logs/MacCleaner/launcher.log`，并在 1.2 秒后把窗口内容截成
# `launcher-snapshot.png`。本脚本只认这两样证据：
#
#   ✓ 日志里出现 `loaded stage=<非 none>`  → HTML + JS 真的执行了
#   ✓ 快照存在且大小 > 20KB                → 画面不是纯色/空白
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${HOME}/Applications/MacCleaner.app"
BIN="${APP}/Contents/MacOS/MacCleaner"
LOG_DIR="${HOME}/Library/Logs/MacCleaner"
LOG="${LOG_DIR}/launcher.log"
SHOT="${LOG_DIR}/launcher-snapshot.png"

if [[ ! -x "${BIN}" ]]; then
  echo "未安装原生外壳：请先运行 bash scripts/install_launcher.sh" >&2
  exit 2
fi

rm -f "${LOG}" "${SHOT}"
WORK="$(mktemp -d)"
# 用临时 HOME 起，避免污染真实的 ~/.maccleaner 状态与会话锁。
HOME="${WORK}" "${BIN}" >/dev/null 2>&1 &
PID=$!

loaded=""
for _ in $(seq 1 60); do
  if grep -q "loaded stage=" "${LOG}" 2>/dev/null; then
    loaded=$(grep -o "loaded stage=[^ ]*" "${LOG}" | tail -1)
    break
  fi
  sleep 0.5
done

sleep 2
kill "${PID}" 2>/dev/null
wait "${PID}" 2>/dev/null

echo "日志:"
tail -3 "${LOG}" 2>/dev/null | sed 's/^/  /'

if [[ -z "${loaded}" || "${loaded}" == "loaded stage=(none)" ]]; then
  echo "❌ 页面未渲染（日志里没有 loaded stage=<stage>）"
  exit 1
fi

size=0
[[ -f "${SHOT}" ]] && size=$(stat -f%z "${SHOT}" 2>/dev/null || echo 0)
if (( size < 20000 )); then
  echo "❌ 快照缺失或过小（${size} 字节）：画面可能仍是空白"
  exit 1
fi

echo "✅ 原生窗口渲染正常：${loaded}，快照 ${size} 字节"
echo "   可人工看一眼: open ${SHOT}"
rm -rf "${WORK}"
