import unittest

from backend.integrations.crawler.zujuan.parsing import FORMULA_IMG_TAG_PATTERN, IMG_TAG_PATTERN


class TestZujuanParsingPatterns(unittest.TestCase):
    def test_img_tag_pattern_extracts_src(self) -> None:
        html = '<img src="https://example.com/a.png" alt="x" />'
        m = IMG_TAG_PATTERN.search(html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("src"), "https://example.com/a.png")

    def test_formula_img_tag_pattern_extracts_hash(self) -> None:
        html = (
            '<img src="https://staticzujuan.xkw.com/quesimg/Upload/formula/'
            '37ab7408ffcefcb8e5e1ad4a9c58f1b1.png" style="vertical-align:middle;" />'
        )
        m = FORMULA_IMG_TAG_PATTERN.search(html)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("hash"), "37ab7408ffcefcb8e5e1ad4a9c58f1b1")
