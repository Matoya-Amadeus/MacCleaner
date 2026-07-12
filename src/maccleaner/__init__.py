"""MacCleaner public package API."""

from .cli import _context_from_args, _parse_csv, build_parser, main
from .core import CleanupTarget, ExplicitPlanRequiredError, StorageContext, StorageManager
from .render import render_markdown, render_text, render_trace_markdown, render_trace_text

__version__ = "0.1.0"

__all__ = [
    "CleanupTarget",
    "ExplicitPlanRequiredError",
    "StorageContext",
    "StorageManager",
    "_context_from_args",
    "_parse_csv",
    "__version__",
    "build_parser",
    "main",
    "render_markdown",
    "render_text",
    "render_trace_markdown",
    "render_trace_text",
]
