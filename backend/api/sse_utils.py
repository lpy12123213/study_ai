from __future__ import annotations

from typing import Any

from backend.core.helpers import get_logger

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
