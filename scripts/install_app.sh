#!/usr/bin/env bash
# 把构建好的原生 App 装到 ~/Applications，并做一次 ad-hoc 签名。
#
#   bash scripts/build_core.sh && bash scripts/build_native.sh && bash scripts/install_app.sh
#
# 为什么不直接双击 build/native 里的那个：构建目录随时会被清掉（`build_core.sh` 曾经
# 顺手把 build 整个删了），装到 ~/Applications 才是"日常用的那一份"。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/.build/native/MacCleaner.app"
DEST="$HOME/Applications/MacCleaner.app"

if [[ ! -d "$SRC" ]]; then
  echo "没有构建产物：先跑 bash scripts/build_core.sh && bash scripts/build_native.sh" >&2
  exit 2
fi

mkdir -p "$HOME/Applications"

# 只保留一份：这些位置如果还有同名/旧 bundle 的副本，一并清掉。
# （构建目录 .build/native 留着——那是源码产物，隐藏目录不会被 Spotlight/Launchpad 列出来。）
for legacy in \
  "/Applications/MacCleaner.app" \
  "$HOME/Applications/Mac Cleaner.app" \
  "$HOME/Applications/MacCleaner 2.app"; do
  if [[ -d "$legacy" ]]; then
    echo "移除旧副本：$legacy"
    rm -rf "$legacy"
  fi
done

rm -rf "$DEST"
cp -R "$SRC" "$DEST"
source "$(dirname "$0")/sign_app.sh"
sign_app "$DEST"

echo "已安装：$DEST"
echo "提示：首次打开后在磁盘页点一下「打开『完全磁盘访问权限』设置」，勾上 MacCleaner 再重启 App。"
