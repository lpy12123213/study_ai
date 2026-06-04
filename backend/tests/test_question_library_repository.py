import json
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.question import question_cache as cache_repo
from backend.database.repositories.question import question_library as lib_repo
from backend.database.schema import Base


class TestQuestionLibraryRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(lib_repo, "async_session_maker", self.session_maker),
            patch.object(cache_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_schema_includes_question_library_table(self) -> None:
        async with self.engine.begin() as conn:
            rows = (await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        names = {r[0] for r in rows}
        self.assertIn("question_library", names)

    async def test_upsert_and_list_scoped_by_user(self) -> None:
        await cache_repo.upsert_question_cache(
            [
                {"question_id": "q1", "subject": "高中数学", "stem": "stem 1"},
                {"question_id": "q2", "subject": "高中数学", "stem": "stem 2"},
            ]
        )

        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {"question_id": "q1", "subject": "高中数学", "origin": "crawled"},
                {"question_id": "q2", "subject": "高中数学", "origin": "ai"},
            ],
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-b",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )

        list_a = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="0", limit=10)
        list_b = await lib_repo.list_question_library_items(user_id="user-b", subject="高中数学", hidden="0", limit=10)

        self.assertEqual({it["question_id"] for it in list_a["items"]}, {"q1", "q2"})
        self.assertEqual({it["question_id"] for it in list_b["items"]}, {"q1"})

        q1 = next(it for it in list_a["items"] if it["question_id"] == "q1")
        self.assertEqual(q1.get("stem"), "stem 1")

    async def test_hide_unhide(self) -> None:
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )
        ok_hide = await lib_repo.set_hidden(user_id="user-a", question_id="q1", hidden=True)
        self.assertTrue(ok_hide)

        visible = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="0", limit=10)
        self.assertEqual(len(visible["items"]), 0)

        hidden_list = await lib_repo.list_question_library_items(
            user_id="user-a", subject="高中数学", hidden="1", limit=10
        )
        self.assertEqual(len(hidden_list["items"]), 1)

        ok_unhide = await lib_repo.set_hidden(user_id="user-a", question_id="q1", hidden=False)
        self.assertTrue(ok_unhide)

    async def test_partial_update_does_not_wipe_fields(self) -> None:
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "q1", "ai_score": 80, "ai_verdict": "好题"}],
        )
        rows = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="all", limit=10)
        self.assertEqual(len(rows["items"]), 1)
        it = rows["items"][0]
        self.assertEqual(it.get("subject"), "高中数学")
        self.assertEqual(it.get("origin"), "crawled")
        self.assertEqual(it.get("ai_score"), 80)

    async def test_list_and_detail_expose_thinking_depth_from_dimensions(self) -> None:
        await cache_repo.upsert_question_cache([{"question_id": "q1", "subject": "高中数学", "stem": "stem 1"}])
        dims = [
            {
                "name": "思维深度",
                "score": 8,
                "comment": "辅助构造较少见",
                "method_family": "辅助圆构造",
                "method_rarity": "rare",
                "similar_method_count": 3,
            }
        ]
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {
                    "question_id": "q1",
                    "subject": "高中数学",
                    "ai_dimensions_json": json.dumps(dims, ensure_ascii=False),
                }
            ],
        )

        rows = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="all", limit=10)
        self.assertEqual(rows["items"][0]["thinking_depth_score"], 8)
        self.assertEqual(rows["items"][0]["thinking_method_family"], "辅助圆构造")
        self.assertEqual(rows["items"][0]["thinking_method_rarity"], "rare")

        detail = await lib_repo.get_question_library_item(user_id="user-a", question_id="q1")
        self.assertIsNotNone(detail)
        self.assertEqual(detail.get("thinking_depth_score"), 8)

    async def test_method_stats_come_from_existing_thinking_depth_dimensions(self) -> None:
        dims = [
            {
                "name": "思维深度",
                "score": 7,
                "method_family": "辅助圆构造",
                "method_rarity": "uncommon",
                "similar_method_count": 2,
            }
        ]
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {
                    "question_id": "q1",
                    "subject": "高中数学",
                    "origin": "crawled",
                    "ai_dimensions_json": json.dumps(dims, ensure_ascii=False),
                },
                {
                    "question_id": "q2",
                    "subject": "高中数学",
                    "origin": "crawled",
                    "ai_dimensions_json": json.dumps(dims, ensure_ascii=False),
                },
            ],
        )

        stats = await lib_repo.list_thinking_method_stats(user_id="user-a", subject="高中数学")
        self.assertEqual(stats[0]["method_family"], "辅助圆构造")
        self.assertEqual(stats[0]["count"], 2)

    async def test_bulk_delete_scoped_by_user(self) -> None:
        await cache_repo.upsert_question_cache(
            [
                {"question_id": "q1", "subject": "高中数学", "stem": "stem 1"},
                {"question_id": "q2", "subject": "高中数学", "stem": "stem 2"},
            ]
        )

        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {"question_id": "q1", "subject": "高中数学", "origin": "crawled"},
                {"question_id": "q2", "subject": "高中数学", "origin": "crawled"},
            ],
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-b",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )

        deleted = await lib_repo.bulk_delete_question_library_items(user_id="user-a", question_ids=["q1", "q2"])  # type: ignore[attr-defined]
        self.assertEqual(deleted, 2)

        list_a = await lib_repo.list_question_library_items(
            user_id="user-a", subject="高中数学", hidden="all", limit=10
        )
        list_b = await lib_repo.list_question_library_items(
            user_id="user-b", subject="高中数学", hidden="all", limit=10
        )

        self.assertEqual(len(list_a["items"]), 0)
        self.assertEqual({it["question_id"] for it in list_b["items"]}, {"q1"})
