"""
FastAPI 后端服务入口。

API 路由在 `backend/api/` 下；此文件负责：
- CORS 等中间件
- 应用生命周期（初始化数据库）
- 生产环境静态文件托管（`frontend/dist`）
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import sys
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

if __package__ is None or __package__ == "":
    # Allow running as a script: `python backend/app.py`
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.api.auth import local_auth_user
from backend.api.error_codes import ErrorCode, build_error_payload, is_safe_error_code
from backend.api.media import close_proxy_http_client
from backend.api.middleware.input_validation import InputValidationMiddleware
from backend.api.middleware.rate_limit import register_rate_limit_middleware
from backend.api.middleware.request_id import ensure_request_id, register_request_id_middleware
from backend.api.middleware.security_headers import register_security_headers_middleware
from backend.api.router import api_router
from backend.core.audit import AuditAction, audit_logger
from backend.core.auth import validate_access_token
from backend.core.config_check import log_config_check
from backend.core.logging_utils import configure_logging, get_logger
from backend.core.metrics import instrument_app
from backend.integrations.crawler.manager import close_crawler
from backend.database.engine import init_db
from backend.llm.client import (
    close_shared_llm_http_client,
    reset_llm_api_key_override,
    reset_moonshot_api_key_override,
    set_llm_api_key_override,
    set_moonshot_api_key_override,
)
from backend.media.generated import cleanup_expired_generated_files
from backend.generation.question_library.worker import run_question_library_scoring_worker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = PROJECT_ROOT / "frontend" / "dist"

# NOTE: This app includes the new `/api/study-materials/*` routes via `backend/api/router.py`.

_log_format = (os.getenv("LOG_FORMAT") or "").strip().lower()
configure_logging(force=(not _log_format or _log_format == "json"))
logger = get_logger(__name__)


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, *, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


async def _run_generated_files_cleanup_worker(*, stop: asyncio.Event) -> None:
    # Default: cleanup every 30 minutes.
    interval_s = max(60, min(_env_int("GENERATED_FILES_CLEANUP_INTERVAL_S", default=30 * 60), 24 * 60 * 60))
    while not stop.is_set():
        try:
            await cleanup_expired_generated_files(limit=_env_int("GENERATED_FILES_CLEANUP_BATCH", default=500))
        except Exception:
            logger.exception("generated_files_cleanup_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=float(interval_s))
        except asyncio.TimeoutError:
            continue


def _client_ip(request: Request) -> str:
    """Best-effort client IP extraction with optional proxy header trust."""

    if _env_truthy("TRUST_PROXY_HEADERS", default=False) and _is_trusted_proxy(request):
        # RFC 7239 Forwarded: for=...
        forwarded = str(request.headers.get("Forwarded") or "").strip()
        if forwarded:
            try:
                first = forwarded.split(",", 1)[0]
                m = re.search(r'(?i)(?:^|;|\s)for=("[^"]+"|[^;\s]+)', first)
                if m:
                    v = str(m.group(1) or "").strip().strip('"')
                    if v.startswith("[") and "]" in v:
                        v = v[1 : v.index("]")]
                    # Strip IPv4 :port (keep IPv6 intact).
                    if ":" in v and "." in v:
                        host, _, port = v.partition(":")
                        if port.isdigit():
                            v = host
                    if v and v.lower() != "unknown":
                        return v
            except (IndexError, ValueError):
                logger.debug("failed to parse Forwarded header", exc_info=True)

        # X-Forwarded-For can be a list: client, proxy1, proxy2...
        xff = str(request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
        xri = str(request.headers.get("X-Real-IP") or "").strip()
        if xri:
            return xri
        cfip = str(request.headers.get("CF-Connecting-IP") or "").strip()
        if cfip:
            return cfip

    return (request.client.host if request.client else "") or "unknown"


def _parse_trusted_proxies(raw: str) -> list[ipaddress._BaseNetwork]:
    value = str(raw or "").strip()
    if not value:
        return []
    parts = re.split(r"[,\n;\s]+", value)
    nets: list[ipaddress._BaseNetwork] = []
    for p in parts:
        p = str(p or "").strip()
        if not p:
            continue
        if p == "*":
            # Wildcard trust makes proxy headers trivially spoofable; ignore and warn.
            continue
        try:
            if "/" in p:
                nets.append(ipaddress.ip_network(p, strict=False))
                continue
            addr = ipaddress.ip_address(p)
            if addr.version == 4:
                nets.append(ipaddress.ip_network(f"{p}/32"))
            else:
                nets.append(ipaddress.ip_network(f"{p}/128"))
        except ValueError:
            continue
        except Exception:
            logger.exception("failed to parse TRUSTED_PROXIES entry", extra={"value": p})
    return nets


@lru_cache(maxsize=1)
def _trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = str(os.getenv("TRUSTED_PROXIES") or "").strip()
    return tuple(_parse_trusted_proxies(raw))


def _warn_proxy_settings_on_startup() -> None:
    """Emit security warnings for risky proxy-header settings."""

    raw = str(os.getenv("TRUSTED_PROXIES") or "").strip()
    if raw:
        parts = [p for p in re.split(r"[,\n;\s]+", raw) if p]
        if "*" in parts:
            logger.warning(
                "trusted_proxies_wildcard_forbidden",
                extra={"trusted_proxies": raw},
            )

    if _env_truthy("TRUST_PROXY_HEADERS", default=False) and not _trusted_proxy_networks():
        # This is a common misconfig: enabling proxy headers without defining trusted proxy IPs
        # effectively disables all proxy-header parsing (fail-closed), which surprises users.
        logger.warning("trust_proxy_headers_enabled_but_no_trusted_proxies")


def _is_trusted_proxy(request: Request) -> bool:
    nets = _trusted_proxy_networks()
    if not nets:
        return False
    host = (request.client.host if request.client else "") or ""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    except Exception:
        logger.exception("failed to parse request.client.host", extra={"host": host})
        return False
    return any(ip in net for net in nets)


class _CachedAssetFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        try:
            if resp.status_code == 200:
                resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        except Exception:
            logger.exception("failed to set cache headers for asset")
        return resp


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()

    # Fail orphaned DB tasks that were left as `running` by a previous process.
    # This avoids hanging SSE/polling clients after a server restart.
    try:
        from backend.shared.tasks import task_runtime

        await task_runtime.restart_recovery(reason="server_restarted")
    except Exception:
        logger.exception("task_runtime_restart_recovery_failed")

    # Question-library sessions/previews are stored as local JSON snapshots. If the
    # process restarts mid-run, some sessions may remain at status=running and the
    # frontend will keep waiting. Downgrade them to an interrupted state.
    try:
        from backend.generation.question_library.preview_store import mark_running_sessions_interrupted

        changed = mark_running_sessions_interrupted(reason="server_restarted")
        if changed:
            logger.info("question_library_sessions_interrupted_on_startup", extra={"count": int(changed or 0)})
    except Exception:
        logger.exception("question_library_sessions_interrupted_on_startup_failed")

    # Restore study-materials tasks snapshots early (under lock) so refresh/replay works.
    try:
        from backend.generation.study_materials.orchestrator_singleton import study_material_tasks

        await study_material_tasks.restore_tasks_from_disk()
    except Exception:
        logger.exception("study_material_tasks_restore_failed")

    stop = asyncio.Event()
    worker_task: Optional[asyncio.Task] = None
    cleanup_task: Optional[asyncio.Task] = None
    if _env_truthy(
        "QUESTION_LIBRARY_WORKER_ENABLED", default=_env_truthy("QUESTION_LIBRARY_AUTO_SCORE", default=False)
    ):
        worker_task = asyncio.create_task(run_question_library_scoring_worker(stop=stop))
    if _env_truthy("GENERATED_FILES_CLEANUP_ENABLED", default=True):
        cleanup_task = asyncio.create_task(_run_generated_files_cleanup_worker(stop=stop))
    try:
        yield
    finally:
        stop.set()
        # Best-effort: cancel long-running tasks so DB isn't stuck at `running`.
        try:
            from backend.shared.tasks import task_runtime

            await task_runtime.shutdown(reason="server_shutdown")
        except Exception:
            logger.exception("task_runtime_shutdown_failed")
        try:
            from backend.generation.study_materials.orchestrator_singleton import study_material_tasks

            await study_material_tasks.shutdown(reason="server_shutdown")
        except Exception:
            logger.exception("study_materials_shutdown_failed")

        if worker_task is not None:
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                worker_task.cancel()
            except asyncio.CancelledError:
                logger.info("worker_cancelled")
            except Exception:
                logger.exception("worker_shutdown_failed")
        if cleanup_task is not None:
            try:
                await asyncio.wait_for(cleanup_task, timeout=5.0)
            except asyncio.TimeoutError:
                cleanup_task.cancel()
            except asyncio.CancelledError:
                logger.info("cleanup_task_cancelled")
            except Exception:
                logger.exception("cleanup_task_shutdown_failed")
        await close_crawler()
        await close_shared_llm_http_client()
        await close_proxy_http_client()


def create_app() -> FastAPI:
    app = FastAPI(
        title="智能组卷辅助系统",
        description="基于AI的组卷网题目搜索和筛选系统",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Prometheus /metrics + request instrumentation (configurable).
    instrument_app(app)

    # Security warnings for proxy-header trust settings (startup-time).
    _warn_proxy_settings_on_startup()
    log_config_check()

    # Optional OpenTelemetry tracing (disabled by default; enable with OTEL_ENABLE=1).
    try:
        from backend.core.otel import setup_otel

        setup_otel(app)
    except Exception:
        logger.exception("otel_setup_failed")

    # CORS: restrict origins in production; allow localhost for dev.
    cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    cors_origins = [o.strip() for o in cors_origins if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-LLM-API-Key",
            "X-Moonshot-API-Key",
        ],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(InputValidationMiddleware)

    register_security_headers_middleware(app)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        rid = ensure_request_id(request)
        detail = exc.detail
        msg = detail if isinstance(detail, str) else str(ErrorCode.HTTP_ERROR)
        code = f"http_{int(exc.status_code or 500)}"
        if isinstance(detail, str):
            candidate = detail.strip()
            if is_safe_error_code(candidate):
                code = candidate
        payload = build_error_payload(
            code=code,
            message=str(msg if isinstance(msg, str) else str(msg)),
            details=detail,
            request_id=rid,
            http_status=int(exc.status_code or 500),
        )
        response = JSONResponse(status_code=int(exc.status_code or 500), content=payload)
        response.headers.setdefault("X-Request-ID", rid)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = ensure_request_id(request)
        errors = exc.errors()
        for err in errors:
            if str(err.get("type") or "").strip() != "string_too_long":
                continue
            loc = [str(part).strip() for part in list(err.get("loc") or []) if str(part).strip() not in {"body"}]
            field = "_".join(loc) or "input"
            code = f"{field}_too_long"
            payload = build_error_payload(
                code=code,
                message="input_too_long",
                details=code,
                request_id=rid,
                http_status=400,
            )
            response = JSONResponse(status_code=400, content=payload)
            response.headers.setdefault("X-Request-ID", rid)
            return response

        payload = build_error_payload(
            code=str(ErrorCode.VALIDATION_ERROR),
            message=str(ErrorCode.VALIDATION_ERROR),
            details=errors,
            request_id=rid,
            http_status=422,
        )
        response = JSONResponse(status_code=422, content=payload)
        response.headers.setdefault("X-Request-ID", rid)
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"path": str(request.url.path or "")})
        rid = ensure_request_id(request)
        payload = build_error_payload(
            code=str(ErrorCode.INTERNAL_ERROR),
            message=str(ErrorCode.INTERNAL_ERROR),
            details=str(ErrorCode.INTERNAL_ERROR),
            request_id=rid,
            http_status=500,
        )
        response = JSONResponse(status_code=500, content=payload)
        response.headers.setdefault("X-Request-ID", rid)
        return response

    register_request_id_middleware(app, client_ip=_client_ip)
    register_rate_limit_middleware(app, client_ip=_client_ip)

    @app.middleware("http")
    async def llm_api_key_override_middleware(request: Request, call_next):
        """
        Allow the frontend to supply an LLM API key per request (saved in browser localStorage).

        Security notes:
        - The key is only held in-memory for the duration of the request (ContextVar).
        - Never persist/log the key (tasks snapshots, events, db, etc.).
        """

        llm_key_header = str(request.headers.get("X-LLM-API-Key") or "").strip()
        moonshot_key_header = str(request.headers.get("X-Moonshot-API-Key") or "").strip()
        has_override_headers = bool(llm_key_header or moonshot_key_header)

        allow_override = _env_truthy("LLM_API_KEY_OVERRIDE_ENABLED", default=False)
        require_admin = _env_truthy("LLM_API_KEY_OVERRIDE_REQUIRE_ADMIN", default=True)
        permitted = allow_override

        if has_override_headers and not allow_override:
            raise HTTPException(status_code=403, detail="llm_api_key_override_disabled")

        if permitted and require_admin and has_override_headers:
            payload = None
            auth = str(request.headers.get("Authorization") or "")
            if auth.lower().startswith("bearer "):
                payload = validate_access_token(auth[7:].strip())
            if not payload:
                payload = local_auth_user()
            role = str((payload or {}).get("role") or "").strip()
            if role != "admin":
                raise HTTPException(status_code=403, detail="llm_api_key_override_forbidden")
            try:
                audit_logger.log(
                    user_id=str((payload or {}).get("user_id") or "").strip(),
                    action=AuditAction.API_KEY_USE,
                    resource="/api/* (llm_api_key_override)",
                    details={
                        "llm_key_override": bool(llm_key_header),
                        "moonshot_key_override": bool(moonshot_key_header),
                    },
                )
            except Exception:
                # Best-effort only; never block request on audit failures.
                logger.exception("audit_api_key_use_failed")

        llm_token = set_llm_api_key_override(llm_key_header if permitted else "")
        moonshot_token = set_moonshot_api_key_override(moonshot_key_header if permitted else "")
        try:
            return await call_next(request)
        finally:
            reset_llm_api_key_override(llm_token)
            reset_moonshot_api_key_override(moonshot_token)

    app.include_router(api_router)

    assets_path = DIST_PATH / "assets"
    if assets_path.exists():
        app.mount("/assets", _CachedAssetFiles(directory=assets_path), name="assets")

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "HEAD"],
    )
    async def serve_spa(full_path: str):
        """
        Serving Single Page Application.

        - `/api/*` 已由 API 路由处理；这里兜底返回 404。
        - `/assets/*` 已由 StaticFiles 托管。
        - 其他路径返回 `index.html`，交由前端路由处理。
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        index_path = DIST_PATH / "index.html"
        if index_path.exists():
            # Prevent stale SPA shells after redeploys/builds. Asset files are fingerprinted
            # (hashed) so they can still be cached safely.
            return FileResponse(index_path, headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"})
        raise HTTPException(
            status_code=503,
            detail="Frontend not built. Please run 'npm run build' in frontend directory.",
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True, log_level="info")
