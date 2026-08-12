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

    def test_blueprint_prompt_carries_controlled_extension_contract(self):
        from backend.generation.study_materials.author.pipeline import _FALLBACK_BLUEPRINT_PROMPT

        for prompt in (self.reg.render("study.author.blueprint.v1").content, _FALLBACK_BLUEPRINT_PROMPT):
            self.assertIn("[拓展:主题全名]", prompt)
            self.assertIn("[高中连接]", prompt)

    def test_blueprint_prompt_assigns_every_explicit_task_obligation(self):
        from backend.generation.study_materials.author.pipeline import _FALLBACK_BLUEPRINT_PROMPT

        for prompt in (self.reg.render("study.author.blueprint.v1").content, _FALLBACK_BLUEPRINT_PROMPT):
            self.assertIn("逐项分配", prompt)
            self.assertIn("时间顺序", prompt)
            self.assertIn("比较双方", prompt)

    def test_blueprint_prompt_proactively_covers_contrasts_and_distinct_misconceptions(self):
        from backend.generation.study_materials.author.pipeline import _FALLBACK_BLUEPRINT_PROMPT

        for prompt in (self.reg.render("study.author.blueprint.v1").content, _FALLBACK_BLUEPRINT_PROMPT):
            self.assertIn("至少4组", prompt)
            self.assertIn("易混概念辨析", prompt)
            self.assertIn("至少4个互不重复", prompt)

    def test_fill_prompt_forbids_urls_and_requires_grounded_misconceptions(self):
        p = self.reg.render("study.author.fill.v1")
        self.assertEqual(
            MarkdownOutputContract(educational_writing=True).validate_prompt_text(p.content),
            [],
        )
        self.assertIn("出处", p.content)
        self.assertIn("[EXn]", p.content)
        self.assertIn("80%~130%", p.content)

    def test_learning_repair_prompt_defines_whole_document_contract(self):
        p = self.reg.render("study.author.learning_repair.v1")
        for keyword in ["学习目标", "前置知识", "带完整步骤", "[基础]", "评分点"]:
            self.assertIn(keyword, p.content)

    def test_backbone_prompt_defines_placeholders(self):
        p = self.reg.render("study.author.backbone.v1")
        self.assertIn("[[FILL:", p.content)
        self.assertIn("[[FIG:", p.content)

    def test_backbone_prompt_defines_skeleton_contract(self):
        # 真实运行缺陷：骨架缺使用方式/锚点目录小节，且模型自加「正文占位」空标题。
        p = self.reg.render("study.author.backbone.v1")
        for kw in ["使用方式", "知识点目录", "锚点", "单独占一行"]:
            self.assertIn(kw, p.content)

    def test_blueprint_prompt_requires_kp_titled_sections(self):
        # benchmark 按小节标题匹配知识点：蓝图必须要求 title 含知识点名称关键词。
        p = self.reg.render("study.author.blueprint.v1")
        self.assertIn("知识点", p.content)

    def test_blueprint_prompt_requires_one_section_per_knowledge_point(self):
        # benchmark 真实缺陷：LLM 把「定义」「特征多项式与求法」两个知识点合并成一节
        # 「定义与求法」，标题无「特征多项式」关键词 → kp 小节匹配失败（4/6）。
        # 蓝图必须强制 1:1 映射：每个输入知识点恰好对应一个 section（不得合并/拆分）。
        p = self.reg.render("study.author.blueprint.v1")
        self.assertIn("恰好对应一个", p.content)
        self.assertIn("不得合并", p.content)

    def test_fallback_blueprint_prompt_keeps_kp_mapping_wording_in_sync(self):
        # pipeline 内置降级 prompt 的措辞关键词必须与注册版本保持一致。
        from backend.generation.study_materials.author.pipeline import _FALLBACK_BLUEPRINT_PROMPT

        self.assertIn("恰好对应一个", _FALLBACK_BLUEPRINT_PROMPT)
        self.assertIn("不得合并", _FALLBACK_BLUEPRINT_PROMPT)

    def test_blueprint_prompt_constrains_section_id_charset(self):
        # 真实缺陷：模型产出大写/点号/下划线混合 id（S0.FrontMatter、s0_frontmatter），
        # 与汇编器占位符字符集错位 → 提示词必须给死 id 字符集与示例。
        p = self.reg.render("study.author.blueprint.v1")
        self.assertIn("小写字母", p.content)
        self.assertIn("下划线", p.content)
        self.assertIn("s1_definition", p.content)

    def test_fill_prompt_defines_inline_citation_contract(self):
        # C2 内联引用：关键事实句末 [^n] 标注，编号只能来自给定来源清单，禁裸 URL。
        p = self.reg.render("study.author.fill.v1")
        self.assertIn("[^n]", p.content)
        self.assertIn("来源清单", p.content)
        self.assertIn("裸 URL", p.content)

    def test_audit_prompt_is_json_contract(self):
        p = self.reg.render("study.author.audit.v1")
        self.assertEqual(JsonOutputContract().validate_prompt_text(p.content), [])

    def test_split_prompt_exists_and_is_json_contract(self):
        # 知识点拆分提示词：注册为 JSON 契约，覆盖数量上限/学习顺序/独立可教学/不重叠。
        p = self.reg.render("study.author.split.v1")
        self.assertEqual(JsonOutputContract().validate_prompt_text(p.content), [])
        for kw in ["knowledge_points", "max_points", "学习顺序", "独立可教学", "不重叠"]:
            self.assertIn(kw, p.content)

    def test_fallback_split_prompt_keeps_keywords_in_sync(self):
        # pipeline 内置降级 split prompt 的措辞关键词必须与注册版本保持一致。
        from backend.generation.study_materials.author.pipeline import _FALLBACK_SPLIT_PROMPT

        for kw in ["knowledge_points", "min_points", "max_points", "学习顺序", "不重叠", "受控拓展"]:
            self.assertIn(kw, _FALLBACK_SPLIT_PROMPT)

    def test_registered_split_prompt_carries_minimum_and_extension_contract(self):
        p = self.reg.render("study.author.split.v1")
        for kw in ["min_points", "全局输出要求", "受控拓展"]:
            self.assertIn(kw, p.content)

    def test_fill_prompts_require_global_and_section_contracts(self):
        from backend.generation.study_materials.author.fill import _FALLBACK_SYSTEM_PROMPT

        for prompt in (self.reg.render("study.author.fill.v1").content, _FALLBACK_SYSTEM_PROMPT):
            self.assertIn("全局输出要求", prompt)
            self.assertIn("本节硬性标记", prompt)
            self.assertIn("明确驳正", prompt)
            self.assertIn("同时点名", prompt)

    def test_fill_prompt_requires_numbered_labels_and_levels(self):
        # benchmark 真实缺陷：**[EX1] [Q1]** 合并标签、自测题无层级标注、
        # **[EX1]**（基础）充当答案标签。注册版与降级版 fill prompt 都必须给死纪律。
        from backend.generation.study_materials.author.fill import _FALLBACK_SYSTEM_PROMPT

        registered = self.reg.render("study.author.fill.v1").content
        for prompt in (registered, _FALLBACK_SYSTEM_PROMPT):
            self.assertIn("不得合并", prompt)
            self.assertIn("层级", prompt)
            self.assertIn("评分点", prompt)
            self.assertIn("充当答案标签", prompt)

    def test_figure_spec_prompt_is_json_contract(self):
        p = self.reg.render("figure.spec.v1")
        self.assertEqual(JsonOutputContract().validate_prompt_text(p.content), [])
        for kw in ["intent", "kind", "content_spec", "caption", "code", "mermaid", "tikz"]:
            self.assertIn(kw, p.content)


if __name__ == "__main__":
    unittest.main()
