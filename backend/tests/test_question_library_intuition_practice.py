from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.api.auth import require_auth
from backend.app import create_app
from backend.database.repositories.question import question_cache as cache_repo
from backend.database.schema import Base
from backend.generation.question_library import preview_store
from backend.generation.question_library.intuition_practice import (
    normalize_intuition_packet,
    normalize_intuition_practice_config,
    validate_intuition_packet_structure,
)


def _atom() -> dict:
    return {
        "concept": "函数单调性的变化模型",
        "internal_model": "把函数图像看成随参数移动的对象",
        "mental_action": "先估计，再换成图像表征",
        "decisive_cue": "导数符号变化而非计算长度",
        "expected_first_feel": "参数增大时转折点向右移动",
        "common_false_intuition": "只看常数项大小猜单调性",
        "formal_anchor": "检查导数零点两侧的符号",
        "transfer_mutation": "把代数式换成图像并反向询问参数范围",
        "boundary_flip": "导数出现重根时结论发生变化",
        "feedback": "先指出判断抓住的变化方向，再校准决定性符号",
    }


def _packet(*, goal: str = "structural_intuition", include_appreciation: bool = False) -> dict:
    stages = [
        {
            "stage": "perception",
            "kind": "prediction",
            "prompt": "不完整计算，先判断图像怎样移动。",
            "expected_answer": "向右移动。",
        },
        {
            "stage": "model_externalization",
            "kind": "representation",
            "prompt": "说明脑中的图像，并用导数符号作最短检验。",
            "expected_answer": "检查导数零点两侧符号。",
        },
        {
            "stage": "transfer",
            "kind": "representation",
            "prompt": "改成图像给定、反求参数后重新判断。",
            "expected_answer": "仍由导数符号变化决定。",
        },
    ]
    if include_appreciation:
        stages.append(
            {
                "stage": "appreciation",
                "kind": "solution_comparison",
                "prompt": "比较图像法与展开计算法，依据统一性和推广性说明哪种更自然。",
                "expected_answer": "图像法更直接揭示结构。",
            }
        )
    return {
        "version": "1.0",
        "practice_goal": goal,
        "atom": _atom(),
        "stages": stages,
        "curriculum_alignment": {"knowledge_points": ["函数单调性"], "scope_note": "课内"},
    }


def _validation(*, passed: bool) -> dict:
    return {
        "pass": passed,
        "scope_ok": passed,
        "answer_correct": passed,
        "answer_analysis_consistent": passed,
        "conditions_sufficient": passed,
        "unambiguous": passed,
        "transfer_valid": passed,
        "intuition_aligned": passed,
        "structural_depth": passed,
        "request_aligned": passed,
        "issues": [] if passed else ["answer_incorrect"],
        "summary": "通过" if passed else "需修复",
    }


def _request_alignment(
    *,
    goal: str,
    bindings: list[dict],
    knowledge_points: list[str] | None = None,
    routes: list[dict] | None = None,
    comparison_evidence: str = "",
) -> dict:
    return {
        "request_aligned": True,
        "request_alignment": {
            "topic_bindings": bindings,
            "knowledge_points_used": list(knowledge_points or []),
            "goal_check": {
                "practice_goal": goal,
                "passed": True,
                "non_mechanical_core": True,
                "routes": list(routes or []),
                "comparison_criterion": "结构可见性与可迁移性" if goal == "solution_appreciation" else "",
                "comparison_evidence": comparison_evidence,
            },
        },
    }


