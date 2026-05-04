from __future__ import annotations

import os
import unittest
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

    def test_settings_model_tier_map_accepts_env_json_override(self) -> None:
        env = {
            "MODEL_TIER_MAP": '{"fast":"env-fast","cheap":"env-cheap","main":"env-main-tier","heavy":"env-heavy"}',
            "MAIN_MODEL": "env-main",
            "SUB_MODEL": "env-sub",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        self.assertEqual(settings.model_tier_map["fast"], "env-fast")
        self.assertEqual(settings.model_tier_map["cheap"], "env-cheap")
        self.assertEqual(settings.model_tier_map["main"], "env-main-tier")
        self.assertEqual(settings.model_tier_map["heavy"], "env-heavy")


if __name__ == "__main__":
    unittest.main()
