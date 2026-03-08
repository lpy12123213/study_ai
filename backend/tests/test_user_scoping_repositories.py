import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories import canvas as canvas_repo
from backend.database.repositories import conversations as conversations_repo
from backend.database.repositories import papers as papers_repo
from backend.database.schema import Base


class TestUserScopingRepositories(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(conversations_repo, "async_session_maker", self.session_maker),
            patch.object(papers_repo, "async_session_maker", self.session_maker),
            patch.object(canvas_repo, "async_session_maker", self.session_maker),
        ]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_conversations_are_scoped_by_user(self) -> None:
        conv_a = await conversations_repo.create_conversation(user_id="user-a", title="A")
        conv_b = await conversations_repo.create_conversation(user_id="user-b", title="B")

        await conversations_repo.add_message(
            user_id="user-a",
            conv_id=conv_a,
            role="user",
            content="hello from a",
        )

        self.assertIsNotNone(await conversations_repo.get_conversation(user_id="user-a", conv_id=conv_a))
        self.assertIsNone(await conversations_repo.get_conversation(user_id="user-b", conv_id=conv_a))

        list_a = await conversations_repo.list_conversations(user_id="user-a")
        list_b = await conversations_repo.list_conversations(user_id="user-b")
        self.assertEqual([item["id"] for item in list_a], [conv_a])
        self.assertEqual([item["id"] for item in list_b], [conv_b])

        messages_a = await conversations_repo.get_messages(user_id="user-a", conv_id=conv_a)
        messages_b = await conversations_repo.get_messages(user_id="user-b", conv_id=conv_a)
        self.assertEqual(len(messages_a), 1)
        self.assertEqual(messages_b, [])

        with self.assertRaisesRegex(ValueError, "conversation_not_found"):
            await conversations_repo.add_message(
                user_id="user-b",
                conv_id=conv_a,
                role="user",
                content="should fail",
            )

    async def test_papers_are_scoped_by_user(self) -> None:
        paper_a = await papers_repo.save_paper(
            user_id="user-a",
            paper_name="Paper A",
            questions=[{"question_id": "qa-1"}],
        )
        paper_b = await papers_repo.save_paper(
            user_id="user-b",
            paper_name="Paper B",
            questions=[{"question_id": "qb-1"}],
        )

        self.assertIsNotNone(await papers_repo.get_paper(user_id="user-a", paper_id=paper_a))
        self.assertIsNone(await papers_repo.get_paper(user_id="user-b", paper_id=paper_a))

        list_a = await papers_repo.list_papers(user_id="user-a")
        list_b = await papers_repo.list_papers(user_id="user-b")
        self.assertEqual([item["paper_id"] for item in list_a], [paper_a])
        self.assertEqual([item["paper_id"] for item in list_b], [paper_b])

        self.assertFalse(await papers_repo.delete_paper(user_id="user-b", paper_id=paper_a))
        self.assertTrue(await papers_repo.delete_paper(user_id="user-a", paper_id=paper_a))
        self.assertIsNone(await papers_repo.get_paper(user_id="user-a", paper_id=paper_a))

    async def test_canvas_boards_are_scoped_by_user(self) -> None:
        board_a = await canvas_repo.create_canvas_board(
            user_id="user-a", title="Board A", subject="math", snapshot="{}"
        )
        board_b = await canvas_repo.create_canvas_board(
            user_id="user-b", title="Board B", subject="physics", snapshot="{}"
        )

        self.assertIsNotNone(await canvas_repo.get_canvas_board(user_id="user-a", board_id=board_a["id"]))
        self.assertIsNone(await canvas_repo.get_canvas_board(user_id="user-b", board_id=board_a["id"]))

        list_a = await canvas_repo.list_canvas_boards(user_id="user-a")
        list_b = await canvas_repo.list_canvas_boards(user_id="user-b")
        self.assertEqual([item["id"] for item in list_a], [board_a["id"]])
        self.assertEqual([item["id"] for item in list_b], [board_b["id"]])

        update_denied = await canvas_repo.update_canvas_board(
            "user-b",
            board_a["id"],
            title="Denied",
        )
        self.assertFalse(update_denied["success"])
        self.assertEqual(update_denied["error"], "board_not_found")
