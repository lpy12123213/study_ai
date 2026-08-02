"""study.author.* 蓝图/主干/填充/核查提示词与 figure.spec.v1 配图代码提示词的注册与输出契约测试。

- blueprint/audit/figure.spec：JSON 输出契约（禁 Markdown/代码块），且蓝图提示词覆盖叙事、术语、配图计划等关键要求；
- backbone/fill：Markdown 教育写作契约（原创改写、来源 grounding、禁 URL），占位符与例题/自测标签约定。
"""

from __future__ import annotations

import unittest

from backend.generation.agentic.prompt_contracts import (
    JsonOutputContract,
    MarkdownOutputContract,
)
from backend.llm.prompts import create_default_prompt_registry


class AuthorPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = create_default_prompt_registry()

    def test_blueprint_prompt_exists_and_is_json_contract(self):
        p = self.reg.render("study.author.blueprint.v1")
        self.assertEqual(JsonOutputContract().validate_prompt_text(p.content), [])
        for kw in ["叙事", "小节", "术语", "配图计划", "易错点", "置信"]:
            self.assertIn(kw, p.content)

    def test_blueprint_prompt_constrains_figure_kind_and_difficulty_vocabularies(self):
        # 真实运行中模型自造 kind（diagram/flow-chart）并用数字难度 → 提示词必须给死词表。
        p = self.reg.render("study.author.blueprint.v1")
        for kw in ["mermaid", "tikz", "迁移"]:
            self.assertIn(kw, p.content)

    def test_fill_prompt_forbids_urls_and_requires_grounded_misconceptions(self):
        p = self.reg.render("study.author.fill.v1")
        self.assertEqual(
            MarkdownOutputContract(educational_writing=True).validate_prompt_text(p.content),
            [],
        )
        self.assertIn("出处", p.content)
        self.assertIn("[EXn]", p.content)

    def test_backbone_prompt_defines_placeholders(self):
        p = self.reg.render("study.author.backbone.v1")
        self.assertIn("[[FILL:", p.content)
        self.assertIn("[[FIG:", p.content)

    def test_audit_prompt_is_json_contract(self):
        p = self.reg.render("study.author.audit.v1")
        self.assertEqual(JsonOutputContract().validate_prompt_text(p.content), [])

    def test_figure_spec_prompt_is_json_contract(self):
        p = self.reg.render("figure.spec.v1")
        self.assertEqual(JsonOutputContract().validate_prompt_text(p.content), [])
        for kw in ["intent", "kind", "content_spec", "caption", "code", "mermaid", "tikz"]:
            self.assertIn(kw, p.content)


if __name__ == "__main__":
    unittest.main()
