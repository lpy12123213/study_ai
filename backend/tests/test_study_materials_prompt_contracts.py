"""study-materials 提示词契约与流水线事件契约测试。

- 角色提示词：注册表里每个 study-materials 角色必须声明其输入变量并提及输出契约关键词；
- 阶段提示词：plan/draft/revise 的 build_stage_prompt 必须说明各自的输入与输出字段；
- 文本 lint：截断类信号（独立公式未闭合、空标题、句末截断）；
- 流水线事件：research_retry_required / quality_degraded 的载荷形状。
"""

from __future__ import annotations

import unittest


# 每个 study-materials 角色提示词必须提及的输出契约关键词（角色新增时必须同步补充）。
_ROLE_OUTPUT_KEYWORDS = {
    "planner": ["rationale", "steps"],
    "researcher": ["queries"],
    "writer": ["Markdown"],
    "reviewer": ["passed", "issues", "suggestions"],
    "exporter": ["exported", "formats", "artifacts", "errors", "next_action"],
}


class StudyMaterialsRolePromptContractTests(unittest.TestCase):
    def _spec(self):
        from backend.generation.agentic.study_materials import build_study_materials_agent_spec

        return build_study_materials_agent_spec(
            query="函数单调性",
            subject="高中数学",
            options={"preset": "standard"},
        )

    def test_every_role_prompt_is_registered_with_input_vars_and_output_contract(self) -> None:
        from backend.llm.prompts import create_default_prompt_registry

        registry = create_default_prompt_registry()
        spec = self._spec()

        for role in spec.roles:
            with self.subTest(role=role.name):
                self.assertIn(role.name, _ROLE_OUTPUT_KEYWORDS)
                template = registry.get(role.prompt_id)
                self.assertIsNotNone(template)
                # 输入变量必须在模板中以占位符形式出现，且渲染时真正被替换。
                for key in template.input_keys:
                    self.assertIn("{" + key + "}", template.template)
                sentinel = {key: f"<{key}>" for key in template.input_keys}
                rendered = registry.render(role.prompt_id, **sentinel)
                for key in template.input_keys:
                    self.assertIn(f"<{key}>", rendered.content)
                # 输出契约关键词必须出现在模板正文中。
                for keyword in _ROLE_OUTPUT_KEYWORDS[role.name]:
                    self.assertIn(keyword, template.template)

    def test_role_prompt_ids_are_stable(self) -> None:
        spec = self._spec()

        self.assertEqual(
            {role.name: role.prompt_id for role in spec.roles},
            {
                "planner": "agent.planner.study_materials.v1",
                "researcher": "search.query.decompose.v1",
                "writer": "study.material.writer.v1",
                "reviewer": "study.material.document_review.v1",
                "exporter": "agent.exporter.study_materials.v1",
            },
        )


class StudyMaterialsStagePromptContractTests(unittest.TestCase):
    def _prompt(self, stage: str, payload: dict) -> str:
        from backend.generation.study_materials.codex_stages import build_stage_prompt

        return build_stage_prompt(
            stage=stage,
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            options={"preset": "standard"},
            payload=payload,
        )

    def test_plan_prompt_states_knowledge_point_output_contract(self) -> None:
        prompt = self._prompt("plan", {"requirements": "偏直观"})

        self.assertIn("payload.knowledge_points", prompt)
        self.assertIn("payload.content_dimensions", prompt)
        self.assertIn('"stage":"plan"', prompt)
        self.assertIn('"stage_status":"completed"', prompt)
        self.assertIn('"topic":"函数单调性"', prompt)

    def test_draft_prompt_carries_plan_and_research_inputs(self) -> None:
        prompt = self._prompt(
            "draft",
            {
                "plan": {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]},
                "research": {"kp-1": [{"source_class": "web", "url": "https://example.test/a", "snippet": "定义。"}]},
            },
        )

        self.assertIn("payload.markdown", prompt)
        self.assertIn("payload.coverage_map", prompt)
        self.assertIn("kp-1", prompt)
        self.assertIn("https://example.test/a", prompt)

    def test_revise_prompt_carries_issues_and_resolved_issues_contract(self) -> None:
        prompt = self._prompt(
            "revise",
            {
                "markdown": "# 函数单调性\n\n## 增函数\n\n定义。",
                "issues": ["kp_dimensions_missing:kp-1"],
                "plan": {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]},
                "research": {"kp-1": []},
            },
        )

        self.assertIn("payload.markdown", prompt)
        self.assertIn("payload.coverage_map", prompt)
        self.assertIn("payload.resolved_issues", prompt)
        self.assertIn("kp_dimensions_missing:kp-1", prompt)


