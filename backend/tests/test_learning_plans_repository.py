import asyncio
import unittest
from datetime import datetime

from backend.database.repositories.system.learning_plans import create_learning_plan
from backend.database.schema import LearningPlan, LearningPlanItem


class CountingSession:
    def __init__(self):
        self.added = []
        self.refresh_calls = []
        self.flush_count = 0
        self._next_plan_id = 1
        self._next_item_id = 100
        self._now = datetime(2026, 1, 1, 0, 0, 0)

    def add(self, obj):
        self.added.append(obj)
        self._assign_defaults(obj)

    def add_all(self, objects):
        for obj in objects:
            self.add(obj)

    async def flush(self):
        self.flush_count += 1

    async def refresh(self, obj):
        self.refresh_calls.append(obj)

    def _assign_defaults(self, obj):
        if isinstance(obj, LearningPlan):
            if obj.id is None:
                obj.id = self._next_plan_id
                self._next_plan_id += 1
            obj.created_at = obj.created_at or self._now
            obj.updated_at = obj.updated_at or self._now
        elif isinstance(obj, LearningPlanItem):
            if obj.id is None:
                obj.id = self._next_item_id
                self._next_item_id += 1
            obj.created_at = obj.created_at or self._now
            obj.updated_at = obj.updated_at or self._now


class LearningPlansRepositoryTest(unittest.TestCase):
    def test_create_learning_plan_does_not_refresh_each_created_item(self):
        async def run():
            session = CountingSession()
            result = await create_learning_plan(
                user_id="teacher-1",
                title="期中复习",
                items=[
                    {"title": "函数"},
                    {"title": "导数"},
                    {"title": "数列"},
                ],
                session=session,
            )
            return session, result

        session, result = asyncio.run(run())

        self.assertEqual([item["title"] for item in result["items"]], ["函数", "导数", "数列"])
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(len([obj for obj in session.added if isinstance(obj, LearningPlanItem)]), 3)
        self.assertLessEqual(
            len(session.refresh_calls),
            1,
            "bulk item creation should not issue one refresh query per item",
        )


if __name__ == "__main__":
    unittest.main()
