#!/usr/bin/env bash
# 可移植性实测（2026-10-19）。**不是 pytest 用例**（要拷仓库、装 .app），人工运行：
#
#     bash tests/acceptance_portability.sh
#
# 它回答的是"别人 clone 下来能不能跑"：把仓库复制到一个**无关路径**、用全新 HOME，
# 依次验 CLI、测试套件、以及从副本装出来的 .app（plist 里的仓库路径必须是副本路径）。
# 任何一处写死了作者机器上的路径，这一步就会红。
#
# 只验"能不能起"，不动任何真实文件：HOME 与状态目录都在临时目录里。
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
COPY="$WORK/elsewhere/MacCleaner"          # 故意换一个和原路径无关的目录
FAKE_HOME="$WORK/home"
APPS="$WORK/Applications"
mkdir -p "$(dirname "$COPY")" "$FAKE_HOME" "$APPS"

echo "=== ① 复制仓库（不带 .git）到 $COPY ==="
rsync -a --exclude '.git' --exclude '__pycache__' "$SRC/" "$COPY/"

echo "=== ② 用全新 HOME 跑 CLI（不依赖原路径） ==="
cd "$COPY" || exit 1
HOME="$FAKE_HOME" ./bin/maccleaner --help 2>&1 | head -3
echo "--- ui --no-open（3 秒后关掉）---"
HOME="$FAKE_HOME" PYTHONPATH="$COPY/src" no_proxy='*' NO_PROXY='*' \
  printf '{"id":"1","cmd":"disk.summary"}\n' | ./dist/maccleaner-core/maccleaner-core serve --stdio \
  > "$WORK/ui.out" 2> "$WORK/ui.err" &
UI_PID=$!
sleep 4
URL=$(grep -m1 '^http://' "$WORK/ui.out" || true)
if [[ -n "${URL}" ]]; then
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "${URL}" || echo 000)
  echo "  入口: ${URL:0:46}…  HTTP=${CODE}"
else
  echo "  ❌ 没拿到入口 URL"; tail -3 "$WORK/ui.err"
fi
kill $UI_PID 2>/dev/null

echo "=== ③ 从这份副本装 .app，再用它启动 ==="
bash "$COPY/scripts/install_launcher.sh" --prefix "$APPS" >/dev/null 2>&1
PLIST_REPO=$(/usr/libexec/PlistBuddy -c "Print :MacCleanerRepo" "$APPS/MacCleaner.app/Contents/Info.plist" 2>/dev/null)
echo "  plist 里的仓库路径: ${PLIST_REPO}"
echo "  与副本路径一致: $([[ "$PLIST_REPO" == "$COPY" ]] && echo 是 || echo 否)"

rm -f "$FAKE_HOME/Library/Logs/MacCleaner/launcher.log"
HOME="$FAKE_HOME" MACCLEANER_STATE_ROOT="$WORK/state2" \
  "$APPS/MacCleaner.app/Contents/MacOS/MacCleaner" >/dev/null 2>&1 &
APP_PID=$!
sleep 9
grep -E "loaded stage=|snapshot ok|repository not found" "$FAKE_HOME/Library/Logs/MacCleaner/launcher.log" 2>/dev/null | sed 's/^/  /'
kill -9 $APP_PID 2>/dev/null
pkill -f "$COPY" 2>/dev/null

echo "=== ④ 在这份副本里跑测试 ==="
cd "$COPY" && HOME="$FAKE_HOME" PYTHONPATH="$COPY/src" \
  /usr/local/bin/python3 -m unittest discover -s tests > "$WORK/tests.log" 2>&1
grep -E "^(OK|FAILED|Ran )" "$WORK/tests.log" | tail -2 | sed 's/^/  /'

echo "=== 清理 ==="
rm -rf "$WORK"
echo "done"
