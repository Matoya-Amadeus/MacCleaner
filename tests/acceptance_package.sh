#!/usr/bin/env bash
# 打包验收（2026-10-19）。**不是 pytest 用例**，人工运行：
#
#     bash tests/acceptance_package.sh
#
# 回答的是"别人从 PyPI / 从 dist/ 拿到包能不能跑"：
#   ① 能否构建出 sdist + wheel（用**本地** setuptools，不联网）；
#   ② 干净 venv 里**离线**装 wheel → 两个入口 + 真实审计；
#   ③ 没有 `mcp` extra 时 `maccleaner-mcp` 是否给出可执行提示（exit 2，而不是崩栈）；
#   ④ 离线装 sdist（需要本机已有 `wheel`；缺了就明确提示，而不是报"包坏了"）。
#
# 首次构建需要本机有 setuptools + wheel：
#     python3 -m pip install wheel
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

DIST="$(mktemp -d)/dist"
WORK="$(mktemp -d)"
PY="${PYTHON:-/usr/local/bin/python3}"
FAILED=0

echo "=== ① 构建（--no-isolation，不联网）==="
if ! "$PY" -c "import wheel" 2>/dev/null; then
  echo "  ⚠️  本机缺 wheel：先跑 $PY -m pip install wheel（否则构建 wheel 会失败）"
fi
if "$PY" -m build --no-isolation --outdir "$DIST" . >"$WORK/build.log" 2>&1; then
  ls -1 "$DIST" | sed 's/^/  /'
else
  echo "  ❌ 构建失败："; tail -5 "$WORK/build.log" | sed 's/^/     /'; FAILED=1
fi

echo "=== ② 干净 venv 离线装 wheel ==="
if ! ls "$DIST"/maccleaner-*.whl >/dev/null 2>&1; then
  false
fi
WHL=$(ls "$DIST"/maccleaner-*.whl 2>/dev/null | head -1 || true)
SDIST=$(ls "$DIST"/maccleaner-*.tar.gz 2>/dev/null | head -1 || true)
if [[ -n "${WHL}" ]]; then
  "$PY" -m venv "$WORK/venv"
  "$WORK/venv/bin/python" -m pip install --quiet --no-index "$WHL" 2>&1 | tail -2
  VERSION=$("$WORK/venv/bin/python" -c "import importlib.metadata as m; print(m.version('maccleaner'))" 2>/dev/null)
  echo "  已安装版本: ${VERSION:-<失败>}"
  "$WORK/venv/bin/maccleaner" --help >"$WORK/help.out" 2>&1 || FAILED=1
  grep -q "audit" "$WORK/help.out" && echo "  CLI: $(head -1 "$WORK/help.out")" || { echo "  ❌ CLI 入口不可用"; FAILED=1; }

  echo "=== ③ 无 mcp extra 的报错路径 ==="
  "$WORK/venv/bin/maccleaner-mcp" --help >"$WORK/mcp.out" 2>&1
  CODE=$?
  echo "  exit=$CODE · $(head -1 "$WORK/mcp.out")"
  [[ $CODE -eq 2 ]] || { echo "  ❌ 期望 exit 2"; FAILED=1; }

  echo "=== ④ 装完真跑一次审计（临时 HOME）==="
  mkdir -p "$WORK/home/Library/Caches/Demo"
  printf 'z%.0s' {1..2048} > "$WORK/home/Library/Caches/Demo/x.bin"
  touch -t 202001010000 "$WORK/home/Library/Caches/Demo/x.bin"
  HOME="$WORK/home" "$WORK/venv/bin/maccleaner" audit --markdown >"$WORK/audit.out" 2>&1
  grep -q "home-caches" "$WORK/audit.out" && echo "  审计命中 home-caches ✓" || { echo "  ❌ 审计没有输出候选"; FAILED=1; }

  echo "=== ⑤ 离线装 sdist（需本机有 wheel）==="
  if [[ -n "${SDIST}" ]] && "$PY" -c "import wheel" 2>/dev/null; then
    "$PY" -m venv --system-site-packages "$WORK/venv2"
    if "$WORK/venv2/bin/python" -m pip install --quiet --no-index --no-build-isolation "$SDIST" 2>&1 | tail -2; then
      "$WORK/venv2/bin/maccleaner" --help >/dev/null 2>&1 && echo "  sdist 安装可用 ✓" || { echo "  ❌ sdist 装完入口不可用"; FAILED=1; }
    else
      echo "  ❌ sdist 离线安装失败"; FAILED=1
    fi
  else
    echo "  跳过（本机无 wheel，或没有 sdist）"
  fi
else
  echo "  跳过：没有 wheel 产物"
  FAILED=1
fi

rm -rf "$WORK" "$(dirname "$DIST")"
if [[ $FAILED -eq 0 ]]; then
  echo "✅ 打包验收通过"
else
  echo "❌ 打包验收未通过"
fi
exit $FAILED
