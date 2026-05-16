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


if __name__ == "__main__":
    unittest.main()
