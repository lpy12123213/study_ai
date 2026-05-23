from __future__ import annotations

import importlib
from pathlib import Path
import unittest


class MigrationForwarderTests(unittest.TestCase):
    def test_old_domain_submodule_imports_resolve_to_canonical_modules(self) -> None:
        cases = {
            "backend.question_library.table_repair": ("backend", "generation", "question_library"),
            "backend.crawler.zujuan.client": ("backend", "integrations", "crawler"),
            "backend.mcp.search.github": ("backend", "integrations", "mcp"),
            "backend.chat.service": ("backend", "workspace", "chat"),
        }

        for old_name, canonical_parts in cases.items():
            with self.subTest(old_name=old_name):
                module = importlib.import_module(old_name)
                module_file = Path(str(getattr(module, "__file__", ""))).resolve()
                module_parts = tuple(module_file.parts)
                self.assertIn(canonical_parts, [module_parts[i : i + len(canonical_parts)] for i in range(len(module_parts))])


if __name__ == "__main__":
    unittest.main()
