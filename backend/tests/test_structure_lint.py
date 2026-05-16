from __future__ import annotations

import unittest

from scripts.audit import structure_lint


class StructureLintTests(unittest.TestCase):
    def test_compatibility_wrappers_have_explicit_removal_targets(self) -> None:
        self.assertEqual(structure_lint.check_expiring_compat_modules(), [])

    def test_banned_file_patterns_cover_legacy_and_compat_modules(self) -> None:
        self.assertTrue(any(pattern.match("thing_legacy.py") for pattern in structure_lint.BANNED_LONG_LIVED_FILE_PATTERNS))
        self.assertTrue(any(pattern.match("thing_compat.py") for pattern in structure_lint.BANNED_LONG_LIVED_FILE_PATTERNS))


if __name__ == "__main__":
    unittest.main()
