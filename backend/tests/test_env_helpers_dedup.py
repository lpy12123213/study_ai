"""Regression tests for env helper deduplication (P0 of duplicate-function report).

Codifies the three severe duplications identified in the duplicate-function audit:

1.1 - `configure_logging` must have a single implementation (core.logging_utils).
       core.helpers must not re-implement it.
1.2 - `_env_int` / `_get_int` / `_int_env` / `_get_int_env` / `_getenv_int`
      must not be duplicated
       across modules; a public `env_int` must live in core.settings.
1.3 - `_env_truthy` / `_get_bool` must not be duplicated; a public `env_bool`
       must live in core.settings.
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def _module_functions(mod_path: str) -> set[str]:
    """Return the set of top-level function names defined in a module file."""
    py = REPO_ROOT / (mod_path.replace(".", "/") + ".py")
    if not py.exists():
        return set()
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return set()
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _find_function_definitions(pattern_names: set[str]) -> dict[str, list[str]]:
    """Find backend modules defining any named helper, including nested scopes."""
    found: dict[str, list[str]] = {name: [] for name in pattern_names}
    for py in BACKEND.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in pattern_names:
                rel = py.relative_to(REPO_ROOT).as_posix()
                found[node.name].append(rel)
    return found


class TestConfigureLoggingSingleImplementation(unittest.TestCase):
    """1.1 - configure_logging must have only one implementation."""

    def test_core_helpers_does_not_define_configure_logging(self):
        """core.helpers must not re-implement configure_logging (use core.logging_utils)."""
        funcs = _module_functions("backend.core.helpers")
        self.assertNotIn(
            "configure_logging",
            funcs,
            "core.helpers.configure_logging is a duplicate of core.logging_utils.configure_logging — remove it.",
        )

    def test_core_logging_utils_defines_configure_logging(self):
        """core.logging_utils must be the single source of configure_logging and get_logger."""
        found = _find_function_definitions({"configure_logging", "get_logger"})
        expected = ["backend/core/logging_utils.py"]
        self.assertEqual(found["configure_logging"], expected)
        self.assertEqual(found["get_logger"], expected)

    def test_production_modules_use_canonical_get_logger(self):
        """Production modules must not bypass core.logging_utils.get_logger."""
        offenders: list[str] = []
        canonical = BACKEND / "core" / "logging_utils.py"
        for py in BACKEND.rglob("*.py"):
            if "__pycache__" in py.parts or py.name.startswith("test_") or py == canonical:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            logging_module_aliases = {"logging"}
            get_logger_aliases: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    logging_module_aliases.update(
                        alias.asname or alias.name for alias in node.names if alias.name == "logging"
                    )
                elif isinstance(node, ast.ImportFrom) and node.module == "logging":
                    get_logger_aliases.update(
                        alias.asname or alias.name for alias in node.names if alias.name == "getLogger"
                    )
            directly_gets_logger = any(
                isinstance(node, ast.Call)
                and (
                    (
                        isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in logging_module_aliases
                        and node.func.attr == "getLogger"
                    )
                    or (isinstance(node.func, ast.Name) and node.func.id in get_logger_aliases)
                )
                for node in ast.walk(tree)
            )
            if directly_gets_logger:
                offenders.append(py.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(
            offenders,
            [],
            f"Modules bypassing backend.core.logging_utils.get_logger: {offenders}",
        )


class TestEnvIntDeduplication(unittest.TestCase):
    """1.2 - private env-int helper variants must not be duplicated."""

    def test_no_duplicate_env_int_private_helpers(self):
        """At most one backend module may define a private env-int helper; the rest must use core.settings.env_int."""
        names = {"_env_int", "_get_int", "_int_env", "_get_int_env", "_getenv_int"}
        found = _find_function_definitions(names)
        offenders = {name: mods for name, mods in found.items() if mods}
        self.assertEqual(
            offenders,
            {},
            f"Private env-int helpers still defined (use core.settings.env_int instead): {offenders}",
        )

    def test_core_settings_exports_public_env_int(self):
        """core.settings must export a public `env_int` function."""
        from backend.core import settings as settings_mod

        self.assertTrue(hasattr(settings_mod, "env_int"), "core.settings must export `env_int` as a public helper")
        self.assertTrue(callable(getattr(settings_mod, "env_int")))

    def test_env_int_preserves_default_fallback_behavior(self):
        """Unset, blank, and invalid values must retain the old private-helper fallback behavior."""
        from backend.core import settings as settings_mod

        name = "TEST_ENV_HELPERS_DEDUP_INT"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(name, None)
            self.assertEqual(settings_mod.env_int(name, 7), 7)
            os.environ[name] = "  "
            self.assertEqual(settings_mod.env_int(name, 7), 7)
            os.environ[name] = "invalid"
            self.assertEqual(settings_mod.env_int(name, 7), 7)
            os.environ[name] = " 42 "
            self.assertEqual(settings_mod.env_int(name, 7), 42)


class TestEnvBoolDeduplication(unittest.TestCase):
    """1.3 - _env_truthy / _get_bool must not be duplicated."""

    def test_no_duplicate_env_bool_private_helpers(self):
        """At most one backend module may define a private env-bool helper; use core.settings.env_bool."""
        names = {"_env_truthy", "_get_bool"}
        found = _find_function_definitions(names)
        offenders = {name: mods for name, mods in found.items() if mods}
        self.assertEqual(
            offenders,
            {},
            f"Private env-bool helpers still defined (use core.settings.env_bool instead): {offenders}",
        )

    def test_core_settings_exports_public_env_bool(self):
        """core.settings must export a public `env_bool` function."""
        from backend.core import settings as settings_mod

        self.assertTrue(hasattr(settings_mod, "env_bool"), "core.settings must export `env_bool` as a public helper")
        self.assertTrue(callable(getattr(settings_mod, "env_bool")))

    def test_env_bool_preserves_default_fallback_behavior(self):
        """Unset and blank values use the default while explicit values override it."""
        from backend.core import settings as settings_mod

        name = "TEST_ENV_HELPERS_DEDUP_BOOL"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(name, None)
            self.assertTrue(settings_mod.env_bool(name, True))
            os.environ[name] = "  "
            self.assertTrue(settings_mod.env_bool(name, True))
            for value in ("1", "true", "YES", "y", "On"):
                with self.subTest(value=value):
                    os.environ[name] = value
                    self.assertTrue(settings_mod.env_bool(name, False))
            for value in ("0", "false", "no", "off", "invalid"):
                with self.subTest(value=value):
                    os.environ[name] = value
                    self.assertFalse(settings_mod.env_bool(name, True))


class TestCoreHelpersCleanup(unittest.TestCase):
    """core.helpers should not retain dead duplicates; get_logger users point to logging_utils."""

    def test_core_helpers_module_is_removed(self):
        """The duplicate helper module should not survive as a compatibility shell."""
        self.assertFalse((REPO_ROOT / "backend/core/helpers.py").exists())

    def test_core_helpers_is_not_imported(self):
        """Deleted core.helpers must have no live backend importers."""
        offenders: list[str] = []
        for py in BACKEND.rglob("*.py"):
            if "__pycache__" in py.parts or py.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError):
                continue
            imports_deleted_module = any(
                (
                    isinstance(node, ast.ImportFrom)
                    and (
                        node.module == "backend.core.helpers"
                        or (node.module == "backend.core" and any(alias.name == "helpers" for alias in node.names))
                    )
                )
                or (
                    isinstance(node, ast.Import)
                    and any(alias.name == "backend.core.helpers" for alias in node.names)
                )
                for node in ast.walk(tree)
            )
            if imports_deleted_module:
                offenders.append(py.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(offenders, [], f"Modules still importing deleted backend.core.helpers: {offenders}")

    def test_core_helpers_not_imported_for_get_logger(self):
        """No backend module should import get_logger from core.helpers (use core.logging_utils)."""
        offenders: list[str] = []
        for py in BACKEND.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            # Skip test files (this very test references the import string for detection)
            if py.name.startswith("test_"):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "from backend.core.helpers import" in text:
                for line in text.splitlines():
                    if "from backend.core.helpers import" in line and "get_logger" in line:
                        offenders.append(py.relative_to(REPO_ROOT).as_posix())
                        break
        self.assertEqual(
            offenders,
            [],
            f"Modules still importing get_logger from core.helpers (use core.logging_utils): {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
