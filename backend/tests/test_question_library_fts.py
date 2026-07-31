import tempfile
import unittest

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.migrations import sync_migrate_db_schema
from backend.database.repositories.system.search import search_fulltext
from backend.database.schema import Base


class QuestionLibraryFtsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/question-library-fts.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _run_migrations(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(sync_migrate_db_schema)

    async def _seed_question(
        self,
        *,
        user_id: str,
        question_id: str,
        stem: str,
        answer: str = "",
        analysis: str = "",
        subject: str = "高中数学",
        knowledge_point: str = "函数",
        hidden: int = 0,
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO question_cache "
                "(question_id, subject, knowledge_point, stem, answer, analysis) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (question_id, subject, knowledge_point, stem, answer, analysis),
            )
            await conn.exec_driver_sql(
                "INSERT INTO question_library (user_id, question_id, subject, hidden) VALUES (?, ?, ?, ?)",
                (user_id, question_id, subject, hidden),
            )

    async def _search_questions(self, user_id: str, query: str) -> list[dict]:
        async with self.session_maker() as session:
            return await search_fulltext(user_id=user_id, query=query, types=["question"], limit=10, session=session)

    async def test_search_returns_visible_question_library_item_by_cache_text(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-visible",
            stem="Solve uniqueparabola42 from the question stem.",
            answer="x = 2",
            analysis="Use the focus chord relation.",
        )
        await self._seed_question(
            user_id="user-b",
            question_id="q-other-user",
            stem="Solve uniqueparabola42 for another user.",
        )

        await self._run_migrations()

        rows = await self._search_questions("user-a", "uniqueparabola42")

        self.assertEqual([row["question_id"] for row in rows], ["q-visible"])
        self.assertEqual(rows[0]["type"], "question")
        self.assertIn("uniqueparabola42", rows[0]["snippet"])
        self.assertIsInstance(rows[0]["score"], float)

    async def test_search_filters_hidden_question_library_items(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-visible",
            stem="Shared hiddenfiltertoken text.",
        )
        await self._seed_question(
            user_id="user-a",
            question_id="q-hidden",
            stem="Shared hiddenfiltertoken text.",
            hidden=1,
        )

        await self._run_migrations()

        rows = await self._search_questions("user-a", "hiddenfiltertoken")

        self.assertEqual([row["question_id"] for row in rows], ["q-visible"])

    async def test_cache_update_refreshes_question_fts_content(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-refresh",
            stem="Refresh test stem.",
            analysis="oldanalysisneedle",
        )
        await self._run_migrations()

        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "UPDATE question_cache SET analysis = ? WHERE question_id = ?",
                ("newanalysisneedle", "q-refresh"),
            )

        new_rows = await self._search_questions("user-a", "newanalysisneedle")
        old_rows = await self._search_questions("user-a", "oldanalysisneedle")

        self.assertEqual([row["question_id"] for row in new_rows], ["q-refresh"])
        self.assertEqual(old_rows, [])

    async def test_zero_fts_matches_does_not_fall_back_to_like(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-substring-only",
            stem="prefixsubstringfallbackneedlepostfix",
        )
        await self._run_migrations()

        rows = await self._search_questions("user-a", "substringfallbackneedle")

        self.assertEqual(rows, [])

    async def test_search_supports_prefix_matching_for_longer_chinese_tokens(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-chinese-prefix",
            stem="函数单调性综合题",
        )
        await self._run_migrations()

        rows = await self._search_questions("user-a", "函数")

        self.assertEqual([row["question_id"] for row in rows], ["q-chinese-prefix"])
        self.assertLess(rows[0]["score"], 1000000.0)

    async def test_migration_rebuilds_legacy_unindexed_search_fields(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-legacy-index",
            stem="综合题",
            knowledge_point="函数单调性",
        )
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE question_library_fts USING fts5("
                "user_id UNINDEXED,"
                "question_id UNINDEXED,"
                "subject UNINDEXED,"
                "knowledge_point UNINDEXED,"
                "hidden UNINDEXED,"
                "content,"
                "tokenize='unicode61 remove_diacritics 2'"
                ")"
            )

        await self._run_migrations()

        async with self.engine.begin() as conn:
            table_sql = (
                await conn.exec_driver_sql(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='question_library_fts'"
                )
            ).scalar_one()
        rows = await self._search_questions("user-a", "函数")

        self.assertNotIn("knowledge_point UNINDEXED", table_sql)
        self.assertEqual([row["question_id"] for row in rows], ["q-legacy-index"])

    async def test_like_fallback_remains_available_when_fts_table_is_missing(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-like-fallback",
            stem="standalonefallbackneedle",
        )

        rows = await self._search_questions("user-a", "standalonefallbackneedle")

        self.assertEqual([row["question_id"] for row in rows], ["q-like-fallback"])

    async def test_question_fts_migration_is_idempotent(self) -> None:
        await self._seed_question(
            user_id="user-a",
            question_id="q-idempotent",
            stem="Idempotent idempotentneedle text.",
        )

        await self._run_migrations()
        await self._run_migrations()

        async with self.engine.begin() as conn:
            table_name = (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='question_library_fts'"
                )
            ).scalar_one_or_none()
            self.assertEqual(table_name, "question_library_fts")
            row_count = (await conn.exec_driver_sql("SELECT count(*) FROM question_library_fts")).scalar_one()

        self.assertEqual(row_count, 1)
