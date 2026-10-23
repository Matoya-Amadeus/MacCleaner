#!/usr/bin/env bash
# 用**固定的自签证书**签名（而不是 ad-hoc）。
#
# 为什么：ad-hoc 签名每次构建 cdhash 都变，macOS 认为这是不同的 App，
# TCC 的「App 管理」授权就要重新勾。固定证书后，designated requirement 变成
# "identifier + 证书叶子"，重建多少次都还是同一个 App —— 授权一次长期有效。
#
# 证书由 scripts/setup_signing.sh 创建；没建过就自动回退到 ad-hoc，不阻塞构建。
set -uo pipefail

SIGN_ID="MacCleaner Dev"
SIGN_KC="$HOME/Library/Keychains/maccleaner-signing.keychain-db"

sign_app() {
  local app="$1"
  if [[ -f "$SIGN_KC" ]] && security find-certificate -c "$SIGN_ID" "$SIGN_KC" >/dev/null 2>&1; then
    security unlock-keychain -p maccleaner "$SIGN_KC" >/dev/null 2>&1 || true
    if codesign --force --sign "$SIGN_ID" --keychain "$SIGN_KC" "$app" >/dev/null 2>&1; then
      echo "已签名：$SIGN_ID"
      return 0
    fi
    echo "（自签证书失败，回退 ad-hoc）" >&2
  fi
  codesign --force --sign - "$app" >/dev/null 2>&1 || true
  echo "已签名：ad-hoc（未找到 $SIGN_ID）"
}
