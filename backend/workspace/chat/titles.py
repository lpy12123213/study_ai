from __future__ import annotations

import unicodedata
from collections.abc import Awaitable, Callable

from backend.database.repositories.content.conversations import update_conversation_title


async def _default_update_title(*, user_id: str, conv_id: int, title: str) -> bool:
    return await update_conversation_title(user_id=user_id, conv_id=conv_id, title=title)


def truncate_display_title(text: str, max_width: int = 30) -> str:
    s = str(text or "").strip()
    if not s or max_width <= 0:
        return ""

    width = 0
    out: list[str] = []
    for ch in s:
        ch_w = 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1
        if width + ch_w > max_width:
            break
        out.append(ch)
        width += ch_w

    clipped = "".join(out).strip()
    if clipped and len(clipped) < len(s):
        return clipped + "..."
    return clipped or s[: max(0, max_width)]


async def update_title_for_first_user_message(
    *,
    user_id: str,
    conv_id: int,
    user_message: str,
    history_count: int,
    update_title: Callable[[str, int, str], Awaitable[bool]] | None = None,
) -> bool:
    if int(history_count or 0) > 0:
        return False

    title = truncate_display_title(user_message, max_width=30)
    if not title:
        return False

    updater = update_title or _default_update_title
    return await updater(user_id=user_id, conv_id=conv_id, title=title)
