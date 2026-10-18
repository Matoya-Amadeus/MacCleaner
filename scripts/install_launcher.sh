#!/usr/bin/env bash
# 生成一个可双击的 MacCleaner.app（2026-10-18）。
#
# 为什么需要它：`maccleaner ui` 是个命令行入口，但产品要能"独立单用"——双击图标就打开界面。
# 这里只做**打包**（Info.plist / 图标 / 启动脚本），不含任何清理逻辑；逻辑永远在 `src/maccleaner/`。
#
# 用法：
#   bash scripts/install_launcher.sh                # 装到 ~/Applications/MacCleaner.app
#   bash scripts/install_launcher.sh --refresh      # 顺带重启 Dock 刷新图标缓存
#   bash scripts/install_launcher.sh --prefix /tmp  # 换安装位置（测试用）
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${HOME}/Applications"
REFRESH=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --refresh) REFRESH=1; shift ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

APP="${PREFIX}/MacCleaner.app"
CONTENTS="${APP}/Contents"

mkdir -p "${CONTENTS}/MacOS" "${CONTENTS}/Resources"

cat > "${CONTENTS}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>MacCleaner</string>
  <key>CFBundleDisplayName</key><string>MacCleaner</string>
  <key>CFBundleIdentifier</key><string>local.maho.maccleaner.launcher</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
</dict>
</plist>
PLIST

# 启动脚本：优先用仓库内的源码（免安装），退回到 PATH 上的 maccleaner。
cat > "${CONTENTS}/MacOS/launch" <<LAUNCH
#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="${REPO_DIR}"
if [[ -d "\${REPO_DIR}/src/maccleaner" ]]; then
  export PYTHONPATH="\${REPO_DIR}/src\${PYTHONPATH:+:\${PYTHONPATH}}"
  exec /usr/bin/env python3 -m maccleaner ui "\$@"
fi
exec /usr/bin/env maccleaner ui "\$@"
LAUNCH
chmod +x "${CONTENTS}/MacOS/launch"

if [[ -f "${REPO_DIR}/assets/AppIcon.icns" ]]; then
  cp "${REPO_DIR}/assets/AppIcon.icns" "${CONTENTS}/Resources/AppIcon.icns"
else
  echo "警告：assets/AppIcon.icns 缺失，Dock 会显示系统占位图" >&2
fi

# 让 LaunchServices 重新认识这个 bundle（否则图标/名称可能沿用缓存）。
/usr/bin/touch "${APP}"

if [[ "${REFRESH}" == "1" ]]; then
  /usr/bin/killall Dock 2>/dev/null || true
  echo "已重启 Dock 刷新图标缓存"
fi

echo "已安装: ${APP}"
echo "双击即可打开；也可命令行: ${CONTENTS}/MacOS/launch --no-open"
