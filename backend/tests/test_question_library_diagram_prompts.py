from __future__ import annotations

import unittest

from backend.llm.prompts import create_default_prompt_registry


class QuestionLibraryDiagramPromptTests(unittest.TestCase):
    def test_diagram_revise_prompt_uses_registry(self) -> None:
        from backend.generation.question_library import diagram_revise

        self.assertEqual(
            diagram_revise._REVISE_SYSTEM_PROMPT,
            create_default_prompt_registry().render("question.diagram.revise.v1").content,
        )

    def test_diagram_generation_prompts_use_registry(self) -> None:
        from backend.generation.question_library import diagram_integration

        self.assertEqual(
            diagram_integration._diagram_need_system_prompt(),
            create_default_prompt_registry().render("question.diagram.need.v1").content,
        )
        self.assertEqual(
            diagram_integration._diagram_spec_system_prompt(),
            create_default_prompt_registry().render("question.diagram.spec.v1").content,
        )

    def test_diagram_verify_prompt_uses_registry(self) -> None:
        from backend.generation.question_library import verify_diagram

        self.assertEqual(
            verify_diagram._system_prompt(),
            create_default_prompt_registry().render("question.diagram.verify.v1").content,
        )


if __name__ == "__main__":
    unittest.main()
