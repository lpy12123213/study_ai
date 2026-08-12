import asyncio
import unittest

from backend.generation.study_materials.author.blueprint import Blueprint
from backend.generation.study_materials.author.fill import (
    FillRunner,
    remap_out_of_scope_citations,
    restore_missing_example_tag,
)

BP = Blueprint.from_dict({
    "narrative": "n", "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小"}],
    "sections": [{"id": "sec-1", "title": "t", "purpose": "p", "key_points": ["k"],
                  "target_chars": 800, "difficulty": "基础", "misconceptions": [],
                  "frontier": False}],
    "figures": [],
})


# 长度门恢复 min(target_chars*0.5, min_chars) 后，fake 正文需 ≥200 字符（target 800 → 400，被 min_chars 盖帽）。
GROUNDED_BODY = (
    "本节严格讲解极限的直观概念：当自变量无限接近某个值时，函数值无限接近一个确定的数，"
    "这个数就是极限；$\\epsilon$ 作为任意小正数刻画了这种接近程度，逼近不要求到达。"
    "[EX1] 例题：求 x 趋近 2 时 x+1 的极限。步骤一：观察 x 接近 2 的趋势；"
    "步骤二：x+1 随之接近 3；步骤三：得出极限为 3，并说明这与直接代入一致纯属巧合。"
    "[Q1] 自测（基础）：用自己的话解释无限逼近的含义；（应用）：求 x→0 时 2x 的极限并说明理由。"
    "[A1] 答案：0。评分点：趋势判断正确、表述无循环论证、能区分函数值与极限值。"
)


