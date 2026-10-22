"""Local stdio MCP adapter for MacCleaner."""

from __future__ import annotations

import sys
from typing import Literal, Sequence

from .mcp_service import PlanValidationError, StorageService


class McpDependencyError(RuntimeError):
    """Raised when the optional MCP SDK is not installed."""


def _load_fast_mcp():  # noqa: ANN202
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError as exc:
        if exc.name != "mcp":
            raise
        raise McpDependencyError(
            'MCP support requires the optional dependency. Install it with pipx install "maccleaner[mcp]".'
        ) from exc
    return FastMCP


def build_mcp_server(service: StorageService | None = None):  # noqa: ANN201
    """Build a stdio-only MCP server around one canonical StorageService."""
    FastMCP = _load_fast_mcp()
    storage = service or StorageService()
    mcp = FastMCP(
        "MacCleaner",
        instructions=(
            "Audit first, plan second, and apply only exact target IDs from the returned plan_id. "
            "**Always show the plan (paths + sizes) to the user and get explicit confirmation before "
            "applying** — never clean on your own initiative, and never expand the approved list. "
            "Plans are single-use: a used or expired plan_id must be regenerated. "
            "Browser identity and credential data remain blocked."
        ),
    )

    @mcp.tool()
    def audit_storage(
        profile: Literal["generic", "repo-evidence"] = "generic",
        days_to_keep: int = 7,
        include_system: bool = False,
        include_hidden_home: bool = False,
        flutter_search_root: str | None = None,
        app_path: str | None = None,
    ) -> dict[str, object]:
        """Read-only storage audit. It never changes files."""
        return storage.audit(
            profile=profile,
            days_to_keep=days_to_keep,
            include_system=include_system,
            include_hidden_home=include_hidden_home,
            flutter_search_root=flutter_search_root,
            app_path=app_path,
        )

    @mcp.tool()
    def plan_storage(
        profile: Literal["generic", "repo-evidence"] = "generic",
        days_to_keep: int = 7,
        include_system: bool = False,
        include_hidden_home: bool = False,
        flutter_search_root: str | None = None,
        app_path: str | None = None,
        state_root: str | None = None,
        require_zero_hit: Sequence[str] = (),
    ) -> dict[str, object]:
        """Build a read-only plan and return its one-time plan_id."""
        return storage.plan(
            profile=profile,
            days_to_keep=days_to_keep,
            include_system=include_system,
            include_hidden_home=include_hidden_home,
            flutter_search_root=flutter_search_root,
            app_path=app_path,
            state_root=state_root,
            require_zero_hit=require_zero_hit,
        )

    @mcp.tool()
    def trace_storage(
        target_path: str,
        keyword: str,
        profile: Literal["generic", "repo-evidence"] = "generic",
    ) -> dict[str, object]:
        """Read-only trace for a directory or cache that reappears."""
        return storage.trace(target_path=target_path, keyword=keyword, profile=profile)

    @mcp.tool()
    def uninstall_plan(
        app_path: str,
        bundle_id: str = "",
        app_name: str = "",
    ) -> dict[str, object]:
        """List an app's leftover files (read-only). Never deletes anything."""
        return storage.uninstall_plan(app_path=app_path, bundle_id=bundle_id, app_name=app_name)

    @mcp.tool()
    def updates_check() -> dict[str, object]:
        """List third-party updates (Homebrew + App Store). macOS system updates are out of scope."""
        return storage.updates_check()

    @mcp.tool()
    def updates_apply(names: Sequence[str] = ()) -> dict[str, object]:
        """Upgrade the named third-party packages (empty = all). Each group reports its own exit code."""
        return storage.updates_apply(names=names)

    @mcp.tool()
    def apply_storage_plan(
        plan_id: str,
        approved_targets: Sequence[str],
        confirm_targets: Sequence[str] = (),
        plan_digest: str = "",
    ) -> dict[str, object]:
        """Apply one live plan using exact approved target IDs only.

        Pass the `plan_digest` returned by `plan_storage` to prove the plan being applied is the one
        you showed the user; a mismatch is refused before anything is touched.
        """
        try:
            return storage.apply(
                plan_id=plan_id,
                approved_targets=approved_targets,
                confirm_targets=confirm_targets,
                plan_digest=plan_digest,
            )
        except PlanValidationError as exc:
            raise ValueError(str(exc)) from exc

    return mcp


def main() -> int:
    try:
        mcp = build_mcp_server()
    except McpDependencyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
