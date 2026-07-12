"""Compatibility shim for the installable maccleaner package."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from maccleaner.core import *  # noqa: F401,F403
from maccleaner.core import _find_non_owner_paths  # noqa: F401
