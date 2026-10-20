from __future__ import annotations

import json
import importlib.util
import importlib
from unittest import mock
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import mac_storage_manager as msm  # type: ignore
from mac_storage_manager import CleanupTarget, StorageContext, StorageManager  # type: ignore


class FakeRunner:
    def __init__(self, which_map: dict[str, str | None] | None = None) -> None:
        self.which_map = which_map or {}
        self.responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)

    def set_response(self, args: list[str] | tuple[str, ...], *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        argv = tuple(args)
        self.responses[argv] = subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)

    def run(self, args, *, capture_output=True, text=True, check=False, cwd=None, **kwargs):  # noqa: ANN001
        argv = tuple(args)
        if argv in self.responses:
            return self.responses[argv]
        return subprocess.CompletedProcess(list(argv), 0, "", "")


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _manager(home: Path, *, runner: FakeRunner | None = None, **kwargs) -> StorageManager:
    home.mkdir(parents=True, exist_ok=True)
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
        system_roots=kwargs.pop("system_roots", ()),
        profile=kwargs.pop("profile", "generic"),
        state_root=kwargs.pop("state_root", None),
    )
    return StorageManager(ctx, runner=runner or FakeRunner())


def _item(report, target_id: str):  # noqa: ANN001
    for item in report.plan_items:
        if item.target_id == target_id:
            return item
    raise AssertionError(f"missing target: {target_id}")


