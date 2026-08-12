import unittest

from backend.core.text_lint import lint_text
from backend.generation.study_materials.author.assembler import AssemblyError, assemble, strip_fallback_notes

BACKBONE = "# 自学材料：极限\n\n引言。\n\n## 一、为什么要极限\n\n引入段。\n\n[[FILL:sec-1]]\n\n[[FIG:1]]\n\n## 总结\n\n收尾。"


class AssembleTests(unittest.TestCase):
    def test_fills_sections_and_figures_and_bibliography(self):
        out = assemble(
            BACKBONE,
            sections={"sec-1": "正文 $x\\to 0$。"},
            figures={1: {"url": "/media/f1.svg", "caption": "趋近过程"}},
            references=[{"title": "Wikipedia: Limit", "url": "https://en.wikipedia.org/wiki/Limit"}],
        )
        self.assertIn("正文 $x\\to 0$。", out)
        self.assertIn("![趋近过程](/media/f1.svg)", out)
        self.assertIn("## 参考文献", out)
        self.assertIn("https://en.wikipedia.org/wiki/Limit", out)
        self.assertNotIn("[[FILL:", out)

    def test_references_render_as_footnote_definitions(self):
        """C2：书目以 [^n]: 脚注定义渲染，与正文内联 [^n] 标记一一对应。"""
        out = assemble(
            BACKBONE,
            sections={"sec-1": "正文。[^1]"},
            figures={1: {"url": "/media/f1.svg", "caption": "趋近过程"}},
            references=[{"n": 1, "title": "Wikipedia: Limit", "url": "https://en.wikipedia.org/wiki/Limit"}],
        )
        self.assertIn("## 参考文献", out)
        self.assertIn("[^1]: Wikipedia: Limit — https://en.wikipedia.org/wiki/Limit", out)
        self.assertNotIn("[1] Wikipedia", out)

    def test_references_without_n_fall_back_to_sequential_numbering(self):
        out = assemble(
            BACKBONE,
            sections={"sec-1": "正文。"},
            figures={1: {"url": "/m.svg", "caption": "c"}},
            references=[
                {"title": "A", "url": "https://a.example/1"},
                {"title": "B", "url": "https://b.example/2"},
            ],
        )
        self.assertIn("[^1]: A — https://a.example/1", out)
        self.assertIn("[^2]: B — https://b.example/2", out)

    def test_document_ends_with_closing_footer(self):
        """eof_mid_sentence：参考文献后追加收尾行，成稿以句读终止符结束。"""
        out = assemble(
            BACKBONE,
            sections={"sec-1": "正文。"},
            figures={1: {"url": "/m.svg", "caption": "c"}},
            references=[{"n": 1, "title": "A", "url": "https://a.example/1"}],
        )
        self.assertIn("本资料由作者代理生成", out)
        self.assertTrue(out.rstrip().endswith("。"))

    def test_redundant_empty_group_heading_is_removed_before_delivery(self):
        backbone = "# 教材\n\n## 分类讨论\n\n[[FILL:sec-1]]"
        section = "### 2、三情形的完整分类\n\n### 2.1 情形一\n\n这里给出第一种情形的推导。"

        out = assemble(backbone, sections={"sec-1": section}, figures={}, references=[])

        self.assertNotIn("### 2、三情形的完整分类", out)
        self.assertIn("### 2.1 情形一", out)
        self.assertNotIn("heading_with_empty_body", lint_text(out))

    def test_parent_heading_with_nested_section_body_is_retained(self):
        backbone = "# 教材\n\n[[FILL:sec-1]]"
        section = "### 分类讨论\n\n#### 情形一\n\n这里给出第一种情形的推导。"

        out = assemble(backbone, sections={"sec-1": section}, figures={}, references=[])

        self.assertIn("### 分类讨论", out)

    def test_missing_fill_raises(self):
        with self.assertRaises(AssemblyError) as cm:
            assemble(BACKBONE, sections={}, figures={1: {"url": "/m.svg", "caption": "c"}},
                     references=[])
        self.assertIn("sec-1", str(cm.exception))
        self.assertEqual(cm.exception.code, "missing_fragments")
        self.assertEqual(cm.exception.missing, ["sec-1"])

    def test_underscore_section_id_substituted(self):
        """真实缺陷：LLM 产出下划线小节 id（s0_frontmatter），FILL_RE 字符集不含 _ 时
        占位符既不被替换也不报缺失，静默残留成稿。"""
        backbone = "# 自学材料：极限\n\n[[FILL:s0_frontmatter]]\n\n## 总结\n\n收尾。"
        out = assemble(backbone, sections={"s0_frontmatter": "封面与使用说明。"},
                       figures={}, references=[])
        self.assertIn("封面与使用说明。", out)
        self.assertNotIn("[[FILL:", out)

    def test_missing_underscore_fill_raises_naming_id(self):
        backbone = "# 自学材料：极限\n\n[[FILL:s0_frontmatter]]\n\n收尾。"
        with self.assertRaises(AssemblyError) as cm:
            assemble(backbone, sections={}, figures={}, references=[])
        self.assertIn("s0_frontmatter", str(cm.exception))

    def test_fallback_leak_rejected(self):
        leaky = {"sec-1": "> 注：本段讲解未成功使用模型生成（source=llm_sectioned）"}
        with self.assertRaises(AssemblyError) as cm:
            assemble(BACKBONE, sections=leaky,
                     figures={1: {"url": "/m.svg", "caption": "c"}}, references=[])
        self.assertEqual(cm.exception.code, "fallback_leak")
        self.assertEqual(cm.exception.fragment, "section:sec-1")

    def test_stripping_backbone_fallback_note_preserves_same_line_placeholder(self):
        repaired = strip_fallback_notes("# 书\n\n[[FILL:sec-1]] > 兜底内容\n\n## 总结")

        self.assertIn("[[FILL:sec-1]]", repaired)
        self.assertNotIn("兜底内容", repaired)


if __name__ == "__main__":
    unittest.main()
