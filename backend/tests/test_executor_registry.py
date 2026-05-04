import unittest


class TestExecutorRegistry(unittest.TestCase):
    def test_tool_mixins_are_explicit_and_ordered(self):
        from backend.agent.tools.registry import TOOL_MIXINS

        names = [cls.__name__ for cls in TOOL_MIXINS]
        self.assertEqual(names[0], "KnowledgePointsToolsMixin")
        self.assertEqual(names[-1], "PlotToolsMixin")
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("LatexToolsMixin", names)

    def test_tool_registry_contains_common_tools(self):
        from backend.agent.executor import Executor

        ex = Executor()
        handlers = getattr(ex, "_tool_handlers", None)
        self.assertIsInstance(handlers, dict)

        for tool in (
            "split_knowledge_points",
            "web_search_knowledge",
            "aggregate_knowledge",
            "synthesize_sources",
            "generate_outline",
            "generate_study_material",
            "assemble_study_archive",
            "review_content",
            "convert_markdown_to_latex",
            "refine_latex",
            "compile_latex_to_pdf",
        ):
            self.assertIn(tool, handlers)
