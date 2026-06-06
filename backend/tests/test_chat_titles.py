from __future__ import annotations

import unittest

from backend.workspace.chat.titles import truncate_display_title, update_title_for_first_user_message


class ChatTitleTests(unittest.IsolatedAsyncioTestCase):
    def test_truncate_display_title_counts_cjk_as_double_width(self) -> None:
        self.assertEqual(truncate_display_title("数学高考模拟" * 4, max_width=12), "数学高考模拟...")

    async def test_update_title_for_first_user_message_only_when_history_empty(self) -> None:
        calls: list[tuple[str, int, str]] = []

        async def update_title(*, user_id: str, conv_id: int, title: str) -> bool:
            calls.append((user_id, conv_id, title))
            return True

        updated = await update_title_for_first_user_message(
            user_id="u1",
            conv_id=42,
            user_message="数学高考模拟",
            history_count=0,
            update_title=update_title,
        )
        skipped = await update_title_for_first_user_message(
            user_id="u1",
            conv_id=42,
            user_message="第二轮",
            history_count=1,
            update_title=update_title,
        )

        self.assertTrue(updated)
        self.assertFalse(skipped)
        self.assertEqual(calls, [("u1", 42, "数学高考模拟")])


if __name__ == "__main__":
    unittest.main()
