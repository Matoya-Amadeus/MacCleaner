#!/usr/bin/env bash
# 真浏览器点侧栏（2026-10-18）。
#
# **不是 pytest 用例**（故意用 .sh，且需要 agent-browser）：人工运行
#
#     bash tests/acceptance_nav_click.sh
#
# 为什么要它：侧栏曾出现"点了完全没反应"，而单测只能断言"HTML 里绑定了属性"，
# 断言不了"点了真的会换页"。这条用真浏览器逐步点击并等 stage 变化，四步必须全过。
#
# 注意：`updates-open` 会跑真实的 `brew outdated`（包多时数秒），所以每步**等 stage 变化**，
# 不能用固定 sleep——那会把"慢"误判成"坏"。
# 注意：`updates-open` 会跑真实的 `brew outdated`（几十个包，数秒），所以每步要**等 stage 变化**，
# 不能固定 sleep——那会把"慢"误判成"坏"。
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T=$(mktemp -d)
HOME_T="$T/home"
mkdir -p "$HOME_T/Library/Caches/Demo"
printf 'z%.0s' {1..4096} > "$HOME_T/Library/Caches/Demo/big.cache"
touch -t 202001010000 "$HOME_T/Library/Caches/Demo/big.cache"

cd "$REPO"
PYTHONPATH=src no_proxy='*' NO_PROXY='*' /usr/local/bin/python3 -m maccleaner ui --no-open \
  --home "$HOME_T" --root "$HOME_T" --state-root "$T/state" > "$T/ui.out" 2> "$T/ui.err" &
UI_PID=$!

for _ in $(seq 1 100); do
  URL=$(grep -m1 '^http://' "$T/ui.out" 2>/dev/null || true)
  [ -n "${URL:-}" ] && break
  sleep 0.2
done
if [ -z "${URL:-}" ]; then
  echo "拿不到 URL"; tail -5 "$T/ui.err"; kill $UI_PID 2>/dev/null; exit 1
fi
echo "URL: ${URL%%/bootstrap*}"

stage() { agent-browser eval 'document.documentElement.dataset.stage || "(none)"' 2>/dev/null | tr -d '"' | tail -1; }

wait_for() {   # wait_for <期望 stage> <超时秒>
  local want="$1" limit="${2:-30}" elapsed=0 got=""
  while [ "$elapsed" -lt "$limit" ]; do
    got=$(stage)
    [ "$got" = "$want" ] && { echo "$got"; return 0; }
    sleep 0.5; elapsed=$((elapsed + 1))
  done
  echo "$got"; return 1
}

agent-browser open "$URL" >/dev/null 2>&1
echo "初始 stage: $(wait_for idle 15)"

pass=0; fail=0
check() {  # action, expected stage
  local action="$1" want="$2"
  agent-browser click "button[data-nav-action=\"$action\"]" >/dev/null 2>&1
  local got; got=$(wait_for "$want" 40)
  if [ "$got" = "$want" ]; then echo "  ✓ 点 $action → $got"; pass=$((pass+1));
  else echo "  ✗ 点 $action → 期望 $want，实际 $got"; fail=$((fail+1)); fi
}

check updates-open updates
check uninstall-list uninstall-list
check skills-open skills
check start review

echo "RESULT: pass=$pass fail=$fail"
agent-browser close >/dev/null 2>&1 || true
kill $UI_PID 2>/dev/null; wait $UI_PID 2>/dev/null
rm -rf "$T"
[ "$fail" -eq 0 ]
