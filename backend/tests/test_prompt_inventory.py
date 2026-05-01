from __future__ import annotations

from pathlib import Path
import re
import unittest

from backend.generation.agentic.prompts import (
    PROMPT_INVENTORY_ALLOWLIST,
    PROMPT_INVENTORY_TARGETS,
)


_PROMPT_MARKERS = re.compile(r"(你是|只输出|严格输出|output_format|instructions|system prompt)", re.IGNORECASE)


class PromptInventoryTests(unittest.TestCase):
    def test_inventory_targets_exist(self) -> None:
        root = Path(__file__).resolve().parents[2]
        missing = [path for path in PROMPT_INVENTORY_TARGETS if not (root / path).exists()]

        self.assertEqual(missing, [])

    def test_inline_prompt_locations_are_allowlisted_during_migration(self) -> None:
        root = Path(__file__).resolve().parents[2]
        findings: list[str] = []

        for rel in PROMPT_INVENTORY_TARGETS:
            path = root / rel
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if _PROMPT_MARKERS.search(line):
                    findings.append(f"{rel}:{line_no}")

        unexpected = [item for item in findings if item not in PROMPT_INVENTORY_ALLOWLIST]

        self.assertEqual(unexpected, [], msg="\n".join(unexpected[:80]))


if __name__ == "__main__":
    unittest.main()
