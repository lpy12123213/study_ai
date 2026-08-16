import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core.settings import Settings


class ModelJsonConfigTests(unittest.TestCase):
    def test_production_code_does_not_read_legacy_model_environment_variables(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]
        allowed = {"MODEL_CONFIG_PATH", "STUDY_MATERIALS_MODEL_SELF_CHECK"}
        provider_keys = {
            "CHAT_PROVIDER",
            "LESSON_PLAN_PROVIDER",
            "REVIEW_PROVIDER",
            "LLM_PROVIDER_PINNED",
            "OPENROUTER_API_KEY",
            "OPENROUTER_BASE_URL",
            "MOONSHOT_API_KEY",
            "MOONSHOT_BASE_URL",
            "FIREWORKS_API_KEY",
            "FIREWORKS_BASE_URL",
            "ZHIPU_API_KEY",
            "ZHIPU_BASE_URL",
            "ARK_API",
            "ARK_API_KEY",
            "ARK_BASE_URL",
        }
        violations: list[str] = []
        for path in backend_root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                first = node.args[0]
                if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue
                name = first.value
                if name in allowed:
                    continue
                is_env_loader = (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                    and node.func.attr == "getenv"
                ) or (isinstance(node.func, ast.Name) and node.func.id in {"_get_str", "_get_float", "env_int", "env_bool"})
                if not is_env_loader:
                    continue
                is_model_value = (
                    name.endswith("_MODEL")
                    or "_TEMPERATURE" in name
                    or name.endswith("_MAX_TOKENS")
                    or name.endswith("_THINKING_EFFORT")
                    or name.endswith("_REASONING_EFFORT")
                    or name in provider_keys
                )
                if is_model_value:
                    violations.append(f"{path.relative_to(backend_root)}:{node.lineno}:{name}")

        self.assertEqual(violations, [])

    def test_legacy_model_environment_variables_are_ignored(self) -> None:
        payload = {
            "active_provider": "json-provider",
            "pinned": False,
            "providers": {
                "json-provider": {"base_url": "https://json.example/v1", "api_key": "json-key"}
            },
            "routes": {"chat": "json-provider", "lesson_plan": "json-provider"},
            "models": {"main": "json-main", "sub": "json-sub", "lesson_plan": "json-lesson"},
            "params": {"main_temperature": 0.25, "main_max_tokens": 4321},
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "MODEL_CONFIG_PATH": str(path),
                    "CHAT_PROVIDER": "legacy-provider",
                    "OPENROUTER_API_KEY": "legacy-key",
                    "MAIN_MODEL": "legacy-main",
                    "SUB_MODEL": "legacy-sub",
                    "MAIN_MODEL_TEMPERATURE": "1.5",
                    "MAIN_MODEL_MAX_TOKENS": "99",
                },
                clear=False,
            ):
                settings = Settings.from_env()

        self.assertEqual(settings.chat_provider, "json-provider")
        self.assertEqual(settings.chat_api_key, "json-key")
        self.assertEqual(settings.main_model, "json-main")
        self.assertEqual(settings.sub_model, "json-sub")
        self.assertEqual(settings.lesson_plan_model, "json-lesson")
        self.assertAlmostEqual(settings.main_model_temperature, 0.25)
        self.assertEqual(settings.main_model_max_tokens, 4321)

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
                "thinking_effort": "low",
            },
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            old = os.environ.get("MODEL_CONFIG_PATH")
            old_effort = os.environ.get("STUDY_MATERIALS_THINKING_EFFORT")
            old_effort_alt = os.environ.get("STUDY_MATERIALS_REASONING_EFFORT")
            old_thinking_model = os.environ.get("STUDY_MATERIALS_THINKING_MODEL")
            old_writer_model = os.environ.get("STUDY_MATERIALS_WRITER_MODEL")
            os.environ["MODEL_CONFIG_PATH"] = str(path)
            # Avoid `.env` bleeding into this test (Settings loads dotenv).
            os.environ["STUDY_MATERIALS_THINKING_EFFORT"] = ""
            os.environ["STUDY_MATERIALS_REASONING_EFFORT"] = ""
            os.environ["STUDY_MATERIALS_THINKING_MODEL"] = "legacy-thinking-model"
            os.environ["STUDY_MATERIALS_WRITER_MODEL"] = "legacy-writer-model"
            try:
                settings = Settings.from_env()
            finally:
                if old is None:
                    os.environ.pop("MODEL_CONFIG_PATH", None)
                else:
                    os.environ["MODEL_CONFIG_PATH"] = old
                if old_effort is None:
                    os.environ.pop("STUDY_MATERIALS_THINKING_EFFORT", None)
                else:
                    os.environ["STUDY_MATERIALS_THINKING_EFFORT"] = old_effort
                if old_effort_alt is None:
                    os.environ.pop("STUDY_MATERIALS_REASONING_EFFORT", None)
                else:
                    os.environ["STUDY_MATERIALS_REASONING_EFFORT"] = old_effort_alt
                if old_thinking_model is None:
                    os.environ.pop("STUDY_MATERIALS_THINKING_MODEL", None)
                else:
                    os.environ["STUDY_MATERIALS_THINKING_MODEL"] = old_thinking_model
                if old_writer_model is None:
                    os.environ.pop("STUDY_MATERIALS_WRITER_MODEL", None)
                else:
                    os.environ["STUDY_MATERIALS_WRITER_MODEL"] = old_writer_model

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
        self.assertEqual(settings.study_materials_thinking_effort, "low")
        self.assertEqual(settings.study_materials_thinking_model, "deepseek-chat")
        self.assertEqual(settings.study_materials_writer_model, "deepseek-chat")
