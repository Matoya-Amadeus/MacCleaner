#!/usr/bin/env bash
# 用**沙盒家目录**启动 App：验收 / 演示用，不碰真实数据。
#
#   bash scripts/dev_sandbox.sh [沙盒目录]
#
# 为什么不能 `launchctl setenv` 或 `open --env`：
# 两者都传不到 GUI App（实测 2026-10-24）。必须**直接执行二进制**，
# 环境变量才会进入 App 进程、再传给内核子进程。
set -euo pipefail

APP="/Applications/MacCleaner.app"
SANDBOX="${1:-/tmp/acc-home}"
BIN="$APP/Contents/MacOS/MacCleaner"

if [[ ! -x "$BIN" ]]; then
  echo "没装 App：先跑 bash scripts/build_native.sh && bash scripts/install_app.sh" >&2
  exit 2
fi

# 造一点"够旧"的数据：home-caches 只收 1 天以上的缓存（避免清正在写的文件），
# 刚创建的文件会被正确跳过——验收时容易误以为"扫不到"。
mkdir -p "$SANDBOX/Library/Caches/com.demo.big" \
         "$SANDBOX/Library/Logs" \
         "$SANDBOX/Downloads" \
         "$SANDBOX/Applications"
if [[ ! -f "$SANDBOX/Library/Caches/com.demo.big/blob.bin" ]]; then
  head -c 12000000 /dev/zero > "$SANDBOX/Library/Caches/com.demo.big/blob.bin"
fi
find "$SANDBOX" -exec touch -t "$(date -v-3d +%Y%m%d%H%M)" {} \; 2>/dev/null || true

osascript -e 'quit app "MacCleaner"' 2>/dev/null || true
sleep 1

echo "沙盒：$SANDBOX"
echo "启动：$BIN"
(MACCLEANER_CORE_HOME="$SANDBOX" \
 MACCLEANER_DEV_NO_BIO=1 \
 nohup "$BIN" > /tmp/maccleaner-sandbox.log 2>&1 &)

sleep 3
pgrep -f "$APP/Contents/MacOS/MacCleaner" >/dev/null && echo "已启动（日志：/tmp/maccleaner-sandbox.log）"
