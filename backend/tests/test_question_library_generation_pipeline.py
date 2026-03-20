import json
import unittest
from unittest.mock import AsyncMock, patch


class TestQuestionLibraryGenerationPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_generate_questions_filters_low_quality_and_keeps_novel(self) -> None:
        from backend.question_library.generation import generate_questions
        stage_events: list[dict] = []

        async def fake_chat_completion_text(*, messages, req_id_prefix: str = "", **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            prompt = "\n".join([str(m.get("content") or "") for m in (messages or []) if isinstance(m, dict)])

            if req_id_prefix == "qlg":
                return json.dumps(
                    {
                        "questions": [
                            {
                                "stem": "已知函数 \\(f(x)=x^2\\)，求其单调区间。",
                                "answer": "在 \\((0,+\\infty)\\) 单调递增。",
                                "analysis": "直接求导得到 \\(f'(x)=2x\\)，判断符号即可。",
                            },
                            {
                                "stem": "设参数 \\(a>0\\)。函数 \\(f_a(x)=x^3-3ax\\) 在 \\(\\mathbb R\\) 上有两个极值点。"
                                "若 \\(f_a(x)\\) 在区间 \\([-1,2]\\) 上的最小值为 \\(-2\\)，求 \\(a\\) 的取值，并讨论对应最小值点的位置。",
                                "answer": "分类讨论可得 \\(a\\in[\\tfrac{1}{3},1]\\)，最小值点随 \\(a\\) 分段变化。",
                                "analysis": "先求导 \\(f'_a(x)=3x^2-3a\\)，极值点为 \\(x=\\pm\\sqrt a\\)。"
                                "比较 \\(x=-1,2,\\pm\\sqrt a\\) 处函数值并分类讨论，得到参数范围与最小值点位置。",
                            },
                        ]
                    },
                    ensure_ascii=False,
                )

            if req_id_prefix == "ql_solver":
                return json.dumps(
                    {
                        "match": True,
                        "final_answer": "同意参考答案。",
                        "issues": [],
                        "summary": "可解且答案一致。",
                    },
                    ensure_ascii=False,
                )

            if req_id_prefix == "ql_amb":
                return json.dumps({"ambiguous": False, "issues": [], "summary": "表述清晰。"}, ensure_ascii=False)

            if req_id_prefix == "ql_judge":
                if "求其单调区间" in prompt:
                    overall = 60
                    dims = [
                        {"name": "思维含量", "score": 4, "comment": "套路题"},
                        {"name": "区分度", "score": 4, "comment": "较低"},
                        {"name": "知识覆盖", "score": 5, "comment": "单点"},
                        {"name": "表述规范", "score": 8, "comment": "清楚"},
                        {"name": "创新性", "score": 3, "comment": "无新意"},
                    ]
                else:
                    overall = 92
                    dims = [
                        {"name": "思维含量", "score": 9, "comment": "需要参数+分类"},
                        {"name": "区分度", "score": 9, "comment": "高"},
                        {"name": "知识覆盖", "score": 8, "comment": "导数+最值"},
                        {"name": "表述规范", "score": 8, "comment": "清楚"},
                        {"name": "创新性", "score": 8, "comment": "有变化与讨论"},
                    ]

                return json.dumps(
                    {
                        "verdict": "好题" if overall >= 80 else "普通题",
                        "overall_score": overall,
                        "dimensions": dims,
                        "highlights": [],
                        "issues": [],
                        "summary": "ok",
                        "difficulty_estimate": "困难" if overall >= 85 else "中等",
                        "novelty_score": 8 if overall >= 85 else 3,
                        "reasoning_depth": 9 if overall >= 85 else 4,
                        "pass": overall >= 80,
                    },
                    ensure_ascii=False,
                )

            if req_id_prefix == "ql_repair":
                return json.dumps(
                    {
                        "stem": "修复后的题干",
                        "answer": "修复后的答案",
                        "analysis": "修复后的解析",
                    },
                    ensure_ascii=False,
                )

            if req_id_prefix == "ql_distill":
                return json.dumps(
                    {
                        "facts": [],
                        "skills": ["参数讨论", "分类讨论", "导数最值"],
                        "common_mistakes": ["忽略边界点"],
                        "forbidden_patterns": ["直接求导判断单调区间"],
                    },
                    ensure_ascii=False,
                )

            raise AssertionError(f"unexpected req_id_prefix: {req_id_prefix}")

        with patch("backend.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.question_library.generation.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数应用", "study_markdown": ""},
                count=1,
                difficulty="困难",
                question_type="解答题",
                on_stage_event=stage_events.append,
                config={
                    "beam_width": 1,
                    "expand_budget": 10,
                    "skill_branch_factor": 1,
                    "reasoning_branch_factor": 1,
                    "trap_branch_factor": 1,
                    "surface_branch_factor": 1,
                    "drafts_per_spec": 2,
                    "judge_pass_score": 80,
                    "max_repair_rounds": 1,
                    "solver_consensus_n": 1,
                },
            )

        self.assertEqual(len(out), 1)
        stem_text = str(out[0].get("stem") or "")
        self.assertTrue(stem_text.strip())
        self.assertTrue(("参数" in stem_text) or ("修复后" in stem_text))
        self.assertGreaterEqual(len(stage_events), 4)
        phases = [str(evt.get("phase") or "") for evt in stage_events]
        self.assertIn("spec_search", phases)
        self.assertIn("draft_realization", phases)
        self.assertIn("judge", phases)
        judge_events = [evt for evt in stage_events if str(evt.get("phase") or "") == "judge"]
        self.assertTrue(judge_events)
        reject_counts = {}
        for evt in judge_events:
            stats = evt.get("stats") if isinstance(evt.get("stats"), dict) else {}
            reject_counts.update(stats.get("reject_reason_counts") or {})
        self.assertIn("judge_below_floor", reject_counts)

    async def test_generate_questions_isolates_single_spec_realize_failure(self) -> None:
        from backend.question_library.generation import generate_questions

        qlg_calls = 0

        async def fake_chat_completion_text(*, messages, req_id_prefix: str = "", **kwargs):  # type: ignore[no-untyped-def]
            _ = messages, kwargs
            nonlocal qlg_calls
            if req_id_prefix == "qlg":
                qlg_calls += 1
                if qlg_calls == 1:
                    raise RuntimeError("llm_request_failed status=500 model=test provider=test msg=boom")
                return json.dumps(
                    {"questions": [{"stem": "题干-可保留", "answer": "答案", "analysis": "解析"}]},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_solver":
                return json.dumps({"match": True, "final_answer": "答案", "issues": [], "summary": "ok"}, ensure_ascii=False)
            if req_id_prefix == "ql_amb":
                return json.dumps({"ambiguous": False, "issues": [], "summary": "ok"}, ensure_ascii=False)
            if req_id_prefix == "ql_judge":
                return json.dumps(
                    {"pass": True, "overall_score": 90, "issues": [], "summary": "ok"},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_distill":
                return json.dumps(
                    {"facts": [], "skills": ["分类讨论"], "common_mistakes": [], "forbidden_patterns": []},
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected req_id_prefix: {req_id_prefix}")

        with patch("backend.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.question_library.generation.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数", "study_markdown": ""},
                count=1,
                difficulty="困难",
                question_type="解答题",
                config={
                    "beam_width": 2,
                    "expand_budget": 8,
                    "skill_branch_factor": 1,
                    "reasoning_branch_factor": 1,
                    "trap_branch_factor": 1,
                    "surface_branch_factor": 1,
                    "drafts_per_spec": 1,
                },
            )

        self.assertGreaterEqual(qlg_calls, 2)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out[0].get("stem") or ""), "题干-可保留")

    async def test_generate_questions_mismatch_and_ambiguity_are_penalties_not_veto(self) -> None:
        from backend.question_library.generation import generate_questions

        async def fake_chat_completion_text(*, messages, req_id_prefix: str = "", **kwargs):  # type: ignore[no-untyped-def]
            _ = messages, kwargs
            if req_id_prefix == "qlg":
                return json.dumps(
                    {"questions": [{"stem": "题干-高质量", "answer": "x=2", "analysis": "完整推导"}]},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_solver":
                return json.dumps(
                    {"match": False, "final_answer": "x=2", "issues": ["answer_form_diff"], "summary": "形式不一致"},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_amb":
                return json.dumps(
                    {"ambiguous": True, "issues": ["range_not_explicit"], "summary": "有轻微歧义"},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_judge":
                return json.dumps(
                    {
                        "pass": False,
                        "overall_score": 92,
                        "issues": [],
                        "summary": "题目质量高",
                        "novelty_score": 9,
                        "reasoning_depth": 9,
                    },
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_distill":
                return json.dumps(
                    {"facts": [], "skills": ["分类讨论"], "common_mistakes": [], "forbidden_patterns": []},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_repair":
                return json.dumps(
                    {"stem": "题干-修复", "answer": "修复答案", "analysis": "修复解析"},
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected req_id_prefix: {req_id_prefix}")

        with patch("backend.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.question_library.generation.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数", "study_markdown": ""},
                count=1,
                difficulty="困难",
                question_type="解答题",
                config={
                    "beam_width": 1,
                    "expand_budget": 6,
                    "skill_branch_factor": 1,
                    "reasoning_branch_factor": 1,
                    "trap_branch_factor": 1,
                    "surface_branch_factor": 1,
                    "drafts_per_spec": 1,
                    "judge_pass_score": 70,
                },
            )

        self.assertEqual(len(out), 1)
        self.assertEqual(str(out[0].get("stem") or ""), "题干-高质量")

    async def test_generate_questions_skips_repair_for_very_low_scores(self) -> None:
        from backend.question_library.generation import generate_questions

        repair_calls = 0

        async def fake_chat_completion_text(*, messages, req_id_prefix: str = "", **kwargs):  # type: ignore[no-untyped-def]
            _ = messages, kwargs
            nonlocal repair_calls
            if req_id_prefix == "qlg":
                return json.dumps(
                    {"questions": [{"stem": "题干-低分", "answer": "答案", "analysis": "解析"}]},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_solver":
                return json.dumps({"match": False, "final_answer": "答案", "issues": ["mismatch"], "summary": "不一致"}, ensure_ascii=False)
            if req_id_prefix == "ql_amb":
                return json.dumps({"ambiguous": False, "issues": [], "summary": "ok"}, ensure_ascii=False)
            if req_id_prefix == "ql_judge":
                return json.dumps(
                    {"pass": False, "overall_score": 45, "issues": ["low_quality"], "summary": "低分"},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_repair":
                repair_calls += 1
                return json.dumps(
                    {"stem": "题干-修复后", "answer": "答案-修复后", "analysis": "解析-修复后"},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_distill":
                return json.dumps(
                    {"facts": [], "skills": ["分类讨论"], "common_mistakes": [], "forbidden_patterns": []},
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected req_id_prefix: {req_id_prefix}")

        with patch("backend.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.question_library.generation.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数", "study_markdown": ""},
                count=1,
                difficulty="困难",
                question_type="解答题",
                config={
                    "beam_width": 1,
                    "expand_budget": 6,
                    "skill_branch_factor": 1,
                    "reasoning_branch_factor": 1,
                    "trap_branch_factor": 1,
                    "surface_branch_factor": 1,
                    "drafts_per_spec": 1,
                    "judge_pass_score": 70,
                    "max_repair_rounds": 2,
                    "repair_score_band": 20,
                },
            )

        self.assertEqual(out, [])
        self.assertEqual(repair_calls, 0)
