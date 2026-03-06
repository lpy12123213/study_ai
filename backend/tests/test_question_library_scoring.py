import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories import question_cache as cache_repo
from backend.database.repositories import question_library as lib_repo
from backend.database.schema import Base


class TestQuestionLibraryScoring(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(cache_repo, "async_session_maker", self.session_maker),
            patch.object(lib_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_score_updates_and_hides(self) -> None:
        await cache_repo.upsert_question_cache([{"question_id": "q1", "subject": "高中数学", "stem": "stem 1"}])
        await lib_repo.upsert_question_library_items(user_id="u1", items=[{"question_id": "q1", "subject": "高中数学"}])

        from backend.question_library.scoring import apply_score_and_hide

        await apply_score_and_hide(
            user_id="u1",
            question_id="q1",
            overall_score=60,
            verdict="差题",
            dimensions=[],
            summary="bad",
            threshold=70,
        )

        hidden_list = await lib_repo.list_question_library_items(user_id="u1", subject="高中数学", hidden="1", limit=10)
        self.assertEqual(len(hidden_list["items"]), 1)

