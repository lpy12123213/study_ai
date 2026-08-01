import tempfile
import unittest

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.migrations import sync_migrate_db_schema
from backend.database.repositories.content.conversations import update_conversation_title
from backend.database.repositories.system.search import search_fulltext
from backend.database.schema import Base


class SearchFtsRegressionsTests(unittest.IsolatedAsyncioTestCase):
    """F3/F5/F10 regressions for the global search FTS pipeline."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/search-fts-regressions.db"
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

    async def _seed_conversation_messages(
        self, *, user_id: str, conv_id: int, title: str, messages: list[str]
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)",
                (conv_id, user_id, title),
            )
            for idx, content in enumerate(messages, start=1):
                await conn.exec_driver_sql(
                    "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, 'user', ?)",
                    (conv_id * 1000 + idx, conv_id, content),
                )

    async def _seed_question(
        self, *, user_id: str, question_id: str, stem: str, subject: str = "高中数学"
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO question_cache (question_id, subject, stem) VALUES (?, ?, ?)",
                (question_id, subject, stem),
            )
            await conn.exec_driver_sql(
                "INSERT INTO question_library (user_id, question_id, subject) VALUES (?, ?, ?)",
                (user_id, question_id, subject),
            )

    async def _search(self, user_id: str, query: str, types: list[str], limit: int = 50) -> list[dict]:
        async with self.session_maker() as session:
            return await search_fulltext(
                user_id=user_id, query=query, types=types, limit=limit, session=session
            )

    # ---- F3: title refresh ----

    async def test_conversation_rename_makes_new_title_searchable_and_old_zero_hit(self) -> None:
        await self._seed_conversation_messages(
            user_id="user-a", conv_id=1, title="旧标题", messages=["关于数列的一道题", "数列求和"]
        )
        await self._run_migrations()

        before = await self._search("user-a", "旧标题", ["conversation"])
        self.assertEqual([row["conversation_id"] for row in before], [1])

        # App-level rename path (repo sets conversations.title -> DB trigger refreshes FTS).
        async with self.session_maker() as session:
            ok = await update_conversation_title(user_id="user-a", conv_id=1, title="新标题", session=session)
            await session.commit()
        self.assertTrue(ok)

        rows_new = await self._search("user-a", "新标题", ["conversation"])
        self.assertEqual([row["conversation_id"] for row in rows_new], [1])
        # FTS is authoritative: zero matches must not fall back to a LIKE scan.
        self.assertEqual(await self._search("user-a", "旧标题", ["conversation"]), [])

    async def test_raw_conversations_update_fires_db_trigger(self) -> None:
        await self._seed_conversation_messages(
            user_id="user-a", conv_id=1, title="TITLE-OLD", messages=["needle one", "needle two"]
        )
        await self._run_migrations()

        self.assertEqual(len(await self._search("user-a", "TITLE-OLD", ["conversation"])), 1)

        # Bypass the repo: the DB trigger must keep messages_fts.title in sync.
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "UPDATE conversations SET title = ? WHERE id = ?", ("TITLE-NEW", 1)
            )

        self.assertEqual(len(await self._search("user-a", "TITLE-NEW", ["conversation"])), 1)
        self.assertEqual(await self._search("user-a", "TITLE-OLD", ["conversation"]), [])

    async def test_conversations_fts_migration_is_idempotent(self) -> None:
        await self._seed_conversation_messages(user_id="user-a", conv_id=1, title="幂等标题", messages=["内容"])
        await self._run_migrations()
        await self._run_migrations()

        async with self.engine.begin() as conn:
            row_count = (await conn.exec_driver_sql("SELECT count(*) FROM messages_fts")).scalar_one()
            trigger = (
                await conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name='conversations_title_au'"
                )
            ).scalar_one_or_none()
        self.assertEqual(row_count, 1)
        self.assertEqual(trigger, "conversations_title_au")

    # ---- F5: paper LIKE fallback + structured logging ----

    async def test_paper_like_fallback_returns_paper_when_fts_missing(self) -> None:
        async with self.engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO papers (id, user_id, paper_name) VALUES (?, ?, ?)",
                (1, "user-a", "函数专题卷"),
            )
            await conn.exec_driver_sql(
                "INSERT INTO paper_questions (id, user_id, paper_id, question_id, stem, knowledge_point) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (1, "user-a", 1, "q-1", "关于函数单调性的内容", "函数"),
            )
        # No migration: paper_questions_fts is absent, so the FTS query fails and the
        # LIKE fallback must return the paper row (paper_name column, not p.name).
        rows = await self._search("user-a", "函数", ["paper"])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "paper")
        self.assertEqual(rows[0]["paper_id"], 1)
        self.assertEqual(rows[0]["title"], "函数专题卷")
        self.assertEqual(rows[0]["match_count"], 1)

    async def test_try_query_logs_structured_warning_with_entity(self) -> None:
        await self._seed_conversation_messages(user_id="user-a", conv_id=1, title="标题", messages=["内容"])
        # No migration -> messages_fts missing -> FTS query fails and logs entity.

        with self.assertLogs("backend.database.repositories.system.search", level="WARNING") as ctx:
            rows = await self._search("user-a", "内容", ["conversation"])

        # LIKE fallback still returns the matching message.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "conversation")
        self.assertEqual(rows[0]["match_count"], 1)

        warning_records = [r for r in ctx.records if r.getMessage() == "search_fallback_failed"]
        self.assertEqual(len(warning_records), 1)
        self.assertEqual(warning_records[0].entity, "conversation")

    # ---- F10: entity grouping + per-type quota ----

    async def test_conversation_grouping_keeps_best_row_with_match_count(self) -> None:
        await self._seed_conversation_messages(
            user_id="user-a", conv_id=1, title="会话一", messages=[f"sharedneedle {i}" for i in range(6)]
        )
        await self._seed_conversation_messages(
            user_id="user-a", conv_id=2, title="会话二", messages=["sharedneedle only"]
        )
        await self._run_migrations()

        rows = await self._search("user-a", "sharedneedle", ["conversation"], limit=10)

        self.assertEqual(len(rows), 2)
        counts = sorted(int(r["match_count"]) for r in rows)
        self.assertEqual(counts, [1, 6])
        self.assertEqual({r["conversation_id"] for r in rows}, {1, 2})

    async def test_per_type_quota_applies_before_cross_type_sort(self) -> None:
        for conv_id in (1, 2, 3):
            await self._seed_conversation_messages(
                user_id="user-a", conv_id=conv_id, title=f"会话{conv_id}", messages=[f"quotaneedle {conv_id}"]
            )
        await self._seed_question(user_id="user-a", question_id="q-1", stem="quotaneedle question")
        await self._run_migrations()

        rows = await self._search("user-a", "quotaneedle", ["conversation", "question"], limit=2)

        # per_type = ceil(2 / 2) = 1: neither type may crowd out the other.
        self.assertEqual(len(rows), 2)
        conv_rows = [r for r in rows if r["type"] == "conversation"]
        question_rows = [r for r in rows if r["type"] == "question"]
        self.assertEqual(len(conv_rows), 1)
        self.assertEqual(len(question_rows), 1)
        self.assertEqual(conv_rows[0]["match_count"], 1)
        self.assertEqual(question_rows[0]["question_id"], "q-1")
