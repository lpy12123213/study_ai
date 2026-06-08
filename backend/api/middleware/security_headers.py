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
            response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
            )
            if str(request.url.scheme or "").lower() == "https":
                response.headers.setdefault("Strict-Transport-Security", "max-age=15552000; includeSubDomains")
        except Exception:
            logger.exception("failed to set security headers")
        return response
