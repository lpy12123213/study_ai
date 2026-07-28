import unittest


class TestQuestionLibraryGenerationSpecs(unittest.TestCase):
    def test_seed_root_specs_are_diverse(self) -> None:
        from backend.generation.question_library.generation import seed_root_specs

        source_pack = {"subject": "高中数学", "topic": "椭圆", "study_markdown": ""}
        specs = seed_root_specs(source_pack, count=5, difficulty="中等", question_type="解答题")

        self.assertGreaterEqual(len(specs), 4)
        seed_tags = {str(s.get("seed_tag") or "").strip() for s in specs if isinstance(s, dict)}
        seed_tags = {t for t in seed_tags if t}
        self.assertGreaterEqual(len(seed_tags), 3)

    def test_seed_root_specs_preserve_complete_requested_topic_contract(self) -> None:
        from backend.generation.question_library.generation import seed_root_specs

        requested_topic = "等差数列\n" + "先观察结构再验证；" + "迁移必须改变关系或边界。" * 12
        source_pack = {
            "subject": "高中数学",
            "topic": "等差数列",
            "requested_topic": requested_topic,
        }

        specs = seed_root_specs(source_pack, count=1, difficulty="中等", question_type="解答题")

        self.assertTrue(specs)
        self.assertTrue(all(spec["topic"] == requested_topic for spec in specs))

    def test_expand_layers_populate_key_fields(self) -> None:
        from backend.generation.question_library.generation import (
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

    def test_brainstorm_mother_question_demand_reaches_root_spec(self) -> None:
        from backend.generation.question_library.generation import seed_root_specs_from_brainstorm

        specs = seed_root_specs_from_brainstorm(
            {"subject": "高中数学", "topic": "等差数列"},
            [
                {
                    "concept": "部分和对称",
                    "seed_tag": "隐藏对称",
                    "skill_hint": "等差数列性质与前n项和的结构联结",
                    "reasoning_hint": "从相等部分和反推配对不变量，再比较两种表征",
                    "mother_question_demand": "从相等部分和反推隐藏的下标配对关系",
                    "topic_binding": "对称性进入下标配对，不变量进入部分和差的判断",
                }
            ],
            count=1,
            difficulty="中等",
            question_type="解答题",
        )

        self.assertEqual(
            specs[0]["brainstorm_mother_question_demand"],
            "从相等部分和反推隐藏的下标配对关系",
        )
        self.assertIn("不变量", specs[0]["brainstorm_topic_binding"])

        from backend.generation.question_library.generation import expand_reasoning_layer, expand_skill_layer

        skilled = expand_skill_layer(specs, {"skill_branch_factor": 3, "expand_budget": 20})
        self.assertEqual(
            {item["skill"] for item in skilled},
            {"等差数列性质与前n项和的结构联结"},
        )
        reasoned = expand_reasoning_layer(skilled, {"reasoning_branch_factor": 3, "expand_budget": 20})
        self.assertEqual(
            {item["reasoning"] for item in reasoned},
            {"从相等部分和反推配对不变量，再比较两种表征"},
        )

    def test_solution_appreciation_fallback_expansions_stay_on_goal(self) -> None:
        from backend.generation.question_library.generation import (
            expand_reasoning_layer,
            expand_surface_layer,
            expand_trap_layer,
        )

        specs = [
            {
                "spec_id": "s1",
                "subject": "高中数学",
                "topic": "等差数列的对称性与不变量",
                "intuition_practice": {"practice_goal": "solution_appreciation"},
            }
        ]
        config = {"reasoning_branch_factor": 3, "trap_branch_factor": 2, "surface_branch_factor": 2, "expand_budget": 20}

        reasoning = expand_reasoning_layer(specs, config)
        self.assertTrue(reasoning)
        self.assertTrue(all("比较" in item["reasoning"] or "评价" in item["reasoning"] for item in reasoning))
        traps = expand_trap_layer(reasoning[:1], config)
        self.assertTrue(all("解法" in item["trap"] or "练习包" in item["trap"] for item in traps))
        surfaces = expand_surface_layer(traps[:1], config)
        self.assertTrue(all("品鉴" in item["surface"] or "表征" in item["surface"] for item in surfaces))

    def test_score_spec_prefers_deeper_reasoning(self) -> None:
        from backend.generation.question_library.generation import score_spec

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

    def test_score_spec_rewards_hidden_structure_and_penalizes_recipe_execution(self) -> None:
        from backend.generation.question_library.generation import score_spec

        source_pack = {"subject": "高中数学", "topic": "等差数列", "study_markdown": ""}
        cfg = {
            "intuition_alignment_weight": 0.5,
            "template_penalty": 0.3,
            "score_jitter": 0,
        }
        base = {
            "subject": "高中数学",
            "topic": "等差数列",
            "difficulty": "中等",
            "question_type": "解答题",
            "skill": "性质判定",
            "trap": "把表面计算当作结构理解",
        }
        routine = score_spec(
            {
                **base,
                "spec_id": "routine",
                "reasoning": "直接代入前 n 项和公式",
                "surface": "题面要求分别使用公式法并按步骤计算",
                "intuition_atom": {
                    "concept": "等差数列求和",
                    "internal_model": "把已知量代入公式",
                    "mental_action": "套公式",
                    "decisive_cue": "使用前 n 项和公式",
                    "expected_first_feel": "结果可以直接计算",
                    "common_false_intuition": "算错数字",
                    "formal_anchor": "重新代入检查",
                    "transfer_mutation": "只换数字后再次计算",
                },
            },
            source_pack,
            cfg,
        )
        structural = score_spec(
            {
                **base,
                "spec_id": "structural",
                "reasoning": "从相等的部分和反推隐藏对称关系，再用最短配对验证",
                "surface": "不明示方法的关系发现题",
                "intuition_atom": {
                    "concept": "等差数列部分和的镜像关系",
                    "internal_model": "把部分和看成关于下标变化的离散图像，并寻找对称轴",
                    "mental_action": "从局部零和反推全局对称，再换成图像表征",
                    "decisive_cue": "相等部分和之间的新增项之和为零",
                    "expected_first_feel": "最大部分和应落在两个对称下标的中点附近",
                    "common_false_intuition": "必须先求首项和公差才能判断最大项",
                    "formal_anchor": "用下标和相同的等差数列项配对验证",
                    "transfer_mutation": "把部分和等式改为带边界约束的不等关系，并改用图像表征",
                    "boundary_flip": "改变公差符号时单峰方向翻转",
                },
            },
            source_pack,
            cfg,
        )

        self.assertGreater(float(structural["structural_depth_score"]), float(routine["structural_depth_score"]))
        self.assertGreater(float(structural["intuition_alignment"]), float(routine["intuition_alignment"]))
        self.assertGreater(float(structural["score"]), float(routine["score"]))
        self.assertGreater(float(routine["template_similarity"]), float(structural["template_similarity"]))

    def test_score_spec_penalizes_formula_scaffolded_mother_question(self) -> None:
        from backend.generation.question_library.generation import score_spec

        source_pack = {"subject": "高中数学", "topic": "等差数列", "study_markdown": ""}
        cfg = {"template_penalty": 0.35, "score_jitter": 0}
        base = {
            "subject": "高中数学",
            "topic": "等差数列",
            "difficulty": "中等",
            "question_type": "解答题",
            "reasoning": "寻找不变量与对称性",
            "surface": "关系发现题",
        }

        scaffold = score_spec(
            {
                **base,
                "spec_id": "scaffold",
                "brainstorm_mother_question_demand": "先求通项，再求前n项和并求最值",
            },
            source_pack,
            cfg,
        )
        insight = score_spec(
            {
                **base,
                "spec_id": "insight",
                "brainstorm_mother_question_demand": "从两个部分和相等推断隐藏配对关系，并用边界变化判断极值位置",
            },
            source_pack,
            cfg,
        )

        self.assertGreater(float(scaffold["template_similarity"]), float(insight["template_similarity"]))
        self.assertGreater(float(insight["score"]), float(scaffold["score"]))

    def test_score_spec_requires_requested_symmetry_and_invariant_clauses(self) -> None:
        from backend.generation.question_library.generation import score_spec

        full_topic = (
            "等差数列的对称性、不变量与前n项和："
            "迁移题须改变关系、约束、边界或表示，不得只换数字"
        )
        source_pack = {"subject": "高中数学", "topic": full_topic}
        cfg = {"template_penalty": 0.3, "score_jitter": 0}
        base = {
            "subject": "高中数学",
            "topic": full_topic,
            "difficulty": "中等",
            "question_type": "解答题",
            # Expanded reasoning labels alone must not satisfy the topic: they can
            # be attached mechanically after a routine brainstorm seed.
            "reasoning": "寻找不变量与对称性并比较解法",
            "surface": "解答题",
        }
        bolted_on = score_spec(
            {
                **base,
                "spec_id": "bolted-on",
                "brainstorm_mother_question_demand": "给定通项 a_n=35-4n，求S_n最大值并比较两种方法",
                "brainstorm_topic_binding": "前n项和用于求最大值",
            },
            source_pack,
            cfg,
        )
        bound = score_spec(
            {
                **base,
                "spec_id": "bound",
                "brainstorm_mother_question_demand": "从相等部分和发现镜像配对，并提炼配对和保持不变的结构",
                "brainstorm_topic_binding": "对称性由镜像下标配对体现；不变量是配对项之和；前n项和提供观察证据",
            },
            source_pack,
            cfg,
        )

        self.assertEqual(bolted_on["topic_binding_score"], 0.0)
        self.assertCountEqual(bolted_on["missing_topic_focus"], ["symmetry", "invariant"])
        self.assertEqual(bound["topic_binding_score"], 1.0)
        self.assertEqual(bound["missing_topic_focus"], [])
        self.assertGreater(float(bolted_on["template_similarity"]), float(bound["template_similarity"]))
        self.assertGreater(float(bound["score"]), float(bolted_on["score"]))

