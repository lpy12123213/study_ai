"""Compatibility forwarder for ``backend.chat.service``.

The canonical implementation lives in ``backend.workspace.chat.service``.
SSE disconnect handling lives at the API boundary via is_sse_client_disconnected.
"""

from __future__ import annotations

from backend.workspace.chat.service import *  # noqa: F401,F403
