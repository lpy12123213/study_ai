from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.agent.config import AgentConfig
from backend.core.settings import Settings


class AgentModelTierTests(unittest.TestCase):
    def test_agent_config_resolves_tier_with_fallback(self) -> None:
        cfg = AgentConfig(
            planner_model="planner",
            summarizer_model="summarizer",
            reflector_model="reflector",
            model_tier_map={"fast": "cheap-model", "main": "main-model", "heavy": "heavy-model"},
        )

        self.assertEqual(cfg.model_for_tier("fast", fallback="summarizer"), "cheap-model")
        self.assertEqual(cfg.model_for_tier("main", fallback="planner"), "main-model")
        self.assertEqual(cfg.model_for_tier("missing", fallback="fallback-model"), "fallback-model")

    def test_settings_model_tier_map_accepts_model_json_override(self) -> None:
        payload = {
            "active_provider": "test",
            "providers": {"test": {"base_url": "https://example.test/v1", "api_key": "key"}},
            "models": {"main": "json-main", "sub": "json-sub"},
            "params": {
                "model_tier_map": {
                    "fast": "json-fast",
                    "cheap": "json-cheap",
                    "main": "json-main-tier",
                    "heavy": "json-heavy",
                }
            },
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {"MODEL_CONFIG_PATH": str(path)}, clear=False):
                settings = Settings.from_env()

        self.assertEqual(settings.model_tier_map["fast"], "json-fast")
        self.assertEqual(settings.model_tier_map["cheap"], "json-cheap")
        self.assertEqual(settings.model_tier_map["main"], "json-main-tier")
        self.assertEqual(settings.model_tier_map["heavy"], "json-heavy")


if __name__ == "__main__":
    unittest.main()
