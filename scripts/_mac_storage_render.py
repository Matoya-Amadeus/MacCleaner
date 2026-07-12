"""Compatibility shim for the installable maccleaner package."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from maccleaner.render import render_markdown, render_text, render_trace_markdown, render_trace_text
