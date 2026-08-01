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
