import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.repositories.question import gaokao as gaokao_repo
from backend.database.repositories.question import question_cache as cache_repo
from backend.database.repositories.question import question_library as lib_repo
from backend.database.schema import Base, QuestionLibraryItem


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
            patch.object(gaokao_repo, "async_session_maker", self.session_maker),
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
        self.assertIn("gaokao_question_sources", names)

    async def test_gaokao_area_is_isolated_and_exposes_structured_source(self) -> None:
        await cache_repo.upsert_question_cache(
            [{"question_id": "general-1", "subject": "高中数学", "stem": "普通练习题"}]
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "general-1", "subject": "高中数学", "origin": "crawled"}],
        )
        result = await gaokao_repo.upsert_gaokao_questions(
            user_id="user-a",
            items=[
                {
                    "question_id": "gaokao-2024-bj-1",
                    "subject": "高中数学",
                    "stem": "设集合 A，求 A 的补集。",
                    "answer": "略",
                    "question_type": "单选题",
                    "origin": "media",
                    "source": {
                        "exam_year": 2024,
                        "region": "北京",
                        "paper_name": "2024年普通高等学校招生全国统一考试（北京卷）数学",
                        "paper_variant": "北京卷",
                        "question_number": "1",
                        "source_url": "https://example.test/2024-beijing-math.pdf",
                        "source_note": "依据正式试卷逐题转录",
                        "verified": True,
                    },
                }
            ],
        )
        self.assertEqual(result, {"upserted": 1, "question_ids": ["gaokao-2024-bj-1"]})

        general = await lib_repo.list_question_library_items(user_id="user-a", area="general", hidden="all")
        gaokao = await lib_repo.list_question_library_items(user_id="user-a", area="gaokao", hidden="all")
        all_items = await lib_repo.list_question_library_items(user_id="user-a", area="all", hidden="all")

        self.assertEqual([item["question_id"] for item in general["items"]], ["general-1"])
        self.assertEqual([item["question_id"] for item in gaokao["items"]], ["gaokao-2024-bj-1"])
        self.assertEqual({item["question_id"] for item in all_items["items"]}, {"general-1", "gaokao-2024-bj-1"})
        item = gaokao["items"][0]
        self.assertEqual(item["library_area"], "gaokao")
        self.assertEqual(item["gaokao_source"]["exam_year"], 2024)
        self.assertEqual(item["gaokao_source"]["region"], "北京")
        self.assertTrue(item["gaokao_source"]["verified"])

        detail = await lib_repo.get_question_library_item(user_id="user-a", question_id="gaokao-2024-bj-1")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["library_area"], "gaokao")
        self.assertEqual(detail["gaokao_source"]["question_number"], "1")

        other_user = await lib_repo.list_question_library_items(user_id="user-b", area="gaokao", hidden="all")
        self.assertEqual(other_user["items"], [])

    async def test_gaokao_filters_use_structured_source_and_subject_aliases(self) -> None:
        await gaokao_repo.upsert_gaokao_questions(
            user_id="user-a",
            items=[
                {
                    "question_id": "gaokao-math-2024-3",
                    "subject": "高中数学",
                    "stem": "三角函数题干",
                    "source": {
                        "exam_year": 2024,
                        "region": "全国",
                        "paper_name": "2024年新课标I卷数学",
                        "paper_variant": "新课标I卷",
                        "question_number": "3",
                        "verified": False,
                    },
                },
                {
                    "question_id": "gaokao-physics-2023-17",
                    "subject": "物理",
                    "stem": "电磁感应题干",
                    "source": {
                        "exam_year": 2023,
                        "region": "全国甲卷",
                        "paper_name": "2023年全国甲卷理综物理",
                        "paper_variant": "全国甲卷",
                        "question_number": "17",
                        "verified": False,
                    },
                },
            ],
        )

        math_rows = await lib_repo.list_question_library_items(
            user_id="user-a",
            area="gaokao",
            subject="数学",
            year="2024",
            region="全国",
            paper_name="新课标I卷",
            question_number="3",
            hidden="all",
        )
        physics_rows = await lib_repo.list_question_library_items(
            user_id="user-a",
            area="gaokao",
            subject="高中物理",
            q="17",
            hidden="all",
        )

        self.assertEqual([item["question_id"] for item in math_rows["items"]], ["gaokao-math-2024-3"])
        self.assertEqual([item["question_id"] for item in physics_rows["items"]], ["gaokao-physics-2023-17"])

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

    async def test_list_filters_by_local_question_metadata(self) -> None:
        await cache_repo.upsert_question_cache(
            [
                {
                    "question_id": "q1",
                    "subject": "高中数学",
                    "stem": "这是一道需要分类讨论考法的函数题。",
                    "question_type": "单项选择题",
                    "difficulty": "简单",
                    "knowledge_point": "函数新文化题",
                    "source": "2024年北京市高三期末真题",
                    "date": "2024/01",
                },
                {
                    "question_id": "q2",
                    "subject": "高中数学",
                    "stem": "这是一道常规计算题。",
                    "question_type": "解答题",
                    "difficulty": "困难",
                    "knowledge_point": "数列典型题",
                    "source": "2023年上海市高一期中模拟",
                    "date": "2023/11",
                },
            ]
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {"question_id": "q1", "subject": "高中数学", "origin": "crawled"},
                {"question_id": "q2", "subject": "高中数学", "origin": "crawled"},
            ],
        )

        rows = await lib_repo.list_question_library_items(
            user_id="user-a",
            subject="高中数学",
            hidden="all",
            exam_scene="期末",
            question_type="单选题",
            difficulty="容易",
            category="新文化题",
            year="2024",
            region="北京",
            grade="高三",
            semester="期末",
            method="分类讨论",
            limit=10,
        )

        self.assertEqual([it["question_id"] for it in rows["items"]], ["q1"])
        self.assertEqual(rows["total"], 1)

    async def test_single_choice_filter_does_not_match_multiple_choice(self) -> None:
        await cache_repo.upsert_question_cache(
            [
                {
                    "question_id": "single",
                    "subject": "高中数学",
                    "stem": "单选题干",
                    "question_type": "单项选择题",
                },
                {
                    "question_id": "multi",
                    "subject": "高中数学",
                    "stem": "多选题干",
                    "question_type": "多项选择题",
                },
            ]
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {"question_id": "single", "subject": "高中数学", "origin": "crawled"},
                {"question_id": "multi", "subject": "高中数学", "origin": "crawled"},
            ],
        )

        rows = await lib_repo.list_question_library_items(
            user_id="user-a",
            subject="高中数学",
            hidden="all",
            question_type="单选题",
            limit=10,
        )

        self.assertEqual([it["question_id"] for it in rows["items"]], ["single"])
        self.assertEqual(rows["total"], 1)

    async def test_list_only_new_filters_recent_library_updates(self) -> None:
        await cache_repo.upsert_question_cache(
            [
                {"question_id": "recent", "subject": "高中数学", "stem": "recent stem"},
                {"question_id": "old", "subject": "高中数学", "stem": "old stem"},
            ]
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {"question_id": "recent", "subject": "高中数学", "origin": "crawled"},
                {"question_id": "old", "subject": "高中数学", "origin": "crawled"},
            ],
        )

        old_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=45)
        async with self.session_maker() as session:
            await session.execute(
                update(QuestionLibraryItem)
                .where(QuestionLibraryItem.user_id == "user-a", QuestionLibraryItem.question_id == "old")
                .values(created_at=old_time, updated_at=old_time)
            )
            await session.commit()

        rows = await lib_repo.list_question_library_items(
            user_id="user-a",
            subject="高中数学",
            hidden="all",
            only_new=True,
            limit=10,
        )

        self.assertEqual([it["question_id"] for it in rows["items"]], ["recent"])
        self.assertEqual(rows["total"], 1)

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
