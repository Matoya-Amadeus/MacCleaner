from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from maccleaner.cli import _context_from_args, _parse_csv, build_parser, main
from maccleaner.core import *  # noqa: F401,F403
from maccleaner.core import _find_non_owner_paths  # noqa: F401
from maccleaner.policy import *  # noqa: F401,F403
from maccleaner.render import render_markdown, render_text, render_trace_markdown, render_trace_text

if __name__ == "__main__":
    raise SystemExit(main())
