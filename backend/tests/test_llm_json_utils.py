from __future__ import annotations

import unittest

from backend.llm.json_utils import (
    extract_first_json_array,
    extract_first_json_object,
    extract_json_value,
    json_parse_stats,
    reset_json_parse_stats,
    strip_code_fences,
)


class TestLlmJsonUtils(unittest.TestCase):
    def setUp(self) -> None:
        reset_json_parse_stats()

    def test_strip_code_fences_handles_language_tag(self) -> None:
        self.assertEqual(strip_code_fences("```json\n{\"ok\": true}\n```"), '{"ok": true}')

    def test_extract_first_json_object_lenient(self) -> None:
        self.assertEqual(extract_first_json_object("prefix {\"a\": 1} suffix", default={}), {"a": 1})

    def test_extract_first_json_array_lenient(self) -> None:
        self.assertEqual(extract_first_json_array("```json\n[{\"a\": 1}]\n```", default=[]), [{"a": 1}])

    def test_extract_json_value_tracks_stats(self) -> None:
        self.assertEqual(extract_json_value("not json [1,2]", default=[]), [1, 2])
        self.assertEqual(extract_first_json_object("nope", default={}), {})

        stats = json_parse_stats()
        self.assertEqual(stats.get("value_success"), 1)
        self.assertEqual(stats.get("object_failure"), 1)

