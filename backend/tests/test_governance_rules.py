from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestGovernanceRules(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]

    def test_no_long_lived_legacy_or_versioned_paths(self) -> None:
        """Prevent re-introducing the same tech debt we just removed."""

        forbidden_exact = {"legacy", "compat", "shim"}
        # Examples: lesson_plan_v2, question_library_v3, service_v10
        versioned_re = re.compile(r".*_v\d+$", re.IGNORECASE)

        def should_skip(path: Path) -> bool:
            rel = path.relative_to(self.root)
            for part in rel.parts:
                if part.startswith("."):
                    return True
                if part in {"__pycache__", "node_modules", "venv", "artifacts", "data", "playwright-report", "test-results"}:
                    return True
            return False

        roots = [self.root / "backend", self.root / "frontend" / "src"]
        for base in roots:
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if should_skip(p):
                    continue
                for part in p.relative_to(self.root).parts:
                    if part.lower() in forbidden_exact:
                        self.fail(f"forbidden_path_segment: {p}")
                    if versioned_re.match(part):
                        self.fail(f"versioned_path_segment: {p}")

        # Explicit historic offenders (should stay deleted).
        self.assertFalse((self.root / "backend" / "api" / "models.py").exists())
        self.assertFalse((self.root / "backend" / "database" / "models.py").exists())
        self.assertFalse((self.root / "backend" / "database" / "legacy_migrations.py").exists())

    def test_gitignore_does_not_hide_nextstep_csv(self) -> None:
        gitignore = (self.root / ".gitignore").read_text(encoding="utf-8")
        # `nextstep.csv` is the governance checklist; it should stay visible/tracked.
        self.assertNotIn("\nnextstep.csv\n", "\n" + gitignore.replace("\r\n", "\n") + "\n")


if __name__ == "__main__":
    unittest.main()