class TextLintTruncationTests(unittest.TestCase):
    def test_unclosed_display_math_flag(self) -> None:
        from backend.core.text_lint import lint_text

        self.assertIn("unclosed_display_math", lint_text("公式 $$x^2 未闭合"))
        self.assertNotIn("unclosed_display_math", lint_text("公式 $$x^2$$ 完整。"))

    def test_inline_and_display_math_do_not_confuse_each_other(self) -> None:
        from backend.core.text_lint import lint_text

        flags = lint_text("行内 $x+1$ 与独立 $$x^2$$ 都闭合。")

        self.assertNotIn("unbalanced_inline_math", flags)
        self.assertNotIn("unclosed_display_math", flags)

    def test_heading_with_empty_body_flag(self) -> None:
        from backend.core.text_lint import lint_text

        self.assertIn(
            "heading_with_empty_body",
            lint_text("# 标题\n\n## 1、定义\n\n## 2、性质\n\n性质内容。"),
        )
        self.assertNotIn(
            "heading_with_empty_body",
            lint_text("# 标题\n\n## 1、定义\n\n定义内容。\n\n## 2、性质\n\n性质内容。"),
        )

    def test_eof_mid_sentence_flag(self) -> None:
        from backend.core.text_lint import lint_text

        self.assertIn("eof_mid_sentence", lint_text("这段话没有说完"))
        self.assertNotIn("eof_mid_sentence", lint_text("这段话完整。"))

    def test_eof_inside_open_fence_or_math_is_mid_sentence(self) -> None:
        from backend.core.text_lint import lint_text

        self.assertIn("eof_mid_sentence", lint_text("```python\nprint(1)"))
        self.assertIn("eof_mid_sentence", lint_text("公式：$$x^2"))

    def test_eof_after_closed_fence_or_math_is_not_mid_sentence(self) -> None:
        from backend.core.text_lint import lint_text

        self.assertNotIn("eof_mid_sentence", lint_text("代码：\n\n```python\nprint(1)\n```"))
        self.assertNotIn("eof_mid_sentence", lint_text("公式：\n\n$$x^2$$"))


class _ContractToolExecutor:
    """按脚本返回 research/review 结果的假执行器（记录 research 调用参数）。"""

    def __init__(self, *, research_results: list[dict], reviews: list[dict]) -> None:
        self.research_results = list(research_results)
        self.reviews = list(reviews)
        self.working_memory: dict = {}
        self.step_results: list[dict] = []
        self.research_kwargs: list[dict] = []

    async def research(self, *, plan: dict, event_sink, only_point_ids=None, attempt: int = 0) -> dict:
        self.research_kwargs.append({"only_point_ids": only_point_ids, "attempt": attempt})
        return dict(self.research_results.pop(0))

    async def review(self, *, markdown: str, event_sink) -> dict:
        from backend.generation.study_materials.quality_gate import draft_hash

        review = dict(self.reviews.pop(0))
        review["draft_hash"] = draft_hash(markdown)
        return review


_ENOUGH_RESEARCH = {
    "kp-1": [
        {
            "source_class": "web",
            "url": "https://example.test/a",
            "title": "增函数定义",
            "snippet": "增函数的定义、性质和判定。",
        },
        {
            "source_class": "wikipedia",
            "url": "https://zh.wikipedia.org/wiki/单调函数",
            "title": "单调函数",
            "snippet": "单调函数的百科定义。",
        },
    ]
}

_PASSING_REVIEW = {
    "passed": True,
    "issues": [],
    "suggestions": [],
    "dimensions": {
        "增函数": {
            "present": ["定义/概念", "性质/结论", "条件/适用范围", "反例/边界", "应用/题型"],
            "missing": [],
        }
    },
}

_FAILING_REVIEW = {
    "passed": False,
    "issues": ["缺少适用条件"],
    "suggestions": ["补充条件"],
    "dimensions": {"增函数": {"present": ["定义/概念"], "missing": ["条件/适用范围"]}},
}


