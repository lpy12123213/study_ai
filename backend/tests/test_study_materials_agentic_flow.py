from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.generation.agentic.study_materials import build_study_materials_agent_spec
from backend.study_materials.orchestrator import StudyMaterialsTaskManager


class StudyMaterialsAgenticFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_study_materials_agent_spec_defaults_to_tavily_search_policy(self) -> None:
        spec = build_study_materials_agent_spec(
            query="函数单调性",
            subject="高中数学",
            options={"preset": "deep", "requirements": "偏直观"},
        )

        self.assertEqual(spec.domain, "study_materials")
        self.assertIn("函数单调性", spec.goal)
        self.assertEqual(spec.subject, "高中数学")
        self.assertEqual(spec.user_requirements, "偏直观")
        self.assertEqual(spec.search_policy.providers[0], "tavily")
        self.assertIn("web_search_knowledge", spec.tool_policy.allowed_tools)
        self.assertTrue(any(role.name == "planner" for role in spec.roles))
        self.assertTrue(any(role.name == "writer" for role in spec.roles))

    async def test_create_task_persists_agent_run_spec_in_meta(self) -> None:
        manager = StudyMaterialsTaskManager()

        async def fake_create_task(**kwargs):
            return SimpleNamespace(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                request=kwargs["request"],
                meta=kwargs["meta"],
                parent_task_id=kwargs.get("parent_task_id"),
                status="running",
                created_at_s=1.0,
                updated_at_s=1.0,
            )

        with patch("backend.study_materials.orchestrator.task_runtime.create_task", new=AsyncMock(side_effect=fake_create_task)):
            with patch.object(manager, "_persist_snapshot"):
                task = await manager.create_task(
                    query="函数单调性",
                    user_id="u-1",
                    subject="高中数学",
                    options={"preset": "standard"},
                )

        spec = task.meta.get("agent_run_spec")
        self.assertIsInstance(spec, dict)
        self.assertEqual(spec["domain"], "study_materials")
        self.assertEqual(spec["input_payload"]["topic"], "函数单调性")
        self.assertEqual(spec["search_policy"]["providers"][0], "tavily")


if __name__ == "__main__":
    unittest.main()
