"""启动器打包（2026-10-18）：真的跑一遍安装脚本，检查 `.app` 结构与图标接线。

为什么不只做静态断言（"plist 里有 CFBundleIconFile"）：图标之前正是**漏在打包环节**——
plist 里没这个键、Resources 里也没有 icns，Dock 就显示系统占位图。
所以这里跑真实脚本，再逐项检查产物。
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "install_launcher.sh"


class LauncherBundleTests(unittest.TestCase):
    def test_installer_builds_a_launchable_app_with_icon(self) -> None:
        with tempfile.TemporaryDirectory(prefix="launcher-") as tmp:
            prefix = Path(tmp) / "Applications"
            env = dict(os.environ)
            env["HOME"] = tmp
            completed = subprocess.run(
                ["/bin/bash", str(SCRIPT), "--prefix", str(prefix)],
                capture_output=True, text=True, env=env, timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            app = prefix / "MacCleaner.app"
            contents = app / "Contents"
            self.assertTrue(contents.is_dir(), "必须有 .app 结构")

            with (contents / "Info.plist").open("rb") as handle:
                plist = plistlib.load(handle)
            self.assertEqual(plist["CFBundleIconFile"], "AppIcon", "缺这个键 Dock 会显示占位图")
            self.assertEqual(plist["CFBundleIdentifier"], "local.maho.maccleaner.launcher")
            self.assertTrue(plist["NSHighResolutionCapable"])
            # 双击入口：有 swiftc 时是原生窗口，没有时退回 launch 脚本（两种都合法，不能写死一个）。
            self.assertIn(plist["CFBundleExecutable"], {"MacCleaner", "launch"})
            self.assertEqual(plist["MacCleanerRepo"], str(REPO_ROOT), "原生外壳要靠它找到仓库")
            # 缺这个键，WKWebView 会被 ATS 拦住 http://127.0.0.1，而**失败时不报错、只黑屏**
            # （2026-10-18 用户实际遇到）。它是打包契约，不是可选优化。
            ats = plist.get("NSAppTransportSecurity") or {}
            self.assertTrue(ats.get("NSAllowsLocalNetworking"), "必须放行本机网络")
            self.assertTrue(
                (ats.get("NSExceptionDomains") or {}).get("127.0.0.1", {}).get("NSExceptionAllowsInsecureHTTPLoads"),
                "必须为本机 loopback 放行明文 HTTP",
            )

            icon = contents / "Resources" / "AppIcon.icns"
            self.assertTrue(icon.is_file() and icon.stat().st_size > 0, "图标必须真的被拷进 bundle")

            launch = contents / "MacOS" / "launch"
            self.assertTrue(launch.is_file())
            self.assertTrue(os.access(launch, os.X_OK), "launch 必须可执行")
            # 有 swiftc 时必须产出真正的 Mach-O 可执行（不是脚本），否则双击会跳浏览器。
            native = contents / "MacOS" / "MacCleaner"
            if plist["CFBundleExecutable"] == "MacCleaner":
                self.assertTrue(native.is_file(), "原生外壳缺失")
                info = subprocess.run(["/usr/bin/file", str(native)], capture_output=True, text=True)
                self.assertIn("Mach-O", info.stdout, f"双击入口必须是原生可执行：{info.stdout.strip()}")

    def test_launch_forwards_arguments_to_the_cli(self) -> None:
        """`launch --help` 应当打到 `maccleaner ui` 的帮助页（证明它真的接到 CLI，而不是空壳）。"""
        with tempfile.TemporaryDirectory(prefix="launcher-run-") as tmp:
            prefix = Path(tmp) / "Applications"
            env = dict(os.environ)
            env["HOME"] = tmp
            subprocess.run(
                ["/bin/bash", str(SCRIPT), "--prefix", str(prefix)],
                capture_output=True, text=True, env=env, timeout=60, check=True,
            )
            launch = prefix / "MacCleaner.app" / "Contents" / "MacOS" / "launch"
            completed = subprocess.run(
                [str(launch), "--help"], capture_output=True, text=True, env=env, timeout=60
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("--no-open", completed.stdout, "应转发给 maccleaner ui，而不是自己吃掉参数")

    def test_installer_reports_missing_icon_instead_of_failing(self) -> None:
        """图标缺失时只警告，不阻断安装（构建机上可能没有二进制资产）。"""
        with tempfile.TemporaryDirectory(prefix="launcher-noicon-") as tmp:
            fake_repo = Path(tmp) / "repo"
            (fake_repo / "scripts").mkdir(parents=True)
            (fake_repo / "src" / "maccleaner").mkdir(parents=True)
            script = fake_repo / "scripts" / "install_launcher.sh"
            script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")

            env = dict(os.environ)
            env["HOME"] = tmp
            completed = subprocess.run(
                ["/bin/bash", str(script), "--prefix", str(Path(tmp) / "Applications")],
                capture_output=True, text=True, env=env, timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("AppIcon.icns 缺失", completed.stderr)
            self.assertTrue((Path(tmp) / "Applications" / "MacCleaner.app" / "Contents" / "Info.plist").is_file())


if __name__ == "__main__":
    unittest.main()
