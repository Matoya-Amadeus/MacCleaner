#!/usr/bin/env bash
# 生成可双击的 MacCleaner.app（2026-10-18）。
#
# 两种运行方式，装进同一个 bundle：
#   1. `Contents/MacOS/MacCleaner` —— **原生窗口**（Swift + WKWebView）。双击走它：
#      自己起后端、把 loopback 页面装进一个真窗口，不跳浏览器。
#   2. `Contents/MacOS/launch` —— 命令行/无界面入口，直接转发给 `maccleaner ui`（会开浏览器）。
#      没有 Xcode 命令行工具时，双击会退回到它。
#
# 这里只做**打包**，不含任何清理逻辑；逻辑永远在 `src/maccleaner/`。
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
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

APP="${PREFIX}/MacCleaner.app"
CONTENTS="${APP}/Contents"
mkdir -p "${CONTENTS}/MacOS" "${CONTENTS}/Resources"

# 1) 原生窗口（能用 swiftc 就编译；否则退回脚本模式，并明确告知）
EXECUTABLE="launch"
SHELL_BIN="${CONTENTS}/MacOS/MacCleaner"
if xcrun --find swiftc >/dev/null 2>&1; then
  if xcrun swiftc -O -o "${SHELL_BIN}" "${REPO_DIR}/scripts/launcher/main.swift" \
      -framework Cocoa -framework WebKit 2>/tmp/maccleaner-swiftc.log; then
    EXECUTABLE="MacCleaner"
  else
    echo "警告：Swift 编译失败（详见 /tmp/maccleaner-swiftc.log），双击将退回浏览器模式" >&2
    rm -f "${SHELL_BIN}"
  fi
else
  echo "警告：找不到 swiftc（需 Xcode 命令行工具），双击将退回浏览器模式" >&2
fi

# 2) Info.plist（CFBundleExecutable 跟着上一步的结果走）
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
  <key>CFBundleExecutable</key><string>${EXECUTABLE}</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>MacCleanerRepo</key><string>${REPO_DIR}</string>
</dict>
</plist>
PLIST

# 3) 无界面入口（命令行、以及没有 swiftc 时的双击兜底）
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

/usr/bin/touch "${APP}"

if [[ "${REFRESH}" == "1" ]]; then
  /usr/bin/killall Dock 2>/dev/null || true
  echo "已重启 Dock 刷新图标缓存"
fi

echo "已安装: ${APP}（双击入口: ${EXECUTABLE}）"
echo "命令行: ${CONTENTS}/MacOS/launch --no-open"
