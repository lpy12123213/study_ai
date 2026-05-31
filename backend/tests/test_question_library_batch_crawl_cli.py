from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class TestQuestionLibraryBatchCrawlCli(unittest.TestCase):
    def test_build_keyword_plan_filters_to_requested_domain(self) -> None:
        from backend.cli.question_library_crawl import CrawlImportConfig, build_keyword_plan

        config = CrawlImportConfig(subject="高中物理", domains=("electromagnetism",), target=300)

        plan = build_keyword_plan(config)

        self.assertTrue(plan)
        self.assertEqual({item.domain for item in plan}, {"电磁学"})
        self.assertIn("电场", [item.query for item in plan])

    def test_build_keyword_plan_interleaves_physics_domains(self) -> None:
        from backend.cli.question_library_crawl import CrawlImportConfig, build_keyword_plan

        config = CrawlImportConfig(subject="高中物理", domains=("mechanics", "electromagnetism"), target=1000)

        plan = build_keyword_plan(config)

        self.assertGreaterEqual(len(plan), 4)
        self.assertEqual([item.domain for item in plan[:4]], ["力学", "电磁学", "力学", "电磁学"])

    def test_normalize_crawl_items_filters_easy_and_existing_questions(self) -> None:
        from backend.cli.question_library_crawl import normalize_crawl_items

        seen = {"old"}
        items = [
            {
                "question_id": "old",
                "stem": "这是已经存在的题干。",
                "difficulty": "适中",
                "difficulty_value": "0.5",
            },
            {
                "question_id": "easy",
                "stem": "这是一道过于简单的题干。",
                "difficulty": "容易",
                "difficulty_value": "0.94",
            },
            {
                "question_id": "keep",
                "stem": "这是符合中等到困难条件的物理题干。",
                "type": "单选题",
                "difficulty": "较难",
                "difficulty_value": "0.4",
                "knowledge_points": ["电场"],
            },
        ]

        normalized = normalize_crawl_items(
            items,
            seen_ids=seen,
            subject="高中物理",
            domain="电磁学",
            difficulty_value_max=0.65,
        )

        self.assertEqual([item["question_id"] for item in normalized], ["keep"])
        self.assertEqual(normalized[0]["subject"], "高中物理")
        self.assertEqual(normalized[0]["question_type"], "单选题")
        self.assertIn("电磁学", normalized[0]["knowledge_points"])
        self.assertIn("keep", seen)

    def test_normalize_crawl_items_filters_obviously_incomplete_stems(self) -> None:
        from backend.cli.question_library_crawl import normalize_crawl_items

        seen: set[str] = set()
        items = [
            {
                "question_id": "bad-formula",
                "stem": "选项 A. [公式:294f5ba74cdf695fc9a8a8e52f421328] B. [公式:ac047e91852b91af639feec23a9598b2]",
                "difficulty": "较难",
                "difficulty_value": "0.4",
                "quality_flags": ["formula_unconverted:2"],
            },
            {
                "question_id": "bad-choice",
                "stem": "保留3位有效数字，在什么速度范围内，轮胎不会相对于赛道打滑？",
                "type": "单选题",
                "difficulty": "较难",
                "difficulty_value": "0.4",
                "quality_flags": ["choice_missing_options"],
            },
            {
                "question_id": "bad-incomplete-choice",
                "stem": "如图所示，判断物块运动情况。 A. 向左 B. 向右",
                "type": "单选题",
                "difficulty": "较难",
                "difficulty_value": "0.4",
                "quality_flags": ["choice_options_incomplete:2"],
            },
            {
                "question_id": "good",
                "stem": "如图所示，带电粒子以速度 v 进入匀强磁场，判断其圆周运动半径的变化。",
                "type": "单选题",
                "difficulty": "较难",
                "difficulty_value": "0.4",
                "quality_flags": ["choice_options:4"],
            },
        ]

        normalized = normalize_crawl_items(
            items,
            seen_ids=seen,
            subject="高中物理",
            domain="电磁学",
            difficulty_value_max=0.65,
        )

        self.assertEqual([item["question_id"] for item in normalized], ["good"])
        self.assertEqual(seen, {"good"})

    def test_cli_defaults_to_full_content_parsing_for_import_quality(self) -> None:
        from backend.cli.question_library_crawl import build_parser, config_from_args

        parser = build_parser()

        default_config = config_from_args(parser.parse_args(["--target", "2", "--dry-run"]))
        fast_config = config_from_args(parser.parse_args(["--target", "2", "--dry-run", "--no-parse-content"]))
        replace_config = config_from_args(parser.parse_args(["--target", "2", "--dry-run", "--replace-existing"]))

        self.assertTrue(default_config.parse_content)
        self.assertFalse(fast_config.parse_content)
        self.assertTrue(replace_config.replace_existing)

    def test_replace_existing_reimports_existing_question_ids(self) -> None:
        from backend.cli import question_library_crawl
        from backend.cli.question_library_crawl import CrawlImportConfig

        class FakeCrawler:
            def __init__(self, subject: str) -> None:
                self.subject = subject

            async def initialize(self) -> None:
                return None

            async def close(self) -> None:
                return None

        async def fake_load_existing_question_ids(*, user_id: str, subject: str) -> set[str]:
            return {"old-qid"}

        async def fake_delete_existing(*, user_id: str, subject: str) -> int:
            return 1

        captured_seen: list[set[str]] = []

        async def fake_crawl_query(*args, **kwargs) -> list[dict]:
            seen_ids = kwargs["seen_ids"]
            captured_seen.append(set(seen_ids))
            seen_ids.add("old-qid")
            return [
                {
                    "question_id": "old-qid",
                    "stem": "这是重新爬取后的完整题干，包含足够内容并可覆盖旧缓存。",
                    "difficulty": "较难",
                    "difficulty_value": "0.4",
                    "knowledge_points": ["电场"],
                }
            ]

        with TemporaryDirectory() as tmp:
            config = CrawlImportConfig(
                target=1,
                dry_run=True,
                replace_existing=True,
                custom_keywords=("电场",),
                log_path=Path(tmp) / "crawl.jsonl",
                summary_path=Path(tmp) / "summary.json",
            )
            with patch.object(question_library_crawl, "ZujuanCrawler", FakeCrawler):
                with patch.object(question_library_crawl, "load_existing_question_ids", side_effect=fake_load_existing_question_ids):
                    with patch.object(question_library_crawl, "delete_existing_crawled_library_items", side_effect=fake_delete_existing):
                        with patch.object(question_library_crawl, "_crawl_query", side_effect=fake_crawl_query):
                            result = asyncio.run(question_library_crawl.run_import(config))

        self.assertTrue(result["success"])
        self.assertEqual(captured_seen, [set()])

    def test_prompt_interactive_config_collects_choices_and_confirmation(self) -> None:
        from backend.cli.question_library_crawl import CrawlImportConfig, prompt_interactive_config

        answers = iter(
            [
                "",  # user_id
                "",  # subject
                "50",
                "3",  # electromagnetism
                "0.6",
                "",  # limit per query
                "",  # max pages
                "",  # rounds
                "n",  # parse content
                "n",  # replace existing
                "y",  # dry run
                "y",  # confirm
            ]
        )
        output: list[str] = []

        config = prompt_interactive_config(
            CrawlImportConfig(),
            input_fn=lambda _prompt: next(answers),
            output_fn=output.append,
        )

        self.assertEqual(config.user_id, "1")
        self.assertEqual(config.subject, "高中物理")
        self.assertEqual(config.target, 50)
        self.assertEqual(config.domains, ("电磁学",))
        self.assertEqual(config.difficulty_value_max, 0.6)
        self.assertFalse(config.parse_content)
        self.assertFalse(config.replace_existing)
        self.assertTrue(config.dry_run)
        self.assertTrue(any("交互式批量爬取" in line for line in output))

    def test_main_uses_interactive_prompt_when_no_args(self) -> None:
        from backend.cli import question_library_crawl
        from backend.cli.question_library_crawl import CrawlImportConfig

        captured: list[CrawlImportConfig] = []

        async def fake_run_import(config: CrawlImportConfig) -> dict[str, object]:
            captured.append(config)
            return {"success": True}

        interactive_config = CrawlImportConfig(target=3, dry_run=True)
        with patch.object(question_library_crawl, "prompt_interactive_config", return_value=interactive_config) as prompt:
            with patch.object(question_library_crawl, "run_import", side_effect=fake_run_import):
                question_library_crawl.main([])

        prompt.assert_called_once()
        self.assertEqual(captured, [interactive_config])

    def test_main_keeps_non_interactive_mode_when_args_are_given(self) -> None:
        from backend.cli import question_library_crawl
        from backend.cli.question_library_crawl import CrawlImportConfig

        captured: list[CrawlImportConfig] = []

        async def fake_run_import(config: CrawlImportConfig) -> dict[str, object]:
            captured.append(config)
            return {"success": True}

        with patch.object(question_library_crawl, "prompt_interactive_config") as prompt:
            with patch.object(question_library_crawl, "run_import", side_effect=fake_run_import):
                question_library_crawl.main(["--target", "2", "--dry-run"])

        prompt.assert_not_called()
        self.assertEqual(captured[0].target, 2)
        self.assertTrue(captured[0].dry_run)


if __name__ == "__main__":
    unittest.main()
