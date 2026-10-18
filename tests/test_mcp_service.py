from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest

from maccleaner.core import CleanupTarget, StorageContext, TargetScan
from maccleaner.mcp_service import PlanRegistry, PlanValidationError, StorageService
from maccleaner.policy import decide_plan_item


class StrictExecutionScopeTests(unittest.TestCase):
    def test_enforced_scope_blocks_unapproved_low_risk_target(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="maccleaner-enforced-scope-"))
        context = StorageContext(
            home=root,
            root=root,
            dry_run=False,
            apply=True,
            yes=True,
            approved_targets=frozenset({"approved-cache"}),
            enforce_approved_scope=True,
        )
        target = CleanupTarget(
            target_id="unapproved-cache",
            name="Unapproved cache",
            category="cache",
            kind="purge_tree",
            paths=(root / "Library" / "Caches" / "unapproved",),
            risk="low",
        )
        scan = TargetScan(
            target=target,
            exists=True,
            total_bytes=64,
            eligible_bytes=64,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
        )

        item = decide_plan_item(context, scan)

        self.assertEqual(item.status, "blocked")
        self.assertEqual(item.scope_status, "outside_approved_plan")
        self.assertEqual(item.reason, "outside approved cleanup plan")


class PlanRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        self.registry = PlanRegistry(now=lambda: self.now)
        self.context = StorageContext(home=Path("/tmp/home"), root=Path("/tmp/home"))

    def test_rejects_unknown_expired_reused_and_invalid_confirmations(self) -> None:
        snapshot = self.registry.create(
            self.context,
            candidate_target_ids={"cache", "confirm-me"},
            required_confirmation_ids={"confirm-me"},
        )

        with self.assertRaisesRegex(PlanValidationError, "approved_targets must not be empty"):
            self.registry.consume(snapshot.plan_id, (), ())
        with self.assertRaisesRegex(PlanValidationError, "not in plan"):
            self.registry.consume(snapshot.plan_id, ("outside",), ())
        with self.assertRaisesRegex(PlanValidationError, "confirm_targets must be a subset"):
            self.registry.consume(snapshot.plan_id, ("cache",), ("confirm-me",))
        with self.assertRaisesRegex(PlanValidationError, "confirm_targets required"):
            self.registry.consume(snapshot.plan_id, ("confirm-me",), ())

        consumed = self.registry.consume(snapshot.plan_id, ("confirm-me",), ("confirm-me",))
        self.assertEqual(consumed.plan_id, snapshot.plan_id)
        with self.assertRaisesRegex(PlanValidationError, "unknown or already used"):
            self.registry.consume(snapshot.plan_id, ("confirm-me",), ("confirm-me",))

        expiring = self.registry.create(self.context, candidate_target_ids={"cache"})
        self.now += timedelta(minutes=16)
        with self.assertRaisesRegex(PlanValidationError, "expired"):
            self.registry.consume(expiring.plan_id, ("cache",), ())

    def test_high_risk_confirmation_survives_approved_plan_status(self) -> None:
        candidates, confirmations = StorageService._targets_from_plan(
            {
                "plan_items": [
                    {
                        "target_id": "downloads",
                        "status": "blocked",
                        "scope_status": "outside_approved_plan",
                        "protection": "approved_plan",
                        "requires_confirmation": True,
                        "estimated_bytes": 128,
                    }
                ]
            }
        )

        self.assertEqual(candidates, frozenset({"downloads"}))
        self.assertEqual(confirmations, frozenset({"downloads"}))

    def test_protected_session_is_never_an_mcp_apply_candidate(self) -> None:
        candidates, confirmations = StorageService._targets_from_plan(
            {
                "plan_items": [
                    {
                        "target_id": "browser-session",
                        "status": "blocked",
                        "scope_status": "protected_session",
                        "protection": "blocked",
                        "requires_confirmation": False,
                        "estimated_bytes": 128,
                    }
                ]
            }
        )

        self.assertEqual(candidates, frozenset())
        self.assertEqual(confirmations, frozenset())


