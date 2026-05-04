from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]


def register_security_headers_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next: CallNext) -> Response:
        response = await call_next(request)
        try:
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        except Exception:
            logger.exception("failed to set security headers")
        return response
