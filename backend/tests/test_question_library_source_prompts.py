from __future__ import annotations

import unittest

from backend.llm.prompts import create_default_prompt_registry


class QuestionLibrarySourcePromptTests(unittest.TestCase):
    def test_source_pack_prompt_uses_registry(self) -> None:
        from backend.generation.question_library import source_pack

        self.assertEqual(
            source_pack._source_pack_system_prompt(),
            create_default_prompt_registry().render("question.source_pack.extract.v1").content,
        )

    def test_reference_analysis_prompt_uses_registry(self) -> None:
        from backend.generation.question_library import reference_analysis

        self.assertEqual(
            reference_analysis._reference_analysis_system_prompt(),
            create_default_prompt_registry().render("question.reference.analyze.v1").content,
        )


if __name__ == "__main__":
    unittest.main()
