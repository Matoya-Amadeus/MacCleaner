from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mac_storage_manager as msm  # type: ignore
from mac_storage_manager import CleanupTarget, StorageContext, StorageManager  # type: ignore


def _write(path: Path, text: str = "x", *, days_ago: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if days_ago:
        ts = time.time() - days_ago * 24 * 60 * 60
        os.utime(path, (ts, ts))
    return path


class FakeRunner:
    def __init__(self, which_map: dict[str, str | None] | None = None) -> None:
        self.which_map = which_map or {}
        self.responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def set_response(self, args: list[str] | tuple[str, ...], *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        argv = tuple(args)
        self.responses[argv] = subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)

    def run(self, args, *, capture_output=True, text=True, check=False, cwd=None):  # noqa: ANN001
        argv = tuple(args)
        self.calls.append((argv, cwd))
        if argv in self.responses:
            return self.responses[argv]
        return subprocess.CompletedProcess(list(argv), 0, "", "")


def _manager(home: Path, *, runner: FakeRunner | None = None, **kwargs) -> StorageManager:
    ctx = StorageContext(
        home=home,
        root=kwargs.pop("root", home),
        days_to_keep=kwargs.pop("days_to_keep", 7),
        dry_run=kwargs.pop("dry_run", True),
        apply=kwargs.pop("apply", False),
        yes=kwargs.pop("yes", False),
        include_system=kwargs.pop("include_system", False),
        confirm_targets=frozenset(kwargs.pop("confirm_targets", ())),
        approved_targets=frozenset(kwargs.pop("approved_targets", ())),
        include_hidden_home=kwargs.pop("include_hidden_home", False),
        flutter_search_root=kwargs.pop("flutter_search_root", None),
        app_path=kwargs.pop("app_path", None),
        receipt_dir=kwargs.pop("receipt_dir", None),
        backup_dir=kwargs.pop("backup_dir", None),
        require_zero_hit=tuple(kwargs.pop("require_zero_hit", ())),
        profile=kwargs.pop("profile", "generic"),
        state_root=kwargs.pop("state_root", None),
        require_explicit_plan=kwargs.pop("require_explicit_plan", False),
        system_roots=kwargs.pop("system_roots", msm.DEFAULT_SYSTEM_ROOTS),
    )
    return StorageManager(ctx, runner=runner or FakeRunner())


def _item(report, target_id: str):  # noqa: ANN001
    for item in report.plan_items:
        if item.target_id == target_id:
            return item
    raise AssertionError(f"missing target: {target_id}")


class MacStorageManagerTests(unittest.TestCase):
    def test_cli_help_exposes_public_cleanup_interfaces(self) -> None:
        root_help = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "mac_storage_manager.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        clean_help = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "mac_storage_manager.py"), "clean", "--help"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("trace", root_help)
        self.assertIn("--require-zero-hit", clean_help)
        self.assertIn("--receipt-dir", clean_help)
        self.assertIn("--backup-dir", clean_help)

    def test_hidden_home_scan_does_not_special_case_agent_runtime(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-open-source-"))
        home = tmp / "home"
        _write(home / ".agenttool" / ".tmp" / "a.txt")
        manager = _manager(home, include_hidden_home=True)
        target_ids = {target.target_id for target in manager.discover_targets()}
        self.assertNotIn("home-agenttool-temp", target_ids)
        self.assertIn("hidden-home:agenttool", target_ids)

    def test_public_display_path_redacts_private_absolute_paths(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-paths-"))
        home = tmp / "home"
        root = home / "workspace"
        secret = home / "Library" / "Caches" / "pip"
        self.assertEqual(
            msm.public_display_path(secret, home=home, root=root, public_roots=msm.DEFAULT_PUBLIC_ROOTS),
            "~/Library/Caches/pip",
        )
        external = Path("/opt/private-demo/file.txt")
        self.assertEqual(
            msm.public_display_path(external, home=home, root=root, public_roots=msm.DEFAULT_PUBLIC_ROOTS),
            "<external>/file.txt",
        )

    def test_public_note_redacts_sensitive_diagnostics(self) -> None:
        self.assertEqual(msm.public_note("container_bundle_id=com.example.demo"), "container_bundle_id=<redacted>")
        self.assertEqual(msm.public_note("non_owner_path=/Users/demo/.npm/a"), "non_owner_path=<redacted>")
        self.assertEqual(msm.public_note("allocated_bytes=512"), "allocated_bytes=512")

    def test_report_redacts_home_root_paths_and_notes(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-report-"))
        home = tmp / "home"
        root = home / "workspace"
        cache_dir = home / "Library" / "Caches" / "pip"
        _write(cache_dir / "cache.bin", "cache")
        manager = _manager(home, root=root)
        target = CleanupTarget(
            target_id="probe",
            name="Probe",
            category="test",
            kind="purge_tree",
            paths=(cache_dir,),
        )
        scans = manager.scan_targets([target])
        report = manager._make_report(  # type: ignore[attr-defined]
            mode="audit",
            before_scans=scans,
            after_scans=scans,
            plan_items=manager.plan_targets(scans),
            actual_reclaimed_bytes=0,
            before_free_bytes=0,
            after_free_bytes=0,
            notes=["container_bundle_id=com.example.demo", f"non_owner_path={tmp}/private"],
        )
        data = report.to_dict()
        payload = json.dumps(data, ensure_ascii=False)
        self.assertEqual(data["home"], "~")
        self.assertEqual(data["root"], "<root>")
        self.assertEqual(data["top_consumers"][0]["paths"], ["~/Library/Caches/pip"])
        self.assertEqual(data["top_consumers"][0]["notes"], [])
        self.assertEqual(data["notes"], ["container_bundle_id=<redacted>", "non_owner_path=<redacted>"])
        self.assertNotIn(str(tmp), payload)

    def test_custom_system_roots_are_accepted_and_public_in_reports(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-system-roots-"))
        home = tmp / "home"
        external_root = tmp / "sys0"
        target_path = external_root / "Caches" / "demo"
        _write(target_path / "cache.bin", "cache")
        custom_roots = (external_root, tmp / "sys1", tmp / "sys2", tmp / "sys3")
        manager = _manager(home, system_roots=custom_roots)
        self.assertEqual(manager.context.system_roots, custom_roots)
        target = CleanupTarget(
            target_id="external-probe",
            name="External Probe",
            category="test",
            kind="purge_tree",
            paths=(target_path,),
        )
        scans = manager.scan_targets([target])
        report = manager._make_report(  # type: ignore[attr-defined]
            mode="audit",
            before_scans=scans,
            after_scans=scans,
            plan_items=manager.plan_targets(scans),
            actual_reclaimed_bytes=0,
            before_free_bytes=0,
            after_free_bytes=0,
            notes=[],
        )
        self.assertEqual(report.to_dict()["top_consumers"][0]["paths"], [target_path.resolve().as_posix()])

    def test_yes_does_not_clean_downloads_trash_or_docker_without_exact_plan(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-approval-"))
        home = tmp / "home"
        downloads = _write(home / "Downloads" / "large.iso", "x" * 1024, days_ago=15)
        trashed = _write(home / ".Trash" / "old.mov", "x" * 1024, days_ago=15)
        _write(home / "Library" / "Containers" / "com.docker.docker" / "state.bin", "x" * 1024, days_ago=15)
        runner = FakeRunner(which_map={"docker": "/usr/bin/docker"})
        runner.set_response(["docker", "context", "show"], stdout="desktop-linux\n")
        runner.set_response(
            ["docker", "context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"],
            stdout="unix:///var/run/docker.sock\n",
        )

        report = _manager(home, runner=runner, dry_run=False, apply=True, yes=True).clean()

        self.assertTrue(downloads.exists())
        self.assertTrue(trashed.exists())
        self.assertEqual(_item(report, "downloads").status, "blocked")
        self.assertEqual(_item(report, "trash").status, "blocked")
        self.assertEqual(_item(report, "docker-prune").status, "blocked")

    def test_protected_browser_session_target_is_always_blocked(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-protected-"))
        home = tmp / "home"
        cookie = _write(
            home / "Library" / "Application Support" / "Firefox" / "Profiles" / "demo.default" / "cookies.sqlite",
            "session",
            days_ago=20,
        )
        manager = _manager(
            home,
            dry_run=False,
            apply=True,
            yes=True,
            confirm_targets={"firefox-session"},
            approved_targets={"firefox-session"},
        )
        target = CleanupTarget(
            target_id="firefox-session",
            name="Firefox session",
            category="browser-session",
            kind="purge_tree",
            paths=(cookie,),
            risk="low",
        )
        scans = manager.scan_targets([target])
        plan = manager.plan_targets(scans)

        self.assertEqual(plan[0].status, "blocked")
        self.assertEqual(plan[0].source_layer, "protected_session")
        self.assertEqual(plan[0].protection, "blocked")
        self.assertTrue(cookie.exists())

    def test_trace_detects_reappearing_sources_and_redacts_private_paths(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-trace-"))
        home = tmp / "home"
        root = tmp / "repo"
        target = tmp / "Sample-Workspace"
        _write(home / "Library" / "LaunchAgents" / "com.example.sample.plist", str(target))
        _write(home / ".zshrc", f"mkdir -p {target}\n")
        _write(root / "docker-compose.yml", "services:\n  sample-workspace:\n    image: demo\n")
        _write(root / "SKILL.md", "Sample-Workspace cleanup note")
        _write(root / "manifests" / "metrics" / "old.json", '{"topic": "Sample-Workspace"}')
        _write(tmp / "outside" / "old.json", '{"topic": "Sample-Workspace"}')
        runner = FakeRunner(which_map={"docker": "/usr/bin/docker"})
        runner.set_response(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Command}}"],
            stdout="sample-workspace\tdemo\t/run\n",
        )

        report = _manager(home, root=root, runner=runner, profile="repo-evidence").trace(target, "Sample-Workspace")
        data = report.to_dict()
        payload = json.dumps(data, ensure_ascii=False)
        layers = {finding["source_layer"] for finding in data["findings"]}
        sources = {finding["source"] for finding in data["findings"]}

        self.assertIn("active_trigger", layers)
        self.assertIn("repo_reference", layers)
        self.assertIn("historical_index", layers)
        self.assertIn("launch-agent", sources)
        self.assertIn("shell-startup", sources)
        self.assertIn("docker-container", sources)
        self.assertIn("<root>/manifests/metrics/old.json", payload)
        self.assertNotIn("outside/old.json", payload)
        self.assertNotIn(str(tmp), payload)

    def test_backup_dir_rejects_literal_shell_timestamp(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-literal-date-"))
        home = tmp / "home"
        home.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError):
            _manager(home, backup_dir=tmp / "backup-$(date +%Y%m%d)")

    def test_clean_apply_writes_redacted_receipt_backup_and_residual_validation(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-receipt-"))
        home = tmp / "home"
        downloads = _write(home / "Downloads" / "old-note.txt", "delete me", days_ago=20)
        _write(home / "Library" / "Logs" / "old.log", "old-note", days_ago=20)
        receipt_dir = home / ".mac-storage-manager" / "receipts"
        backup_dir = home / ".mac-storage-manager" / "backups" / "backup-20260519-123000"

        report = _manager(
            home,
            dry_run=False,
            apply=True,
            yes=True,
            confirm_targets={"downloads"},
            approved_targets={"downloads"},
            receipt_dir=receipt_dir,
            backup_dir=backup_dir,
            require_zero_hit=("old-note",),
        ).clean()

        payload = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertFalse(downloads.exists())
        self.assertTrue(any(receipt_dir.glob("cleanup-receipt-*.md")))
        self.assertTrue(any(receipt_dir.glob("cleanup-receipt-*.json")))
        self.assertTrue((backup_dir / "touched-files.txt").exists())
        self.assertTrue((backup_dir / "sha256.txt").exists())
        self.assertTrue(report.backup_manifest["enabled"])
        self.assertNotIn("$(", report.backup_manifest["backup_dir"])
        self.assertTrue(report.receipt["markdown"].startswith("~/"))
        self.assertTrue(report.backup_manifest["backup_dir"].startswith("~/"))
        self.assertEqual(report.residual_validation[0]["pattern"], "old-note")
        self.assertEqual(report.residual_validation[0]["status"], "fail")
        self.assertNotIn(str(tmp), payload)
        receipt_text = next(receipt_dir.glob("cleanup-receipt-*.md")).read_text(encoding="utf-8")
        self.assertNotIn(str(tmp), receipt_text)


if __name__ == "__main__":
    unittest.main()
