from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch


class PaperComposeSlotFillTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_review_marks_ai_question_passed_after_judges(self) -> None:
        from backend.generation.paper_compose import auto_review

        question = {
            "question_id": "ai_1",
            "subject": "高中数学",
            "type": "解答题",
            "difficulty": "中等",
            "stem": "求方程 x+1=2 的解。",
            "answer": "x=1",
            "analysis": "移项后求解。",
            "source": "ai_generate_full",
        }

        with patch.object(
            auto_review,
            "solve_draft",
            new=AsyncMock(return_value={"match": True, "issues": [], "summary": "ok"}),
        ) as solve, patch.object(
            auto_review,
            "check_ambiguity",
            new=AsyncMock(return_value={"ambiguous": False, "issues": [], "summary": ""}),
        ), patch.object(
            auto_review,
            "judge_draft",
            new=AsyncMock(return_value={"pass": True, "overall_score": 86, "issues": [], "summary": "good"}),
        ):
            result = await auto_review.review_questions(
                [question],
                subject="高中数学",
                topic="函数",
                judge_pass_score=65,
                run_llm=True,
            )

        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(question["review_status"], "passed")
        self.assertEqual(question["review_score"], 86)
        solve.assert_awaited_once()

    async def test_answer_synthesis_fills_missing_answer_and_analysis(self) -> None:
        from backend.generation.paper_compose import answer_synthesis

        async def fake_regenerate_question_section(**kwargs) -> str:
            if kwargs["section_key"] == "answer":
                return "x=1"
            if kwargs["section_key"] == "analysis":
                return "移项后求解。"
            return ""

        question = {
            "question_id": "q1",
            "subject": "高中数学",
            "type": "解答题",
            "difficulty": "中等",
            "knowledge_point": "函数",
            "stem": "求方程 x+1=2 的解。",
            "answer": "",
            "analysis": "",
        }

        with patch.object(
            answer_synthesis,
            "regenerate_question_section",
            new=fake_regenerate_question_section,
        ):
            result = await answer_synthesis.synthesize_missing_answers(
                [question],
                subject="高中数学",
                topic="函数",
            )

        self.assertEqual(result["updated"], 1)
        self.assertEqual(question["answer"], "x=1")
        self.assertEqual(question["analysis"], "移项后求解。")
        self.assertEqual(question["answer_source"], "ai_synthesis")

    async def test_fetch_local_candidates_merges_question_cache_snapshot(self) -> None:
        from backend.generation.paper_compose import slot_fill

        with patch.object(
            slot_fill,
            "list_question_library_items",
            new=AsyncMock(
                return_value={
                    "items": [
                        {
                            "question_id": "local-1",
                            "subject": "高中数学",
                            "question_type": "选择题",
                            "difficulty": "中等",
                            "knowledge_point": "函数",
                            "stem": "列表里的短题干",
                            "quality_score": 72,
                        }
                    ]
                }
            ),
        ) as list_items, patch.object(
            slot_fill,
            "get_question_cache",
            new=AsyncMock(
                return_value={
                    "local-1": {
                        "question_id": "local-1",
                        "subject": "高中数学",
                        "question_type": "选择题",
                        "difficulty": "中等",
                        "knowledge_point": "函数",
                        "stem": "缓存中的完整题干",
                        "answer": "A",
                        "analysis": "由单调性可知。",
                        "source": "local_question_library",
                    }
                }
            ),
        ):
            candidates = await slot_fill.fetch_local_candidates(
                user_id="user-a",
                subject="高中数学",
                keyword="函数",
                limit=3,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["question_id"], "local-1")
        self.assertEqual(candidates[0]["stem"], "缓存中的完整题干")
        self.assertEqual(candidates[0]["answer"], "A")
        self.assertEqual(candidates[0]["source"], "local_question_library")
        list_items.assert_awaited_once()

    async def test_compose_workflow_backfills_slot_with_ai_when_bank_is_short(self) -> None:
        from backend.generation.paper_compose import workflow

        class EmptyCrawler:
            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                return {"success": True, "questions": []}

        ai_question = {
            "question_id": "ai_backfill_1",
            "subject": "高中数学",
            "type": "解答题",
            "question_type": "解答题",
            "difficulty": "中等",
            "knowledge_point": "函数",
            "stem": "AI 补齐题干",
            "answer": "1",
            "analysis": "直接计算。",
            "source": "ai_generate_full",
        }

        async def fake_save_paper(**_kwargs) -> int:
            return 99

        async def fake_get_paper(**_kwargs) -> dict:
            return {
                "paper_id": 99,
                "paper_name": "测试卷",
                "created_at": "2026-05-31T00:00:00",
                "questions": [
                    {
                        "question_id": "ai_backfill_1",
                        "order": 1,
                        "type": "解答题",
                        "difficulty": "中等",
                        "knowledge_point": "函数",
                        "source_url": "",
                        "stem": "AI 补齐题干",
                    }
                ],
            }

        request = {
            "taskId": "task-1",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "测试卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {"fetchDetails": False, "sourceStrategy": "bank_first", "autoReview": False},
        }

        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=EmptyCrawler())), patch.object(
            workflow,
            "fill_slot_with_ai",
            new=AsyncMock(return_value=[ai_question]),
            create=True,
        ) as ai_fill, patch.object(workflow, "save_paper", new=fake_save_paper), patch.object(
            workflow,
            "get_paper",
            new=fake_get_paper,
        ), patch.object(
            workflow,
            "mark_used_questions",
            new=AsyncMock(return_value=1),
        ), patch.object(
            workflow,
            "upsert_question_cache",
            new=AsyncMock(return_value=1),
        ):
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        self.assertTrue(any(event.get("type") == "result" for event in events))
        self.assertTrue(
            any(
                event.get("type") == "step"
                and isinstance(event.get("step"), dict)
                and event["step"].get("id") == "ai_backfill"
                for event in events
            )
        )
        ai_fill.assert_awaited_once()

    async def test_compose_workflow_ai_first_prefers_ai_before_bank_candidates(self) -> None:
        from backend.generation.paper_compose import workflow

        class BankCrawler:
            def __init__(self) -> None:
                self.search_calls = 0

            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                self.search_calls += 1
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "123456",
                            "subject": "高中数学",
                            "type": "解答题",
                            "question_type": "解答题",
                            "difficulty": "中等",
                            "knowledge_points": ["函数"],
                            "stem": "题库候选题干",
                            "answer": "2",
                            "analysis": "题库解析。",
                            "quality_score": 100,
                            "source": "zujuan",
                        }
                    ],
                }

        crawler = BankCrawler()
        ai_question = {
            "question_id": "ai_first_1",
            "subject": "高中数学",
            "type": "解答题",
            "question_type": "解答题",
            "difficulty": "中等",
            "knowledge_point": "函数",
            "stem": "AI 优先题干",
            "answer": "1",
            "analysis": "AI 解析。",
            "source": "ai_generate_full",
        }
        saved_questions = []

        async def fake_save_paper(**kwargs) -> int:
            saved_questions.extend(kwargs["questions"])
            return 102

        async def fake_get_paper(**_kwargs) -> dict:
            return {
                "paper_id": 102,
                "paper_name": "测试卷",
                "source_mode": "local",
                "created_at": "2026-05-31T00:00:00",
                "questions": [{"question_id": "ai_first_1", "order": 1, "type": "解答题", "stem": "AI 优先题干"}],
            }

        request = {
            "taskId": "task-ai-first",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "测试卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {"fetchDetails": False, "sourceStrategy": "ai_first", "autoReview": False},
        }

        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=crawler)), patch.object(
            workflow,
            "fetch_local_candidates",
            new=AsyncMock(
                return_value=[
                    {
                        "question_id": "local-1",
                        "subject": "高中数学",
                        "type": "解答题",
                        "question_type": "解答题",
                        "difficulty": "中等",
                        "knowledge_points": ["函数"],
                        "stem": "本地题库候选题干",
                        "answer": "3",
                        "analysis": "本地解析。",
                        "quality_score": 100,
                        "source": "local_question_library",
                    }
                ]
            ),
        ) as local_fetch, patch.object(
            workflow,
            "fill_slot_with_ai",
            new=AsyncMock(return_value=[ai_question]),
            create=True,
        ) as ai_fill, patch.object(workflow, "save_paper", new=fake_save_paper), patch.object(
            workflow,
            "get_paper",
            new=fake_get_paper,
        ), patch.object(
            workflow,
            "mark_used_questions",
            new=AsyncMock(return_value=1),
        ), patch.object(
            workflow,
            "upsert_question_cache",
            new=AsyncMock(return_value=1),
        ):
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        self.assertTrue(any(event.get("type") == "result" for event in events))
        self.assertEqual(saved_questions[0]["question_id"], "ai_first_1")
        ai_fill.assert_awaited_once()
        local_fetch.assert_not_awaited()
        self.assertEqual(crawler.search_calls, 0)

    async def test_compose_workflow_respects_string_false_auto_ai_backfill(self) -> None:
        from backend.generation.paper_compose import workflow

        class EmptyCrawler:
            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                return {"success": True, "questions": []}

        request = {
            "taskId": "task-no-backfill",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "测试卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {"fetchDetails": False, "sourceStrategy": "bank_first", "autoAiBackfill": "false"},
        }

        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=EmptyCrawler())), patch.object(
            workflow,
            "fetch_local_candidates",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            workflow,
            "fill_slot_with_ai",
            new=AsyncMock(return_value=[{"question_id": "ai_should_not_run"}]),
            create=True,
        ) as ai_fill:
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        self.assertTrue(any(event.get("type") == "error" and event.get("error") == "no_questions_selected" for event in events))
        ai_fill.assert_not_awaited()

    async def test_compose_workflow_synthesizes_missing_answer_before_save(self) -> None:
        from backend.generation.paper_compose import workflow

        class OneQuestionCrawler:
            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "123456",
                            "subject": "高中数学",
                            "type": "解答题",
                            "question_type": "解答题",
                            "difficulty": "中等",
                            "knowledge_points": ["函数"],
                            "stem": "求方程 x+1=2 的解。",
                            "quality_score": 90,
                            "source": "zujuan",
                        }
                    ],
                }

            async def batch_get_question_details(self, question_ids, **_kwargs) -> dict:
                return {
                    "questions": [
                        {
                            "question_id": question_ids[0],
                            "success": True,
                            "stem": "求方程 x+1=2 的解。",
                            "answer": "",
                            "analysis": "",
                        }
                    ]
                }

        saved_questions = []

        async def fake_save_paper(**kwargs) -> int:
            saved_questions.extend(kwargs["questions"])
            return 100

        async def fake_get_paper(**_kwargs) -> dict:
            return {
                "paper_id": 100,
                "paper_name": "测试卷",
                "source_mode": "zujuan",
                "created_at": "2026-05-31T00:00:00",
                "questions": [
                    {
                        "question_id": "123456",
                        "order": 1,
                        "type": "解答题",
                        "difficulty": "中等",
                        "knowledge_point": "函数",
                        "source_url": "",
                        "stem": "求方程 x+1=2 的解。",
                    }
                ],
            }

        async def fake_synthesize_missing_answers(questions, **_kwargs) -> dict:
            questions[0]["answer"] = "x=1"
            questions[0]["analysis"] = "移项后求解。"
            questions[0]["answer_source"] = "ai_synthesis"
            return {"updated": 1, "skipped": 0, "failed": 0, "items": [{"question_id": "123456"}]}

        request = {
            "taskId": "task-2",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "测试卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {"sourceStrategy": "bank_only", "minQualityScore": 0, "autoReview": False},
        }

        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=OneQuestionCrawler())), patch.object(
            workflow,
            "fetch_local_candidates",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            workflow,
            "get_question_cache",
            new=AsyncMock(return_value={}),
        ), patch.object(
            workflow,
            "save_paper",
            new=fake_save_paper,
        ), patch.object(
            workflow,
            "get_paper",
            new=fake_get_paper,
        ), patch.object(
            workflow,
            "mark_used_questions",
            new=AsyncMock(return_value=1),
        ), patch.object(
            workflow,
            "upsert_question_cache",
            new=AsyncMock(return_value=1),
        ), patch.object(
            workflow,
            "synthesize_missing_answers",
            new=fake_synthesize_missing_answers,
            create=True,
        ):
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        self.assertTrue(any(event.get("type") == "result" for event in events))
        self.assertTrue(
            any(
                event.get("type") == "step"
                and isinstance(event.get("step"), dict)
                and event["step"].get("id") == "answer_synthesis"
                for event in events
            )
        )
        self.assertEqual(saved_questions[0]["answer"], "x=1")
        self.assertEqual(saved_questions[0]["analysis"], "移项后求解。")

    async def test_compose_workflow_runs_auto_review_before_save(self) -> None:
        from backend.generation.paper_compose import workflow

        class OneQuestionCrawler:
            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "ai_1",
                            "subject": "高中数学",
                            "type": "解答题",
                            "question_type": "解答题",
                            "difficulty": "中等",
                            "knowledge_points": ["函数"],
                            "stem": "求方程 x+1=2 的解。",
                            "answer": "x=1",
                            "analysis": "移项后求解。",
                            "quality_score": 90,
                            "source": "ai_generate_full",
                        }
                    ],
                }

            async def batch_get_question_details(self, question_ids, **_kwargs) -> dict:
                return {"questions": [{"question_id": question_ids[0], "success": True}]}

        saved_questions = []

        async def fake_save_paper(**kwargs) -> int:
            saved_questions.extend(kwargs["questions"])
            return 101

        async def fake_get_paper(**_kwargs) -> dict:
            return {
                "paper_id": 101,
                "paper_name": "测试卷",
                "source_mode": "local",
                "created_at": "2026-05-31T00:00:00",
                "questions": [{"question_id": "ai_1", "order": 1, "type": "解答题", "stem": "题干"}],
            }

        async def fake_review_questions(questions, **_kwargs) -> dict:
            questions[0]["review_status"] = "passed"
            questions[0]["review_score"] = 88
            return {"passed": 1, "failed": 0, "replaced": 0, "items": [{"question_id": "ai_1"}]}

        request = {
            "taskId": "task-3",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "测试卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {"sourceStrategy": "bank_only", "fetchDetails": False, "autoReview": True},
        }

        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=OneQuestionCrawler())), patch.object(
            workflow,
            "fetch_local_candidates",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            workflow,
            "get_question_cache",
            new=AsyncMock(return_value={}),
        ), patch.object(
            workflow,
            "save_paper",
            new=fake_save_paper,
        ), patch.object(
            workflow,
            "get_paper",
            new=fake_get_paper,
        ), patch.object(
            workflow,
            "mark_used_questions",
            new=AsyncMock(return_value=1),
        ), patch.object(
            workflow,
            "review_questions",
            new=fake_review_questions,
            create=True,
        ):
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        self.assertTrue(any(event.get("type") == "result" for event in events))
        self.assertTrue(
            any(
                event.get("type") == "step"
                and isinstance(event.get("step"), dict)
                and event["step"].get("id") == "auto_review"
                for event in events
            )
        )
        self.assertEqual(saved_questions[0]["review_status"], "passed")

    async def test_compose_workflow_balance_correction_replaces_difficulty_mismatch(self) -> None:
        from backend.generation.paper_compose import workflow

        class ImbalancedCrawler:
            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "q-easy",
                            "subject": "高中数学",
                            "type": "解答题",
                            "question_type": "解答题",
                            "difficulty": "简单",
                            "knowledge_points": ["函数"],
                            "stem": "高质量但难度偏低的题干",
                            "answer": "1",
                            "analysis": "偏简单。",
                            "quality_score": 100,
                            "source": "zujuan",
                        },
                        {
                            "question_id": "q-medium",
                            "subject": "高中数学",
                            "type": "解答题",
                            "question_type": "解答题",
                            "difficulty": "中等",
                            "knowledge_points": ["函数"],
                            "stem": "符合目标难度的题干",
                            "answer": "2",
                            "analysis": "难度匹配。",
                            "quality_score": 70,
                            "source": "zujuan",
                        },
                    ],
                }

        saved_questions = []

        async def fake_save_paper(**kwargs) -> int:
            saved_questions.extend(kwargs["questions"])
            return 103

        async def fake_get_paper(**_kwargs) -> dict:
            return {
                "paper_id": 103,
                "paper_name": "测试卷",
                "source_mode": "zujuan",
                "created_at": "2026-06-05T00:00:00",
                "questions": [
                    {
                        "question_id": q["question_id"],
                        "order": idx,
                        "type": q["type"],
                        "difficulty": q["difficulty"],
                        "knowledge_point": q["knowledge_point"],
                        "stem": q["stem"],
                    }
                    for idx, q in enumerate(saved_questions, start=1)
                ],
            }

        request = {
            "taskId": "task-balance",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "测试卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {"sourceStrategy": "bank_only", "fetchDetails": False, "autoReview": False, "minQualityScore": 0},
        }

        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=ImbalancedCrawler())), patch.object(
            workflow,
            "fetch_local_candidates",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            workflow,
            "get_question_cache",
            new=AsyncMock(return_value={}),
        ), patch.object(
            workflow,
            "save_paper",
            new=fake_save_paper,
        ), patch.object(
            workflow,
            "get_paper",
            new=fake_get_paper,
        ), patch.object(
            workflow,
            "mark_used_questions",
            new=AsyncMock(return_value=1),
        ):
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        self.assertEqual(saved_questions[0]["question_id"], "q-medium")
        correction_steps = [
            event["step"]
            for event in events
            if event.get("type") == "step"
            and isinstance(event.get("step"), dict)
            and event["step"].get("id") == "paper_balance_correction"
            and event["step"].get("status") == "completed"
        ]
        self.assertEqual(len(correction_steps), 1)
        self.assertEqual(correction_steps[0]["output"]["totalReplaced"], 1)

    async def test_compose_workflow_pending_review_emits_draft_without_saving(self) -> None:
        from backend.generation.paper_compose import workflow

        class OneQuestionCrawler:
            async def get_available_filters(self) -> dict:
                return {"question_types": [{"name": "解答题"}]}

            async def search_by_keyword(self, **_kwargs) -> dict:
                return {
                    "success": True,
                    "questions": [
                        {
                            "question_id": "q-review",
                            "subject": "高中数学",
                            "type": "解答题",
                            "question_type": "解答题",
                            "difficulty": "中等",
                            "knowledge_points": ["函数"],
                            "stem": "待人工审核题干",
                            "answer": "1",
                            "analysis": "解析。",
                            "quality_score": 90,
                            "source": "zujuan",
                        }
                    ],
                }

        request = {
            "taskId": "task-review",
            "subject": "高中数学",
            "topic": "函数",
            "paperName": "待审卷",
            "slots": [{"questionType": "解答题", "count": 1, "difficulty": "medium"}],
            "options": {
                "sourceStrategy": "bank_only",
                "fetchDetails": False,
                "autoReview": False,
                "requireHumanReview": True,
            },
        }

        save_mock = AsyncMock(return_value=104)
        with patch.object(workflow, "get_crawler", new=AsyncMock(return_value=OneQuestionCrawler())), patch.object(
            workflow,
            "fetch_local_candidates",
            new=AsyncMock(return_value=[]),
        ), patch.object(
            workflow,
            "get_question_cache",
            new=AsyncMock(return_value={}),
        ), patch.object(
            workflow,
            "_load_used_question_ids",
            new=AsyncMock(return_value=set()),
        ), patch.object(
            workflow,
            "save_paper",
            new=save_mock,
        ):
            events = [event async for event in workflow.compose_paper_events(request, user_id="user-a")]

        pending = [event for event in events if event.get("type") == "pending_review"]
        self.assertEqual(len(pending), 1)
        draft = pending[0]["composeDraft"]
        self.assertEqual(draft["paperName"], "待审卷")
        self.assertEqual(draft["questions"][0]["question_id"], "q-review")
        save_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
