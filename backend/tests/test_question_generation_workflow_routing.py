from __future__ import annotations

import unittest


class QuestionGenerationWorkflowRoutingTests(unittest.TestCase):
    def test_simple_prompt_routes_to_lightweight_workflow(self) -> None:
        from backend.question_library.workflow_routing import route_question_generation_workflow

        route = route_question_generation_workflow(
            {
                "subject": "高中数学",
                "topic": "出1道函数单调性的基础选择题，用于随堂练习",
                "difficulty": "简单",
                "question_type": "选择题",
                "count": 1,
            }
        )

        self.assertEqual(route.workflow_mode, "lightweight")
        self.assertEqual(route.config["workflow_mode"], "lightweight")
        self.assertFalse(route.config["enable_brainstorm"])
        self.assertFalse(route.config["enable_diagrams"])
        self.assertEqual(route.config["drafts_per_spec"], 1)
        self.assertEqual(route.config["solver_consensus_n"], 1)

    def test_complex_prompt_routes_to_heavyweight_workflow(self) -> None:
        from backend.question_library.workflow_routing import route_question_generation_workflow

        route = route_question_generation_workflow(
            {
                "subject": "高中数学",
                "topic": "围绕导数与参数分类讨论生成高区分度压轴题，参考近五年高考真题风格",
                "difficulty": "困难",
                "question_type": "解答题",
                "count": 3,
                "use_reference_questions": True,
                "reference_source": "gaokao",
                "stream_reasoning": True,
            }
        )

        self.assertEqual(route.workflow_mode, "heavyweight")
        self.assertEqual(route.config["workflow_mode"], "heavyweight")
        self.assertTrue(route.config["enable_brainstorm"])
        self.assertTrue(route.config["enable_diagrams"])
        self.assertGreater(route.config["beam_width"], route.config["drafts_per_spec"])
        self.assertIn("压轴", " ".join(route.reasons))

    def test_explicit_workflow_mode_overrides_prompt_heuristics(self) -> None:
        from backend.question_library.workflow_routing import route_question_generation_workflow

        route = route_question_generation_workflow(
            {
                "subject": "高中数学",
                "topic": "简单基础练习",
                "difficulty": "简单",
                "question_type": "选择题",
                "count": 1,
                "workflow_mode": "heavyweight",
            }
        )

        self.assertEqual(route.workflow_mode, "heavyweight")
        self.assertIn("explicit", route.reason)


if __name__ == "__main__":
    unittest.main()