class MacStorageOpenSourceContractTests(unittest.TestCase):
    def test_generic_profile_excludes_repo_trace_layers(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-generic-trace-"))
        home = tmp / "home"
        root = tmp / "repo"
        target = tmp / "Lite-Brain"
        _write(home / ".zshrc", f"mkdir -p {target}\n")
        _write(root / "manifests" / "metrics" / "old.json", '{"topic": "Lite-Brain"}')
        _write(root / "scripts" / "bootstrap.sh", "Lite-Brain\n")

        report = _manager(home, root=root, profile="generic").trace(target, "Lite-Brain")
        layers = {finding.source_layer for finding in report.findings}

        self.assertNotIn("repo_reference", layers)
        self.assertNotIn("historical_index", layers)

    def test_repo_evidence_profile_restores_repo_trace_layers(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-repo-trace-"))
        home = tmp / "home"
        root = tmp / "repo"
        target = tmp / "Lite-Brain"
        _write(home / ".zshrc", f"mkdir -p {target}\n")
        _write(root / "manifests" / "metrics" / "old.json", '{"topic": "Lite-Brain"}')
        _write(root / "scripts" / "bootstrap.sh", "Lite-Brain\n")

        report = _manager(home, root=root, profile="repo-evidence").trace(target, "Lite-Brain")
        layers = {finding.source_layer for finding in report.findings}

        self.assertIn("repo_reference", layers)
        self.assertIn("historical_index", layers)

    def test_default_state_root_is_generic_not_private_brand(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-state-root-"))
        home = tmp / "home"
        manager = _manager(home, dry_run=False, apply=True, yes=True, profile="generic")

        receipt_dir = manager._default_receipt_dir()
        backup_dir = manager._default_backup_dir()

        self.assertIn(".mac-storage-manager", str(receipt_dir))
        self.assertIn(".mac-storage-manager", str(backup_dir))
        self.assertNotIn(".private-cleanup", str(receipt_dir))
        self.assertNotIn(".private-cleanup", str(backup_dir))

    def test_explicit_state_root_sets_default_receipt_and_backup_dirs(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-explicit-state-root-"))
        home = tmp / "home"
        state_root = tmp / "state"
        manager = _manager(home, dry_run=False, apply=True, yes=True, profile="generic", state_root=state_root)

        self.assertEqual(manager._default_receipt_dir(), state_root / "receipts")
        self.assertTrue(str(manager._default_backup_dir()).startswith(str(state_root / "backups")))

    def test_explicit_receipt_and_backup_dirs_override_state_root(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-override-state-root-"))
        home = tmp / "home"
        state_root = tmp / "state"
        receipt_dir = tmp / "custom-receipts"
        backup_dir = tmp / "custom-backups"
        manager = _manager(
            home,
            dry_run=False,
            apply=True,
            yes=True,
            profile="generic",
            state_root=state_root,
            receipt_dir=receipt_dir,
            backup_dir=backup_dir,
        )

        self.assertEqual(manager._default_receipt_dir(), receipt_dir)
        self.assertEqual(manager._default_backup_dir(), backup_dir)

    def test_parser_accepts_profile_and_state_root(self) -> None:
        parser = msm.build_parser()
        args = parser.parse_args(["audit", "--profile", "generic", "--state-root", "/tmp/mac-storage-state"])

        self.assertEqual(args.profile, "generic")
        self.assertEqual(args.state_root, "/tmp/mac-storage-state")

    def test_plan_is_explicit_mode_not_audit_alias(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-plan-mode-"))
        home = tmp / "home"
        _write(home / "Library" / "Caches" / "cache.bin", "x" * 128)

        report = _manager(home, profile="generic").plan()

        self.assertEqual(report.mode, "plan")

    def test_target_min_age_overrides_global_days_to_keep(self) -> None:
        target = CleanupTarget(
            target_id="example",
            name="Example",
            category="cache",
            kind="purge_tree",
            paths=(Path("/tmp/example"),),
            min_age_days=30,
        )

        self.assertEqual(msm._effective_cutoff_seconds(target, days_to_keep=7), 30 * 24 * 60 * 60)

    def test_clean_require_explicit_plan_fails_for_high_risk_without_exact_approved_targets(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-explicit-plan-fail-"))
        home = tmp / "home"
        _write(home / "Downloads" / "big.iso", "x" * 128)

        exit_code = msm.main(
            [
                "clean",
                "--home",
                str(home),
                "--root",
                str(home),
                "--days-to-keep",
                "0",
                "--apply",
                "--yes",
                "--require-explicit-plan",
            ]
        )

        self.assertNotEqual(exit_code, 0)

    def test_clean_require_explicit_plan_allows_low_risk_cleanup_without_approved_targets(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-explicit-plan-lowrisk-"))
        home = tmp / "home"
        _write(home / "Library" / "Caches" / "cache.bin", "x" * 128)

        exit_code = msm.main(
            [
                "clean",
                "--home",
                str(home),
                "--root",
                str(home),
                "--days-to-keep",
                "0",
                "--apply",
                "--yes",
                "--require-explicit-plan",
            ]
        )

        self.assertEqual(exit_code, 0)

    def test_safe_clean_wrapper_is_deprecated_shim(self) -> None:
        script = ROOT / "scripts" / "safe_clean.sh"
        text = script.read_text(encoding="utf-8")

        self.assertIn("DEPRECATED", text)
        self.assertIn("apply_storage_plan.sh", text)

    def test_apply_and_plan_wrappers_exist(self) -> None:
        self.assertTrue((ROOT / "scripts" / "plan_storage.sh").exists())
        self.assertTrue((ROOT / "scripts" / "apply_storage_plan.sh").exists())

    def test_skill_doc_routes_repo_history_to_repo_evidence_reference(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("repo-evidence", text)
        self.assertIn("historical-index-cleanup.md", text)
        self.assertIn("must", text.lower())

    def test_generic_profile_docs_do_not_expose_private_default_state_dir(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertNotIn(".private-cleanup", text)

    def test_renderer_contract_exposes_shared_core_fields(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-renderer-"))
        home = tmp / "home"
        _write(home / "Library" / "Caches" / "cache.bin", "x" * 128)
        report = _manager(home, profile="generic").plan()

        markdown = msm.render_markdown(report)
        text = msm.render_text(report)
        payload = report.to_dict()

        self.assertIn("Approved targets", markdown)
        self.assertIn("Approved scope", text)
        self.assertIn("approved_targets", json.dumps(payload, ensure_ascii=False))

    def test_facade_import_by_file_path_re_exports_core_symbols(self) -> None:
        module_path = ROOT / "scripts" / "mac_storage_manager.py"
        spec = importlib.util.spec_from_file_location("mac_storage_manager_facade", module_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)

        removed = False
        script_dir = str(SCRIPT_DIR)
        if script_dir in sys.path:
            sys.path.remove(script_dir)
            removed = True
        sys.modules.pop("_mac_storage_core", None)
        try:
            spec.loader.exec_module(mod)
        finally:
            if removed:
                sys.path.insert(0, script_dir)

        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(hasattr(mod, "StorageManager"))
        self.assertTrue(hasattr(mod, "render_markdown"))

    def test_refactor_exposes_dedicated_policy_render_and_cli_modules(self) -> None:
        scripts = ROOT / "scripts"
        self.assertTrue((scripts / "_mac_storage_policy.py").exists())
        self.assertTrue((scripts / "_mac_storage_render.py").exists())
        self.assertTrue((scripts / "_mac_storage_cli.py").exists())

    def test_policy_module_exposes_discovery_and_plan_entrypoints(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")

        self.assertTrue(hasattr(policy, "discover_targets"))
        self.assertTrue(hasattr(policy, "plan_targets"))
        self.assertTrue(hasattr(policy, "explicit_plan_blockers"))

    def test_storage_manager_discover_targets_delegates_to_policy_module(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-delegate-discover-"))
        home = tmp / "home"
        manager = _manager(home, profile="generic")
        policy = importlib.import_module("_mac_storage_policy")
        sentinel = [
            CleanupTarget(
                target_id="sentinel",
                name="Sentinel",
                category="test",
                kind="purge_tree",
                paths=(),
            )
        ]

        with mock.patch.object(policy, "discover_targets", return_value=sentinel) as patched:
            result = manager.discover_targets()

        self.assertEqual(result, sentinel)
        patched.assert_called_once_with(manager)

    def test_policy_discovery_calls_internal_impl_not_public_delegate(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")

        class StubManager:
            def _discover_targets_impl(self):
                return ["discover-impl"]

            def discover_targets(self):
                raise AssertionError("public discover_targets should not be called")

        self.assertEqual(policy.discover_targets(StubManager()), ["discover-impl"])

    def test_policy_plan_calls_internal_impl_not_public_delegate(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")

        class StubManager:
            def _plan_targets_impl(self, scans):
                return ["plan-impl", list(scans)]

            def plan_targets(self, scans):
                raise AssertionError("public plan_targets should not be called")

        self.assertEqual(policy.plan_targets(StubManager(), ["scan"]), ["plan-impl", ["scan"]])

    def test_policy_blockers_call_internal_impl_not_public_delegate(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")

        class StubManager:
            def _explicit_plan_blockers_impl(self, plan_items):
                return ["blockers-impl", list(plan_items)]

        self.assertEqual(policy.explicit_plan_blockers(StubManager(), ["item"]), ["blockers-impl", ["item"]])

    def test_policy_target_requires_approved_plan_uses_single_truth_source(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        base = dict(name="Example", category="cache", kind="purge_tree", paths=())

        low = CleanupTarget(target_id="low", risk="low", protection="normal", metadata={}, **base)
        high = CleanupTarget(target_id="high", risk="high", protection="normal", metadata={}, **base)
        meta = CleanupTarget(
            target_id="meta",
            risk="low",
            protection="normal",
            metadata={"cleanup_requires_approved_plan": True},
            **base,
        )
        protected = CleanupTarget(target_id="protected", risk="low", protection="approved_plan", metadata={}, **base)

        self.assertFalse(policy.target_requires_approved_plan(low))
        self.assertTrue(policy.target_requires_approved_plan(high))
        self.assertTrue(policy.target_requires_approved_plan(meta))
        self.assertTrue(policy.target_requires_approved_plan(protected))

    def test_policy_target_is_confirmed_keeps_low_risk_category_rule_only(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        low_target = CleanupTarget(target_id="home-caches", name="Cache", category="cache", kind="purge_tree", paths=(), risk="low")
        high_target = CleanupTarget(target_id="downloads", name="Downloads", category="user-files", kind="trash_tree", paths=(), risk="high")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-confirm-"))

        yes_context = StorageContext(home=tmp, root=tmp, yes=True)
        category_context = StorageContext(home=tmp, root=tmp, confirm_targets=frozenset({"cache", "user-files"}))
        exact_context = StorageContext(home=tmp, root=tmp, confirm_targets=frozenset({"downloads"}))

        self.assertTrue(policy.target_is_confirmed(yes_context, low_target))
        self.assertFalse(policy.target_is_confirmed(yes_context, high_target))
        self.assertTrue(policy.target_is_confirmed(category_context, low_target))
        self.assertFalse(policy.target_is_confirmed(category_context, high_target))
        self.assertTrue(policy.target_is_confirmed(exact_context, high_target))

    def test_policy_should_back_up_uses_single_truth_source(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        base = dict(name="Example", category="cache", kind="purge_tree", paths=())

        low = CleanupTarget(target_id="low", risk="low", source_layer="runtime_artifact", metadata={}, **base)
        high = CleanupTarget(target_id="high", risk="high", source_layer="runtime_artifact", metadata={}, **base)
        repo = CleanupTarget(target_id="repo", risk="low", source_layer="repo_reference", metadata={}, **base)
        history = CleanupTarget(target_id="history", risk="low", source_layer="historical_index", metadata={}, **base)
        leftovers = CleanupTarget(
            target_id="app-leftovers:Foo",
            risk="low",
            source_layer="runtime_artifact",
            metadata={"app_name": "Foo"},
            **base,
        )

        self.assertFalse(policy.should_back_up_target(low))
        self.assertTrue(policy.should_back_up_target(high))
        self.assertTrue(policy.should_back_up_target(repo))
        self.assertTrue(policy.should_back_up_target(history))
        self.assertTrue(policy.should_back_up_target(leftovers))

    def test_policy_resolves_default_protection_and_rollback(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")

        self.assertEqual(policy.resolve_target_protection("", {}, False), "normal")
        self.assertEqual(policy.resolve_target_protection("", {"cleanup_requires_approved_plan": True}, False), "approved_plan")
        self.assertEqual(policy.resolve_target_protection("", {}, True), "exact_confirm")
        self.assertEqual(policy.resolve_target_rollback("", "trash_tree"), "trash")
        self.assertEqual(policy.resolve_target_rollback("", "purge_tree"), "none")

    def test_policy_evaluate_plan_item_calls_internal_impl_not_public_delegate(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")

        class StubManager:
            def _evaluate_plan_item_impl(self, scan):
                return "evaluated", scan

            def evaluate_plan_item(self, scan):
                raise AssertionError("public evaluate_plan_item should not be called")

        self.assertEqual(policy.evaluate_plan_item(StubManager(), "scan"), ("evaluated", "scan"))

    def test_policy_evaluate_plan_item_returns_protected_session_block(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-eval-protected-"))
        manager = _manager(tmp, dry_run=False, apply=True, profile="generic")
        target = CleanupTarget(
            target_id="firefox-session",
            name="Firefox session",
            category="browser-session",
            kind="purge_tree",
            paths=(tmp / "cookies.sqlite",),
            risk="low",
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=10,
            eligible_bytes=10,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
            existing_paths=(str(tmp / "cookies.sqlite"),),
            notes=("protected_session=Firefox browser identity/session data is protected",),
        )

        item = policy.evaluate_plan_item(manager, scan)

        self.assertEqual(item.status, "blocked")
        self.assertEqual(item.scope_status, "protected_session")
        self.assertEqual(item.source_layer, "protected_session")
        self.assertEqual(item.protection, "blocked")

    def test_policy_evaluate_plan_item_returns_outside_approved_plan_block(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-eval-approved-"))
        manager = _manager(tmp, dry_run=False, apply=True, profile="generic")
        target = CleanupTarget(
            target_id="downloads",
            name="Downloads",
            category="user-files",
            kind="trash_tree",
            paths=(tmp / "Downloads",),
            risk="high",
            requires_confirmation=True,
            protection="approved_plan",
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=100,
            eligible_bytes=100,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
            existing_paths=(str(tmp / "Downloads"),),
        )

        item = policy.evaluate_plan_item(manager, scan)

        self.assertEqual(item.status, "blocked")
        self.assertEqual(item.scope_status, "outside_approved_plan")
        self.assertEqual(item.protection, "approved_plan")

    def test_policy_evaluate_plan_item_returns_exact_confirm_block(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-eval-confirm-"))
        manager = _manager(
            tmp,
            dry_run=False,
            apply=True,
            profile="generic",
            approved_targets={"downloads"},
        )
        target = CleanupTarget(
            target_id="downloads",
            name="Downloads",
            category="user-files",
            kind="trash_tree",
            paths=(tmp / "Downloads",),
            risk="high",
            requires_confirmation=True,
            protection="approved_plan",
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=100,
            eligible_bytes=100,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
            existing_paths=(str(tmp / "Downloads"),),
        )

        item = policy.evaluate_plan_item(manager, scan)

        self.assertEqual(item.status, "blocked")
        self.assertEqual(item.protection, "exact_confirm")
        self.assertIn("confirmation", item.reason)

    def test_policy_evaluate_plan_item_returns_ready_for_apply(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-eval-ready-"))
        manager = _manager(tmp, dry_run=False, apply=True, yes=True, profile="generic")
        target = CleanupTarget(
            target_id="home-caches",
            name="Home caches",
            category="cache",
            kind="purge_tree",
            paths=(tmp / "Library" / "Caches",),
            risk="low",
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=100,
            eligible_bytes=100,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
            existing_paths=(str(tmp / "Library" / "Caches"),),
        )

        item = policy.evaluate_plan_item(manager, scan)

        self.assertEqual(item.status, "ready")
        self.assertEqual(item.scope_status, "in_scope")
        self.assertEqual(item.reason, "eligible for cleanup")

    def test_policy_decide_plan_item_pure_function_ready_without_manager(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-decide-ready-"))
        context = StorageContext(home=tmp, root=tmp, dry_run=False, apply=True, yes=True)
        target = CleanupTarget(
            target_id="home-caches",
            name="Home caches",
            category="cache",
            kind="purge_tree",
            paths=(tmp / "Library" / "Caches",),
            risk="low",
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=100,
            eligible_bytes=100,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
            existing_paths=(str(tmp / "Library" / "Caches"),),
        )

        item = policy.decide_plan_item(context, scan, missing_tools=(), docker_context_local=True)

        self.assertEqual(item.status, "ready")
        self.assertEqual(item.reason, "eligible for cleanup")
        self.assertEqual(item.protection, "normal")

    def test_policy_decide_plan_item_pure_function_protected_session_without_manager(self) -> None:
        policy = importlib.import_module("_mac_storage_policy")
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-decide-protected-"))
        context = StorageContext(home=tmp, root=tmp, dry_run=False, apply=True, yes=True)
        target = CleanupTarget(
            target_id="firefox-session",
            name="Firefox session",
            category="browser-session",
            kind="purge_tree",
            paths=(tmp / "cookies.sqlite",),
            risk="low",
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=10,
            eligible_bytes=10,
            total_files=1,
            eligible_files=1,
            newest_mtime=None,
            oldest_mtime=None,
            existing_paths=(str(tmp / "cookies.sqlite"),),
            notes=("protected_session=Firefox browser identity/session data is protected",),
        )

        item = policy.decide_plan_item(context, scan, missing_tools=(), docker_context_local=True)

        self.assertEqual(item.status, "blocked")
        self.assertEqual(item.scope_status, "protected_session")
        self.assertEqual(item.protection, "blocked")

    def test_discover_targets_impl_composes_builder_sections(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-builder-compose-"))
        home = tmp / "home"
        home.mkdir(parents=True, exist_ok=True)
        manager = _manager(home, profile="generic", include_hidden_home=True, include_system=True)

        def sentinel(target_id: str) -> CleanupTarget:
            return CleanupTarget(
                target_id=target_id,
                name=target_id,
                category="test",
                kind="purge_tree",
                paths=(),
            )

        manager._discover_base_targets = lambda: [sentinel("base")]  # type: ignore[attr-defined]
        manager._discover_hidden_home_targets = lambda: [sentinel("hidden")]  # type: ignore[attr-defined]
        manager._discover_system_targets = lambda: [sentinel("system")]  # type: ignore[attr-defined]
        manager._discover_flutter_targets = lambda: [sentinel("flutter")]  # type: ignore[method-assign]
        manager._discover_app_leftovers_targets = lambda: [sentinel("leftovers")]  # type: ignore[method-assign]

        targets = manager._discover_targets_impl()

        self.assertEqual(
            [target.target_id for target in targets],
            ["base", "hidden", "system", "flutter", "leftovers"],
        )

    def test_flutter_discovery_uses_shared_target_factory(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-flutter-factory-"))
        home = tmp / "home"
        projects = tmp / "projects"
        _write(projects / "demo" / "pubspec.yaml", "name: demo\n")
        manager = _manager(home, root=projects, flutter_search_root=projects)
        calls: list[str] = []

        def fake_factory():
            def make(target_id: str, *args, **kwargs):
                calls.append(target_id)
                return CleanupTarget(
                    target_id=target_id,
                    name=kwargs.get("name", target_id) if "name" in kwargs else target_id,
                    category=kwargs.get("category", "test") if "category" in kwargs else "test",
                    kind=kwargs.get("kind", "purge_tree") if "kind" in kwargs else "purge_tree",
                    paths=tuple(kwargs.get("raw_paths", ()) if "raw_paths" in kwargs else ()),
                )
            return make

        manager._target_factory = fake_factory  # type: ignore[method-assign]

        targets = manager._discover_flutter_targets()

        self.assertEqual(calls, ["flutter-cleanup:demo"])
        self.assertEqual([target.target_id for target in targets], ["flutter-cleanup:demo"])

    def test_app_leftovers_discovery_uses_shared_target_factory(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-leftovers-factory-"))
        home = tmp / "home"
        app = tmp / "FooCleaner.app"
        info = app / "Contents" / "Info.plist"
        info.parent.mkdir(parents=True, exist_ok=True)
        with info.open("wb") as fh:
            plistlib.dump({"CFBundleIdentifier": "com.example.foocleaner"}, fh)
        _write(app / "Contents" / "MacOS" / "FooCleaner", "#!/usr/bin/env bash\n")
        _write(home / "Library" / "Application Support" / "FooCleaner" / "cache.db", "cache")

        manager = _manager(home, app_path=app, system_roots=(tmp / "var" / "db" / "receipts",))
        calls: list[str] = []

        def fake_factory():
            def make(target_id: str, *args, **kwargs):
                calls.append(target_id)
                return CleanupTarget(
                    target_id=target_id,
                    name=kwargs.get("name", target_id) if "name" in kwargs else target_id,
                    category=kwargs.get("category", "test") if "category" in kwargs else "test",
                    kind=kwargs.get("kind", "purge_tree") if "kind" in kwargs else "purge_tree",
                    paths=tuple(kwargs.get("raw_paths", ()) if "raw_paths" in kwargs else ()),
                )
            return make

        manager._target_factory = fake_factory  # type: ignore[method-assign]

        targets = manager._discover_app_leftovers_targets()

        self.assertEqual(calls, ["app-leftovers:FooCleaner"])
        self.assertEqual([target.target_id for target in targets], ["app-leftovers:FooCleaner"])

    def test_probe_facts_collects_missing_tools_and_docker_locality(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-probe-facts-"))
        home = tmp / "home"
        runner = FakeRunner(which_map={"docker": "/usr/bin/docker", "brew": None})
        runner.set_response(["docker", "context", "show"], stdout="desktop-linux\n")
        runner.set_response(
            ["docker", "context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"],
            stdout="unix:///var/run/docker.sock\n",
        )
        manager = _manager(home, runner=runner, dry_run=False, apply=True)
        docker_target = CleanupTarget(
            target_id="docker-prune",
            name="Docker prune",
            category="docker",
            kind="command",
            paths=(),
            required_tools=("docker",),
        )
        brew_target = CleanupTarget(
            target_id="brew-cleanup",
            name="Brew cleanup",
            category="homebrew",
            kind="command",
            paths=(),
            required_tools=("brew",),
        )

        docker_facts = manager._probe_target_facts(docker_target)
        brew_facts = manager._probe_target_facts(brew_target)

        self.assertEqual(docker_facts.missing_tools, ())
        self.assertTrue(docker_facts.docker_context_local)
        self.assertEqual(brew_facts.missing_tools, ("brew",))
        self.assertIsNone(brew_facts.docker_context_local)

    def test_evaluate_plan_item_impl_consumes_probe_layer(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-probe-consume-"))
        home = tmp / "home"
        manager = _manager(home, dry_run=False, apply=True)
        target = CleanupTarget(
            target_id="docker-prune",
            name="Docker prune",
            category="docker",
            kind="command",
            paths=(tmp / "Library" / "Containers" / "com.docker.docker",),
            risk="high",
            protection="approved_plan",
            required_tools=("docker",),
        )
        scan = msm.TargetScan(
            target=target,
            exists=True,
            total_bytes=1,
            eligible_bytes=1,
            total_files=0,
            eligible_files=0,
            newest_mtime=None,
            oldest_mtime=None,
        )
        manager._probe_target_facts = lambda _target: msm.ProbeFacts(missing_tools=(), docker_context_local=False)  # type: ignore[method-assign]

        item = manager._evaluate_plan_item_impl(scan)

        self.assertEqual(item.status, "skipped")
        self.assertEqual(item.reason, "docker context is remote")

    def test_probe_facts_is_explicit_model(self) -> None:
        self.assertTrue(hasattr(msm, "ProbeFacts"))
        facts = msm.ProbeFacts(missing_tools=("brew",), docker_context_local=None)
        self.assertEqual(facts.missing_tools, ("brew",))
        self.assertIsNone(facts.docker_context_local)

    def test_scan_target_notes_delegate_to_helper(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-note-helper-"))
        home = tmp / "home"
        target_path = _write(home / ".npm" / "_cacache" / "owned.txt", "cache")
        manager = _manager(home, include_hidden_home=True)
        target = CleanupTarget(
            target_id="probe-cache",
            name="Probe cache",
            category="cache",
            kind="purge_tree",
            paths=(target_path.parent,),
        )
        manager._collect_target_notes = lambda _target, _path, _total_bytes, _owner_uid: ["helper-note=used"]  # type: ignore[method-assign]

        scans = manager.scan_targets([target])

        self.assertEqual(scans[0].notes, ("helper-note=used",))

    def test_audit_runs_with_default_policy_module_without_recursion(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-audit-runtime-"))
        home = tmp / "home"
        _write(home / "Library" / "Caches" / "cache.bin", "x" * 128)

        report = _manager(home, profile="generic").audit()

        self.assertEqual(report.mode, "audit")
        self.assertTrue(any(item.target_id == "home-caches" for item in report.plan_items))

    def test_storage_manager_plan_targets_delegates_to_policy_module(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="mac-storage-policy-delegate-plan-"))
        home = tmp / "home"
        manager = _manager(home, profile="generic")
        policy = importlib.import_module("_mac_storage_policy")
        sentinel_item = msm.PlanItem(
            target_id="sentinel",
            name="Sentinel",
            category="test",
            kind="purge_tree",
            risk="low",
            status="planned",
            reason="sentinel",
            estimated_bytes=0,
        )

        with mock.patch.object(policy, "plan_targets", return_value=[sentinel_item]) as patched:
            result = manager.plan_targets([])

        self.assertEqual(result, [sentinel_item])
        patched.assert_called_once_with(manager, [])


if __name__ == "__main__":
    unittest.main()