class FillRunnerTests(unittest.TestCase):
    def test_context_pack_is_bounded_and_grounded(self):
        seen = {}

        async def fake_llm(system, user):
            seen["user"] = user
            return GROUNDED_BODY

        r = FillRunner(llm_func=fake_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], backbone_excerpt="衔接段",
                                 research_slice="fact: x | src: https://a",
                                 terminology=BP.terminology))
        self.assertIn("$\\epsilon$", out.text)
        self.assertIn("衔接段", seen["user"])          # 知道接在哪
        self.assertIn("https://a", seen["user"])       # 笔记切片注入
        self.assertLess(len(seen["user"]), 12000)      # 有界

    def test_retry_then_author_fallback_flag(self):
        events = []

        async def bad_llm(system, user):
            return "太短"

        r = FillRunner(llm_func=bad_llm, max_retries=2, min_chars=100, on_event=events.append)
        out = asyncio.run(r.fill(BP.sections[0], backbone_excerpt="",
                                 research_slice="", terminology=[]))
        self.assertTrue(out.needs_author_rewrite)
        self.assertEqual(out.attempts, 2)
        self.assertTrue(any("长度不足" in issue for issue in out.missing))
        failed = next(event for event in events if event["data"]["status"] == "failed")
        self.assertEqual(failed["data"]["missing"], list(out.missing))

    def test_url_in_output_rejected(self):
        async def leaky_llm(system, user):
            return "见 https://example.com 详情……" * 20

        r = FillRunner(llm_func=leaky_llm, max_retries=1, min_chars=10)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)

    def test_length_gate_uses_half_target_ratio(self):
        """I-4：长度门恢复 min(target_chars*0.5, min_chars)；800 字目标 → 需 ≥200 字符。"""
        short = "简要讲解极限概念并配例题。[EX1] 例 …[Q1] 题（基础） …[A1] 答 …" * 4  # ~140 字符，标签齐全但长度不足

        async def short_llm(system, user):
            return short

        out = asyncio.run(FillRunner(llm_func=short_llm, max_retries=1).fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)

        async def long_llm(system, user):
            return short * 2  # ~240 字符，过 200 盖帽线

        ok = asyncio.run(FillRunner(llm_func=long_llm, max_retries=1).fill(BP.sections[0], "", "", []))
        self.assertFalse(ok.needs_author_rewrite)

    def test_default_max_retries_is_two(self):
        """M-5：默认 max_retries 对齐设计“默认 ≤2”。"""
        async def bad_llm(system, user):
            return "太短"

        runner = FillRunner(llm_func=bad_llm, min_chars=100)
        self.assertEqual(runner.max_retries, 2)
        out = asyncio.run(runner.fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)
        self.assertEqual(out.attempts, 2)

    def test_global_requirements_and_required_marker_are_enforced(self):
        seen = []

        async def marker_llm(system, user):
            seen.append(user)
            if len(seen) == 1:
                return GROUNDED_BODY
            return GROUNDED_BODY + "\n\n[高中连接] 用切线近似帮助检查高中导数题的估算结果。"

        runner = FillRunner(llm_func=marker_llm, max_retries=2)
        out = asyncio.run(
            runner.fill(
                BP.sections[0],
                "",
                "",
                [],
                global_requirements="必须比较精确值与近似值，并说明误差来源。",
                required_markers=["[高中连接]"],
            )
        )

        self.assertFalse(out.needs_author_rewrite)
        self.assertEqual(out.attempts, 2)
        self.assertIn("必须比较精确值与近似值", seen[0])
        self.assertIn("[高中连接]", seen[0])
        self.assertIn("缺少必需标记 [高中连接]", seen[1])

    def test_requested_comparison_and_sourced_misconception_need_explicit_semantics(self):
        section = Blueprint.from_dict({
            "narrative": "n",
            "terminology": [],
            "sections": [{
                "id": "sec-compare",
                "title": "必要条件与充分条件",
                "purpose": "辨析两个条件",
                "key_points": ["区分必要条件与充分条件"],
                "target_chars": 200,
                "difficulty": "应用",
                "misconceptions": [{
                    "claim": "必要条件就是充分条件",
                    "source_url": "https://example.edu/logic",
                }],
                "frontier": False,
            }],
            "figures": [],
        }).sections[0]
        weak = (
            "本节介绍两个条件及其数学表达，并给出若干命题帮助学习者掌握基本用法。" * 6
            + "\n\n**[EX1]**\n例题。步骤：写出命题。"
            + "\n\n**[Q1]** [基础]\n判断命题。"
            + "\n\n**[A1]**\n答案成立。评分点：判断正确。"
        )

        missing = FillRunner._validate(  # noqa: SLF001 - 直接锁定分节语义门
            weak,
            0,
            set(),
            [],
            section_spec=section,
        )
        self.assertTrue(any("明确驳正" in item for item in missing))
        self.assertTrue(any("明确比较" in item for item in missing))

        strong = weak + (
            "\n\n### 易错点辨析\n常见误区认为必要条件就是充分条件；这种说法错误，因为二者方向不同。"
            "必要条件与充分条件相比，前者是结论成立所必需，后者足以推出结论，区别不能混同。"
        )
        self.assertEqual(
            FillRunner._validate(strong, 0, set(), [], section_spec=section),  # noqa: SLF001
            [],
        )

    def test_section_with_registered_sources_requires_a_valid_inline_citation(self):
        uncited = GROUNDED_BODY
        missing = FillRunner._validate(uncited, 0, {"1"}, [])  # noqa: SLF001
        self.assertTrue(any("有效内联引用" in item for item in missing))

        cited = uncited + "\n\n上述极限定义与逼近条件可由本节来源核对。[^1]"
        self.assertEqual(FillRunner._validate(cited, 0, {"1"}, []), [])  # noqa: SLF001


class HeadingLevelTests(unittest.TestCase):
    """真实缺陷：fill 小节正文出现 ## 级标题（## [EX1] 例题、## 自测题），
    与骨架的 ## 小节标题同级，破坏全书层级。入口应确定性降为 H3，避免重跑模型。"""

    def test_h2_heading_in_output_demoted_without_retry(self):
        seen = []

        async def heading_llm(system, user):
            seen.append(user)
            return GROUNDED_BODY + "\n\n## [EX2] 例题\n\n补充例题讲解与步骤拆解。"

        r = FillRunner(llm_func=heading_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)
        self.assertEqual(len(seen), 1)
        self.assertIn("### [EX2] 例题", out.text)
        self.assertNotRegex(out.text, r"(?m)^##\s+\[EX2\]", msg=out.text)

    def test_h1_heading_in_output_demoted(self):
        async def heading_llm(system, user):
            return "# 小节标题\n\n" + GROUNDED_BODY

        r = FillRunner(llm_func=heading_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)
        self.assertTrue(out.text.startswith("### 小节标题"))

    def test_h3_h4_headings_accepted(self):
        async def heading_llm(system, user):
            return "### 直观理解\n\n" + GROUNDED_BODY + "\n\n#### 备注\n\n补充说明与提醒。"
        r = FillRunner(llm_func=heading_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)
        self.assertIn("### 直观理解", out.text)

    def test_fill_prompt_restricts_heading_levels(self):
        # fill system prompt 必须给死标题层级纪律（注册表与内置降级 prompt 同步）。
        from backend.generation.study_materials.author.fill import _FALLBACK_SYSTEM_PROMPT
        from backend.llm.prompts import create_default_prompt_registry

        registered = create_default_prompt_registry().render("study.author.fill.v1").content
        for prompt in (registered, _FALLBACK_SYSTEM_PROMPT):
            self.assertIn("###", prompt)
            self.assertIn("加粗", prompt)


