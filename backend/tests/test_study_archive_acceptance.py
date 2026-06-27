from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.migrations import sync_migrate_db_schema
from backend.database.repositories.content.study_archives import (
    get_study_archive_by_fingerprint,
    upsert_study_archive,
)
from backend.database.schema import Base


class StudyArchiveAcceptanceMigrationTests(unittest.TestCase):
    def test_sync_migration_adds_acceptance_json_to_legacy_archive_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{temp_dir}/archives.db", future=True)
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        "CREATE TABLE study_archives ("
                        "id INTEGER PRIMARY KEY,"
                        "user_id VARCHAR(64) NOT NULL DEFAULT '',"
                        "subject VARCHAR(100) NOT NULL DEFAULT '',"
                        "topic VARCHAR(200) NOT NULL DEFAULT '',"
                        "fingerprint VARCHAR(32) NOT NULL,"
                        "preset VARCHAR(32) NOT NULL DEFAULT '',"
                        "requirements TEXT NOT NULL DEFAULT '',"
                        "markdown TEXT NOT NULL DEFAULT '',"
                        "sections_json TEXT NOT NULL DEFAULT '[]',"
                        "created_at DATETIME"
                        ")"
                    )

                    sync_migrate_db_schema(conn)
                    columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(study_archives)").fetchall()}
            finally:
                engine.dispose()

        self.assertIn("acceptance_json", columns)


class StudyArchiveAcceptanceRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_and_fingerprint_lookup_round_trip_acceptance(self) -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        acceptance = {
            "accepted": True,
            "preset": "quick",
            "draft_hash": "abc",
            "quality_policy_version": 1,
            "review_schema_version": 1,
        }
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with session_factory() as session:
                await upsert_study_archive(
                    user_id="u-1",
                    subject="高中数学",
                    topic="函数单调性",
                    preset="quick",
                    requirements="",
                    markdown="# 函数单调性",
                    sections=[],
                    acceptance=acceptance,
                    session=session,
                )
                await session.commit()

            async with session_factory() as session:
                archive = await get_study_archive_by_fingerprint(
                    user_id="u-1",
                    subject="高中数学",
                    topic="函数单调性",
                    requirements="",
                    session=session,
                )
        finally:
            await engine.dispose()

        self.assertIsInstance(archive, dict)
        self.assertEqual(archive["acceptance"], acceptance)


if __name__ == "__main__":
    unittest.main()
