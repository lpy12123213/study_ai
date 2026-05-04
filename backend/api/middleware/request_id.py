import uuid
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

from backend.core.logging_utils import get_logger, get_request_id, set_client_ip, set_request_id

logger = get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]
ClientIpGetter = Callable[[Request], str]


def ensure_request_id(request: Request) -> str:
    """Return a stable request id for the current request context."""

    rid = get_request_id() or str(request.headers.get("X-Request-ID") or "").strip()
    if not rid:
        rid = f"req_{uuid.uuid4().hex[:12]}"
    set_request_id(rid)
    return rid


def register_request_id_middleware(app: FastAPI, *, client_ip: ClientIpGetter) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: CallNext) -> Response:
        incoming = str(request.headers.get("X-Request-ID") or "").strip()
        rid = incoming or f"req_{uuid.uuid4().hex[:12]}"
        set_request_id(rid)
        try:
            set_client_ip(client_ip(request))
        except (RuntimeError, TypeError, ValueError):
            logger.debug("failed to set client_ip context", exc_info=True)

        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
