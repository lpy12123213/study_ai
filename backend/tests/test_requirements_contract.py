from __future__ import annotations

import unittest
from pathlib import Path


class TestRequirementsContract(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[2]

    def _requirement_lines(self, relative_path: str) -> list[str]:
        path = self.root / relative_path
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_chromadb_is_not_required_for_base_setup(self) -> None:
        base_requirements = self._requirement_lines("requirements.txt")
        semantic_requirements = self._requirement_lines("requirements-semantic-memory.txt")

        self.assertFalse(
            any(line.startswith("chromadb") for line in base_requirements),
            "Base setup should not require chromadb because SemanticStore already has a JSONL fallback.",
        )
        self.assertTrue(
            any(line.startswith("chromadb") for line in semantic_requirements),
            "Optional semantic memory requirements should carry chromadb explicitly.",
        )


if __name__ == "__main__":
    unittest.main()
