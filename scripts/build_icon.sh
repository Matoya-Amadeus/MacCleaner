#!/usr/bin/env bash
# 重新生成 App 图标（改配色/形状后跑这个）。
#
#   bash scripts/build_icon.sh
#
# 产出：native/Resources/AppIcon-1024.png（源图，便于查看）
#       native/Resources/AppIcon.icns（打包用，build_native.sh 会拷进 App）
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

xcrun swiftc -O -o /tmp/mc_make_icon scripts/make_icon.swift \
  -framework AppKit -framework CoreGraphics
/tmp/mc_make_icon buddy native/Resources/AppIcon-1024.png 1024

ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" native/Resources/AppIcon-1024.png \
    --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" native/Resources/AppIcon-1024.png \
    --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "$ICONSET" -o native/Resources/AppIcon.icns
echo "图标已更新：native/Resources/AppIcon.icns"
