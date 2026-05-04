import unittest

from backend.agent.react.loop import _format_observation
from backend.agent.types import StepResult


class TestAgentReactObservation(unittest.TestCase):
    def test_search_observation_gets_longer_preview(self) -> None:
        result = StepResult(
            step_id="s1",
            tool="web_search_knowledge",
            success=True,
            output={"summary": "x" * 420},
        )

        observation = _format_observation([result], quality="HIGH", reason="")

        self.assertIn("x" * 300, observation)

    def test_study_material_observation_omits_full_body(self) -> None:
        result = StepResult(
            step_id="s1",
            tool="generate_study_material",
            success=True,
            output={
                "sections": [
                    {"knowledge_point": "函数", "explanation_markdown": "SECRET_BODY" * 100},
                ],
                "markdown": "SECRET_MARKDOWN" * 100,
            },
        )

        observation = _format_observation([result], quality="HIGH", reason="")

        self.assertIn('"sections_count": 1', observation)
        self.assertIn("函数", observation)
        self.assertNotIn("SECRET_BODY", observation)
        self.assertNotIn("SECRET_MARKDOWN", observation)


if __name__ == "__main__":
    unittest.main()