# 来源登记表行（[^n] title url）：fill 上下文里唯一允许出现的 URL 形态。
SOURCE_REGISTRY = (
    "## 来源登记表\n\n"
    "- [^1] 极限 通俗解释 https://example.com/limits\n"
    "- [^2]  epsilon-delta 定义 https://example.com/epsilon\n"
)


class InlineCitationTests(unittest.TestCase):
    """C2：正文允许并校验 [^n] 内联引用，编号必须落在该节来源清单内。"""

    def test_payload_carries_numbered_source_list(self):
        seen = {}

        async def fake_llm(system, user):
            seen["user"] = user
            return GROUNDED_BODY

        r = FillRunner(llm_func=fake_llm, max_retries=1)
        research = SOURCE_REGISTRY + "\n## 极限\n- 极限是无限逼近 | src: https://example.com/limits | conf: 0.90"
        asyncio.run(r.fill(BP.sections[0], "", research, []))
        self.assertIn("来源清单", seen["user"])
        self.assertIn("全书固定编号，不得从 [^1] 重新编号", seen["user"])
        self.assertIn("[^1] 极限 通俗解释 https://example.com/limits", seen["user"])
        # 事实行出处改写为编号，正文中不再出现裸 URL 形态的 src
        self.assertIn("src: [^1]", seen["user"])

    def test_inline_marker_in_source_list_accepted(self):
        body = GROUNDED_BODY + "这一直观解释有检索来源支持[^1]。"

        async def fake_llm(system, user):
            return body

        r = FillRunner(llm_func=fake_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", SOURCE_REGISTRY, []))
        self.assertFalse(out.needs_author_rewrite)
        self.assertIn("[^1]", out.text)

    def test_hallucinated_citation_id_rejected(self):
        async def fake_llm(system, user):
            return GROUNDED_BODY + "来源[^9]。"

        r = FillRunner(llm_func=fake_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", SOURCE_REGISTRY, []))
        self.assertTrue(out.needs_author_rewrite)

    def test_author_level_citation_repair_uses_only_supplied_global_ids(self):
        text, remapped = remap_out_of_scope_citations(
            "第一条[^9]，已有编号保留[^7]，第二条[^12]，再次引用[^9]。",
            {"3", "7"},
        )

        self.assertEqual(remapped, {"9": "3", "12": "7"})
        self.assertEqual(text, "第一条[^3]，已有编号保留[^7]，第二条[^7]，再次引用[^3]。")

    def test_author_level_citation_repair_keeps_unsupported_ids_without_sources(self):
        text, remapped = remap_out_of_scope_citations("来源[^9]。", set())

        self.assertEqual(text, "来源[^9]。")
        self.assertEqual(remapped, {})

    def test_author_level_example_label_repair_requires_real_example_cue(self):
        repaired, changed = restore_missing_example_tag("讲解正文。\n### 示例：求函数极值\n步骤一：求导。")

        self.assertTrue(changed)
        self.assertIn("**[EX1]**\n### 示例：求函数极值", repaired)

        untouched, changed = restore_missing_example_tag("只有概念讲解，没有演算块。")
        self.assertFalse(changed)
        self.assertEqual(untouched, "只有概念讲解，没有演算块。")

    def test_citation_without_source_list_rejected(self):
        async def fake_llm(system, user):
            return GROUNDED_BODY + "来源[^1]。"

        r = FillRunner(llm_func=fake_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "无来源笔记。", []))
        self.assertTrue(out.needs_author_rewrite)


class LatexDelimiterTests(unittest.TestCase):
    """真实缺陷（实跑 #5）：模型用 \\(...\\) / \\[...\\] 定界符——前端 remark-math 不渲染，
    且 lint 数学区间豁免不覆盖。fill 入口应无损归一化，避免为机械格式差异重跑模型。"""

    def test_paren_delimiter_normalized_without_retry(self):
        seen = []

        async def paren_llm(system, user):
            seen.append(user)
            return GROUNDED_BODY + "公式 \\(A=\\begin{bmatrix}0&1\\\\1&0\\end{bmatrix}\\) 见上。"

        r = FillRunner(llm_func=paren_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)
        self.assertEqual(len(seen), 1)
        self.assertIn("$A=\\begin{bmatrix}0&1\\\\1&0\\end{bmatrix}$", out.text)
        self.assertNotIn("\\(", out.text)

    def test_bracket_delimiter_normalized(self):
        async def bracket_llm(system, user):
            return GROUNDED_BODY + "\n\\[x+1=2\\]"

        r = FillRunner(llm_func=bracket_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)
        self.assertIn("$$x+1=2$$", out.text)

    def test_delimiters_inside_fenced_code_are_not_rewritten(self):
        async def fenced_llm(system, user):
            return GROUNDED_BODY + "\n```text\n# literal\n\\(literal\\)\n```\n正文 \\(x+1\\)。"

        out = asyncio.run(FillRunner(llm_func=fenced_llm, max_retries=1).fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)
        self.assertIn("```text\n# literal\n\\(literal\\)\n```", out.text)
        self.assertIn("正文 $x+1$。", out.text)

    def test_dollar_delimiters_accepted(self):
        async def dollar_llm(system, user):
            return GROUNDED_BODY + "公式 $x+1=2$ 与 $$y=2x$$ 见上。"

        r = FillRunner(llm_func=dollar_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertFalse(out.needs_author_rewrite)


class QuestionLabelTests(unittest.TestCase):
    """真实缺陷（benchmark eigen_decomposition 实跑）：自测题标签与例题合并书写
    （``**[EX1] [Q1]**``）、不标层级，答案节用 ``**[EX1]**（基础）`` 充当答案标签
    （应为 [A1]），层级与评分点识别失败。fill 验收必须拒绝并要求编号标签 + 层级标注。"""

    # 合并标签（EX 与 Q 共行）且无层级标注：编号在但层级缺 → 拒并喂回。
    MERGED_Q_BODY = GROUNDED_BODY.replace(
        "[Q1] 自测（基础）：用自己的话解释无限逼近的含义；（应用）：求 x→0 时 2x 的极限并说明理由。",
        "**[EX1] [Q1]** 自测：求 x→0 时 2x 的极限并说明理由。",
    )
    UNNUMBERED_A_BODY = GROUNDED_BODY.replace("[A1] 答案", "[A] 答案")
    UNNUMBERED_Q_BODY = GROUNDED_BODY.replace("[Q1] 自测", "[Q] 自测")
    EX_AS_ANSWER_BODY = GROUNDED_BODY.replace("[A1] 答案", "[EX1] 答案")

    def test_merged_ex_q_label_without_level_rejected_and_fed_back(self):
        seen = []

        async def merged_llm(system, user):
            seen.append(user)
            return self.MERGED_Q_BODY

        r = FillRunner(llm_func=merged_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertTrue(out.needs_author_rewrite)
        self.assertEqual(len(seen), 2)
        self.assertIn("层级", seen[1])  # 缺层级标注的原因必须喂回模型

    def test_unnumbered_answer_label_rejected_and_fed_back(self):
        seen = []

        async def unnumbered_llm(system, user):
            seen.append(user)
            return self.UNNUMBERED_A_BODY

        r = FillRunner(llm_func=unnumbered_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))

        self.assertTrue(out.needs_author_rewrite)
        self.assertIn("答案标签必须带编号", seen[1])

    def test_unnumbered_question_label_rejected(self):
        async def unnumbered_llm(system, user):
            return self.UNNUMBERED_Q_BODY

        r = FillRunner(llm_func=unnumbered_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)

    def test_ex_label_as_answer_rejected(self):
        async def ex_answer_llm(system, user):
            return self.EX_AS_ANSWER_BODY

        r = FillRunner(llm_func=ex_answer_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)

    def test_wellformed_numbered_labels_with_levels_accepted(self):
        async def good_llm(system, user):
            return GROUNDED_BODY  # [EX1]/[Q1]（基础）（应用）/[A1] 评分点

        r = FillRunner(llm_func=good_llm, max_retries=1)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))
        self.assertFalse(out.needs_author_rewrite)


if __name__ == "__main__":
    unittest.main()
