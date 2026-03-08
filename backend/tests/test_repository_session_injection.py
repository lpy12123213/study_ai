from __future__ import annotations

import tempfile
import unittest

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories import conversations as conversations_repo
from backend.database.schema import Base


class TestRepositorySessionInjection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_injected_session_rolls_back_without_residue(self) -> None:
        async with self.session_maker() as session:
            tx = await session.begin()
            try:
                conv_id = await conversations_repo.create_conversation(
                    user_id="user-a",
                    title="Hello",
                    session=session,
                )
                conversations = await conversations_repo.list_conversations(user_id="user-a", session=session)
                self.assertEqual([c["id"] for c in conversations], [conv_id])

                ok = await conversations_repo.delete_conversation(user_id="user-a", conv_id=conv_id, session=session)
                self.assertTrue(ok)
                conversations = await conversations_repo.list_conversations(user_id="user-a", session=session)
                self.assertEqual(conversations, [])
            finally:
                await tx.rollback()

        async with self.session_maker() as session2:
            conversations2 = await conversations_repo.list_conversations(user_id="user-a", session=session2)
            self.assertEqual(conversations2, [])
