import unittest

from backend.generation.question_library.curriculum_context import (
    _build_curriculum_system_prompt,
    curriculum_context_for_prompt,
    enrich_source_pack_with_curriculum,
    get_static_curriculum_baseline,
)
from backend.generation.question_library.curriculum_reference import (
    CURRICULUM_REFERENCE_ARTICLE,
    CURRICULUM_STANDARD,
    get_curriculum_reference_article,
)
from backend.llm.prompts import create_default_prompt_registry


class TestQuestionLibraryCurriculumContext(unittest.TestCase):
    def test_reference_article_is_embedded(self) -> None:
        article = get_curriculum_reference_article()
        self.assertEqual(article, CURRICULUM_REFERENCE_ARTICLE)
        self.assertIn("2017年版2020年修订", article)
        self.assertIn("不存在“2022 版普通高中课程标准”", article)
        self.assertIn("学业质量水平一", article)
        self.assertIn("无价值，不入题", article)
        self.assertIn("选择性必修", article)
        self.assertIn("知识范围", article)
        self.assertIn("前置知识", article)

    def test_curriculum_system_prompt_renders_from_registry(self) -> None:
        registered = create_default_prompt_registry().render(
            "question.curriculum_context.v1",
            curriculum_reference_article=CURRICULUM_REFERENCE_ARTICLE,
        ).content

        self.assertEqual(_build_curriculum_system_prompt(), registered)
        self.assertIn(CURRICULUM_REFERENCE_ARTICLE, registered)
        self.assertIn("2017年版2020年修订", registered)

    def test_curriculum_standard_name(self) -> None:
        self.assertIn("2017年版2020年修订", CURRICULUM_STANDARD)
        self.assertNotIn("2022版普通高中", CURRICULUM_STANDARD)

    def test_static_baseline_for_math(self) -> None:
        baseline = get_static_curriculum_baseline("高中数学")
        self.assertEqual(baseline["curriculum_standard"], CURRICULUM_STANDARD)
        self.assertIn("数学抽象", baseline["core_competencies"])
        self.assertTrue(baseline["question_requirements"])

    def test_enrich_source_pack_merges_knowledge_points_into_prompt(self) -> None:
        source_pack = enrich_source_pack_with_curriculum(
            {"subject": "高中数学", "topic": "导数应用", "knowledge_points": ["单调性", "极值"]},
            {
                "question_requirements": ["考查推理过程"],
                "prerequisites": ["导数定义"],
                "knowledge_scope": {"in_scope": ["导数应用"], "out_of_scope": ["泰勒展开"]},
            },
        )
        prompt_ctx = curriculum_context_for_prompt(source_pack)
        self.assertIn("单调性", prompt_ctx["knowledge_scope"]["in_scope"])
        self.assertIn("导数定义", prompt_ctx["prerequisites"])
        self.assertIn(CURRICULUM_REFERENCE_ARTICLE, prompt_ctx["reference_article"])
