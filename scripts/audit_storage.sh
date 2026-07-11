#!/bin/zsh
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$script_dir/mac_storage_manager.py" audit --markdown "$@"
