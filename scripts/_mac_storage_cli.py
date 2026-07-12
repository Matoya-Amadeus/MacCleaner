"""Compatibility shim for the installable maccleaner package."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from maccleaner.cli import _context_from_args, _parse_csv, build_parser, main

__all__ = ["_context_from_args", "_parse_csv", "build_parser", "main"]
