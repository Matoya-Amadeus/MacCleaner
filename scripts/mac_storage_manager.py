from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _mac_storage_core import *  # noqa: F401,F403
from _mac_storage_core import _find_non_owner_paths  # noqa: F401
from _mac_storage_policy import *  # noqa: F401,F403
from _mac_storage_render import render_markdown, render_text, render_trace_markdown, render_trace_text
from _mac_storage_cli import _context_from_args, _parse_csv, build_parser, main

if __name__ == "__main__":
    raise SystemExit(main())
