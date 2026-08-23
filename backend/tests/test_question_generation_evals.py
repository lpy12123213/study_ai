"""AI 出题 benchmark 的离线单元测试：全部 fixture 内联，不触网、不调 LLM。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.evals.question_generation.case_schema import (
    CaseValidationError,
    default_cases_dir,
    load_case,
    load_case_file,
    load_cases,
    parse_case,
)
from backend.evals.question_generation.graders import (
    DIMENSION_MAX,
    find_duplicate_stems,
    grade_case,
    render_report,
)
from backend.evals.question_generation.runner import (
    _apply_task_status,
    _consume_sse_lines,
    _effective_parallel,
    _resolve_cases,
)
from backend.generation.question_library.evolution import policy_fitness
from backend.generation.question_library.evolution_penalties import (
    difficulty_mismatch,
    evaluate_evolution_penalties,
    imitation_penalty,
    solution_fingerprint_similarity,
)

_CASE_DIR = default_cases_dir()


def _case(**overrides) -> dict:
    base = {
        "id": "mini",
        "title": "迷你出题用例",
        "subject": "高中数学",
        "topic": "等差数列：首项 a1=2、公差 d=3，求 a_10=29 与 S_10=155",
        "difficulty": "困难",
        "question_type": "解答题",
        "count": 3,
        "knowledge_points": ["等差数列通项公式", "等差数列前n项和公式"],
        "stem_anchors": ["等差数列", "首项.{0,10}2"],
        "answer_anchors": ["29", "155"],
        "analysis_anchors": ["通项"],
        "forbidden_patterns": ["(?<![0-9])165(?![0-9])"],
    }
    base.update(overrides)
    return base


def _draft(stem: str, answer: str, analysis: str) -> dict:
    return {"question_id": "q", "stem": stem, "answer": answer, "analysis": analysis, "review": None}


_GOOD_STEMS = [
    "已知等差数列 {a_n} 的首项 a_1=2、公差 d=3，写出通项公式并求第 10 项与前 10 项和。",
    "设某等差数列首项为 2、公差等于 3，请求出其第 10 项以及最初 10 项之和。",
    "一个等差数列，首项是 2，公差取 3，求 a_10 与 S_10 的值。",
]
_GOOD_ANSWER = "第 10 项 a_10=29；前 10 项和 S_10=155。"
_GOOD_ANALYSIS = (
    "解：由等差数列通项公式 a_n=a_1+(n-1)d=2+3(n-1)=3n-1，取 n=10 得 a_10=29。"
    "再由等差数列前 n 项和公式 S_n=n(a_1+a_n)/2=10×(2+29)/2=155。"
    "最后核对：逐项累加 2+5+8+…+29 亦为 155，两种算法一致。"
)


class CaseSchemaTests(unittest.TestCase):
    def test_all_shipped_cases_load_and_validate(self) -> None:
        cases = load_cases(_CASE_DIR)
        self.assertEqual(len(cases), 26)
        difficulties = {c.difficulty for c in cases}
        self.assertEqual(difficulties, {"困难", "压轴"})
        for case in cases:
            self.assertTrue(case.stem_anchors, case.id)
            self.assertTrue(case.answer_anchors, case.id)
            self.assertGreaterEqual(len(case.knowledge_points), 3, case.id)
            self.assertIn("高中", case.subject, case.id)
            self.assertGreaterEqual(case.min_stem_chars, 30, case.id)
            self.assertGreaterEqual(case.min_analysis_chars, 80, case.id)
            payload = case.request_payload()
            self.assertEqual(payload["subject"], case.subject)
            self.assertEqual(payload["difficulty"], case.difficulty)
            self.assertEqual(payload["question_type"], case.question_type)
            self.assertEqual(payload["count"], case.count)
            self.assertFalse(payload["use_study_archive"])
            self.assertTrue(payload["use_reference_questions"])
            self.assertEqual(payload["mode"], "standard")
            self.assertIn("evolution_evaluation", payload)

    def test_reject_missing_or_invalid_fields(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case({"id": "x", "title": "t", "subject": "高中数学", "topic": "topic"})
        with self.assertRaises(CaseValidationError):
            parse_case(_case(difficulty="超难"))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(question_type="判断题"))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(count=6))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(count=0))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(stem_anchors=[]))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(answer_anchors=[]))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(knowledge_points=[]))
        with self.assertRaises(CaseValidationError):
            parse_case(_case(stem_anchors=["(["]))

    def test_duplicate_ids_rejected_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cases_dir = Path(tmp)
            (cases_dir / "a.json").write_text(json.dumps(_case(id="dup")), encoding="utf-8")
            (cases_dir / "b.json").write_text(json.dumps(_case(id="dup")), encoding="utf-8")
            with self.assertRaises(CaseValidationError):
                load_cases(cases_dir)

    def test_case_pack_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text(
                json.dumps({"cases": [_case(id="p1"), _case(id="p2", difficulty="压轴")]}, ensure_ascii=False),
                encoding="utf-8",
            )
            cases = load_case_file(path)
        self.assertEqual([c.id for c in cases], ["p1", "p2"])
        self.assertEqual(cases[1].difficulty, "压轴")


class GraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = load_case_from_dict()

    def test_good_drafts_clear_all_gates(self) -> None:
        drafts = [
            _draft(stem, _GOOD_ANSWER, _GOOD_ANALYSIS)
            for stem in _GOOD_STEMS
        ]
        card = grade_case(self.case, drafts)
        self.assertTrue(all(g.passed for g in card.quality_gates), card.to_dict()["quality_gates"])
        self.assertEqual(card.applied_ceiling, 100.0)
        self.assertEqual(card.total, card.raw_total)
        self.assertGreater(card.total, 85.0)
        self.assertIn("优秀", card.readiness_level)

    def test_wrong_answer_fails_correctness_gate(self) -> None:
        wrong = _draft(_GOOD_STEMS[0], "第 10 项为 29；前 10 项和为 165。", _GOOD_ANALYSIS)
        card = grade_case(self.case, [_draft(_GOOD_STEMS[1], _GOOD_ANSWER, _GOOD_ANALYSIS), wrong, _draft(_GOOD_STEMS[2], _GOOD_ANSWER, _GOOD_ANALYSIS)])
        correctness = next(g for g in card.quality_gates if g.id == "GQ_correctness")
        self.assertFalse(correctness.passed)
        # 165 同时命中禁用模式：D2 归零并封顶 19
        by_dim = {d.dimension: d for d in card.dimensions}
        self.assertEqual(by_dim["D2"].score, 0.0)
        self.assertLessEqual(card.total, 19.0)

    def test_missing_answer_and_short_sections_fail_delivery(self) -> None:
        drafts = [
            _draft(_GOOD_STEMS[0], "", _GOOD_ANALYSIS),
            _draft("太短", _GOOD_ANSWER, "寥寥数语。"),
        ]
        card = grade_case(self.case, drafts)
        delivery = next(g for g in card.quality_gates if g.id == "GQ_delivery")
        self.assertFalse(delivery.passed)
        self.assertLessEqual(card.total, 9.0)

    def test_near_duplicate_stems_detected(self) -> None:
        drafts = [
            _draft(_GOOD_STEMS[0], _GOOD_ANSWER, _GOOD_ANALYSIS),
            _draft(_GOOD_STEMS[0] + "？", _GOOD_ANSWER, _GOOD_ANALYSIS),
            _draft(_GOOD_STEMS[1], _GOOD_ANSWER, _GOOD_ANALYSIS),
        ]
        self.assertEqual(find_duplicate_stems(drafts), [1])
        card = grade_case(self.case, drafts)
        d1 = {d.dimension: d for d in card.dimensions}["D1"]
        distinct = next(c for c in d1.checks if c.id == "D1c_distinct")
        self.assertEqual(distinct.metrics["duplicate_indexes"], [1])

    def test_empty_drafts_score_zero(self) -> None:
        card = grade_case(self.case, [])
        self.assertEqual(card.raw_total, 0.0)
        self.assertFalse(all(g.passed for g in card.quality_gates))

    def test_scorecard_serialization_and_report(self) -> None:
        card = grade_case(self.case, [_draft(s, _GOOD_ANSWER, _GOOD_ANALYSIS) for s in _GOOD_STEMS])
        payload = card.to_dict()
        json.dumps(payload, ensure_ascii=False)
        self.assertAlmostEqual(sum(DIMENSION_MAX.values()), 100.0)
        report = render_report(card)
        self.assertIn("必要质量门槛", report)
        self.assertIn("GQ_correctness", report)
        self.assertIn("原始诊断分", report)

    def test_review_echo_is_process_diagnostic_only(self) -> None:
        drafts = [
            _draft(s, _GOOD_ANSWER, _GOOD_ANALYSIS)
            for s in _GOOD_STEMS
        ]
        for d in drafts:
            d["review"] = {"verdict": "差题", "overall_score": 10}
        card = grade_case(self.case, drafts)
        self.assertTrue(all(g.passed for g in card.quality_gates))
        self.assertEqual([c.id for c in card.process_diagnostics], ["P1_pipeline_self_review"])

    def test_fill_blank_type_cue_scored(self) -> None:
        """填空题：题面空线计入 D4a，答案形态只需非空（如 9/4 与取等条件）。"""
        fill_case = parse_case(_case(
            question_type="填空题",
            min_stem_chars=30,
            min_analysis_chars=60,
            topic="已知 x>0、y>0 且 x+2y=4，则 1/x+2/y 的最小值为____（柯西不等式，答案 9/4，x=y=4/3）",
            stem_anchors=["x\\s*\\+\\s*2\\s*y", "_{2,}|填空"],
            answer_anchors=["9\\s*/\\s*4|\\\\frac\\{9\\}\\{4\\}"],
            analysis_anchors=["柯西|均值"],
            forbidden_patterns=[],
        ))
        drafts = [
            _draft(
                "已知 $x>0$，$y>0$，且 $x+2y=4$，则 $\\frac{1}{x}+\\frac{2}{y}$ 的最小值为____。",
                "$\\frac{9}{4}$（当且仅当 $x=y=\\frac{4}{3}$）。",
                "解：由柯西不等式（恩格尔形式）原式 $\\geq\\frac{(1+2)^{2}}{x+2y}=\\frac{9}{4}$，当 $x=y=\\frac{4}{3}$ 时取等号。",
            )
            for _ in range(3)
        ]
        card = grade_case(fill_case, drafts)
        self.assertTrue(all(g.passed for g in card.quality_gates))
        by_dim = {d.dimension: d for d in card.dimensions}
        self.assertGreater(by_dim["D4"].score, by_dim["D4"].max_score * 0.8)


class EvolutionPenaltyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fingerprint = [
            {
                "id": "increment_set",
                "concepts": ["平移参数", "增量集合", "函数值比较"],
                "weight": 3.0,
            },
            {
                "id": "reverse_inclusion",
                "concepts": ["反向包含", "函数值次序", "集合包含"],
                "weight": 3.0,
            },
            {
                "id": "cross_axis",
                "concepts": ["选择平移量", "跨过零点", "已知半轴"],
                "weight": 3.0,
            },
        ]

    def test_difficulty_mismatch_requires_grounded_evidence(self) -> None:
        unsupported = difficulty_mismatch(target="压轴", assessed="中等", evidence_count=0)
        grounded = difficulty_mismatch(target="压轴", assessed="中等", evidence_count=1)
        self.assertEqual(unsupported["penalty"], 0.0)
        self.assertFalse(unsupported["counted"])
        self.assertEqual(grounded["gap"], 2)
        self.assertEqual(grounded["penalty"], 0.16)

    def test_solution_similarity_requires_multiple_distinctive_units(self) -> None:
        copied = solution_fingerprint_similarity(
            solution_text=(
                "先用平移参数定义增量集合并完成函数值比较，再由函数值次序推出反向包含与集合包含，"
                "最后选择平移量跨过零点进入已知半轴。"
            ),
            fingerprint=self.fingerprint,
        )
        generic = solution_fingerprint_similarity(
            solution_text="利用集合包含关系并采用反证法完成证明。",
            fingerprint=self.fingerprint,
        )
        self.assertGreaterEqual(copied["score"], 0.95)
        self.assertEqual(copied["matched_ids"], ["increment_set", "reverse_inclusion", "cross_axis"])
        self.assertLess(generic["score"], 0.2)
        self.assertEqual(
            imitation_penalty(local_similarity=copied["score"], threshold=0.56)["penalty"],
            0.3,
        )
        self.assertEqual(imitation_penalty(local_similarity=generic["score"], threshold=0.56)["penalty"], 0.0)

    def test_penalties_reduce_policy_fitness_and_candidate_score(self) -> None:
        base = policy_fitness(
            passed=True,
            confidence=0.9,
            evidence_count=2,
            usage={"output_tokens": 100},
            latency_s=1.0,
            arbitrated=False,
        )
        penalized = policy_fitness(
            passed=True,
            confidence=0.9,
            evidence_count=2,
            usage={"output_tokens": 100},
            latency_s=1.0,
            arbitrated=False,
            difficulty_penalty=0.16,
            imitation_penalty=0.3,
        )
        self.assertAlmostEqual(base - penalized, 0.46, places=4)

        evaluation = {
            "reference_id": "abstract_reference",
            "solution_fingerprint": self.fingerprint,
            "max_solution_similarity": 0.56,
        }
        result = evaluate_evolution_penalties(
            draft={
                "answer": "结论",
                "analysis": (
                    "用平移参数定义增量集合比较函数值；函数值次序对应反向包含和集合包含；"
                    "选择平移量跨过零点进入已知半轴。"
                ),
            },
            target_difficulty="压轴",
            assessed_difficulty="中等",
            difficulty_evidence=["grounded"],
            evaluation=evaluation,
        )
        self.assertEqual(result["difficulty"]["penalty"], 0.16)
        self.assertEqual(result["imitation"]["penalty"], 0.3)
        self.assertEqual(result["total"], 0.46)

    def test_benchmark_score_subtracts_evolution_penalties(self) -> None:
        case = parse_case(
            _case(
                count=1,
                difficulty="压轴",
                evolution_evaluation={
                    "reference_id": "abstract_reference",
                    "solution_fingerprint": self.fingerprint,
                    "max_solution_similarity": 0.56,
                },
            )
        )
        draft = _draft(_GOOD_STEMS[0], _GOOD_ANSWER, _GOOD_ANALYSIS + (
            "用平移参数定义增量集合比较函数值；函数值次序对应反向包含和集合包含；"
            "选择平移量跨过零点进入已知半轴。"
        ))
        draft["supervision_summary"] = {
            "difficulty_estimate": "中等",
            "difficulty_evidence_count": 1,
            "evolution_penalties": {"imitation": {}},
        }
        card = grade_case(case, [draft])
        self.assertEqual([item.id for item in card.evolution_penalties], [
            "EP_difficulty_mismatch",
            "EP_solution_imitation",
        ])
        self.assertEqual(card.penalty_total, 46.0)
        self.assertEqual(card.raw_total, card.pre_penalty_total - 46.0)


def load_case_from_dict():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mini.json"
        path.write_text(json.dumps(_case(), ensure_ascii=False), encoding="utf-8")
        return load_case(path)


class RunnerHelperTests(unittest.TestCase):
    def test_sse_eof_recovers_completed_durable_task_result(self) -> None:
        events = []
        state = {"terminal": False, "error": "", "preview_id": "", "session_id": "", "task_id": ""}
        _consume_sse_lines(
            [
                'data: {"taskId":"ql_gen_race","type":"ping","data":{"status":"running"}}',
            ],
            events,
            state,
        )
        self.assertEqual(state["task_id"], "ql_gen_race")
        self.assertFalse(state["terminal"])
        recovered = _apply_task_status(
            {
                "status": "completed",
                "result": {"preview_id": "preview_race", "session_id": "session_race"},
            },
            state,
        )
        self.assertTrue(recovered)
        self.assertTrue(state["terminal"])
        self.assertEqual(state["preview_id"], "preview_race")
        self.assertEqual(state["session_id"], "session_race")

    def test_resolve_cases_all_and_single(self) -> None:
        all_cases = _resolve_cases("all", _CASE_DIR)
        self.assertEqual(len(all_cases), 26)
        single = _resolve_cases("math_conic_focus_chord", _CASE_DIR)
        self.assertEqual([c.id for c in single], ["math_conic_focus_chord"])
        with self.assertRaises(CaseValidationError):
            _resolve_cases("nonexistent", _CASE_DIR)

    def test_resolve_cases_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "one.json"
            path.write_text(json.dumps(_case(id="file_case"), ensure_ascii=False), encoding="utf-8")
            cases = _resolve_cases(str(path), _CASE_DIR)
        self.assertEqual([c.id for c in cases], ["file_case"])

    def test_effective_parallel(self) -> None:
        self.assertEqual(_effective_parallel(0, 1), 1)
        self.assertEqual(_effective_parallel(0, 20), 4)
        self.assertEqual(_effective_parallel(2, 10), 2)
        with self.assertRaises(CaseValidationError):
            _effective_parallel(-1, 3)

    def test_dry_run_main(self) -> None:
        from backend.evals.question_generation.runner import main

        with tempfile.TemporaryDirectory() as tmp:
            cases_dir = Path(tmp)
            (cases_dir / "a.json").write_text(json.dumps(_case(id="qa")), encoding="utf-8")
            (cases_dir / "b.json").write_text(json.dumps(_case(id="qb", difficulty="压轴")), encoding="utf-8")
            rc = main(["--case", "all", "--cases-dir", str(cases_dir), "--dry-run"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
