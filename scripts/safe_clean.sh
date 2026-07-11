#!/bin/zsh
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
echo "DEPRECATED: safe_clean.sh is a compatibility shim. Prefer apply_storage_plan.sh with exact --approved-targets." >&2
exec "$script_dir/apply_storage_plan.sh" "$@"
