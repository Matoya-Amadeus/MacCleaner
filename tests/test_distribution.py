from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        source_root = str(ROOT / "src")
        env["PYTHONPATH"] = source_root + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_package_module_cli_and_legacy_facade_are_available(self) -> None:
        imported = self._run("-c", "import maccleaner; print(maccleaner.__version__)")
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertEqual(imported.stdout.strip(), "0.1.0")

        module_help = self._run("-m", "maccleaner", "--help")
        self.assertEqual(module_help.returncode, 0, module_help.stderr)
        self.assertIn("Audit and clean macOS storage safely.", module_help.stdout)

        legacy_help = self._run("scripts/mac_storage_manager.py", "--help")
        self.assertEqual(legacy_help.returncode, 0, legacy_help.stderr)
        self.assertIn("Audit and clean macOS storage safely.", legacy_help.stdout)


if __name__ == "__main__":
    unittest.main()
