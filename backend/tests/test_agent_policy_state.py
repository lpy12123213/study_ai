import json
import unittest

from backend.agent.policy import StudyMaterialsPolicy, StudyMaterialsPolicyConfig
from backend.agent.types import CompressedContext, UserProfile


def _ctx(*, working_memory: dict | None = None) -> CompressedContext:
    return CompressedContext(
        user_profile=UserProfile(user_id="u"),
        system_instructions="",
        current_task="导数",
        working_memory=working_memory or {},
    )


class TestAgentPolicyState(unittest.TestCase):
    def test_policy_state_is_stored_outside_working_memory(self) -> None:
        ctx = _ctx()
        policy = StudyMaterialsPolicy(config=StudyMaterialsPolicyConfig())

        policy.mark_auto_research(ctx, ["导数", "导数", "函数"])
        policy.mark_auto_revise(ctx)

        self.assertNotIn("_study_policy", ctx.working_memory)
        self.assertEqual(ctx.policy_state.auto_research_rounds, 1)
        self.assertEqual(ctx.policy_state.auto_research_done_kps, ["导数", "函数"])
        self.assertEqual(ctx.policy_state.auto_revise_rounds, 1)

    def test_legacy_study_policy_state_is_migrated_once(self) -> None:
        ctx = _ctx(
            working_memory={
                "_study_policy": {
                    "auto_research_rounds": 2,
                    "auto_research_done_kps": ["A", "B", "A"],
                    "auto_revise_rounds": 1,
                }
            }
        )
        policy = StudyMaterialsPolicy(config=StudyMaterialsPolicyConfig())

        policy.mark_auto_research(ctx, ["C"])

        self.assertNotIn("_study_policy", ctx.working_memory)
        self.assertEqual(ctx.policy_state.auto_research_rounds, 3)
        self.assertEqual(ctx.policy_state.auto_research_done_kps, ["A", "B", "C"])
        self.assertEqual(ctx.policy_state.auto_revise_rounds, 1)

    def test_context_json_contains_policy_state(self) -> None:
        ctx = _ctx()
        ctx.policy_state.auto_revise_rounds = 2

        payload = json.loads(ctx.to_json())

        self.assertEqual(payload["policy_state"]["auto_revise_rounds"], 2)


if __name__ == "__main__":
    unittest.main()
