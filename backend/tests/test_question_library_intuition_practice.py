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
        "issues": [] if passed else ["answer_incorrect"],
        "summary": "通过" if passed else "需修复",
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
