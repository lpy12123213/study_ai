import unittest

from backend.paper_compose.slot_selection import select_slot_with_relax


class SlotSelectionRelaxTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_slot_with_progressive_relaxation(self) -> None:
        candidates = [
            {"question_id": "1", "quality_score": 80, "stem": "same"},
        ]

        async def fetch_more(max_pages: int):
            self.assertGreaterEqual(max_pages, 4)
            return (
                [
                    {"question_id": "2", "quality_score": 50, "stem": "same"},
                    {"question_id": "3", "quality_score": 70, "stem": "unique"},
                ],
                "",
            )

        def sort_candidates(items):
            items.sort(key=lambda q: int(q.get("quality_score") or 0), reverse=True)

        def stem_fp(stem: str) -> str:
            return (stem or "").strip().lower()

        global_seen_ids: set[str] = set()
        global_seen_fps: set[str] = set()

        out = await select_slot_with_relax(
            requested=3,
            candidates=candidates,
            fetch_more=fetch_more,
            sort_candidates=sort_candidates,
            global_seen_ids=global_seen_ids,
            global_seen_fps=global_seen_fps,
            used_ids=set(),
            max_pages=2,
            max_pages_cap=4,
            min_quality_score=60,
            quality_floor=50,
            dedup_by_stem=True,
            stem_fingerprint=stem_fp,
        )

        selected = out.get("selected") or []
        self.assertEqual(len(selected), 3)
        selected_ids = {q.get("question_id") for q in selected}
        self.assertEqual(selected_ids, {"1", "2", "3"})

        trace = out.get("relax_trace") or []
        actions = [t.get("action") for t in trace]
        self.assertGreaterEqual(len(actions), 3)
        self.assertEqual(actions[0], "initial_select")
        self.assertIn("increase_max_pages", actions)
        self.assertIn("lower_min_quality_score", actions)
        self.assertIn("disable_dedup_by_stem", actions)

        self.assertFalse(out.get("dedup_by_stem"))


if __name__ == "__main__":
    unittest.main()