class IntuitionPracticeContractTests(unittest.TestCase):
    def test_solution_appreciation_forces_four_stage_packet_and_canonical_order(self) -> None:
        config = normalize_intuition_practice_config(
            {"practice_goal": "solution_appreciation", "packet_size": 3}
        )
        self.assertEqual(config["packet_size"], 4)

        raw = _packet(goal="solution_appreciation", include_appreciation=True)
        raw["stages"] = [
            raw["stages"][2],
            raw["stages"][0],
            {**raw["stages"][0], "kind": "invariant", "prompt": "重复感知阶段"},
            raw["stages"][3],
            raw["stages"][1],
        ]
        packet = normalize_intuition_packet(raw, practice_config=config)
        self.assertEqual(
            [stage["stage"] for stage in packet["stages"]],
            ["perception", "model_externalization", "transfer", "appreciation"],
        )
        self.assertEqual(validate_intuition_packet_structure(packet, packet_size=4), [])

    def test_validation_quality_flags_survive_packet_normalization(self) -> None:
        raw = _packet()
        raw["validation"] = {
            "status": "passed",
            "scope_ok": True,
            "answer_correct": True,
            "answer_analysis_consistent": True,
            "conditions_sufficient": True,
            "unambiguous": True,
            "transfer_valid": True,
            "intuition_aligned": True,
            "structural_depth": True,
            "request_aligned": True,
        }

        validation = normalize_intuition_packet(raw)["validation"]

        self.assertIs(validation["intuition_aligned"], True)
        self.assertIs(validation["structural_depth"], True)
        self.assertIs(validation["request_aligned"], True)

    def test_math_reasoning_expansion_uses_intuition_actions_not_multistep_proxy(self) -> None:
        from backend.generation.question_library.beam_search import expand_reasoning_layer

        specs = [{"spec_id": "s1", "subject": "高中数学", "topic": "函数"}]
        out = expand_reasoning_layer(specs, {"reasoning_branch_factor": 6, "expand_budget": 10})
        reasoning = {str(item.get("reasoning") or "") for item in out}
        self.assertTrue(reasoning)
        self.assertTrue(any("估计" in item or "表征" in item or "不变量" in item for item in reasoning))
        self.assertFalse(any("多步推导" in item or "综合推理" in item for item in reasoning))

    def test_generation_prompt_requires_intuition_packet_and_explicit_appreciation_criteria(self) -> None:
        from backend.generation.question_library.draft_realization import build_generation_messages

        messages = build_generation_messages(
            subject="高中数学",
            topic="函数单调性",
            difficulty="中等",
            question_type="解答题",
            study_markdown="",
            count=1,
            spec={
                "subject": "高中数学",
                "topic": "函数单调性",
                "intuition_atom": _atom(),
                "intuition_practice": {
                    "practice_goal": "solution_appreciation",
                    "intuition_kinds": ["prediction", "representation", "solution_comparison"],
                    "packet_size": 4,
                    "feedback_mode": "guided",
                },
            },
            source_pack={},
        )
        system_prompt = str(messages[0]["content"])
        user_payload = str(messages[1]["content"])
        self.assertIn("Intuition is a trainable internal representation", system_prompt)
        self.assertIn("simplicity, symmetry, unification, invariants", system_prompt)
        self.assertIn("Build quick facility with basic objects", system_prompt)
        self.assertIn("Make relationships, transformations, and invariants", system_prompt)
        self.assertIn("safe cognitive conflict", system_prompt)
        self.assertIn("Preserve one decisive structure", system_prompt)
        self.assertIn("Compare correct approaches", system_prompt)
        self.assertIn("Give progressive hints", system_prompt)
        self.assertIn("Give only the decisive cue", system_prompt)
        self.assertIn("make the learner restate and revise the internal model", system_prompt)
        self.assertIn("Short is allowed; intellectually pre-solved is not", system_prompt)
        self.assertIn("must not name or paraphrase the exact invariant", system_prompt)
        self.assertIn("Changing only numbers, labels, or story context is invalid", system_prompt)
        self.assertIn("two genuinely different correct representations", system_prompt)
        self.assertIn('"intuition_packet"', user_payload)

    def test_reference_prompt_rejects_long_derivation_as_quality_proxy(self) -> None:
        from backend.generation.question_library import reference_analysis

        captured: list[dict] = []

        async def fake_chat(**kwargs):  # type: ignore[no-untyped-def]
            captured.extend(kwargs.get("messages") or [])
            return "{}"

        async def run() -> None:
            with patch.object(reference_analysis, "is_llm_configured", return_value=True), patch.object(
                reference_analysis, "_chat_json_with_reasoning", new=AsyncMock(side_effect=fake_chat)
            ):
                await reference_analysis.analyze_reference_questions(
                    subject="高中数学",
                    topic="函数",
                    difficulty="中等",
                    question_type="解答题",
                    reference_questions=[{"question_id": "r1", "stem": "参考题"}],
                )

        import asyncio

        asyncio.run(run())
        system_prompt = str(captured[0].get("content") or "")
        self.assertIn("Do not praise long derivations", system_prompt)
        self.assertIn("Never copy", system_prompt)


class IntuitionPracticePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_quick_validation_deterministically_rejects_routine_arithmetic_sequence_decomposition(self) -> None:
        from backend.generation.question_library import judging

        optimistic_report = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                "issues": [],
                "summary": "模型把附带的对称性说明误判为结构深度。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=optimistic_report)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": (
                        "已知等差数列 $\\{a_n\\}$ 满足 $a_1=2,a_4=8$。"
                        "（1）求数列的通项公式；（2）设前 $n$ 项和为 $S_n$，求 $S_n$ 的最大值。"
                    ),
                    "answer": "先求首项、公差和通项，再代入前 n 项和公式。",
                    "analysis": "附带说明二次函数图像具有对称性。",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {"subject": "高中数学", "topic": "等差数列"},
            )

        self.assertIs(report["pass"], False)
        self.assertIs(report["structural_depth"], False)
        self.assertIn("structural_depth_insufficient", report["issues"])
        self.assertIn("routine_arithmetic_sequence_decomposition", report["issues"])

    async def test_quick_validation_rejects_explicit_general_term_extremum_with_bolted_on_comparison(self) -> None:
        from backend.generation.question_library import judging

        optimistic_report = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                "issues": [],
                "summary": "题后比较了两种方法，因此声称具有结构深度。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=optimistic_report)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": (
                        "已知等差数列的通项为 $a_n=35-4n$，前 $n$ 项和为 $S_n$。"
                        "求 $S_n$ 的最大值；再分别用配方法与相邻项符号法解答，比较两种方法哪种更自然。"
                    ),
                    "answer": "由前 n 项和公式求出二次式并计算顶点。",
                    "analysis": "两种方法最终都是对已给通项的常规执行。",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {"subject": "高中数学", "topic": "等差数列的对称性与不变量"},
            )

        self.assertIs(report["pass"], False)
        self.assertIs(report["structural_depth"], False)
        self.assertIn("routine_explicit_general_term_sum_extremum", report["issues"])
        self.assertNotIn("solution_appreciation_missing_mother_question_comparison", report["issues"])

    async def test_quick_validation_keeps_relation_led_arithmetic_sequence_problem_eligible(self) -> None:
        from backend.generation.question_library import judging

        passing_report = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                **_request_alignment(
                    goal="structural_intuition",
                    bindings=[
                        {
                            "requested_clause": "等差数列",
                            "stem_evidence": "S_5=S_9",
                            "analysis_evidence": "",
                            "necessary": True,
                        }
                    ],
                ),
                "issues": [],
                "summary": "由部分和关系发现隐藏的配对结构。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=passing_report)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": (
                        "等差数列 $\\{a_n\\}$ 的前 $n$ 项和为 $S_n$，已知 $S_5=S_9$。"
                        "不求通项，判断 $S_n$ 在何处取得最大值，并说明结论为何由该关系决定。"
                    ),
                    "answer": "从相等部分和反推中间新增项之和为零，再利用等差项配对判断。",
                    "analysis": "关键是部分和差对应一段连续项的和，而不是先恢复首项和公差。",
                    "intuition_packet": _packet(),
                },
                {"subject": "高中数学", "topic": "等差数列"},
            )

        self.assertIs(report["pass"], True)
        self.assertIs(report["structural_depth"], True)
        self.assertNotIn("routine_arithmetic_sequence_decomposition", report["issues"])

    async def test_solution_appreciation_requires_comparison_in_the_mother_question(self) -> None:
        from backend.generation.question_library import judging

        optimistic_report = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                "issues": [],
                "summary": "附加练习包提供了方法比较。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=optimistic_report)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "根据图表中的证据说明该实验结论。",
                    "answer": "结论成立。",
                    "analysis": "解析在题后另外列出图表法和代数法。",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {"subject": "高中物理", "topic": "实验数据"},
            )

        self.assertIs(report["pass"], False)
        self.assertIs(report["structural_depth"], False)
        self.assertIn("solution_appreciation_missing_mother_question_comparison", report["issues"])

    async def test_solution_appreciation_accepts_explicit_scored_solution_comparison(self) -> None:
        from backend.generation.question_library import judging

        passing_report = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                **_request_alignment(
                    goal="solution_appreciation",
                    bindings=[
                        {
                            "requested_clause": "函数",
                            "stem_evidence": "参数边界",
                            "analysis_evidence": "边界翻转",
                            "necessary": True,
                        }
                    ],
                    routes=[
                        {
                            "representation": "图像",
                            "organizing_object": "边界翻转",
                            "decisive_move": "直接观察",
                            "stem_evidence": "比较图像法与代数法",
                            "analysis_evidence": "图像法直接呈现边界翻转",
                        },
                        {
                            "representation": "代数",
                            "organizing_object": "参数不等式",
                            "decisive_move": "精确验证",
                            "stem_evidence": "比较图像法与代数法",
                            "analysis_evidence": "代数法便于精确验证",
                        },
                    ],
                    comparison_evidence="依据统一性、解释力和可迁移性评价两种表征",
                ),
                "issues": [],
                "summary": "母题明确考查两种表征的比较与选择。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=passing_report)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "比较图像法与代数法这两种解法，并说明哪一种方法更自然地揭示参数边界。",
                    "answer": "图像法直接呈现边界翻转，代数法便于精确验证。",
                    "analysis": "依据统一性、解释力和可迁移性评价两种表征。",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {"subject": "高中数学", "topic": "函数"},
            )

        self.assertIs(report["pass"], True)
        self.assertIs(report["structural_depth"], True)
        self.assertNotIn("solution_appreciation_missing_mother_question_comparison", report["issues"])

    async def test_solution_appreciation_keeps_relation_led_sequence_symmetry_eligible(self) -> None:
        from backend.generation.question_library import judging

        passing_report = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                **_request_alignment(
                    goal="solution_appreciation",
                    bindings=[
                        {
                            "requested_clause": "对称性",
                            "stem_evidence": "S_5=S_9",
                            "analysis_evidence": "离散图像法揭示对称轴",
                            "necessary": True,
                        },
                        {
                            "requested_clause": "不变量",
                            "stem_evidence": "S_5=S_9",
                            "analysis_evidence": "配对法揭示下标和不变量",
                            "necessary": True,
                        },
                    ],
                    routes=[
                        {
                            "representation": "连续项配对",
                            "organizing_object": "下标和",
                            "decisive_move": "由相等部分和反推零和区间",
                            "stem_evidence": "连续项配对法",
                            "analysis_evidence": "配对法揭示下标和不变量",
                        },
                        {
                            "representation": "离散图像",
                            "organizing_object": "部分和对称轴",
                            "decisive_move": "由等高点定位对称轴",
                            "stem_evidence": "部分和离散图像法",
                            "analysis_evidence": "离散图像法揭示对称轴",
                        },
                    ],
                    comparison_evidence="配对法揭示下标和不变量，离散图像法揭示对称轴",
                ),
                "issues": [],
                "summary": "部分和等式迫使学生发现配对与离散图像对称。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=passing_report)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": (
                        "等差数列的前 $n$ 项和为 $S_n$，且 $S_5=S_9$。不求通项，判断最大部分和的位置；"
                        "比较连续项配对法与部分和离散图像法，并评价哪种方法更直接揭示对称性。"
                    ),
                    "answer": "先由相等部分和得到中间连续项和为零，再比较两种结构表征。",
                    "analysis": "配对法揭示下标和不变量，离散图像法揭示对称轴；二者都由 S_5=S_9 驱动。",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {
                    "subject": "高中数学",
                    "topic": "等差数列的对称性与不变量；迁移题须改变关系、约束、边界或表示",
                },
            )

        self.assertIs(report["pass"], True)
        self.assertIs(report["structural_depth"], True)
        self.assertNotIn("routine_explicit_general_term_sum_extremum", report["issues"])
        self.assertNotIn("routine_arithmetic_sequence_decomposition", report["issues"])

    async def test_quick_validation_rejects_number_only_transfer_in_same_review_call(self) -> None:
        from backend.generation.question_library import judging

        report_json = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": False,
                "intuition_aligned": True,
                "structural_depth": True,
                "issues": [],
                "summary": "迁移阶段只替换了数字。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=report_json)
        ) as review_mock:
            report = await judging.quick_validate_draft(
                {
                    "stem": "题干",
                    "answer": "答案",
                    "analysis": "解析",
                    "intuition_packet": _packet(),
                },
                {"subject": "高中数学"},
                source_pack={"question_requirements": ["课内"]},
            )

        self.assertEqual(review_mock.await_count, 1)
        self.assertIs(report["pass"], False)
        self.assertIs(report["transfer_valid"], False)
        self.assertIn("transfer_invalid", report["issues"])

    async def test_quick_validation_fails_closed_when_new_quality_flags_are_missing(self) -> None:
        from backend.generation.question_library import judging

        legacy_report_json = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "issues": [],
                "summary": "旧格式错误地声称通过。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=legacy_report_json)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "题干",
                    "answer": "答案",
                    "analysis": "解析",
                    "intuition_packet": _packet(),
                },
                {"subject": "高中数学"},
            )

        self.assertIs(report["pass"], False)
        self.assertIs(report["intuition_aligned"], False)
        self.assertIs(report["structural_depth"], False)
        self.assertIs(report["request_aligned"], False)
        self.assertIn("intuition_mismatch", report["issues"])
        self.assertIn("structural_depth_insufficient", report["issues"])
        self.assertIn("request_contract_mismatch", report["issues"])

    async def test_topic_terms_only_in_packet_do_not_establish_request_alignment(self) -> None:
        from backend.generation.question_library import judging

        report_json = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                **_request_alignment(
                    goal="structural_intuition",
                    bindings=[
                        {
                            "requested_clause": "对称性与不变量",
                            "stem_evidence": "对称性与不变量",
                            "analysis_evidence": "解析声称存在对称性与不变量",
                            "necessary": True,
                        }
                    ],
                ),
                "issues": [],
                "summary": "关键词只出现在题后说明。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=report_json)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "已知函数解析式，直接代入求函数值。",
                    "answer": "代入计算。",
                    "analysis": "解析声称存在对称性与不变量。",
                    "intuition_packet": _packet(),
                },
                {"subject": "高中数学", "topic": "函数的对称性与不变量"},
            )

        self.assertIs(report["pass"], False)
        self.assertIs(report["request_aligned"], False)
        self.assertIn("requested_topic_not_grounded_in_stem", report["issues"])

    async def test_requested_practice_goal_mismatch_rejected_before_judge(self) -> None:
        from backend.generation.question_library import judging

        review_mock = AsyncMock(return_value="{}")
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=review_mock
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "比较两种解法。",
                    "answer": "答案",
                    "analysis": "解析",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {"subject": "高中数学", "topic": "函数"},
                source_pack={
                    "topic": "函数",
                    "intuition_practice": {"practice_goal": "structural_intuition"},
                },
            )

        self.assertEqual(review_mock.await_count, 0)
        self.assertIs(report["request_aligned"], False)
        self.assertIn("practice_goal_mismatch", report["issues"])

    async def test_solution_appreciation_rejects_identical_route_fingerprints(self) -> None:
        from backend.generation.question_library import judging

        repeated_route = {
            "representation": "代数式",
            "organizing_object": "同一个前 n 项和公式",
            "decisive_move": "展开并配方",
            "stem_evidence": "比较方法甲与方法乙",
            "analysis_evidence": "两种方法都展开同一个前 n 项和公式",
        }
        report_json = json.dumps(
            {
                "pass": True,
                "scope_ok": True,
                "answer_correct": True,
                "answer_analysis_consistent": True,
                "conditions_sufficient": True,
                "unambiguous": True,
                "transfer_valid": True,
                "intuition_aligned": True,
                "structural_depth": True,
                **_request_alignment(
                    goal="solution_appreciation",
                    bindings=[
                        {
                            "requested_clause": "函数",
                            "stem_evidence": "函数",
                            "analysis_evidence": "函数",
                            "necessary": True,
                        }
                    ],
                    routes=[repeated_route, dict(repeated_route)],
                    comparison_evidence="两种方法都展开同一个前 n 项和公式",
                ),
                "issues": [],
                "summary": "把同一公式的展开顺序误称为两条路线。",
            },
            ensure_ascii=False,
        )
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(return_value=report_json)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "对这个函数，比较方法甲与方法乙并说明依据。",
                    "answer": "函数结论相同。",
                    "analysis": "两种方法都展开同一个前 n 项和公式。",
                    "intuition_packet": _packet(goal="solution_appreciation", include_appreciation=True),
                },
                {"subject": "高中数学", "topic": "函数"},
            )

        self.assertIs(report["request_aligned"], False)
        self.assertIn("solution_routes_not_distinct_or_ungrounded", report["issues"])

    async def test_quick_validation_rejects_shallow_misaligned_packet_and_requests_rebuild(self) -> None:
        from backend.generation.question_library import judging

        captured_messages: list[dict] = []

        async def fake_review(**kwargs):  # type: ignore[no-untyped-def]
            captured_messages.extend(kwargs.get("messages") or [])
            return json.dumps(
                {
                    "pass": True,
                    "scope_ok": True,
                    "answer_correct": True,
                    "answer_analysis_consistent": True,
                    "conditions_sufficient": True,
                    "unambiguous": True,
                    "transfer_valid": True,
                    "intuition_aligned": False,
                    "structural_depth": False,
                    "issues": [],
                    "summary": "题目直接给出完整方法，且直觉原子与题干错配。",
                },
                ensure_ascii=False,
            )

        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(side_effect=fake_review)
        ):
            report = await judging.quick_validate_draft(
                {
                    "stem": "请分别用公式法和配对法直接计算。",
                    "answer": "答案",
                    "analysis": "解析",
                    "intuition_packet": _packet(),
                },
                {"subject": "高中数学"},
            )

        self.assertIs(report["pass"], False)
        self.assertIn("intuition_mismatch", report["issues"])
        self.assertIn("structural_depth_insufficient", report["issues"])
        system_prompt = str(captured_messages[0].get("content") or "")
        self.assertIn("same decisive structure", system_prompt)
        self.assertIn("fully names the method", system_prompt)
        self.assertIn("genuinely different solution paths", system_prompt)

    async def test_repair_prompt_rebuilds_depth_and_alignment_instead_of_only_rephrasing(self) -> None:
        from backend.generation.question_library import judging

        captured_messages: list[dict] = []

        async def fake_repair(**kwargs):  # type: ignore[no-untyped-def]
            captured_messages.extend(kwargs.get("messages") or [])
            return json.dumps(
                {
                    "stem": "重构后的题干",
                    "answer": "答案",
                    "analysis": "解析",
                    "intuition_packet": _packet(),
                },
                ensure_ascii=False,
            )

        draft = {
            "stem": "直接套公式计算。",
            "answer": "答案",
            "analysis": "解析",
            "intuition_packet": _packet(),
        }
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(side_effect=fake_repair)
        ):
            repaired = await judging.refine_draft(
                draft,
                {"issues": ["intuition_mismatch", "structural_depth_insufficient"]},
            )

        self.assertEqual(repaired["stem"], "重构后的题干")
        system_prompt = str(captured_messages[0].get("content") or "")
        self.assertIn("rebuild the mother task", system_prompt)
        self.assertIn("Do not fix a depth or alignment failure by adding reflective prose", system_prompt)

    async def test_repair_preserves_complete_request_contract_and_requested_goal(self) -> None:
        from backend.generation.question_library import judging

        captured_messages: list[dict] = []

        async def fake_repair(**kwargs):  # type: ignore[no-untyped-def]
            captured_messages.extend(kwargs.get("messages") or [])
            return json.dumps(
                {
                    "stem": "按完整契约重构后的题干",
                    "answer": "答案",
                    "analysis": "解析",
                    # Deliberately tries to rewrite the requested goal.
                    "intuition_packet": _packet(
                        goal="solution_appreciation",
                        include_appreciation=True,
                    ),
                },
                ensure_ascii=False,
            )

        requested_topic = "等差数列\n必须从对称性与不变量出发，不能只换数字。"
        with patch.object(judging, "is_llm_configured", return_value=True), patch.object(
            judging, "_chat_json_with_reasoning", new=AsyncMock(side_effect=fake_repair)
        ):
            repaired = await judging.refine_draft(
                {
                    "stem": "旧题干",
                    "answer": "旧答案",
                    "analysis": "旧解析",
                    "intuition_packet": _packet(),
                },
                {"issues": ["request_contract_mismatch"]},
                spec={"subject": "高中数学", "topic": "等差数列"},
                source_pack={
                    "subject": "高中数学",
                    "topic": "等差数列",
                    "requested_topic": requested_topic,
                    "knowledge_points": ["等差数列的性质", "等差数列前n项和"],
                    "intuition_practice": {
                        "practice_goal": "structural_intuition",
                        "intuition_kinds": ["prediction", "invariant"],
                        "packet_size": 3,
                    },
                },
            )

        payload = json.loads(str(captured_messages[1]["content"]))
        contract = payload["request_contract"]
        self.assertEqual(contract["requested_topic"], requested_topic)
        self.assertEqual(
            contract["requested_knowledge_points"],
            ["等差数列的性质", "等差数列前n项和"],
        )
        self.assertEqual(contract["requested_practice_goal"], "structural_intuition")
        self.assertEqual(contract["requested_intuition_kinds"], ["prediction", "invariant"])
        self.assertEqual(repaired["intuition_packet"]["practice_goal"], "structural_intuition")
        self.assertIn("request_contract_mismatch", str(captured_messages[0]["content"]))

    async def test_pipeline_repairs_at_most_once_and_persists_validation(self) -> None:
        from backend.generation.question_library import generation

        config = normalize_intuition_practice_config({})
        spec = {
            "spec_id": "s1",
            "subject": "高中数学",
            "topic": "函数",
            "difficulty": "中等",
            "question_type": "解答题",
            "intuition_atom": _atom(),
            "intuition_practice": config,
            "intuition_alignment": 0.9,
            "score": 90,
        }
        candidate = {
            "spec_id": "s1",
            "stem": "题干",
            "answer": "答案",
            "analysis": "解析",
            "intuition_packet": _packet(),
            "intuition_score": 0.9,
        }
        repaired = {**candidate, "answer": "修复答案", "analysis": "修复解析"}

        with patch.object(generation, "seed_root_specs", return_value=[spec]), patch.object(
            generation, "expand_skill_layer", side_effect=lambda items, _cfg: items
        ), patch.object(generation, "expand_reasoning_layer", side_effect=lambda items, _cfg: items), patch.object(
            generation, "expand_trap_layer", side_effect=lambda items, _cfg: items
        ), patch.object(generation, "expand_surface_layer", side_effect=lambda items, _cfg: items), patch.object(
            generation, "score_spec", side_effect=lambda item, _sp, _cfg: item
        ), patch.object(generation, "beam_select", side_effect=lambda items, _cfg: items), patch.object(
            generation, "realize_drafts", new=AsyncMock(return_value=[candidate])
        ), patch.object(
            generation, "enrich_drafts_with_diagrams", new=AsyncMock(side_effect=lambda drafts, **_kwargs: drafts)
        ), patch.object(
            generation,
            "quick_validate_draft",
            new=AsyncMock(side_effect=[_validation(passed=False), _validation(passed=True)]),
        ) as validate_mock, patch.object(
            generation, "refine_draft", new=AsyncMock(return_value=repaired)
        ) as repair_mock:
            out = await generation.generate_questions(
                source_pack={
                    "subject": "高中数学",
                    "topic": "函数",
                    "skills": ["函数"],
                    "question_requirements": ["课内"],
                    "intuition_practice": config,
                },
                count=1,
                difficulty="中等",
                question_type="解答题",
                config={"enable_brainstorm": False, "max_repair_rounds": 5, "drafts_per_spec": 1},
            )

        self.assertEqual(len(out), 1)
        self.assertEqual(repair_mock.await_count, 1)
        self.assertEqual(validate_mock.await_count, 2)
        self.assertEqual(out[0]["intuition_packet"]["validation"]["status"], "passed")
        self.assertIs(out[0]["intuition_packet"]["validation"]["repaired"], True)
        self.assertIs(out[0]["intuition_packet"]["validation"]["intuition_aligned"], True)
        self.assertIs(out[0]["intuition_packet"]["validation"]["structural_depth"], True)
        self.assertIs(out[0]["intuition_packet"]["validation"]["request_aligned"], True)
        self.assertIn("直觉一致", [item["name"] for item in out[0]["review"]["dimensions"]])
        self.assertIn("结构深度", [item["name"] for item in out[0]["review"]["dimensions"]])
        self.assertIn("请求契约", [item["name"] for item in out[0]["review"]["dimensions"]])

    async def test_pipeline_deduplicates_same_intuition_packet_before_callback(self) -> None:
        from backend.generation.question_library import generation

        config = normalize_intuition_practice_config({})
        spec = {
            "spec_id": "s1",
            "subject": "高中数学",
            "topic": "函数",
            "difficulty": "中等",
            "question_type": "解答题",
            "intuition_atom": _atom(),
            "intuition_practice": config,
            "score": 90,
        }
        candidates = [
            {
                "spec_id": "s1",
                "stem": f"题干{i}",
                "answer": "答案",
                "analysis": "解析",
                "intuition_packet": _packet(),
            }
            for i in (1, 2)
        ]
        accepted: list[dict] = []
        with patch.object(generation, "seed_root_specs", return_value=[spec]), patch.object(
            generation, "expand_skill_layer", side_effect=lambda items, _cfg: items
        ), patch.object(generation, "expand_reasoning_layer", side_effect=lambda items, _cfg: items), patch.object(
            generation, "expand_trap_layer", side_effect=lambda items, _cfg: items
        ), patch.object(generation, "expand_surface_layer", side_effect=lambda items, _cfg: items), patch.object(
            generation, "score_spec", side_effect=lambda item, _sp, _cfg: item
        ), patch.object(generation, "beam_select", side_effect=lambda items, _cfg: items), patch.object(
            generation, "realize_drafts", new=AsyncMock(return_value=candidates)
        ), patch.object(
            generation, "enrich_drafts_with_diagrams", new=AsyncMock(side_effect=lambda drafts, **_kwargs: drafts)
        ), patch.object(
            generation, "quick_validate_draft", new=AsyncMock(return_value=_validation(passed=True))
        ):
            out = await generation.generate_questions(
                source_pack={
                    "subject": "高中数学",
                    "topic": "函数",
                    "skills": ["函数"],
                    "question_requirements": ["课内"],
                    "intuition_practice": config,
                },
                count=2,
                difficulty="中等",
                question_type="解答题",
                on_candidate_accepted=accepted.append,
                config={"enable_brainstorm": False, "max_repair_rounds": 1, "drafts_per_spec": 1},
            )

        self.assertEqual(len(out), 1)
        self.assertEqual(len(accepted), 1)


