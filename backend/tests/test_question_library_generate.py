import unittest
from unittest.mock import AsyncMock, patch


class TestQuestionLibraryGenerate(unittest.TestCase):
    def test_build_ai_question_id(self) -> None:
        from backend.question_library.generation import build_ai_question_id

        qid = build_ai_question_id(now_ts=0, suffix="a1b2c3d4")
        self.assertTrue(qid.startswith("ai_"))
        self.assertLessEqual(len(qid), 50)

    def test_build_generation_messages_require_latex_math(self) -> None:
        from backend.question_library.generation import build_generation_messages
        from backend.generation.agentic.prompts import create_default_prompt_registry

        messages = build_generation_messages(
            subject="高中数学",
            topic="函数单调性",
            difficulty="中等",
            question_type="解答题",
            study_markdown="复习导数与单调性",
            count=1,
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(create_default_prompt_registry().render("question.draft.realize.v1").content, messages[0]["content"])
        self.assertIn("LaTeX", messages[0]["content"])
        self.assertIn("\\(", messages[0]["content"])
        self.assertIn("\\[", messages[0]["content"])
        self.assertIn("表格", messages[0]["content"])
        self.assertTrue("\\begin{array}" in messages[0]["content"] or "array/matrix/cases" in messages[0]["content"])

    def test_build_regenerate_section_messages_require_latex_math(self) -> None:
        from backend.question_library.generation import build_regenerate_section_messages
        from backend.generation.agentic.prompts import create_default_prompt_registry

        messages = build_regenerate_section_messages(
            subject="高中数学",
            topic="函数单调性",
            difficulty="中等",
            question_type="解答题",
            study_markdown="复习导数与单调性",
            section_key="analysis",
            stem="已知函数 \\(f(x)=x^2+1\\)，判断其单调区间。",
            answer="在区间 \\((0,+\\infty)\\) 单调递增。",
            analysis="旧解析",
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(
            create_default_prompt_registry().render("question.section.regenerate.v1").content,
            messages[0]["content"],
        )
        self.assertIn("LaTeX", messages[0]["content"])
        self.assertIn("\\(", messages[0]["content"])
        self.assertIn("\\[", messages[0]["content"])
        self.assertIn("表格", messages[0]["content"])
        self.assertIn('"section_key": "analysis"', messages[1]["content"])


class TestQuestionLibraryGenerateErrors(unittest.IsolatedAsyncioTestCase):
    def assertQuestionCore(
        self,
        question: dict,
        *,
        stem: str,
        answer: str,
        analysis: str,
        spec_id: str = "",
        skill: str = "",
        reasoning: str = "",
        trap: str = "",
        surface: str = "",
        seed_tag: str = "",
    ) -> None:
        self.assertEqual(question.get("stem"), stem)
        self.assertEqual(question.get("answer"), answer)
        self.assertEqual(question.get("analysis"), analysis)
        self.assertEqual(question.get("spec_id"), spec_id)
        self.assertEqual(question.get("skill"), skill)
        self.assertEqual(question.get("reasoning"), reasoning)
        self.assertEqual(question.get("trap"), trap)
        self.assertEqual(question.get("surface"), surface)
        self.assertEqual(question.get("seed_tag"), seed_tag)

    async def test_realize_drafts_raises_real_llm_error(self) -> None:
        from backend.question_library import generation

        async def _fake_chat_completion_text(**kwargs):
            if not bool(kwargs.get("raise_on_fail")):
                return ""
            raise RuntimeError("llm_request_failed status=404 model=bad provider=fireworks msg=Model not found")

        spec = {"subject": "高中数学", "topic": "导数", "difficulty": "困难", "question_type": "解答题"}
        source_pack = {"subject": "高中数学", "topic": "导数", "study_markdown": ""}

        with patch("backend.question_library.draft_realization.is_llm_configured", return_value=True):
            with patch(
                "backend.question_library.gen_llm.chat_completion",
                new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
            ), patch("backend.question_library.gen_llm.chat_completion_text", new=_fake_chat_completion_text):
                with self.assertRaisesRegex(RuntimeError, "llm_request_failed"):
                    await generation.realize_drafts(spec, source_pack=source_pack, n=1)

    async def test_realize_drafts_parses_json_code_fence(self) -> None:
        from backend.question_library import generation

        async def _fake_chat_completion_text(**_kwargs):
            return (
                "```json\n"
                '{"questions":[{"stem":"题干A","answer":"答案A","analysis":"解析A"}]}\n'
                "```"
            )

        spec = {"subject": "高中数学", "topic": "导数"}
        source_pack = {"subject": "高中数学", "topic": "导数", "study_markdown": ""}

        with patch("backend.question_library.draft_realization.is_llm_configured", return_value=True):
            with patch(
                "backend.question_library.gen_llm.chat_completion",
                new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
            ), patch("backend.question_library.gen_llm.chat_completion_text", new=_fake_chat_completion_text):
                out = await generation.realize_drafts(spec, source_pack=source_pack, n=1)
        self.assertEqual(len(out), 1)
        self.assertQuestionCore(out[0], stem="题干A", answer="答案A", analysis="解析A")

    async def test_realize_drafts_parses_list_root(self) -> None:
        from backend.question_library import generation

        async def _fake_chat_completion_text(**_kwargs):
            return '[{"stem":"题干B","answer":"答案B","analysis":"解析B"}]'

        spec = {"subject": "高中数学", "topic": "导数"}
        source_pack = {"subject": "高中数学", "topic": "导数", "study_markdown": ""}

        with patch("backend.question_library.draft_realization.is_llm_configured", return_value=True):
            with patch(
                "backend.question_library.gen_llm.chat_completion",
                new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
            ), patch("backend.question_library.gen_llm.chat_completion_text", new=_fake_chat_completion_text):
                out = await generation.realize_drafts(spec, source_pack=source_pack, n=1)
        self.assertEqual(len(out), 1)
        self.assertQuestionCore(out[0], stem="题干B", answer="答案B", analysis="解析B")

    async def test_realize_drafts_supports_chinese_keys(self) -> None:
        from backend.question_library import generation

        async def _fake_chat_completion_text(**_kwargs):
            return '{"questions":[{"题干":"题干C","答案":"答案C","解析":["步骤1","步骤2"]}]}'

        spec = {"subject": "高中数学", "topic": "导数"}
        source_pack = {"subject": "高中数学", "topic": "导数", "study_markdown": ""}

        with patch("backend.question_library.draft_realization.is_llm_configured", return_value=True):
            with patch(
                "backend.question_library.gen_llm.chat_completion",
                new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
            ), patch("backend.question_library.gen_llm.chat_completion_text", new=_fake_chat_completion_text):
                out = await generation.realize_drafts(spec, source_pack=source_pack, n=1)
        self.assertEqual(len(out), 1)
        self.assertQuestionCore(out[0], stem="题干C", answer="答案C", analysis="步骤1\n步骤2")

    async def test_realize_drafts_uses_dedicated_higher_max_tokens_budget(self) -> None:
        from backend.question_library import generation

        seen_max_tokens: list[int] = []

        async def _fake_chat_completion_text(**kwargs):
            seen_max_tokens.append(int(kwargs.get("max_tokens") or 0))
            return '{"questions":[{"stem":"题干D","answer":"答案D","analysis":"解析D"}]}'

        spec = {"subject": "高中数学", "topic": "导数"}
        source_pack = {"subject": "高中数学", "topic": "导数", "study_markdown": ""}

        with patch("backend.question_library.draft_realization.is_llm_configured", return_value=True), patch(
            "backend.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
        ), patch(
            "backend.question_library.draft_realization.LESSON_PLAN_MAX_TOKENS", 2000
        ), patch("backend.question_library.gen_llm.chat_completion_text", new=_fake_chat_completion_text):
            out = await generation.realize_drafts(spec, source_pack=source_pack, n=1)

        self.assertEqual(len(out), 1)
        self.assertTrue(seen_max_tokens)
        self.assertGreaterEqual(seen_max_tokens[0], 5000)
