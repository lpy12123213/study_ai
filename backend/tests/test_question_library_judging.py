import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.generation.question_library.judging import (
    _evidence_is_grounded,
    judge_draft,
    quick_validate_draft,
)


class TestQuestionLibraryJudging(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _nine_gate_review(*, request_aligned: bool, alignment: dict) -> str:
        return json.dumps(
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
                "request_aligned": request_aligned,
                "requestContractAlignment": alignment,
                "issues": [],
                "summary": "All nine gates pass.",
            },
            ensure_ascii=False,
        )

    async def test_judge_draft_tolerates_non_integer_scores(self) -> None:
        async def fake_chat_json_with_reasoning(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return (
                '{"pass": true, "verdict": "普通题", "overall_score": "高", '
                '"dimensions": [], "highlights": [], "issues": [], "summary": "ok", '
                '"difficulty_estimate": "中等", "novelty_score": "8.5", "reasoning_depth": "深"}'
            )

        with (
            patch("backend.generation.question_library.judging.is_llm_configured", return_value=True),
            patch(
                "backend.generation.question_library.judging._chat_json_with_reasoning",
                new=AsyncMock(side_effect=fake_chat_json_with_reasoning),
            ),
        ):
            out = await judge_draft(
                {"stem": "题干", "answer": "2", "analysis": "计算。"},
                {"subject": "高中数学", "difficulty": "中等"},
            )

        self.assertTrue(out["pass"])
        self.assertEqual(out["overall_score"], 0)
        self.assertEqual(out["novelty_score"], 0)
        self.assertEqual(out["reasoning_depth"], 0)

    async def test_request_alignment_accepts_audited_aliases_and_shared_stem_contract(self) -> None:
        stem = (
            "等差数列 $\\{a_n\\}$ 的前 $n$ 项和为 $S_n$，已知 $S_3=S_9$。"
            "先观察结构并猜想 $S_{12}$ 的值，再给出两种思路不同的证明，"
            "并比较它们在结构可见性与迁移性上的差异。"
        )
        analysis = (
            "配对路线把中间连续项组织成下标和固定的配对，由相等部分和得到中间项和为零。"
            "二次函数路线把部分和看成离散抛物线，由两个等高点定位对称轴。"
            "写成 $S_n=An^2+Bn$ 后，由 $S_m=S_n$ 得 $(m-n)[A(m+n)+B]=0$，"
            "故 $S_{m+n}=...=0$。"
            "配对路线更直接揭示下标和不变量；二次函数路线更便于迁移。"
        )
        alignment = {
            "topicEvidence": {
                "requestedTopicClause": "等差数列的对称性质",
                "questionQuote": "$S_{3} = S_{9}$",
                "solutionQuote": "两个等高点定位对称轴",
                "isNecessary": "true",
            },
            "knowledgePointsUsed": [
                {
                    "knowledgePoint": "等差数列的性质",
                    "necessary": True,
                    "evidence": "由等差数列的性质可知上述结论（见分析证明2）",
                },
                {
                    "requestedKnowledgePoint": "等差数列前n项和",
                    "isNecessary": True,
                    "groundedEvidence": "已知等差数列的前n项和（见题干），分析中多次使用该结构",
                },
            ],
            "practiceGoalCheck": {
                "goal": "solution_appreciation",
                "satisfied": "passed",
                "nonMechanical": "true",
                "routeFingerprints": [
                    {
                        "representationType": "连续项配对",
                        "organizingIdea": "下标和不变量",
                        "keyStep": "由相等部分和得到中间项和为零",
                        # The mother task intentionally does not reveal this
                        # route name.  Its shared "two approaches" instruction
                        # is the stem-side contract; differentiation is in the
                        # grounded solution quote below.
                        "questionQuote": "连续项配对法",
                        "solutionQuote": "配对路线把中间连续项组织成下标和固定的配对",
                    },
                    {
                        "representation": "部分和二次函数图像",
                        "coreObject": "离散抛物线的对称轴",
                        "criticalMove": "由两个等高点定位对称轴",
                        "questionEvidence": "二次函数路线",
                        "reasoningEvidence": (
                            "$S_n=An^2+Bn$…$(m-n)[A(m+n)+B]=0$…"
                            "$S_{m+n}=...=0$"
                        ),
                    },
                ],
                "comparison": {
                    "criterion": "结构可见性与可迁移性",
                    # Only punctuation differs from the final analysis.
                    "evidence": "配对路线更直接揭示下标和不变量，二次函数路线更便于迁移",
                },
            },
        }
        review = self._nine_gate_review(request_aligned=True, alignment=alignment)

        with (
            patch("backend.generation.question_library.judging.is_llm_configured", return_value=True),
            patch(
                "backend.generation.question_library.judging._chat_json_with_reasoning",
                new=AsyncMock(return_value=review),
            ),
        ):
            out = await quick_validate_draft(
                {
                    "stem": stem,
                    "answer": "猜想 $S_{12}=0$，并分别证明。",
                    "analysis": analysis,
                    "intuition_packet": {"practice_goal": "solution_appreciation"},
                },
                {"subject": "高中数学", "topic": "等差数列"},
                source_pack={
                    "subject": "高中数学",
                    "requested_topic": "等差数列的对称性质；先观察结构并作出猜想",
                    "knowledge_points": ["等差数列的性质", "等差数列前n项和"],
                    "intuition_practice": {"practice_goal": "solution_appreciation"},
                },
            )

        self.assertIs(out["pass"], True)
        self.assertIs(out["request_aligned"], True)
        self.assertNotIn("solution_routes_not_distinct_or_ungrounded", out["issues"])
        self.assertNotIn("solution_comparison_not_grounded", out["issues"])

    def test_compound_ellipsis_evidence_rejects_any_substantial_free_rewrite(self) -> None:
        source = (
            "写成 $S_n=An^2+Bn$ 后，由 $S_m=S_n$ 得 "
            "$(m-n)[A(m+n)+B]=0$，故 $S_{m+n}=...=0$。"
        )
        grounded = "$S_n=An^2+Bn$…$(m-n)[A(m+n)+B]=0$…$S_{m+n}=...=0$"
        paraphrased = "$S_n=An^2+Bn$…两式相减就能得到关键关系…$S_{m+n}=...=0$"

        self.assertIs(_evidence_is_grounded(grounded, source), True)
        self.assertIs(_evidence_is_grounded(paraphrased, source), False)

    async def test_explanatory_knowledge_evidence_still_needs_final_artifact_grounding(self) -> None:
        alignment = {
            "topic_bindings": [
                {
                    "requested_clause": "函数单调性",
                    "stem_evidence": "函数的单调性",
                    "necessary": True,
                }
            ],
            "knowledge_points_used": [
                {
                    "requested_knowledge_point": "圆锥曲线离心率",
                    "necessary": True,
                    "evidence": "由圆锥曲线离心率定义可知（见分析证明2）",
                }
            ],
            "goal_check": {
                "practice_goal": "structural_intuition",
                "passed": True,
                "non_mechanical_core": True,
                "routes": [],
                "comparison_criterion": "",
                "comparison_evidence": "",
            },
        }
        review = self._nine_gate_review(request_aligned=True, alignment=alignment)

        with (
            patch("backend.generation.question_library.judging.is_llm_configured", return_value=True),
            patch(
                "backend.generation.question_library.judging._chat_json_with_reasoning",
                new=AsyncMock(return_value=review),
            ),
        ):
            out = await quick_validate_draft(
                {
                    "stem": "观察函数的单调性，判断参数边界。",
                    "answer": "由单调性判断。",
                    "analysis": "函数在边界两侧的单调方向不同。",
                    "intuition_packet": {"practice_goal": "structural_intuition"},
                },
                {"subject": "高中数学", "topic": "函数单调性"},
                source_pack={
                    "subject": "高中数学",
                    "requested_topic": "函数单调性",
                    "knowledge_points": ["圆锥曲线离心率"],
                    "intuition_practice": {"practice_goal": "structural_intuition"},
                },
            )

        self.assertIs(out["request_aligned"], False)
        self.assertIn("requested_knowledge_point_missing:圆锥曲线离心率", out["issues"])

    async def test_semantic_request_aligned_boolean_remains_a_hard_gate(self) -> None:
        alignment = {
            "topic_bindings": [
                {
                    "requested_clause": "函数单调性",
                    "stem_evidence": "函数的单调性",
                    "necessary": True,
                }
            ],
            "knowledge_points_used": [],
            "goal_check": {
                "practice_goal": "structural_intuition",
                "passed": True,
                "non_mechanical_core": True,
                "routes": [],
                "comparison_criterion": "",
                "comparison_evidence": "",
            },
        }
        review = self._nine_gate_review(request_aligned=False, alignment=alignment)

        with (
            patch("backend.generation.question_library.judging.is_llm_configured", return_value=True),
            patch(
                "backend.generation.question_library.judging._chat_json_with_reasoning",
                new=AsyncMock(return_value=review),
            ),
        ):
            out = await quick_validate_draft(
                {
                    "stem": "观察函数的单调性，判断参数边界。",
                    "answer": "由单调性判断。",
                    "analysis": "函数在边界两侧的单调方向不同。",
                    "intuition_packet": {"practice_goal": "structural_intuition"},
                },
                {"subject": "高中数学", "topic": "函数单调性"},
                source_pack={
                    "requested_topic": "函数单调性",
                    "intuition_practice": {"practice_goal": "structural_intuition"},
                },
            )

        self.assertIs(out["pass"], False)
        self.assertIs(out["request_aligned"], False)
        self.assertIn("request_contract_mismatch", out["issues"])

    async def test_alias_normalization_does_not_bypass_distinct_routes_or_concrete_comparison(self) -> None:
        repeated_route = {
            "representationType": "代数展开",
            "organizingIdea": "同一个前n项和公式",
            "keyStep": "展开后配方",
            "solutionQuote": "两种写法都只是展开后配方",
        }
        alignment = {
            "topicEvidence": {
                "requestedTopicClause": "等差数列",
                "questionQuote": "等差数列",
                "isNecessary": True,
            },
            "knowledgePointsUsed": [],
            "practiceGoalCheck": {
                "goal": "solution_appreciation",
                "satisfied": True,
                "nonMechanical": True,
                "routeFingerprints": [repeated_route, dict(repeated_route)],
                "comparison": {"criterion": "不同", "evidence": "两种写法"},
            },
        }
        review = self._nine_gate_review(request_aligned=True, alignment=alignment)

        with (
            patch("backend.generation.question_library.judging.is_llm_configured", return_value=True),
            patch(
                "backend.generation.question_library.judging._chat_json_with_reasoning",
                new=AsyncMock(return_value=review),
            ),
        ):
            out = await quick_validate_draft(
                {
                    "stem": "对这个等差数列给出两种不同方法，并比较两种方法。",
                    "answer": "两种写法结论相同。",
                    "analysis": "两种写法都只是展开后配方。",
                    "intuition_packet": {"practice_goal": "solution_appreciation"},
                },
                {"subject": "高中数学", "topic": "等差数列"},
                source_pack={
                    "requested_topic": "等差数列",
                    "intuition_practice": {"practice_goal": "solution_appreciation"},
                },
            )

        self.assertIs(out["request_aligned"], False)
        self.assertIn("solution_routes_not_distinct_or_ungrounded", out["issues"])
        self.assertIn("solution_comparison_not_grounded", out["issues"])


if __name__ == "__main__":
    unittest.main()
