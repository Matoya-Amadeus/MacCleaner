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


class IconAssetTests(unittest.TestCase):
    """图标必须是**多尺寸真 icns**（2026-10-19 重做：原来只有一个占位方块）。"""

    def test_icns_carries_every_size(self) -> None:
        import subprocess
        import tempfile

        icns = REPO_ROOT / "assets" / "AppIcon.icns"
        self.assertTrue(icns.is_file(), "缺少图标资产")
        self.assertGreater(icns.stat().st_size, 100_000, "过小的 icns 通常只有一种尺寸")
        with tempfile.TemporaryDirectory(prefix="icns-") as tmp:
            out = Path(tmp) / "AppIcon.iconset"
            result = subprocess.run(
                ["/usr/bin/iconutil", "-c", "iconset", str(icns), "-o", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            names = {item.name for item in out.iterdir()}
        for expected in ("icon_16x16.png", "icon_32x32.png", "icon_128x128.png",
                         "icon_256x256.png", "icon_512x512.png", "icon_512x512@2x.png"):
            self.assertIn(expected, names, f"icns 缺尺寸 {expected}")

    def test_generator_script_is_reproducible(self) -> None:
        """图标要能重跑生成——否则下次换色只能靠"谁手里有那张 png"。"""
        script = REPO_ROOT / "assets" / "icon" / "build_icon.py"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("superellipse", text, "超椭圆几何要写在脚本里，不是手画个圆角矩形")
        self.assertIn("AppIcon-1024.png", text)

class WindowFrameTests(unittest.TestCase):
    """窗口尺寸记忆（2026-10-19 实测）：autosave 能存能恢复，但**恢复后必须夹到最小尺寸**。

    `NSWindow.minSize` 只约束用户拖拽，管不住 autosave 恢复出来的 frame
    （种 400x300 会原样恢复），所以源码里必须有一次显式夹取——这里钉住它，
    避免以后有人"优化"掉这段让布局被挤坏。
    """

    def test_frame_is_clamped_after_restore(self) -> None:
        source = (REPO_ROOT / "scripts" / "launcher" / "main.swift").read_text(encoding="utf-8")
        self.assertIn("setFrameAutosaveName", source)
        self.assertIn("minSize", source)
        self.assertIn("clamped.size.width = max(", source, "恢复后要显式夹一次")
        self.assertIn("clamped.size.height = max(", source)

class PackagingMetadataTests(unittest.TestCase):
    """`pyproject.toml` 的 license 写法必须与声明的最低 setuptools 版本匹配。

    2026-10-19 实测：`license = "MIT"` + `license-files` 是 PEP 639（需 setuptools>=77），
    而 build-system 声明的是 `>=61` → 在 setuptools 63 上直接
    `ValueError: invalid pyproject.toml config: project.license`，构建失败。
    """

    def test_license_uses_pep621_table_form(self) -> None:
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('license = { text = "MIT" }', text)
        self.assertNotRegex(text, r'(?m)^license = "', "字符串形式需要 setuptools>=77，与 >=61 的声明不符")

