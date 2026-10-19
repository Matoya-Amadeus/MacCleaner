"""仓库里不许出现"本机信息"或密钥（2026-10-20 用户明确要求）。

本机信息指：真实用户名下的绝对家目录路径（`/Users/<你的名字>/...`）、主机名、序列号。
密钥指：GitHub token、OpenAI key、AWS key、私钥块、`.env` 一类文件。

为什么要有这条守卫：这类泄漏一旦进了 git 历史，改代码也删不掉（历史仍能检出），
所以必须在**提交前**就拦住；测试跑的是 `git ls-files`，只看被跟踪的文件。
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 允许出现的"家目录"前缀：全是文档/测试里约定的占位名。
ALLOWED_HOME_USERS = {
    "x",
    "demo",
    "example",
    "you",
    "yourname",
    "user",
    "runner",       # GitHub Actions
    "shared",
}

HOME_PATH = re.compile(r"/Users/(?P<name>[A-Za-z0-9._-]+)/")
# 只查"本机真实主机名"，不做通用的 `*.local` 匹配：
# 仓库里合法出现的 `dataSources.local.xml`、`"Dockerfile.local"` 都是文件名，不是主机名。


def local_hostnames() -> set[str]:
    names: set[str] = set()
    try:
        import socket

        host = socket.gethostname()
        if host and host not in {"localhost"}:
            names.add(host)
            names.add(host.split(".")[0])
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["/usr/sbin/scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if out and out != "localhost":
            names.add(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return {name for name in names if len(name) >= 4}
SECRETS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

SENSITIVE_SUFFIXES = (".env", ".pem", ".p12", ".pfx", ".key", ".keystore", ".mobileprovision")


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    return [ROOT / name for name in out.split("\0") if name]


def text_files() -> list[Path]:
    files: list[Path] = []
    for path in tracked_files():
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".icns", ".zip", ".gz", ".whl"}:
            continue
        files.append(path)
    return files


class NoLocalInfoOrSecretsTests(unittest.TestCase):
    def test_no_real_home_paths(self) -> None:
        offenders: list[str] = []
        for path in text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for match in HOME_PATH.finditer(line):
                    if match.group("name") not in ALLOWED_HOME_USERS:
                        offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {match.group(0)}")
        self.assertEqual(offenders, [], "仓库里出现了真实用户的家目录路径：\n" + "\n".join(offenders))

    def test_no_this_machines_hostname(self) -> None:
        """只针对**运行测试的这台机器**的主机名（CI 上没有就跳过）。"""
        names = local_hostnames()
        if not names:
            self.skipTest("拿不到本机主机名")
        offenders: list[str] = []
        for path in text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for name in names:
                if name in text:
                    offenders.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual(offenders, [], "仓库里出现了本机主机名：\n" + "\n".join(offenders))

    def test_no_secret_material(self) -> None:
        offenders: list[str] = []
        for path in text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for pattern in SECRETS:
                    if pattern.search(line):
                        offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {pattern.pattern}")
        self.assertEqual(offenders, [], "疑似密钥：\n" + "\n".join(offenders))

    def test_no_sensitive_file_types_are_tracked(self) -> None:
        tracked = {path.name for path in tracked_files()}
        offenders = sorted(
            name
            for name in tracked
            if name.endswith(SENSITIVE_SUFFIXES) or name in {"id_rsa", "id_ed25519", ".env"}
        )
        self.assertEqual(offenders, [], f"这些文件不该进仓库：{offenders}")


if __name__ == "__main__":
    unittest.main()
