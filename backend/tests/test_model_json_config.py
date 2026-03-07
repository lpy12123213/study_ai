import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.core.settings import Settings


class ModelJsonConfigTests(unittest.TestCase):
    def test_settings_loads_model_json_and_pins_provider(self) -> None:
        payload = {
            "active_provider": "deepseek",
            "providers": {
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1/chat/completions",
                    "api_key": "ds-key",
                },
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "or-key",
                },
            },
            "models": {
                "main": {"deepseek": "deepseek-chat", "openrouter": "openai/gpt-4o-mini"},
                "sub": "deepseek-chat",
                "lesson_plan": {"deepseek": "deepseek-chat"},
            },
            "params": {
                "main_temperature": 0.4,
                "main_max_tokens": 1234,
                "sub_temperature": 0.2,
                "sub_max_tokens": 567,
            },
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            old = os.environ.get("MODEL_CONFIG_PATH")
            os.environ["MODEL_CONFIG_PATH"] = str(path)
            try:
                settings = Settings.from_env()
            finally:
                if old is None:
                    os.environ.pop("MODEL_CONFIG_PATH", None)
                else:
                    os.environ["MODEL_CONFIG_PATH"] = old

        self.assertTrue(settings.llm_provider_pinned)
        self.assertEqual(settings.llm_active_provider, "deepseek")

        self.assertEqual(settings.chat_provider, "deepseek")
        self.assertEqual(settings.chat_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(settings.chat_api_key, "ds-key")

        self.assertEqual(settings.lesson_plan_provider, "deepseek")
        self.assertEqual(settings.lesson_plan_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(settings.lesson_plan_api_key, "ds-key")

        self.assertEqual(settings.openrouter_base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(settings.openrouter_api_key, "or-key")

        self.assertEqual(settings.main_model, "deepseek-chat")
        self.assertEqual(settings.sub_model, "deepseek-chat")
        self.assertEqual(settings.lesson_plan_model, "deepseek-chat")

        self.assertAlmostEqual(settings.main_model_temperature, 0.4, places=3)
        self.assertEqual(settings.main_model_max_tokens, 1234)
        self.assertAlmostEqual(settings.sub_model_temperature, 0.2, places=3)
        self.assertEqual(settings.sub_model_max_tokens, 567)

