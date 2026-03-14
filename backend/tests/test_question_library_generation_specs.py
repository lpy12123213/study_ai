import unittest


class TestQuestionLibraryGenerationSpecs(unittest.TestCase):
    def test_seed_root_specs_are_diverse(self) -> None:
        from backend.question_library.generation import seed_root_specs

        source_pack = {"subject": "高中数学", "topic": "椭圆", "study_markdown": ""}
        specs = seed_root_specs(source_pack, count=5, difficulty="中等", question_type="解答题")

        self.assertGreaterEqual(len(specs), 4)
        seed_tags = {str(s.get("seed_tag") or "").strip() for s in specs if isinstance(s, dict)}
        seed_tags = {t for t in seed_tags if t}
        self.assertGreaterEqual(len(seed_tags), 3)

    def test_expand_layers_populate_key_fields(self) -> None:
        from backend.question_library.generation import (
            expand_reasoning_layer,
            expand_skill_layer,
            expand_surface_layer,
            expand_trap_layer,
            seed_root_specs,
        )

        source_pack = {"subject": "高中数学", "topic": "导数应用", "study_markdown": ""}
        cfg = {"expand_budget": 80, "skill_branch_factor": 3, "reasoning_branch_factor": 3, "trap_branch_factor": 2, "surface_branch_factor": 2}

        specs = seed_root_specs(source_pack, count=5, difficulty="困难", question_type="解答题")
        specs = expand_skill_layer(specs, cfg)
        self.assertTrue(all(str(s.get("skill") or "").strip() for s in specs))

        specs = expand_reasoning_layer(specs, cfg)
        self.assertTrue(all(str(s.get("reasoning") or "").strip() for s in specs))

        specs = expand_trap_layer(specs, cfg)
        self.assertTrue(all(str(s.get("trap") or "").strip() for s in specs))

        specs = expand_surface_layer(specs, cfg)
        self.assertTrue(all(str(s.get("surface") or "").strip() for s in specs))

    def test_score_spec_prefers_deeper_reasoning(self) -> None:
        from backend.question_library.generation import score_spec

        source_pack = {"subject": "高中数学", "topic": "函数", "study_markdown": ""}
        cfg = {
            "difficulty_match_weight": 0.3,
            "novelty_weight": 0.3,
            "skill_coverage_weight": 0.2,
            "solvability_weight": 0.2,
            "ambiguity_penalty": 0.3,
            "template_penalty": 0.2,
        }

        base = {
            "spec_id": "spec_base",
            "subject": "高中数学",
            "topic": "函数",
            "difficulty": "中等",
            "question_type": "解答题",
            "layer": "surface",
            "skill": "性质判定",
            "trap": "边界点误判",
            "surface": "参数变化探究题",
        }

        shallow = score_spec({**base, "reasoning": "直接求导判断"}, source_pack, cfg)
        deep = score_spec({**base, "reasoning": "参数变化分析 + 分类讨论"}, source_pack, cfg)

        self.assertGreater(float(deep.get("score") or 0.0), float(shallow.get("score") or 0.0))

