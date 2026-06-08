from __future__ import annotations

import importlib
import sys
import unittest


class MigrationForwarderTests(unittest.TestCase):
    def test_retained_mcp_stdio_entrypoint_resolves_to_canonical_module(self) -> None:
        module = importlib.import_module("backend.mcp.stdio_server")
        self.assertEqual(module.main.__module__, "backend.integrations.mcp.tools.stdio_server")

    def test_removed_domain_forwarders_no_longer_resolve(self) -> None:
        old_names = [
            "backend.study_materials.orchestrator",
            "backend.lesson_plan.service",
            "backend.deepthink.tot_engine",
            "backend.question_library.table_repair",
            "backend.question_evaluate.service",
            "backend.paper_compose.workflow",
            "backend.chat.service",
            "backend.crawler.zujuan.client",
        ]

        importlib.invalidate_caches()
        for old_name in old_names:
            with self.subTest(old_name=old_name):
                sys.modules.pop(old_name, None)
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(old_name)


if __name__ == "__main__":
    unittest.main()