class StorageServiceTests(unittest.TestCase):
    def test_apply_consumes_plan_and_keeps_unapproved_low_risk_target(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="maccleaner-mcp-apply-"))
        approved_file = root / "Library" / "Caches" / "approved" / "cache.bin"
        blocked_file = root / "Library" / "Logs" / "blocked" / "log.txt"
        approved_file.parent.mkdir(parents=True)
        blocked_file.parent.mkdir(parents=True)
        approved_file.write_bytes(b"cache")
        blocked_file.write_bytes(b"log")
        old = datetime.now().timestamp() - 9 * 24 * 60 * 60
        os.utime(approved_file, (old, old))
        os.utime(blocked_file, (old, old))

        service = StorageService(home=root, root=root)
        planned = service.plan()

        self.assertIn("plan_id", planned)
        self.assertIn("home-caches", planned["applicable_target_ids"])
        self.assertIn("home-logs", planned["applicable_target_ids"])

        applied = service.apply(
            plan_id=planned["plan_id"],
            approved_targets=("home-caches",),
            confirm_targets=(),
        )

        self.assertFalse(approved_file.exists())
        self.assertTrue(blocked_file.exists())
        statuses = {item["target_id"]: item["status"] for item in applied["plan_items"]}
        self.assertEqual(statuses["home-caches"], "cleaned")
        self.assertEqual(statuses["home-logs"], "blocked")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()


class UninstallAndUpdatesServiceTests(unittest.TestCase):
    """service 层的两个新入口（2026-10-18）：只做编排，语义在 uninstall/updates 模块里。"""

    def test_uninstall_plan_is_read_only_and_scoped_to_home(self) -> None:
        import plistlib
        import tempfile
        from pathlib import Path

        from maccleaner.mcp_service import StorageService

        with tempfile.TemporaryDirectory(prefix="svc-uninstall-") as tmp:
            root = Path(tmp)
            app = root / "Applications" / "Example.app"
            (app / "Contents").mkdir(parents=True)
            with (app / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleIdentifier": "com.example.app", "CFBundleName": "Example App"}, handle)
            (root / "home" / "Library" / "Caches" / "com.example.app").mkdir(parents=True)

            result = StorageService().uninstall_plan(app_path=str(app), home=str(root / "home"))
            paths = {item["path"] for item in result["items"]}
            self.assertIn(str(app), paths, "应用本体要在计划里")
            self.assertTrue(any("com.example.app" in path for path in paths), "缓存残留要被发现")
            self.assertIn("plan_hash", result)
            self.assertTrue(app.is_dir(), "只读：计划生成不得移动任何东西")

    def test_updates_check_delegates_to_the_module(self) -> None:
        from unittest.mock import patch

        from maccleaner.mcp_service import StorageService

        fake = {"items": [{"name": "aom"}], "count": 1, "notes": [], "scope": "third-party only"}
        with patch("maccleaner.updates.discover_updates", return_value=fake) as spy:
            result = StorageService().updates_check()
        self.assertTrue(spy.called)
        self.assertEqual(result["count"], 1)

    def test_updates_apply_filters_by_name(self) -> None:
        from unittest.mock import patch

        from maccleaner.mcp_service import StorageService

        found = {
            "items": [
                {"manager": "brew", "kind": "formula", "name": "aom"},
                {"manager": "brew", "kind": "formula", "name": "cmake"},
            ],
            "count": 2,
        }
        captured: dict[str, object] = {}

        def fake_plan(items, **_kwargs):
            captured["names"] = [item["name"] for item in items]
            return {"groups": [{"command": "brew upgrade aom", "argv": ["brew", "upgrade", "aom"]}], "count": 1}

        with patch("maccleaner.updates.discover_updates", return_value=found), \
                patch("maccleaner.updates.build_upgrade_plan", side_effect=fake_plan), \
                patch("maccleaner.updates.apply_updates", return_value={"status": "dry-run"}) as apply_spy:
            result = StorageService().updates_apply(names=["aom"])
        self.assertEqual(captured["names"], ["aom"], "只把点名的那一个交给执行层")
        self.assertTrue(apply_spy.called)
        self.assertEqual(result["status"], "dry-run")
