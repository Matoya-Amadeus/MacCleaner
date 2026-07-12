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
