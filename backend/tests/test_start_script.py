from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


def load_start_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "start.py"
    spec = importlib.util.spec_from_file_location("study_ai_start_script", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrontendDistStalenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "frontend" / "src").mkdir(parents=True)
        (self.root / "frontend" / "dist").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_with_mtime(self, rel: str, content: str, mtime: float) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_reports_stale_dist_when_source_is_newer(self) -> None:
        self.write_with_mtime("frontend/dist/assets/app.js", "old build", 1000)
        self.write_with_mtime("frontend/src/App.tsx", "new source", 2000)

        stale, message = self.start.frontend_dist_staleness(self.root)

        self.assertTrue(stale)
        self.assertIn("frontend/dist is stale", message)
        self.assertIn("npm run build", message)

    def test_accepts_dist_newer_than_source(self) -> None:
        self.write_with_mtime("frontend/src/App.tsx", "source", 1000)
        self.write_with_mtime("frontend/dist/assets/app.js", "new build", 2000)

        stale, message = self.start.frontend_dist_staleness(self.root)

        self.assertFalse(stale)
        self.assertEqual("", message)

    def test_missing_dist_does_not_warn_for_dev_mode(self) -> None:
        self.write_with_mtime("frontend/src/App.tsx", "source", 1000)
        for item in (self.root / "frontend" / "dist").glob("*"):
            if item.is_file():
                item.unlink()
        (self.root / "frontend" / "dist").rmdir()

        stale, message = self.start.frontend_dist_staleness(self.root)

        self.assertFalse(stale)
        self.assertEqual("", message)


class SelectedRequirementFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, name: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content\n", encoding="utf-8")

    def names(self, files: list[Path]) -> list[str]:
        return [p.name for p in files]

    def test_win32_selects_win_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-win.txt")
        self.write("requirements-dev.txt")

        files = self.start._selected_requirement_files(self.root, "win32")

        self.assertEqual(
            ["requirements.txt", "requirements-lock-win.txt", "requirements-dev.txt"],
            self.names(files),
        )

    def test_win32_falls_back_when_only_linux_lock_present(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-linux.txt")
        self.write("requirements-dev.txt")

        files = self.start._selected_requirement_files(self.root, "win32")

        self.assertEqual(["requirements.txt", "requirements-dev.txt"], self.names(files))

    def test_linux_selects_linux_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-win.txt")
        self.write("requirements-lock-linux.txt")

        files = self.start._selected_requirement_files(self.root, "linux")

        self.assertEqual(["requirements.txt", "requirements-lock-linux.txt"], self.names(files))

    def test_darwin_selects_mac_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-mac.txt")

        files = self.start._selected_requirement_files(self.root, "darwin")

        self.assertEqual(["requirements.txt", "requirements-lock-mac.txt"], self.names(files))

    def test_no_lock_falls_back_to_ranges(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-dev.txt")

        files = self.start._selected_requirement_files(self.root, "win32")

        self.assertEqual(["requirements.txt", "requirements-dev.txt"], self.names(files))

    def test_unknown_platform_never_selects_a_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-win.txt")

        files = self.start._selected_requirement_files(self.root, "freebsd")

        self.assertEqual(["requirements.txt"], self.names(files))

    def test_platform_lock_name_mapping(self) -> None:
        self.assertEqual("requirements-lock-win.txt", self.start._platform_lock_name("win32"))
        self.assertEqual("requirements-lock-linux.txt", self.start._platform_lock_name("linux"))
        self.assertEqual("requirements-lock-mac.txt", self.start._platform_lock_name("darwin"))
        self.assertIsNone(self.start._platform_lock_name("freebsd"))


if __name__ == "__main__":
    unittest.main()
