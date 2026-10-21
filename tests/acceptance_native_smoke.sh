#!/usr/bin/env bash
# 原生窗口五步自测（2026-10-18）。
#
# **不是 pytest 用例**（要起 GUI），人工运行：
#
#     bash tests/acceptance_native_smoke.sh
#
# 背景：用户在真机上遇到"双击后黑屏 / Could not connect / 侧栏点了没反应"，而我此前只验证到
# "进程在跑""HTML 里有绑定"这一层。这个脚本让外壳在**真 WKWebView 里**依次点四个侧栏入口，
# 每步读一次 `data-stage` 并截图，然后逐步比对期望值。
#
# 通过标准：日志里 5 步 expected 与 actual 全部一致，且产出 5 张截图。
set -uo pipefail
APP="${HOME}/Applications/MacCleaner.app/Contents/MacOS/MacCleaner"
LOG="${HOME}/Library/Logs/MacCleaner/launcher.log"
T=$(mktemp -d)

if [[ ! -x "${APP}" ]]; then
  echo "未安装原生外壳：请先 bash scripts/install_launcher.sh" >&2
  exit 2
fi

pkill -f "MacCleaner.app/Contents/MacOS/MacCleaner" 2>/dev/null
pkill -f "python3 -m maccleaner ui" 2>/dev/null
sleep 1
rm -rf "${HOME}/Library/Logs/MacCleaner"

# 用**真实 HOME**起（这样应用列表与 skill 根都是用户真实看到的），
# 但状态隔离到临时目录：不污染 ~/.maccleaner，也不会撞单会话锁。
# 扫描目标指到临时目录：最后两步会真的清理，只允许动这里。
SCAN_HOME="$T/home"
mkdir -p "$SCAN_HOME/Library/Caches/Demo"
printf 'z%.0s' {1..8192} > "$SCAN_HOME/Library/Caches/Demo/big.cache"
touch -t 202001010000 "$SCAN_HOME/Library/Caches/Demo/big.cache"

MACCLEANER_SMOKE=1 MACCLEANER_STATE_ROOT="$T/state" MACCLEANER_SCAN_HOME="$SCAN_HOME" \
  "$APP" >/dev/null 2>&1 &
PID=$!

for _ in $(seq 1 90); do
  grep -q "smoke done" "${LOG}" 2>/dev/null && break
  sleep 1
done
kill "$PID" 2>/dev/null
pkill -f "MacCleaner.app/Contents/MacOS/MacCleaner" 2>/dev/null

echo "=== 步骤 ==="
grep -E "smoke step|smoke done" "${LOG}" 2>/dev/null | sed 's/^/  /'

# 逐行核对 expected == actual
mismatch=$(grep -E "smoke step" "${LOG}" 2>/dev/null | \
  sed -E 's/.*expected=([a-z-]+) actual=([a-z-]+).*/\1 \2/' | \
  awk '$1 != $2 {print}' | wc -l | tr -d ' ')
steps=$(grep -cE "smoke step" "${LOG}" 2>/dev/null || echo 0)
shots=$(ls -1 "${HOME}/Library/Logs/MacCleaner/"smoke-*.png 2>/dev/null | wc -l | tr -d ' ')

echo "=== 文件级判定（页面到位 ≠ 真的清了） ==="
if [[ -d "${SCAN_HOME}/Library/Caches/Demo" ]]; then
  echo "  ❌ 目标目录仍在：清理没有真的发生"
  cleaned=0
else
  echo "  ✓ 目标目录已移走"
  cleaned=1
fi
trash_count=$(ls -1 "${SCAN_HOME}/.Trash" 2>/dev/null | wc -l | tr -d ' ')
echo "  ✓ 废纸篓里 ${trash_count} 项（应为 1）"
[[ "${trash_count}" -ge 1 ]] || cleaned=0

echo "=== 判定 ==="
echo "  步骤数=${steps} 不一致=${mismatch} 截图=${shots} 文件已移动=${cleaned}"

if [[ "${steps}" -ne 14 || "${mismatch}" -ne 0 || "${shots}" -ne 14 || "${cleaned}" -ne 1 ]]; then
  echo "❌ 原生窗口自测未通过"
  exit 1
fi
echo "✅ 原生窗口十四步全部通过（含确认清理，截图见 ~/Library/Logs/MacCleaner/）"

rm -rf "$T"
