from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_lockfile_check():
    path = ROOT / "scripts" / "audit" / "lockfile_check.py"
    spec = importlib.util.spec_from_file_location("study_ai_lockfile_check", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/audit/lockfile_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LockfileCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.check = load_lockfile_check()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_lock(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_accepts_clean_win_lock(self) -> None:
        lock = self.write_lock(
            "requirements-lock-win.txt",
            "fastapi==0.136.1\npywin32==311; sys_platform == 'win32'\n",
        )
        findings = self.check.check_lock_file(lock, platform="win")
        self.assertEqual([], findings)

    def test_rejects_mypy(self) -> None:
        lock = self.write_lock("requirements-lock-win.txt", "fastapi==0.136.1\nmypy==2.1.0\n")
        findings = self.check.check_lock_file(lock, platform="win")
        self.assertTrue(any("removed tool" in f and "mypy" in f for f in findings))

    def test_rejects_mypy_extensions(self) -> None:
        lock = self.write_lock("requirements-lock-win.txt", "mypy_extensions==1.1.0\n")
        findings = self.check.check_lock_file(lock, platform="win")
        self.assertTrue(any("removed tool" in f for f in findings))

    def test_rejects_absolute_local_path(self) -> None:
        lock = self.write_lock("requirements-lock-win.txt", "fastapi==0.136.1\n/home/user/local-pkg\n")
        findings = self.check.check_lock_file(lock, platform="win")
        self.assertTrue(any("local path" in f for f in findings))

    def test_rejects_editable_path(self) -> None:
        lock = self.write_lock("requirements-lock-win.txt", "-e .\n")
        findings = self.check.check_lock_file(lock, platform="win")
        self.assertTrue(any("local path" in f for f in findings))

    def test_rejects_pywin32_in_linux_lock(self) -> None:
        lock = self.write_lock("requirements-lock-linux.txt", "pywin32==311\n")
        findings = self.check.check_lock_file(lock, platform="linux")
        self.assertTrue(any("pywin32" in f for f in findings))

    def test_rejects_pywin32_in_unknown_platform_lock(self) -> None:
        lock = self.write_lock("requirements-lock.txt", "pywin32==311\n")
        findings = self.check.check_lock_file(lock)
        self.assertTrue(any("pywin32" in f for f in findings))


if __name__ == "__main__":
    unittest.main()
