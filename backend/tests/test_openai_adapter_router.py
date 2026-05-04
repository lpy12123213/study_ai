from __future__ import annotations

import unittest

from backend.app import create_app
from backend.core.openai_adapter import create_app as create_openai_adapter_app


def _route_paths(app) -> set[str]:
    return {str(getattr(route, "path", "")) for route in app.routes}


class TestOpenAIAdapterRouter(unittest.TestCase):
    def test_main_app_mounts_openai_adapter_under_integrations_domain(self) -> None:
        paths = _route_paths(create_app())

        self.assertIn("/api/integrations/openai/search-by-keyword", paths)
        self.assertIn("/api/integrations/openai/compose-blueprint", paths)
        self.assertIn("/api/integrations/openai/papers/{paper_id}", paths)
        self.assertNotIn("/api/search-by-keyword", paths)

    def test_standalone_adapter_keeps_legacy_api_prefix(self) -> None:
        paths = _route_paths(create_openai_adapter_app())

        self.assertIn("/api/search-by-keyword", paths)
        self.assertIn("/api/compose-blueprint", paths)
        self.assertIn("/api/papers/{paper_id}", paths)


if __name__ == "__main__":
    unittest.main()

