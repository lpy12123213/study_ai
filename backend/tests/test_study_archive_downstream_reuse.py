from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.content.study_archives import upsert_study_archive
from backend.database.schema import Base
from backend.generation.study_materials.quality_gate import build_acceptance_record, draft_hash


def _current_acceptance(markdown: str, *, preset: str = "standard") -> dict:
    return build_acceptance_record(
        report={"passed": True, "draft_hash": draft_hash(markdown), "failed_checks": []},
        preset=preset,
    )


class StudyArchiveReusableRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reusable_lookups_skip_newer_archives_without_current_acceptance(self) -> None:
        from backend.database.repositories.content.study_archives import (
            get_latest_reusable_study_archive,
            get_latest_reusable_study_archive_for_subject,
            get_reusable_study_archive,
        )

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        accepted_markdown = "# 已验收的函数资料"
        stale_markdown = "# 后写入但未验收的函数资料"
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with session_factory() as session:
                accepted = await upsert_study_archive(
                    user_id="u-1",
                    subject="高中数学",
                    topic="函数",
                    preset="standard",
                    requirements="",
                    markdown=accepted_markdown,
                    sections=[],
                    acceptance=_current_acceptance(accepted_markdown),
                    session=session,
                )
                stale = await upsert_study_archive(
                    user_id="u-1",
                    subject="高中数学",
                    topic="函数",
                    preset="standard",
                    requirements="",
                    markdown=stale_markdown,
                    sections=[],
                    acceptance={
                        **_current_acceptance(stale_markdown),
                        "draft_hash": draft_hash("# 旧草稿"),
                    },
                    session=session,
                )
                await session.commit()

            async with session_factory() as session:
                exact = await get_latest_reusable_study_archive(
                    user_id="u-1",
                    subject="高中数学",
                    topic="函数",
                    session=session,
                )
                by_subject = await get_latest_reusable_study_archive_for_subject(
                    user_id="u-1",
                    subject="高中数学",
                    session=session,
                )
                stale_by_id = await get_reusable_study_archive(
                    user_id="u-1",
                    archive_id=stale["id"],
                    session=session,
                )
        finally:
            await engine.dispose()

        self.assertEqual(exact["id"], accepted["id"])
        self.assertEqual(by_subject["id"], accepted["id"])
        self.assertIsNone(stale_by_id)


class StudyArchiveDownstreamReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_library_falls_back_to_latest_reusable_subject_archive(self) -> None:
        from backend.generation.question_library import preview_store, runner

        captured_markdown: list[str] = []

        async def fake_source_pack(markdown, *_args, **_kwargs):
            captured_markdown.append(markdown)
            return {
                "subject": "高中数学",
                "topic": "导数任务",
                "study_markdown": markdown,
                "facts": [],
                "skills": [],
                "common_mistakes": [],
                "forbidden_patterns": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            previews_dir = Path(temp_dir) / "previews"
            sessions_dir = Path(temp_dir) / "sessions"
            with (
                patch.dict("os.environ", {"AGENT_RUNTIME": "legacy"}, clear=False),
                patch.object(preview_store, "_PREVIEWS_DIR", previews_dir),
                patch.object(preview_store, "_SESSIONS_DIR", sessions_dir),
                patch.object(runner, "is_llm_configured", return_value=True),
                patch.object(runner, "get_latest_reusable_study_archive", new=AsyncMock(return_value=None)) as exact,
                patch.object(
                    runner,
                    "get_latest_reusable_study_archive_for_subject",
                    new=AsyncMock(return_value={"markdown": "# 已验收 subject archive"}),
                ) as by_subject,
                patch.object(runner, "build_source_pack", new=AsyncMock(side_effect=fake_source_pack)),
                patch.object(
                    runner,
                    "generate_questions",
                    new=AsyncMock(return_value=[{"stem": "题干", "answer": "答案", "analysis": "解析"}]),
                ),
                patch.object(runner.task_runtime._store, "upsert_task", new=AsyncMock(return_value={})),
                patch.object(runner.task_runtime._store, "append_task_events", new=AsyncMock(return_value=1)),
                patch.object(runner.task_runtime._store, "update_task_status", new=AsyncMock(return_value=True)),
                patch(
                    "backend.generation.question_library.session_service.db_list_task_events",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                task = await runner.create_generate_task(
                    user_id="u-1",
                    request={
                        "subject": "高中数学",
                        "topic": "导数任务",
                        "count": 1,
                        "task_id": "ql-reusable-archive",
                        "use_study_archive": True,
                    },
                )
                await task.runner

        exact.assert_awaited_once()
        by_subject.assert_awaited_once()
        self.assertEqual(captured_markdown, ["# 已验收 subject archive"])

    async def test_paper_compose_passes_only_reusable_archive_markdown_to_slot_fill(self) -> None:
        from backend.generation.paper_compose import full_paper_workflow

        source_packs: list[dict] = []

        async def fake_fill_slot(*, source_pack, **_kwargs):
            source_packs.append(source_pack)
            return [{"question_id": "q-1", "stem": "题干", "answer": "答案", "analysis": "解析"}]

        with (
            patch.dict("os.environ", {"AGENT_RUNTIME": "legacy", "PAPER_COMPOSE_AGENTIC_FULL": "0"}, clear=False),
            patch.object(full_paper_workflow, "is_codex_runtime_agent_runtime", return_value=False),
            patch.object(
                full_paper_workflow,
                "get_latest_reusable_study_archive",
                new=AsyncMock(return_value={"markdown": "# 已验收组卷资料"}),
            ) as archive_lookup,
            patch.object(
                full_paper_workflow,
                "plan_exam_structure",
                new=AsyncMock(return_value={"slots": [{"question_type": "解答题", "count": 1}]}),
            ),
            patch.object(full_paper_workflow, "fill_slot_with_ai", new=AsyncMock(side_effect=fake_fill_slot)),
            patch.object(full_paper_workflow, "upsert_question_cache", new=AsyncMock()),
            patch.object(full_paper_workflow, "save_paper", new=AsyncMock(return_value=7)),
        ):
            events = [
                event
                async for event in full_paper_workflow.generate_full_paper_events(
                    {"subject": "高中数学", "topic": "函数", "useStudyArchive": True},
                    user_id="u-1",
                )
            ]

        archive_lookup.assert_awaited_once()
        self.assertEqual(source_packs[0]["study_markdown"], "# 已验收组卷资料")
        self.assertEqual(events[-1]["type"], "result")

    async def test_knowledge_video_does_not_hydrate_from_non_reusable_archive(self) -> None:
        from backend.generation.knowledge_video import service

        request = service.normalize_request({"topic": "导数", "source_archive_id": 42})
        with patch.object(
            service,
            "get_reusable_study_archive",
            new=AsyncMock(return_value=None),
        ) as archive_lookup:
            hydrated = await service._hydrate_source_markdown(request, user_id="u-1")

        archive_lookup.assert_awaited_once_with(user_id="u-1", archive_id=42)
        self.assertEqual(hydrated.source_markdown, "")
        self.assertEqual(hydrated.subject, "")


if __name__ == "__main__":
    unittest.main()
