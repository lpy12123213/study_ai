from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.llm.model_config import load_model_json_config
from backend.llm.model_settings import save_model_settings_payload


class ModelSettingsTests(unittest.TestCase):
    def test_save_encrypts_api_key_and_loader_decrypts_it(self) -> None:
        old_model_path = os.environ.get("MODEL_CONFIG_PATH")
        old_key_path = os.environ.get("LOCAL_ENCRYPTION_KEY_PATH")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model_path = root / "model.json"
            key_path = root / "model_config.key"
            os.environ["MODEL_CONFIG_PATH"] = str(model_path)
            os.environ["LOCAL_ENCRYPTION_KEY_PATH"] = str(key_path)
            try:
                saved = save_model_settings_payload(
                    repo_root=root,
                    payload={
                        "active_provider": "deepseek",
                        "pinned": True,
                        "provider": {
                            "name": "deepseek",
                            "base_url": "https://api.deepseek.com/v1/chat/completions",
                            "api_key": "ds-secret-key",
                        },
                        "models": {"main": "deepseek-chat", "sub": "deepseek-chat"},
                    },
                )

                raw_text = model_path.read_text(encoding="utf-8")
                self.assertNotIn("ds-secret-key", raw_text)
                self.assertIn("enc:v1:", raw_text)
                self.assertTrue(saved["providers"][0]["api_key_set"])
                self.assertTrue(saved["providers"][0]["api_key_encrypted"])

                loaded = load_model_json_config(repo_root=root)
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.providers["deepseek"].api_key, "ds-secret-key")
                self.assertEqual(loaded.providers["deepseek"].base_url, "https://api.deepseek.com/v1")
                self.assertTrue(loaded.pinned)
                self.assertEqual(loaded.models["main"], "deepseek-chat")

                save_model_settings_payload(
                    repo_root=root,
                    payload={
                        "active_provider": "deepseek",
                        "pinned": True,
                        "provider": {
                            "name": "deepseek",
                            "base_url": "https://api.deepseek.com/v1",
                        },
                        "models": {"lesson_plan": "deepseek-reasoner"},
                    },
                )
                loaded_again = load_model_json_config(repo_root=root)
                self.assertIsNotNone(loaded_again)
                assert loaded_again is not None
                self.assertEqual(loaded_again.providers["deepseek"].api_key, "ds-secret-key")
                self.assertEqual(loaded_again.models["lesson_plan"], "deepseek-reasoner")

                stored = json.loads(model_path.read_text(encoding="utf-8"))
                self.assertTrue(str(stored["providers"]["deepseek"]["api_key"]).startswith("enc:v1:"))
            finally:
                if old_model_path is None:
                    os.environ.pop("MODEL_CONFIG_PATH", None)
                else:
                    os.environ["MODEL_CONFIG_PATH"] = old_model_path
                if old_key_path is None:
                    os.environ.pop("LOCAL_ENCRYPTION_KEY_PATH", None)
                else:
                    os.environ["LOCAL_ENCRYPTION_KEY_PATH"] = old_key_path

