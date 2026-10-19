#!/usr/bin/env bash
# "关闭 app 是否真把功能都关掉"验收（2026-10-19）。
#
# **不是 pytest 用例**（要起 GUI + 发 AppleEvent），人工运行：
#
#     bash tests/acceptance_quit.sh
#
# 用 osascript 发 quit（等价点 Cmd+Q / 关窗口 → app.terminate），随后检查四件事：
#   ① 外壳进程没了 ② 后端进程没了 ③ 端口不再监听 ④ 状态文件 stage=cancelled / active=false
#
# 第 ④ 项是 2026-10-19 用户反馈"关闭 app 功能没关干净"的实质：SIGTERM 默认直接杀进程，
# 不写终态 → 下一个读状态的地方会以为会话还活着。修法见 session._install_signal_handlers。
set -uo pipefail
APP="${HOME}/Applications/MacCleaner.app/Contents/MacOS/MacCleaner"
LOG="${HOME}/Library/Logs/MacCleaner/launcher.log"
T=$(mktemp -d)

pkill -f "MacCleaner.app/Contents/MacOS/MacCleaner" 2>/dev/null
pkill -f "python3 -m maccleaner ui" 2>/dev/null
sleep 1
rm -rf "${HOME}/Library/Logs/MacCleaner"

echo "启动 app（临时 HOME=${T}）"
HOME="$T" "$APP" >/dev/null 2>&1 &
APP_PID=$!

for _ in $(seq 1 60); do
  grep -q "loaded stage=" "$LOG" 2>/dev/null && break
  sleep 0.5
done

url=$(grep -o "url=http://127.0.0.1:[0-9]*" "$LOG" | tail -1 | sed 's/url=//')
port="${url##*:}"
echo "  页面已加载，端口=${port:-未知}"
echo "  关闭前：后端进程=$(pgrep -fl 'python3 -m maccleaner ui' | wc -l | tr -d ' ')  监听=$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | wc -l | tr -d ' ')"

echo "发送 quit（等价关闭窗口/Cmd+Q）"
osascript -e 'tell application "MacCleaner" to quit' >/dev/null 2>&1 || kill "$APP_PID" 2>/dev/null

sleep 5
echo "  关闭后：外壳进程=$(pgrep -fl 'MacCleaner.app/Contents/MacOS/MacCleaner' | wc -l | tr -d ' ') \
后端进程=$(pgrep -fl 'python3 -m maccleaner ui' | wc -l | tr -d ' ') \
监听=$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | wc -l | tr -d ' ')"

state=$(/usr/local/bin/python3 -c "
import json, pathlib
p = pathlib.Path('$T/.maccleaner/state/session.json')
print(json.loads(p.read_text()) if p.is_file() else 'missing')" 2>/dev/null)
echo "  状态文件: $state"

pkill -f "MacCleaner.app/Contents/MacOS/MacCleaner" 2>/dev/null
pkill -f "python3 -m maccleaner ui" 2>/dev/null
rm -rf "$T"
