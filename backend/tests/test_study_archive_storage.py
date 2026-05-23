from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.agent.tools.generation.exports import ExportToolsMixin
from backend.agent.types import CompressedContext, UserProfile
from backend.generation.study_materials.archive_storage import (
    safe_study_archive_filename,
    warn_if_legacy_backend_study_archives_present,
)


class StudyArchiveStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_markdown_file_defaults_to_local_study_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir).resolve()
            ctx = CompressedContext(
                user_profile=UserProfile(user_id="u-1"),
                system_instructions="",
                current_task="一元二次方程",
                working_memory={"markdown": "# 标题\n"},
            )

            with patch("backend.generation.study_materials.archive_storage._DEFAULT_ARCHIVE_DIR", target):
                result = await ExportToolsMixin()._tool_save_markdown_file({}, ctx)

        self.assertTrue(result["success"])
        self.assertEqual(Path(result["dir"]).resolve(), target)
        self.assertTrue(str(ctx.working_memory.get("archive_path") or "").endswith(".md"))
        self.assertIn("一元二次方程", str(result["filename"]))
        self.assertNotIn("________", str(result["filename"]))

    async def test_safe_filename_falls_back_for_symbol_only_titles(self) -> None:
        filename = safe_study_archive_filename("////::::")

        self.assertTrue(filename.startswith("study-archive-"))
        self.assertTrue(filename.endswith(".md"))

    async def test_legacy_backend_archive_dir_warning_is_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy = Path(tmpdir)
            (legacy / "old.md").write_text("old", encoding="utf-8")
            with (
                patch("backend.generation.study_materials.archive_storage._LEGACY_BACKEND_ARCHIVE_DIR", legacy),
                patch("backend.generation.study_materials.archive_storage._DEFAULT_ARCHIVE_DIR", legacy.parent / "target"),
            ):
                self.assertTrue(warn_if_legacy_backend_study_archives_present())


if __name__ == "__main__":
    unittest.main()
