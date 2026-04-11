import unittest


class TestStudyMaterialsResumeState(unittest.TestCase):
    def test_infer_stage_from_tool(self) -> None:
        from backend.study_materials import orchestrator as tm

        self.assertEqual(tm._infer_stage_from_tool("web_search_knowledge"), "search")
        self.assertEqual(tm._infer_stage_from_tool("browse_web_pages"), "search")
        self.assertEqual(tm._infer_stage_from_tool("aggregate_knowledge"), "aggregate")
        self.assertEqual(tm._infer_stage_from_tool("synthesize_sources"), "aggregate")
        self.assertEqual(tm._infer_stage_from_tool("generate_outline"), "write")
        self.assertEqual(tm._infer_stage_from_tool("generate_study_material"), "write")
        self.assertEqual(tm._infer_stage_from_tool("assemble_study_archive"), "write")
        self.assertEqual(tm._infer_stage_from_tool("convert_markdown_to_latex"), "export")
        self.assertEqual(tm._infer_stage_from_tool("compile_latex_to_pdf"), "export")
        self.assertEqual(tm._infer_stage_from_tool("unknown_tool"), "")

    def test_derive_resume_state_from_step_results(self) -> None:
        from backend.study_materials import orchestrator as tm

        wm = {
            "step_results": [
                {"step_id": "s1", "tool": "web_search_knowledge", "success": True, "error": None},
                {"step_id": "s2", "tool": "aggregate_knowledge", "success": False, "error": "boom"},
            ]
        }

        state = tm._derive_resume_state(wm)
        self.assertEqual(state.get("last_success_step", {}).get("tool"), "web_search_knowledge")
        self.assertEqual(state.get("last_failed_step", {}).get("tool"), "aggregate_knowledge")
        self.assertEqual(state.get("last_success_stage"), "search")
        self.assertEqual(state.get("last_failed_stage"), "aggregate")

    def test_prune_working_memory_for_continue(self) -> None:
        from backend.study_materials import orchestrator as tm

        wm = {
            "split_knowledge_points": {"knowledge_points": ["A"]},
            "web_search_knowledge": {"items": [{"knowledge_point": "A", "results": [{"url": "u"}]}]},
            "aggregate_knowledge": {"items": [{"knowledge_point": "A"}]},
            "source_briefs": {"A": {"definition": ["x"]}},
            "outlines": {"A": {"sections": [{"title": "t"}]}},
            "generate_study_material": {"sections": [{"knowledge_point": "A", "explanation_markdown": "md"}]},
            "markdown": "# doc",
        }

        pruned = tm._prune_resume_working_memory(wm, mode="retry_search", last_failed_stage="write")
        self.assertIn("split_knowledge_points", pruned)
        self.assertNotIn("web_search_knowledge", pruned)
        self.assertNotIn("aggregate_knowledge", pruned)
        self.assertNotIn("generate_study_material", pruned)
