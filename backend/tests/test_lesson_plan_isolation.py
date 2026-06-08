"""Owner-isolation tests for the (now DB-backed) lesson plan store.

These tests guard against cross-user reads/writes after the security fix that
moved ``user_id`` from an optional filter to a required argument on every
``store.get/update/delete/export`` call. They run against an isolated SQLite
file per test class so they do not touch the developer's local DB.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

_RELOAD_MODULES = [
    "backend.database.engine",
    "backend.database.paths",
    "backend.database.repositories.generation.lesson_plans",
    "backend.generation.lesson_plan.store",
]


class LessonPlanIsolationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="lesson_plan_iso_")
        cls._db_path = Path(cls._tmpdir.name) / "exam_papers.db"
        os.environ["STUDY_AI_DB_PATH"] = str(cls._db_path)
        cls._mod_snapshot = {name: sys.modules.get(name) for name in _RELOAD_MODULES}
        for name in _RELOAD_MODULES:
            sys.modules.pop(name, None)

        cls._engine_mod = importlib.import_module("backend.database.engine")
        cls._repo_mod = importlib.import_module("backend.database.repositories.generation.lesson_plans")
        cls._store_mod = importlib.import_module("backend.generation.lesson_plan.store")

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            cls._engine_mod.init_db()
        )

    @classmethod
    def tearDownClass(cls) -> None:
        loop = asyncio.get_event_loop_policy().new_event_loop()
        try:
            loop.run_until_complete(cls._engine_mod.engine.dispose())
        except (OSError, RuntimeError):
            pass
        finally:
            loop.close()

        for name in _RELOAD_MODULES:
            sys.modules.pop(name, None)
        for name, mod in cls._mod_snapshot.items():
            if mod is not None:
                sys.modules[name] = mod
        try:
            cls._tmpdir.cleanup()
        except OSError:
            pass
        os.environ.pop("STUDY_AI_DB_PATH", None)

    async def asyncSetUp(self) -> None:
        self.store = self._store_mod
        # Each test gets a fresh owner pair to avoid cross-test contamination.
        suffix = self._testMethodName
        self.alice = f"alice-{suffix}"
        self.bob = f"bob-{suffix}"
        self.alice_plan = await self.store.create_lesson_plan(
            title="Alice plan",
            subject="math",
            topic="t",
            grade="g",
            duration_minutes=45,
            objectives=["o1"],
            user_id=self.alice,
        )

    async def test_get_returns_none_for_other_user(self) -> None:
        self.assertIsNotNone(await self.store.get_lesson_plan(self.alice_plan.id, user_id=self.alice))
        self.assertIsNone(await self.store.get_lesson_plan(self.alice_plan.id, user_id=self.bob))

    async def test_get_rejects_empty_user_id(self) -> None:
        self.assertIsNone(await self.store.get_lesson_plan(self.alice_plan.id, user_id=""))
        self.assertIsNone(await self.store.get_lesson_plan(self.alice_plan.id, user_id=None))  # type: ignore[arg-type]

    async def test_delete_blocked_for_other_user(self) -> None:
        self.assertFalse(await self.store.delete_lesson_plan(self.alice_plan.id, user_id=self.bob))
        # Plan still exists for alice.
        self.assertIsNotNone(await self.store.get_lesson_plan(self.alice_plan.id, user_id=self.alice))

        # Owner can delete.
        self.assertTrue(await self.store.delete_lesson_plan(self.alice_plan.id, user_id=self.alice))
        self.assertIsNone(await self.store.get_lesson_plan(self.alice_plan.id, user_id=self.alice))

    async def test_update_blocked_for_other_user(self) -> None:
        result = await self.store.update_lesson_plan(self.alice_plan.id, user_id=self.bob, title="Hijacked")
        self.assertIsNone(result)
        plan = await self.store.get_lesson_plan(self.alice_plan.id, user_id=self.alice)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.title, "Alice plan")

    async def test_export_blocked_for_other_user(self) -> None:
        self.assertIsNone(await self.store.export_lesson_plan_markdown(self.alice_plan.id, user_id=self.bob))
        md = await self.store.export_lesson_plan_markdown(self.alice_plan.id, user_id=self.alice)
        self.assertIsNotNone(md)
        assert md is not None
        self.assertIn("Alice plan", md)

    async def test_list_filters_by_user(self) -> None:
        await self.store.create_lesson_plan(
            title="Bob plan", subject="math", topic="t", grade="g", duration_minutes=45, user_id=self.bob
        )
        alice_plans = await self.store.list_lesson_plans(user_id=self.alice)
        bob_plans = await self.store.list_lesson_plans(user_id=self.bob)

        alice_titles = {p.title for p in alice_plans if p.user_id == self.alice} if False else {p.title for p in alice_plans}  # noqa: E501
        bob_titles = {p.title for p in bob_plans}

        self.assertIn("Alice plan", alice_titles)
        self.assertNotIn("Bob plan", alice_titles)
        self.assertIn("Bob plan", bob_titles)
        self.assertNotIn("Alice plan", bob_titles)

    async def test_list_rejects_empty_user_id(self) -> None:
        self.assertEqual(await self.store.list_lesson_plans(user_id=""), [])


if __name__ == "__main__":
    unittest.main()
