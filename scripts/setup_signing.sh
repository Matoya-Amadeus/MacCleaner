#!/usr/bin/env bash
# 建一张**固定的自签代码签名证书**，让 TCC（App 管理）授权一次长期有效。
#
# 为什么需要：ad-hoc 签名（`codesign -s -`）每次构建 cdhash 都变，
# macOS 会把每次构建当成不同的 App，于是「App 管理」权限要反复勾。
# 换成固定证书后，TCC 认的是「identifier + 证书叶子」，重建多少次都算同一个 App。
#
# 特点：
#   - 证书与私钥放**独立 keychain**（密码固定为 maccleaner），不碰登录钥匙串，
#     也不需要你输密码；
#   - 幂等：已存在就跳过；
#   - 只用于本机签名，不涉及公证/分发。
set -euo pipefail

CN="MacCleaner Dev"
KEYCHAIN="$HOME/Library/Keychains/maccleaner-signing.keychain-db"
KEYCHAIN_PASS="maccleaner"
WORK="$(mktemp -d)"

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

if security find-identity -v -p codesigning 2>/dev/null | grep -q "$CN"; then
  echo "已存在证书：$CN"
  exit 0
fi

echo "生成自签证书：$CN"
cat > "$WORK/openssl.cnf" <<'CNF'
[req]
distinguished_name = dn
x509_extensions = codesign
prompt = no

[dn]
CN = MacCleaner Dev
O = MacCleaner Local

[codesign]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF

openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout "$WORK/key.pem" -out "$WORK/cert.pem" \
  -config "$WORK/openssl.cnf" >/dev/null 2>&1

# p12 必须带密码：空密码时 macOS 的 security import 会报
# "MAC verification failed during PKCS12 import"（2026-10-23 实测）。
P12_PASS="maccleaner"
openssl pkcs12 -export -legacy \
  -inkey "$WORK/key.pem" -in "$WORK/cert.pem" \
  -out "$WORK/identity.p12" -passout "pass:$P12_PASS" >/dev/null 2>&1 || \
openssl pkcs12 -export \
  -inkey "$WORK/key.pem" -in "$WORK/cert.pem" \
  -out "$WORK/identity.p12" -passout "pass:$P12_PASS" >/dev/null 2>&1

if [[ ! -f "$KEYCHAIN" ]]; then
  security create-keychain -p "$KEYCHAIN_PASS" "$KEYCHAIN"
fi
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASS" "$KEYCHAIN"

# -A：允许所有程序使用这把私钥（避免每次签名弹"允许访问"）
security import "$WORK/identity.p12" -k "$KEYCHAIN" -P "$P12_PASS" -T /usr/bin/codesign -A >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASS" "$KEYCHAIN" >/dev/null 2>&1 || true

# 加入搜索列表（保留已有条目）
EXISTING="$(security list-keychains -d user | tr -d '"' | tr '\n' ' ')"
# shellcheck disable=SC2086
security list-keychains -d user -s $EXISTING "$KEYCHAIN"

echo "完成："
security find-identity -v -p codesigning "$KEYCHAIN" | sed 's/^/  /'
