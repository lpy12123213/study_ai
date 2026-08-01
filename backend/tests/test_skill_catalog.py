import unittest

from backend.agent.executor import Executor
from backend.agent.mcp.registry import MCPToolRegistry
from backend.agent.planning.skill_catalog import (
    ALWAYS_ON_DIAGRAM_TOOLS,
    COMPOSE_DOMAIN_SKILLS,
    GATED_DIAGRAM_TOOLS,
    QUESTION_TOOL,
    RESEARCH_EXTRA_TOOLS,
    SKILLS,
    STUDY_DOMAIN_SKILLS,
    find_skill_for_tool,
    skills_for_domain,
    tools_for_skills,
)

ALL_CATALOG_TOOLS = sorted({tool for skill in SKILLS.values() for tool in skill["tools"]})


def _fake_registry(names):
    """Build an MCPToolRegistry with `names` registered as no-op tools."""

    async def _noop(_args, _ctx):
        return {"ok": True}

    reg = MCPToolRegistry()
    for name in names:
        reg.register(name=name, description=f"desc:{name}", execute=_noop)
    return reg


class TestSkillCatalogDrift(unittest.TestCase):
    def test_catalog_covers_registry_exactly(self) -> None:
        """Every registered agent tool belongs to exactly one skill (no drift)."""
        registry_tools = {str(t["name"]) for t in Executor().tool_registry.list_tools()}
        self.assertEqual(set(ALL_CATALOG_TOOLS), registry_tools)

    def test_catalog_partition_is_disjoint_and_counts(self) -> None:
        """Skills are pairwise disjoint and match the 58-tool partition."""
        names = list(SKILLS)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                self.assertEqual(
                    set(SKILLS[a]["tools"]).intersection(SKILLS[b]["tools"]),
                    set(),
                    f"skills overlap: {a} / {b}",
                )
        self.assertEqual(len(ALL_CATALOG_TOOLS), 58)
        self.assertEqual(
            len(ALL_CATALOG_TOOLS),
            sum(len(skill["tools"]) for skill in SKILLS.values()),
        )

    def test_every_skill_has_metadata(self) -> None:
        for skill in SKILLS.values():
            self.assertTrue(str(skill["name"] or "").strip())
            self.assertTrue(str(skill["one_liner"] or "").strip())
            self.assertIn(skill["domain"], {"study", "compose"})
            self.assertEqual(skill["prompt_id"], f"agent.skills.{skill['name']}.v1")

    def test_per_skill_tools_are_registered(self) -> None:
        """Each skill's tools are a subset of the real registry."""
        registry_tools = {str(t["name"]) for t in Executor().tool_registry.list_tools()}
        for skill_name, skill in SKILLS.items():
            with self.subTest(skill=skill_name):
                self.assertTrue(set(skill["tools"]).issubset(registry_tools))


class TestSkillsForDomain(unittest.TestCase):
    def test_study_domain_matrix(self) -> None:
        self.assertEqual(
            skills_for_domain("study"),
            list(STUDY_DOMAIN_SKILLS) + ["diagrams"],
        )
        self.assertEqual(
            skills_for_domain("study", enable_diagrams=False),
            list(STUDY_DOMAIN_SKILLS),
        )

    def test_compose_domain_matrix(self) -> None:
        self.assertEqual(
            skills_for_domain("compose"),
            list(COMPOSE_DOMAIN_SKILLS) + ["diagrams"],
        )
        self.assertEqual(
            skills_for_domain("compose", enable_diagrams=False),
            list(COMPOSE_DOMAIN_SKILLS),
        )

    def test_flags_do_not_change_skill_availability(self) -> None:
        for domain in ("study", "compose"):
            base = skills_for_domain(domain, enable_diagrams=False)
            gated = skills_for_domain(
                domain,
                enable_diagrams=False,
                enable_questions=True,
                enable_extra_tools=False,
            )
            self.assertEqual(base, gated)

    def test_unknown_domain_defaults_to_study(self) -> None:
        self.assertEqual(skills_for_domain(""), list(STUDY_DOMAIN_SKILLS) + ["diagrams"])
        self.assertEqual(skills_for_domain("bogus"), list(STUDY_DOMAIN_SKILLS) + ["diagrams"])


class TestToolsForSkills(unittest.TestCase):
    def test_resolves_active_skills_from_registry(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        tools = tools_for_skills(["planning"], reg)
        # planning tools + legacy always-on diagram tools (injected unconditionally).
        self.assertEqual(
            {t["name"] for t in tools},
            set(SKILLS["planning"]["tools"]) | set(ALWAYS_ON_DIAGRAM_TOOLS),
        )

    def test_always_on_diagram_tools_present_without_diagrams_skill(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        tools = tools_for_skills(["planning"], reg, enable_diagrams=False)
        names = {t["name"] for t in tools}
        self.assertTrue(set(ALWAYS_ON_DIAGRAM_TOOLS).issubset(names))
        self.assertEqual(names.intersection(set(GATED_DIAGRAM_TOOLS)), set())

    def test_diagrams_skill_all_eleven_tools(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        tools = tools_for_skills(["diagrams"], reg, enable_diagrams=True)
        self.assertEqual({t["name"] for t in tools}, set(SKILLS["diagrams"]["tools"]))

    def test_enable_questions_gates_question_tool(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        off = {t["name"] for t in tools_for_skills(["examples"], reg, enable_questions=False)}
        on = {t["name"] for t in tools_for_skills(["examples"], reg, enable_questions=True)}
        self.assertNotIn(QUESTION_TOOL, off)
        self.assertIn(QUESTION_TOOL, on)
        self.assertEqual(off | {QUESTION_TOOL}, on)

    def test_enable_extra_tools_gates_research_extras(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        off = {t["name"] for t in tools_for_skills(["research"], reg, enable_extra_tools=False)}
        on = {t["name"] for t in tools_for_skills(["research"], reg, enable_extra_tools=True)}
        self.assertEqual(off.intersection(set(RESEARCH_EXTRA_TOOLS)), set())
        self.assertEqual(off | set(RESEARCH_EXTRA_TOOLS), on)

    def test_drops_unknown_skill_and_tool_names(self) -> None:
        reg = _fake_registry(["split_knowledge_points"])  # only one registered
        tools = tools_for_skills(["planning", "does-not-exist"], reg)
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"split_knowledge_points"})

    def test_output_shape_matches_list_tools(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        tools = tools_for_skills(list(SKILLS), reg)
        for tool in tools:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("input_schema", tool)

    def test_deduplicates_skills(self) -> None:
        reg = _fake_registry(ALL_CATALOG_TOOLS)
        tools = tools_for_skills(["planning", "planning", "planning"], reg)
        self.assertEqual(len(tools), len(SKILLS["planning"]["tools"]) + len(ALWAYS_ON_DIAGRAM_TOOLS))


class TestFindSkillForTool(unittest.TestCase):
    def test_known_tool_maps_to_skill(self) -> None:
        self.assertEqual(find_skill_for_tool("split_knowledge_points"), "planning")
        self.assertEqual(find_skill_for_tool("compose_sandbox_run"), "compose-sandbox")
        self.assertEqual(find_skill_for_tool("plot_3d"), "diagrams")

    def test_unknown_tool_returns_none(self) -> None:
        self.assertIsNone(find_skill_for_tool("not_a_tool"))
        self.assertIsNone(find_skill_for_tool(""))


if __name__ == "__main__":
    unittest.main()
