import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch


class TestQuestionLibraryGenerationPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_chat_json_with_reasoning_executes_scientific_compute_tool_and_emits_logs(self) -> None:
        from backend.generation.question_library import gen_llm
        from backend.llm.client import ChatCompletionResult

        seen_messages: list[list[dict]] = []
        reasoning_events: list[dict] = []

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            seen_messages.append(list(kwargs.get("messages") or []))
            if len(seen_messages) == 1:
                return ChatCompletionResult(
                    content="",
                    tool_calls=[
                        {
                            "id": "tool-1",
                            "type": "function",
                            "function": {
                                "name": "python_scientific_compute",
                                "arguments": json.dumps(
                                    {
                                        "code": "result = math.sqrt(144)",
                                        "purpose": "验证答案",
                                        "timeout_seconds": 5,
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                )
            return ChatCompletionResult(content='{"ok": true}', tool_calls=[])

        async def on_reasoning_event(event: dict) -> None:
            reasoning_events.append(dict(event))

        with patch("backend.generation.question_library.gen_llm.chat_completion", new=AsyncMock(side_effect=fake_chat_completion)), patch(
            "backend.generation.question_library.gen_llm.python_scientific_compute",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "result_repr": "12.0",
                    "result_type": "float",
                    "stdout": "",
                    "warnings": [],
                }
            ),
        ):
            text = await gen_llm._chat_json_with_reasoning(
                messages=[{"role": "user", "content": "请输出 JSON"}],
                model="openai/test-mini",
                temperature=0.2,
                max_tokens=300,
                req_id_prefix="qlg",
                retries=1,
                raise_on_fail=True,
                stage_id="draft_realization",
                stage_label="草稿生成",
                stream_reasoning=False,
                on_reasoning_event=on_reasoning_event,
            )

        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(len(seen_messages), 2)
        self.assertTrue(any(msg.get("role") == "tool" for msg in seen_messages[1]))
        messages = [str(evt.get("message") or "") for evt in reasoning_events if str(evt.get("message") or "").strip()]
        joined = "\n".join(messages)
        self.assertIn("[tool_call] python_scientific_compute", joined)
        self.assertIn("验证答案", joined)
        self.assertIn("[tool_result] python_scientific_compute", joined)
        self.assertIn("12.0", joined)

    async def test_chat_json_with_reasoning_uses_configured_effort_for_chat_and_fallback(self) -> None:
        from backend.generation.question_library import gen_llm

        seen_chat_reasoning: list[dict] = []
        seen_text_reasoning: list[dict] = []

        async def fake_chat_completion(**kwargs):  # type: ignore[no-untyped-def]
            seen_chat_reasoning.append(dict(kwargs.get("reasoning") or {}))
            raise RuntimeError("tool_mode_disabled")

        async def fake_chat_completion_text(**kwargs):  # type: ignore[no-untyped-def]
            seen_text_reasoning.append(dict(kwargs.get("reasoning") or {}))
            return '{"ok": true}'

        with patch(
            "backend.generation.question_library.gen_llm.STUDY_MATERIALS_THINKING_EFFORT_DEFAULT",
            "xhigh",
            create=True,
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=fake_chat_completion),
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion_text",
            new=AsyncMock(side_effect=fake_chat_completion_text),
        ):
            text = await gen_llm._chat_json_with_reasoning(
                messages=[{"role": "user", "content": "return JSON"}],
                model="openai/test-mini",
                temperature=0.2,
                max_tokens=300,
                req_id_prefix="qlg",
                retries=1,
                raise_on_fail=False,
                stage_id="draft_realization",
                stage_label="draft",
                stream_reasoning=False,
                on_reasoning_event=None,
            )

        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(seen_chat_reasoning, [{"effort": "xhigh", "exclude": True}])
        self.assertEqual(seen_text_reasoning, [{"effort": "xhigh", "exclude": True}])

    def test_build_generation_messages_changes_system_prompt_by_difficulty(self) -> None:
        from backend.generation.question_library.generation import build_generation_messages

        easy = build_generation_messages(
            subject="高中数学",
            topic="函数单调性",
            difficulty="简单",
            question_type="解答题",
            study_markdown="",
            count=1,
            spec={"skill": "概念辨析"},
            source_pack={},
        )
        hard = build_generation_messages(
            subject="高中数学",
            topic="函数单调性",
            difficulty="困难",
            question_type="解答题",
            study_markdown="",
            count=1,
            spec={"skill": "综合应用"},
            source_pack={},
        )

        easy_system = str(easy[0].get("content") or "")
        hard_system = str(hard[0].get("content") or "")

        self.assertNotEqual(easy_system, hard_system)
        self.assertIn("基础题", easy_system)
        self.assertIn("高难度", hard_system)

    def test_beam_select_preserves_seed_tag_diversity(self) -> None:
        from backend.generation.question_library.generation import beam_select

        out = beam_select(
            [
                {"spec_id": "a-1", "seed_tag": "参数变化", "skill": "参数讨论", "score": 99},
                {"spec_id": "a-2", "seed_tag": "参数变化", "skill": "综合应用", "score": 98},
                {"spec_id": "b-1", "seed_tag": "构造反例", "skill": "构造反例", "score": 97},
            ],
            {"beam_width": 2},
        )

        self.assertEqual(len(out), 2)
        self.assertEqual(len({str(item.get("seed_tag") or "") for item in out}), 2)

    async def test_solve_and_ambiguity_can_use_lightweight_judge_model_override(self) -> None:
        from backend.generation.question_library.generation import check_ambiguity, solve_draft

        seen_models: list[tuple[str, str]] = []

        async def fake_chat_json_with_reasoning(*, model: str, req_id_prefix: str, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            seen_models.append((req_id_prefix, model))
            if req_id_prefix == "ql_solver":
                return json.dumps(
                    {"match": True, "final_answer": "x=1", "issues": [], "summary": "ok"},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_amb":
                return json.dumps(
                    {"ambiguous": False, "issues": [], "summary": "ok"},
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected req_id_prefix: {req_id_prefix}")

        with patch("backend.generation.question_library.judging.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.judging._chat_json_with_reasoning",
            new=AsyncMock(side_effect=fake_chat_json_with_reasoning),
        ), patch.dict("os.environ", {"QUESTION_LIBRARY_JUDGE_MODEL": "openai/test-judge-mini"}, clear=False):
            await solve_draft("题干", {"subject": "高中数学", "proposed_answer": "x=1"})
            await check_ambiguity({"stem": "题干", "answer": "x=1"})

        self.assertEqual(
            seen_models,
            [("ql_solver", "openai/test-judge-mini"), ("ql_amb", "openai/test-judge-mini")],
        )

    async def test_generate_questions_reduces_search_beam_for_small_request_count(self) -> None:
        from backend.generation.question_library.generation import generate_questions

        stage_events: list[dict] = []

        base_specs = [
            {
                "spec_id": f"spec-{idx}",
                "subject": "高中数学",
                "topic": "导数",
                "difficulty": "中等",
                "question_type": "解答题",
                "seed_tag": "参数变化" if idx < 4 else "构造反例",
                "skill": "参数讨论",
                "reasoning": "分类讨论",
                "trap": "边界点漏判",
                "surface": "综合题",
            }
            for idx in range(10)
        ]

        def identity_expand(specs, config):  # type: ignore[no-untyped-def]
            _ = config
            return list(specs)

        def fake_score_spec(spec, source_pack, config):  # type: ignore[no-untyped-def]
            _ = source_pack, config
            out = dict(spec)
            out["score"] = 100 - int(str(spec.get("spec_id") or "spec-0").split("-")[-1])
            return out

        async def fake_realize_drafts(*args, **kwargs):  # type: ignore[no-untyped-def]
            spec = args[0]
            _ = kwargs
            return [
                {
                    "spec_id": str(spec.get("spec_id") or ""),
                    "stem": f"题干-{spec['spec_id']}",
                    "answer": "答案",
                    "analysis": "解析",
                    "skill": str(spec.get("skill") or ""),
                    "reasoning": str(spec.get("reasoning") or ""),
                    "surface": str(spec.get("surface") or ""),
                }
            ]

        with patch("backend.generation.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.generation.seed_root_specs", return_value=base_specs
        ), patch("backend.generation.question_library.generation.expand_skill_layer", side_effect=identity_expand), patch(
            "backend.generation.question_library.generation.expand_reasoning_layer", side_effect=identity_expand
        ), patch("backend.generation.question_library.generation.expand_trap_layer", side_effect=identity_expand), patch(
            "backend.generation.question_library.generation.expand_surface_layer", side_effect=identity_expand
        ), patch("backend.generation.question_library.generation.score_spec", side_effect=fake_score_spec), patch(
            "backend.generation.question_library.generation.realize_drafts",
            new=AsyncMock(side_effect=fake_realize_drafts),
        ), patch(
            "backend.generation.question_library.generation.solve_draft",
            new=AsyncMock(return_value={"match": True, "final_answer": "答案", "issues": [], "summary": "ok"}),
        ), patch(
            "backend.generation.question_library.generation.check_ambiguity",
            new=AsyncMock(return_value={"ambiguous": False, "issues": [], "summary": "ok"}),
        ), patch(
            "backend.generation.question_library.generation.judge_draft",
            new=AsyncMock(return_value={"pass": True, "overall_score": 90, "issues": [], "summary": "ok", "difficulty_estimate": "中等"}),
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数", "study_markdown": "", "skills": ["参数讨论"]},
                count=2,
                difficulty="中等",
                question_type="解答题",
                on_stage_event=stage_events.append,
            )

        self.assertTrue(out)
        spec_event = next(evt for evt in stage_events if str(evt.get("phase") or "") == "spec_search")
        stats = spec_event.get("stats") if isinstance(spec_event.get("stats"), dict) else {}
        self.assertLessEqual(int(stats.get("search_beam_width") or 0), 8)

    async def test_generate_questions_realize_stage_runs_specs_concurrently(self) -> None:
        from backend.generation.question_library.generation import generate_questions

        active_realize = 0
        max_realize = 0
        base_specs = [
            {
                "spec_id": f"spec-{idx}",
                "subject": "高中数学",
                "topic": "导数",
                "difficulty": "困难",
                "question_type": "解答题",
                "seed_tag": f"seed-{idx}",
                "skill": "参数讨论",
                "reasoning": "分类讨论",
                "trap": "边界点漏判",
                "surface": "综合题",
            }
            for idx in range(4)
        ]

        def identity_expand(specs, config):  # type: ignore[no-untyped-def]
            _ = config
            return list(specs)

        def fake_score_spec(spec, source_pack, config):  # type: ignore[no-untyped-def]
            _ = source_pack, config
            return {**spec, "score": 90}

        async def fake_realize_drafts(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal active_realize, max_realize
            spec = args[0]
            _ = kwargs
            active_realize += 1
            max_realize = max(max_realize, active_realize)
            await asyncio.sleep(0.01)
            active_realize -= 1
            return [
                {
                    "spec_id": str(spec.get("spec_id") or ""),
                    "stem": f"题干-{spec['spec_id']}",
                    "answer": "答案",
                    "analysis": "解析",
                    "skill": str(spec.get("skill") or ""),
                    "reasoning": str(spec.get("reasoning") or ""),
                    "surface": str(spec.get("surface") or ""),
                }
            ]

        with patch("backend.generation.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.generation.seed_root_specs", return_value=base_specs
        ), patch("backend.generation.question_library.generation.expand_skill_layer", side_effect=identity_expand), patch(
            "backend.generation.question_library.generation.expand_reasoning_layer", side_effect=identity_expand
        ), patch("backend.generation.question_library.generation.expand_trap_layer", side_effect=identity_expand), patch(
            "backend.generation.question_library.generation.expand_surface_layer", side_effect=identity_expand
        ), patch("backend.generation.question_library.generation.score_spec", side_effect=fake_score_spec), patch(
            "backend.generation.question_library.generation.realize_drafts",
            new=AsyncMock(side_effect=fake_realize_drafts),
        ), patch(
            "backend.generation.question_library.generation.solve_draft",
            new=AsyncMock(return_value={"match": True, "final_answer": "答案", "issues": [], "summary": "ok"}),
        ), patch(
            "backend.generation.question_library.generation.check_ambiguity",
            new=AsyncMock(return_value={"ambiguous": False, "issues": [], "summary": "ok"}),
        ), patch(
            "backend.generation.question_library.generation.judge_draft",
            new=AsyncMock(return_value={"pass": True, "overall_score": 90, "issues": [], "summary": "ok", "difficulty_estimate": "困难"}),
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数", "study_markdown": "", "skills": ["参数讨论"]},
                count=2,
                difficulty="困难",
                question_type="解答题",
                config={"beam_width": 4, "drafts_per_spec": 1},
            )

        self.assertTrue(out)
        self.assertGreater(max_realize, 1)

    async def test_generate_questions_judge_stage_runs_solve_concurrently(self) -> None:
        from backend.generation.question_library.generation import generate_questions

        active_solves = 0
        max_solves = 0
        base_specs = [
            {
                "spec_id": f"spec-{idx}",
                "subject": "高中数学",
                "topic": "导数",
                "difficulty": "困难",
                "question_type": "解答题",
                "seed_tag": f"seed-{idx}",
                "skill": "参数讨论",
                "reasoning": "分类讨论",
                "trap": "边界点漏判",
                "surface": "综合题",
            }
            for idx in range(3)
        ]

        def identity_expand(specs, config):  # type: ignore[no-untyped-def]
            _ = config
            return list(specs)

        def fake_score_spec(spec, source_pack, config):  # type: ignore[no-untyped-def]
            _ = source_pack, config
            return {**spec, "score": 90}

        async def fake_realize_drafts(*args, **kwargs):  # type: ignore[no-untyped-def]
            spec = args[0]
            _ = kwargs
            return [
                {
                    "spec_id": str(spec.get("spec_id") or ""),
                    "stem": f"题干-{spec['spec_id']}",
                    "answer": "答案",
                    "analysis": "解析",
                    "skill": str(spec.get("skill") or ""),
                    "reasoning": str(spec.get("reasoning") or ""),
                    "surface": str(spec.get("surface") or ""),
                }
            ]

        async def fake_solve(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal active_solves, max_solves
            _ = args, kwargs
            active_solves += 1
            max_solves = max(max_solves, active_solves)
            await asyncio.sleep(0.01)
            active_solves -= 1
            return {"match": True, "final_answer": "答案", "issues": [], "summary": "ok"}

        with patch("backend.generation.question_library.generation.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.generation.seed_root_specs", return_value=base_specs
        ), patch("backend.generation.question_library.generation.expand_skill_layer", side_effect=identity_expand), patch(
            "backend.generation.question_library.generation.expand_reasoning_layer", side_effect=identity_expand
        ), patch("backend.generation.question_library.generation.expand_trap_layer", side_effect=identity_expand), patch(
            "backend.generation.question_library.generation.expand_surface_layer", side_effect=identity_expand
        ), patch("backend.generation.question_library.generation.score_spec", side_effect=fake_score_spec), patch(
            "backend.generation.question_library.generation.realize_drafts",
            new=AsyncMock(side_effect=fake_realize_drafts),
        ), patch(
            "backend.generation.question_library.generation.solve_draft",
            new=AsyncMock(side_effect=fake_solve),
        ), patch(
            "backend.generation.question_library.generation.check_ambiguity",
            new=AsyncMock(return_value={"ambiguous": False, "issues": [], "summary": "ok"}),
        ), patch(
            "backend.generation.question_library.generation.judge_draft",
            new=AsyncMock(return_value={"pass": True, "overall_score": 90, "issues": [], "summary": "ok", "difficulty_estimate": "困难"}),
        ):
            out = await generate_questions(
                source_pack={"subject": "高中数学", "topic": "导数", "study_markdown": "", "skills": ["参数讨论"]},
                count=2,
                difficulty="困难",
                question_type="解答题",
                config={"beam_width": 3, "drafts_per_spec": 1, "solver_consensus_n": 2},
            )

        self.assertTrue(out)
        self.assertGreater(max_solves, 1)

    async def test_generate_questions_rejects_difficulty_mismatch_after_judge(self) -> None:
        from backend.generation.question_library.generation import generate_questions

        async def fake_chat_completion_text(*, messages, req_id_prefix: str = "", **kwargs):  # type: ignore[no-untyped-def]
            _ = messages, kwargs
            if req_id_prefix == "qlg":
                return json.dumps(
                    {"questions": [{"stem": "题干-难度不匹配", "answer": "答案", "analysis": "解析"}]},
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_solver":
                return json.dumps({"match": True, "final_answer": "答案", "issues": [], "summary": "ok"}, ensure_ascii=False)
            if req_id_prefix == "ql_amb":
                return json.dumps({"ambiguous": False, "issues": [], "summary": "ok"}, ensure_ascii=False)
            if req_id_prefix == "ql_judge":
                return json.dumps(
                    {
                        "pass": True,
                        "overall_score": 75,
                        "issues": [],
                        "summary": "题目可用但偏简单",
                        "difficulty_estimate": "简单",
                        "novelty_score": 8,
                        "reasoning_depth": 7,
                    },
                    ensure_ascii=False,
                )
            if req_id_prefix == "ql_distill":
                return json.dumps(
                    {"facts": [], "skills": ["分类讨论"], "common_mistakes": [], "forbidden_patterns": []},
                    ensure_ascii=False,
                )
            raise AssertionError(f"unexpected req_id_prefix: {req_id_prefix}")

        with patch("backend.generation.question_library.source_pack.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.draft_realization.is_llm_configured", return_value=True
        ), patch("backend.generation.question_library.judging.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
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

        self.assertEqual(out, [])

    async def test_generate_questions_filters_low_quality_and_keeps_novel(self) -> None:
        from backend.generation.question_library.generation import generate_questions
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

        with patch("backend.generation.question_library.source_pack.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.draft_realization.is_llm_configured", return_value=True
        ), patch("backend.generation.question_library.judging.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
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
        from backend.generation.question_library.generation import generate_questions

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

        with patch("backend.generation.question_library.source_pack.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.draft_realization.is_llm_configured", return_value=True
        ), patch("backend.generation.question_library.judging.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
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
        from backend.generation.question_library.generation import generate_questions

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

        with patch("backend.generation.question_library.source_pack.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.draft_realization.is_llm_configured", return_value=True
        ), patch("backend.generation.question_library.judging.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
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
        from backend.generation.question_library.generation import generate_questions

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

        with patch("backend.generation.question_library.source_pack.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.draft_realization.is_llm_configured", return_value=True
        ), patch("backend.generation.question_library.judging.is_llm_configured", return_value=True), patch(
            "backend.generation.question_library.gen_llm.chat_completion",
            new=AsyncMock(side_effect=RuntimeError("tool_mode_disabled")),
        ), patch(
            "backend.generation.question_library.gen_llm.chat_completion_text", new=AsyncMock(side_effect=fake_chat_completion_text)
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
