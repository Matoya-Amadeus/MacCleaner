#!/usr/bin/env bash
# 编译 SwiftUI 原生界面，并把内核二进制一起塞进 .app。
#
#   bash scripts/build_native.sh            # 编译 + 组装 .app（build/native/MacCleaner.app）
#   bash scripts/build_native.sh --run      # 编译 + 启动
#
# 不需要 Xcode 工程：swiftc 直接编，手工组装 bundle（实测 Swift 6.4 可用）。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

OUT=".build/native"   # 隐藏目录：不参与 Spotlight/Launchpad 索引，避免出现"同一个 App 的两份"
APP="$OUT/MacCleaner.app"
CORE="$REPO/dist/maccleaner-core"

if [[ ! -x "$CORE/maccleaner-core" ]]; then
  echo "先打内核：bash scripts/build_core.sh" >&2
  exit 2
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "— 编译 SwiftUI —"
xcrun swiftc -swift-version 5 -O -parse-as-library \
  -o "$OUT/MacCleaner" \
  native/Sources/*.swift \
  -framework SwiftUI -framework AppKit

cp "$OUT/MacCleaner" "$APP/Contents/MacOS/MacCleaner"
cp native/Resources/Info.plist "$APP/Contents/Info.plist"

echo "— 嵌入内核（onedir）—"
cp -R "$CORE" "$APP/Contents/Resources/core"

# 开发期内核走仓库构建产物时可用：MACCLEANER_CORE_BINARY=... open ...
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "（跳过签名，本机自用可忽略）"

echo "构建完成：$APP"
if [[ "${1:-}" == "--run" ]]; then
  open "$APP"
fi
