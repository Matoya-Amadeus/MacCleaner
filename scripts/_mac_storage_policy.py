"""Compatibility shim for the installable maccleaner package."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from maccleaner import policy as _policy

# Keep legacy imports patching the canonical policy module, not a copied export set.
sys.modules[__name__] = _policy
