from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.question import papers as papers_repo
from backend.database.repositories.question import question_cache as cache_repo
from backend.database.schema import Base


class PaperMixedSourcesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(papers_repo, "async_session_maker", self.session_maker),
            patch.object(cache_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_save_paper_allows_hybrid_sources_and_forces_cache_snapshot(self) -> None:
        questions = [
            {
                "question_id": "123456",
                "subject": "高中数学",
                "type": "选择题",
                "difficulty": "中等",
                "knowledge_point": "函数",
                "stem": "组卷网题干",
                "answer": "B",
                "analysis": "代入可得。",
                "source": "zujuan",
            },
            {
                "question_id": "ai_abcdef12",
                "subject": "高中数学",
                "type": "解答题",
                "difficulty": "中等",
                "knowledge_point": "函数",
                "stem": "AI 原创题干",
                "answer": "42",
                "analysis": "构造函数求解。",
                "source": "ai_generate_full",
            },
        ]

        with patch.dict(os.environ, {}, clear=True):
            paper_id = await papers_repo.save_paper(user_id="user-a", paper_name="混合卷", questions=questions)

        paper = await papers_repo.get_paper(user_id="user-a", paper_id=paper_id)
        self.assertIsNotNone(paper)
        self.assertEqual(paper.get("source_mode"), "hybrid")

        cache = await cache_repo.get_question_cache(question_ids=["123456", "ai_abcdef12"])
        self.assertEqual(cache["123456"]["stem"], "组卷网题干")
        self.assertEqual(cache["123456"]["answer"], "B")
        self.assertEqual(cache["ai_abcdef12"]["analysis"], "构造函数求解。")

    async def test_add_questions_to_paper_forces_snapshot_when_append_makes_hybrid(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            paper_id = await papers_repo.save_paper(
                user_id="user-a",
                paper_name="待补齐卷",
                questions=[
                    {
                        "question_id": "123456",
                        "subject": "高中数学",
                        "type": "选择题",
                        "difficulty": "中等",
                        "knowledge_point": "函数",
                        "stem": "组卷网题干",
                        "answer": "B",
                        "analysis": "代入可得。",
                        "source": "zujuan",
                    }
                ],
            )

            appended = await papers_repo.add_questions_to_paper(
                user_id="user-a",
                paper_id=paper_id,
                questions=[
                    {
                        "question_id": "ai_append_1",
                        "subject": "高中数学",
                        "type": "解答题",
                        "difficulty": "中等",
                        "knowledge_point": "函数",
                        "stem": "AI 追加题干",
                        "answer": "42",
                        "analysis": "构造函数求解。",
                        "source": "ai_generate_full",
                    }
                ],
            )

        paper = await papers_repo.get_paper(user_id="user-a", paper_id=paper_id)
        self.assertEqual(appended, 1)
        self.assertIsNotNone(paper)
        self.assertEqual(paper.get("source_mode"), "hybrid")
        self.assertEqual(paper["questions"][1]["stem"], "AI 追加题干")
        self.assertEqual(paper["questions"][1]["answer"], "42")
        self.assertEqual(paper["questions"][1]["analysis"], "构造函数求解。")

        cache = await cache_repo.get_question_cache(question_ids=["ai_append_1"])
        self.assertEqual(cache["ai_append_1"]["stem"], "AI 追加题干")
        self.assertEqual(cache["ai_append_1"]["answer"], "42")
        self.assertEqual(cache["ai_append_1"]["analysis"], "构造函数求解。")


if __name__ == "__main__":
    unittest.main()
