import unittest


class TestStudyMaterialsResumeState(unittest.TestCase):
    def test_infer_stage_from_tool(self) -> None:
        from backend.generation.study_materials import orchestrator as tm

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
        from backend.generation.study_materials import orchestrator as tm

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
        from backend.generation.study_materials import orchestrator as tm

        wm = {
            "split_knowledge_points": {"knowledge_points": ["A"]},
            "web_search_knowledge": {"items": [{"knowledge_point": "A", "results": [{"url": "u"}]}]},
            "aggregate_knowledge": {"items": [{"knowledge_point": "A"}]},
            "source_briefs": {"A": {"definition": ["x"]}},
            "outlines": {"A": {"sections": [{"title": "t"}]}},
            "generate_study_material": {"sections": [{"knowledge_point": "A", "explanation_markdown": "md"}]},
            "markdown": "# doc",
        }

        # 失败在检索链路：回到 search，丢弃检索及全部下游产物。
        pruned = tm._prune_resume_working_memory(wm, mode="retry_search", last_failed_stage="read")
        self.assertIn("split_knowledge_points", pruned)
        self.assertNotIn("web_search_knowledge", pruned)
        self.assertNotIn("aggregate_knowledge", pruned)
        self.assertNotIn("generate_study_material", pruned)
        # 丢弃前的成品封存到 previous_attempt，仍可回看上一版。
        self.assertEqual(pruned["previous_attempt"]["dropped_at_stage"], "search")
        self.assertEqual(pruned["previous_attempt"]["keys"]["markdown"], "# doc")

        # 失败在 write：B9 之后不再误毁检索产物，只丢 write 下游键。
        pruned_write = tm._prune_resume_working_memory(wm, mode="retry_search", last_failed_stage="write")
        self.assertIn("web_search_knowledge", pruned_write)
        self.assertIn("aggregate_knowledge", pruned_write)
        self.assertIn("outlines", pruned_write)
        self.assertNotIn("generate_study_material", pruned_write)
        self.assertNotIn("markdown", pruned_write)
        self.assertEqual(pruned_write["previous_attempt"]["dropped_at_stage"], "write")

    def test_resume_failed_stage_prefers_nested_workflow_stage(self) -> None:
        from backend.generation.study_materials.resume import _set_workflow_resume_stage

        resumed = _set_workflow_resume_stage(
            {
                "study_materials_workflow": {
                    "version": 1,
                    "stage": "draft",
                    "last_failure": {},
                    "markdown": "",
                }
            },
            mode="resume_failed_stage",
            last_failed_stage="",
        )

        self.assertEqual(resumed["study_materials_workflow"]["stage"], "draft")

    def test_deepen_research_resets_revision_attempts_for_new_cycle(self) -> None:
        from backend.generation.study_materials.resume import _set_workflow_resume_stage

        resumed = _set_workflow_resume_stage(
            {
                "study_materials_workflow": {
                    "version": 1,
                    "stage": "completed",
                    "last_failure": {},
                    "markdown": "# 成稿",
                    "revision_attempts": 2,
                }
            },
            mode="deepen_research",
            last_failed_stage="",
        )

        workflow = resumed["study_materials_workflow"]
        self.assertEqual(workflow["stage"], "research")
        self.assertEqual(workflow["revision_attempts"], 0)
        self.assertEqual(workflow["resume_after_research"], "review")