def _stage_runner(stages: list[str]):
    async def runner(**kwargs):
        stage = kwargs["stage"]
        stages.append(stage)
        if stage == "plan":
            return {"knowledge_points": [{"id": "kp-1", "title": "增函数", "queries": ["增函数"]}]}
        return {
            "markdown": "# 函数单调性\n\n## 增函数\n\n定义、性质和例题。",
            "coverage_map": {"kp-1": True},
            "resolved_issues": [],
        }

    return runner


class StudyMaterialsWorkflowEventContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_retry_required_event_shape(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        stages: list[str] = []
        events: list[dict] = []
        tool_executor = _ContractToolExecutor(
            research_results=[{"kp-1": []}, dict(_ENOUGH_RESEARCH)],
            reviews=[dict(_PASSING_REVIEW)],
        )

        async def sink(event: dict) -> None:
            events.append(event)

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-retry-contract",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="standard",
            stage_runner=_stage_runner(stages),
            tool_executor=tool_executor,
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        result = await workflow.run()

        retry_events = [event for event in events if event.get("type") == "research_retry_required"]
        self.assertEqual(len(retry_events), 1)
        event = retry_events[0]
        self.assertEqual(event.get("event"), "research_retry_required")
        data = event.get("data") or {}
        self.assertEqual(data.get("point_ids"), ["kp-1"])
        self.assertIsInstance(data.get("attempt"), int)
        self.assertEqual(data["attempt"], 1)
        self.assertIsInstance(data.get("remaining_attempts"), int)
        self.assertEqual(data["remaining_attempts"], 1)
        # 重试调用必须携带 only_point_ids 与 attempt。
        self.assertEqual(
            tool_executor.research_kwargs,
            [
                {"only_point_ids": None, "attempt": 0},
                {"only_point_ids": ["kp-1"], "attempt": 1},
            ],
        )
        # workflow_stage 事件必须带 research_attempts。
        stage_events = [item for item in events if item.get("type") == "workflow_stage"]
        self.assertTrue(stage_events)
        self.assertTrue(all("research_attempts" in (item.get("data") or {}) for item in stage_events))
        self.assertTrue(result["acceptance"]["accepted"])

    async def test_quality_degraded_event_shape_and_result_contract(self) -> None:
        from backend.generation.study_materials.workflow import StudyMaterialsWorkflow

        stages: list[str] = []
        events: list[dict] = []
        tool_executor = _ContractToolExecutor(
            research_results=[dict(_ENOUGH_RESEARCH)],
            reviews=[dict(_FAILING_REVIEW), dict(_FAILING_REVIEW)],
        )

        async def sink(event: dict) -> None:
            events.append(event)

        async def checkpoint(_state: dict, _resume: dict) -> None:
            return None

        workflow = StudyMaterialsWorkflow(
            task_id="task-degraded-contract",
            user_id="u-1",
            topic="函数单调性",
            subject="高中数学",
            preset="quick",
            stage_runner=_stage_runner(stages),
            tool_executor=tool_executor,
            event_sink=sink,
            checkpoint_sink=checkpoint,
        )

        result = await workflow.run()

        degraded_events = [event for event in events if event.get("type") == "quality_degraded"]
        self.assertEqual(len(degraded_events), 1)
        event = degraded_events[0]
        self.assertEqual(event.get("event"), "quality_degraded")
        data = event.get("data") or {}
        self.assertIsInstance(data.get("issues"), list)
        self.assertTrue(data["issues"])
        self.assertTrue(all(isinstance(issue, str) and issue for issue in data["issues"]))
        self.assertIsInstance(data.get("revision_attempts"), int)
        self.assertEqual(data["revision_attempts"], 1)
        # 结果契约：degraded=True、material.passed=False、不落验收记录、状态仍为 completed。
        self.assertTrue(result["degraded"])
        self.assertFalse(result["material"]["passed"])
        self.assertEqual(result["material"]["issues"], data["issues"])
        self.assertEqual(result["acceptance"], {})
        self.assertEqual(workflow.state["acceptance"], {})
        self.assertEqual(workflow.state["stage"], "completed")
        self.assertIn("quality_report", result)


if __name__ == "__main__":
    unittest.main()
