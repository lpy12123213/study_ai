from __future__ import annotations

import json
from typing import Any, AsyncIterable, AsyncIterator

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


async def is_sse_client_disconnected(request: Any) -> bool:
    """Best-effort SSE disconnect check that never breaks the stream handler."""

    try:
        checker = getattr(request, "is_disconnected", None)
        if checker is None:
            return False
        return bool(await checker())
    except Exception:
        logger.warning("sse_disconnect_check_failed", exc_info=True)
        return False


async def stream_with_disconnect_check(
    request: Any,
    events: AsyncIterable[dict],
) -> AsyncIterator[str]:
    """Wrap an async iterable of dict events into SSE-formatted lines.

    - Stops yielding once the client disconnects (best-effort).
    - Always uses ``ensure_ascii=False`` to keep CJK output readable.
    - Skips non-dict events silently to keep callers simple.
    """

    async for event in events:
        if await is_sse_client_disconnected(request):
            return
        if not isinstance(event, dict):
            continue
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