class PracticeStateApiTests(unittest.TestCase):
    def test_patch_practice_state_deep_merges_stages_and_restores_from_session(self) -> None:
        app = create_app()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}
        temp_dir = tempfile.TemporaryDirectory()
        old_previews = preview_store._PREVIEWS_DIR
        old_sessions = preview_store._SESSIONS_DIR
        preview_store._PREVIEWS_DIR = Path(temp_dir.name) / "previews"
        preview_store._SESSIONS_DIR = Path(temp_dir.name) / "sessions"
        try:
            preview_store.save_session(
                {
                    "session_id": "s1",
                    "user_id": "u-1",
                    "preview_id": "p1",
                    "status": "pending_review",
                    "draft_questions": [
                        {
                            "question_id": "q1",
                            "stem": "题干",
                            "answer": "答案",
                            "analysis": "解析",
                            "intuition_packet": _packet(),
                        }
                    ],
                    "practice_attempts": {},
                }
            )
            client = TestClient(app)
            first = client.patch(
                "/api/question-library/sessions/s1/questions/q1/practice-state",
                json={
                    "phase": "perception",
                    "first_guess": "向右",
                    "confidence": 55,
                    "stage_responses": {
                        "perception": {"initial_response": "向右", "confidence": 55, "hint_level": 0}
                    },
                },
            )
            self.assertEqual(first.status_code, 200)
            second = client.patch(
                "/api/question-library/sessions/s1/questions/q1/practice-state",
                json={
                    "phase": "transfer",
                    "stage_responses": {
                        "transfer": {"final_response": "仍看导数符号", "confidence": 80, "hint_level": 1}
                    },
                    "completed": True,
                },
            )
            self.assertEqual(second.status_code, 200)

            detail = client.get("/api/question-library/sessions/s1")
            self.assertEqual(detail.status_code, 200)
            state = detail.json()["session"]["practice_attempts"]["q1"]
            self.assertEqual(state["first_guess"], "向右")
            self.assertEqual(set(state["stage_responses"]), {"perception", "transfer"})
            self.assertIs(state["completed"], True)
            self.assertGreater(state["completed_at_s"], 0)
        finally:
            preview_store._PREVIEWS_DIR = old_previews
            preview_store._SESSIONS_DIR = old_sessions
            app.dependency_overrides.clear()
            temp_dir.cleanup()

    def test_regenerate_changed_section_replaces_session_draft_and_clears_stale_practice_data(self) -> None:
        app = create_app()
        app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}
        temp_dir = tempfile.TemporaryDirectory()
        old_previews = preview_store._PREVIEWS_DIR
        old_sessions = preview_store._SESSIONS_DIR
        preview_store._PREVIEWS_DIR = Path(temp_dir.name) / "previews"
        preview_store._SESSIONS_DIR = Path(temp_dir.name) / "sessions"
        draft = {
            "question_id": "q1",
            "stem": "旧题干",
            "answer": "答案",
            "analysis": "解析",
            "review_status": "confirmed",
            "intuition_packet": _packet(),
            "quick_validation": _validation(passed=True),
            "review": {"verdict": "可练习"},
        }
        try:
            preview_store.save_preview(
                {
                    "preview_id": "p1",
                    "session_id": "s1",
                    "user_id": "u-1",
                    "status": "pending_review",
                    "subject": "高中数学",
                    "topic": "函数",
                    "difficulty": "中等",
                    "question_type": "解答题",
                    "draft_questions": [draft],
                }
            )
            preview_store.save_session(
                {
                    "session_id": "s1",
                    "preview_id": "p1",
                    "user_id": "u-1",
                    "status": "pending_review",
                    "draft_questions": [draft],
                    "practice_attempts": {"q1": {"first_guess": "向右", "completed": True}},
                }
            )

            client = TestClient(app)
            with patch(
                "backend.generation.question_library.session_service.regenerate_question_section",
                new=AsyncMock(return_value="新题干"),
            ):
                response = client.post(
                    "/api/question-library/previews/p1/regenerate-section",
                    json={"question_id": "q1", "section_key": "stem"},
                )

            self.assertEqual(response.status_code, 200)
            session = preview_store.load_session("s1") or {}
            persisted = (session.get("draft_questions") or [])[0]
            self.assertEqual(persisted.get("stem"), "新题干")
            self.assertNotIn("intuition_packet", persisted)
            self.assertNotIn("quick_validation", persisted)
            self.assertIsNone(persisted.get("review"))
            self.assertEqual(persisted.get("review_status"), "pending_review")
            self.assertNotIn("q1", session.get("practice_attempts") or {})
        finally:
            preview_store._PREVIEWS_DIR = old_previews
            preview_store._SESSIONS_DIR = old_sessions
            app.dependency_overrides.clear()
            temp_dir.cleanup()


class IntuitionPacketRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.temp_dir.name}/test.db",
            future=True,
        )
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.cache_patch = patch.object(cache_repo, "async_session_maker", self.session_maker)
        self.cache_patch.start()

    async def asyncTearDown(self) -> None:
        self.cache_patch.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_question_cache_round_trips_structured_packet_and_partial_upsert_preserves_it(self) -> None:
        packet = _packet()
        await cache_repo.upsert_question_cache(
            [
                {
                    "question_id": "q1",
                    "subject": "高中数学",
                    "stem": "题干",
                    "answer": "答案",
                    "analysis": "解析",
                    "intuition_packet": packet,
                }
            ]
        )
        cached = (await cache_repo.get_question_cache(question_ids=["q1"]))["q1"]
        self.assertEqual(cached["intuition_packet"]["atom"]["concept"], packet["atom"]["concept"])
        self.assertTrue(cached["intuition_packet_json"])

        await cache_repo.upsert_question_cache([{"question_id": "q1", "subject": "高中数学", "stem": "新题干"}])
        preserved = (await cache_repo.get_question_cache(question_ids=["q1"]))["q1"]
        self.assertEqual(preserved["intuition_packet"]["atom"]["concept"], packet["atom"]["concept"])


if __name__ == "__main__":
    unittest.main()
