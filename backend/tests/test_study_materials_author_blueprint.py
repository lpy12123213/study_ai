import unittest

from backend.generation.study_materials.author.blueprint import Blueprint, BlueprintError

VALID = {
    "narrative": "从直观到严格",
    "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小正数"}],
    "sections": [
        {"id": "sec-1", "title": "为什么要极限", "purpose": "动机",
         "key_points": ["直觉"], "target_chars": 1200, "difficulty": "基础",
         "misconceptions": [], "frontier": False},
        {"id": "sec-2", "title": "严格定义", "purpose": "定义",
         "key_points": ["epsilon-delta"], "target_chars": 1800, "difficulty": "应用",
         "misconceptions": [{"claim": "极限=函数值", "source_url": "https://a/x"}],
         "frontier": False},
    ],
    "figures": [{"n": 1, "sec_id": "sec-1", "intent": "趋近过程示意", "kind": "mermaid",
                 "caption": "图1"}],
}


class BlueprintTests(unittest.TestCase):
    def test_parse_valid(self):
        bp = Blueprint.from_dict(VALID)
        self.assertEqual([s.id for s in bp.sections], ["sec-1", "sec-2"])
        self.assertEqual(bp.figures[0].sec_id, "sec-1")

    def test_misconception_without_source_rejected(self):
        bad = dict(VALID, sections=[dict(VALID["sections"][0],
                   misconceptions=[{"claim": "x", "source_url": ""}])])
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(bad)

    def test_figure_refs_unknown_section_rejected(self):
        bad = dict(VALID, figures=[dict(VALID["figures"][0], sec_id="sec-99")])
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(bad)

    def test_duplicate_section_id_rejected(self):
        bad = dict(VALID, sections=[VALID["sections"][0], VALID["sections"][0]])
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(bad)

    def test_section_id_charset_validated(self):
        """小节 id 字符集与汇编器 [[FILL:<id>]] 占位符契约对齐：小写字母/数字开头，
        后接小写字母、数字、连字符或下划线；大写/点号/空格拒绝。"""
        for bad_id in ("S0.FrontMatter", "S0_frontmatter", "s0 frontmatter", "-s0", "s0.front"):
            bad = dict(VALID, sections=[dict(VALID["sections"][0], id=bad_id)], figures=[])
            with self.assertRaises(BlueprintError, msg=f"id {bad_id!r} 应被拒绝"):
                Blueprint.from_dict(bad)

    def test_section_id_underscore_and_hyphen_accepted(self):
        for good_id in ("s0_frontmatter", "sec-1", "s1_definition"):
            good = dict(VALID, sections=[dict(VALID["sections"][0], id=good_id)], figures=[])
            bp = Blueprint.from_dict(good)
            self.assertEqual(bp.sections[0].id, good_id)


if __name__ == "__main__":
    unittest.main()
