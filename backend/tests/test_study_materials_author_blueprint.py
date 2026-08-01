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


if __name__ == "__main__":
    unittest.main()
