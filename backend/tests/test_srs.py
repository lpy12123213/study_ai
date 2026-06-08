import unittest
from datetime import datetime, timedelta


class SrsAlgorithmTests(unittest.TestCase):
    def _module(self):
        try:
            from backend.core import srs
        except ImportError as exc:  # pragma: no cover - red-test helper
            self.fail(f"missing backend.core.srs module: {exc}")
        return srs

    def test_again_resets_repetitions_and_schedules_tomorrow(self) -> None:
        srs = self._module()
        now = datetime(2026, 1, 1, 8, 30)

        result = srs.schedule_review(
            rating="again",
            ease_factor=2.5,
            interval_days=20,
            repetitions=5,
            now=now,
        )

        self.assertEqual(result["repetitions"], 0)
        self.assertEqual(result["interval_days"], 1)
        self.assertAlmostEqual(result["ease_factor"], 2.18, places=2)
        self.assertEqual(result["next_review_at"], now + timedelta(days=1))

    def test_good_review_sequence_uses_one_six_then_ease_scaled_interval(self) -> None:
        srs = self._module()
        now = datetime(2026, 1, 1, 8, 30)

        first = srs.schedule_review(rating="good", ease_factor=2.5, interval_days=0, repetitions=0, now=now)
        second = srs.schedule_review(
            rating="good",
            ease_factor=first["ease_factor"],
            interval_days=first["interval_days"],
            repetitions=first["repetitions"],
            now=now,
        )
        third = srs.schedule_review(
            rating="good",
            ease_factor=second["ease_factor"],
            interval_days=second["interval_days"],
            repetitions=second["repetitions"],
            now=now,
        )

        self.assertEqual((first["interval_days"], first["repetitions"]), (1, 1))
        self.assertEqual((second["interval_days"], second["repetitions"]), (6, 2))
        self.assertEqual((third["interval_days"], third["repetitions"]), (15, 3))

    def test_ease_factor_never_drops_below_floor(self) -> None:
        srs = self._module()
        result = srs.schedule_review(
            rating="again",
            ease_factor=1.31,
            interval_days=1,
            repetitions=1,
            now=datetime(2026, 1, 1, 8, 30),
        )

        self.assertEqual(result["ease_factor"], 1.3)

    def test_mastery_delta_is_clamped_to_zero_and_one_hundred(self) -> None:
        srs = self._module()

        self.assertEqual(srs.apply_mastery_delta(10, "again"), 0)
        self.assertEqual(srs.apply_mastery_delta(90, "easy"), 100)
        self.assertEqual(srs.apply_mastery_delta(40, "hard"), 45)
        self.assertEqual(srs.apply_mastery_delta(40, "good"), 55)


if __name__ == "__main__":
    unittest.main()
