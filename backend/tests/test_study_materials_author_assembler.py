import unittest

from backend.generation.study_materials.author.assembler import AssemblyError, assemble

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

    def test_missing_fill_raises(self):
        with self.assertRaises(AssemblyError) as cm:
            assemble(BACKBONE, sections={}, figures={1: {"url": "/m.svg", "caption": "c"}},
                     references=[])
        self.assertIn("sec-1", str(cm.exception))

    def test_fallback_leak_rejected(self):
        leaky = {"sec-1": "> 注：本段讲解未成功使用模型生成（source=llm_sectioned）"}
        with self.assertRaises(AssemblyError):
            assemble(BACKBONE, sections=leaky,
                     figures={1: {"url": "/m.svg", "caption": "c"}}, references=[])


if __name__ == "__main__":
    unittest.main()
