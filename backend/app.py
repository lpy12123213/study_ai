"""
FastAPI 后端服务入口。

API 路由在 `backend/api/` 下；此文件负责：
- CORS 等中间件
- 应用生命周期（初始化数据库）
- 生产环境静态文件托管（`frontend/dist`）
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
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
from backend.core.client_ip import (
    _is_trusted_proxy,  # noqa: F401 - re-exported for external wiring compatibility
    _parse_trusted_proxies,  # noqa: F401 - re-exported for external wiring compatibility
    _trusted_proxy_networks,  # noqa: F401 - re-exported for external wiring compatibility
)
from backend.core.client_ip import client_ip as _client_ip
from backend.core.client_ip import warn_proxy_settings_on_startup as _warn_proxy_settings_on_startup
from backend.core.config_check import log_config_check
from backend.core.logging_utils import configure_logging, get_logger
from backend.core.metrics import instrument_app
from backend.core.settings import env_bool, env_int
from backend.database.engine import init_db
from backend.generation.question_library.worker import run_question_library_scoring_worker
from backend.integrations.crawler.manager import close_crawler
from backend.llm.client import (
    close_shared_llm_http_client,
    reset_llm_api_key_override,
    reset_moonshot_api_key_override,
    set_llm_api_key_override,
    set_moonshot_api_key_override,
)
from backend.media.generated import cleanup_expired_generated_files

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = PROJECT_ROOT / "frontend" / "dist"

# NOTE: This app includes the new `/api/study-materials/*` routes via `backend/api/router.py`.

_log_format = (os.getenv("LOG_FORMAT") or "").strip().lower()
configure_logging(force=(not _log_format or _log_format == "json"))
logger = get_logger(__name__)


async def _run_generated_files_cleanup_worker(*, stop: asyncio.Event) -> None:
    # Default: cleanup every 30 minutes.
    interval_s = max(60, min(env_int("GENERATED_FILES_CLEANUP_INTERVAL_S", default=30 * 60), 24 * 60 * 60))
    while not stop.is_set():
        try:
            await cleanup_expired_generated_files(limit=env_int("GENERATED_FILES_CLEANUP_BATCH", default=500))
        except Exception:
            logger.exception("generated_files_cleanup_failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=float(interval_s))
        except asyncio.TimeoutError:
            continue


class _CachedAssetFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        try:
            if resp.status_code == 200:
                resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        except Exception:
            logger.exception("failed to set cache headers for asset")
        return resp


def _study_materials_model_self_check_enabled() -> bool:
    """Startup model self-check is skipped under pytest/TestClient and via env opt-out."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if "pytest" in sys.modules:
        return False
    return env_bool("STUDY_MATERIALS_MODEL_SELF_CHECK", default=True)


async def _study_materials_model_self_check() -> None:
    """Ping the study-materials thinking/writer models once (max_tokens=1).

    A deprecated or misspelled model id makes every LLM call fail permanently (4xx);
    without this check that only surfaces as each knowledge point burning its full
    step timeout. Log loudly at startup instead. Never raises.
    """
    from backend.core import settings as _settings
    from backend.llm import client as _llm_client

    candidates = [
        ("STUDY_MATERIALS_THINKING_MODEL", str(_settings.STUDY_MATERIALS_THINKING_MODEL or "").strip()),
        ("STUDY_MATERIALS_WRITER_MODEL", str(_settings.STUDY_MATERIALS_WRITER_MODEL or "").strip()),
    ]
    checked: set = set()
    for env_name, model in candidates:
        if not model or model in checked:
            continue
        checked.add(model)
        try:
            result = await _llm_client.chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                model=model,
                temperature=0.0,
                max_tokens=1,
                retries=1,
                raise_on_fail=False,
                req_id_prefix="selfcheck",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("study_materials_model_self_check_error", extra={"model": model, "env": env_name})
            continue
        error_code = str(getattr(result, "error_code", "") or "")
        if error_code == "4xx":
            logger.error(
                "study_materials_model_self_check_failed",
                extra={
                    "model": model,
                    "env": env_name,
                    "status": error_code,
                    "hint": f"模型调用永久失败（4xx）：请检查 {env_name}（当前={model}）是否为已下线或拼错的模型 ID",
                },
            )
        elif error_code:
            logger.warning(
                "study_materials_model_self_check_degraded",
                extra={"model": model, "env": env_name, "error_code": error_code},
            )


async def _run_study_materials_model_self_check() -> None:
    try:
        await asyncio.wait_for(_study_materials_model_self_check(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.warning("study_materials_model_self_check_timeout", extra={"timeout_s": 15.0})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("study_materials_model_self_check_unexpected_error")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()

    # After the schema is ready, retry the auth bootstrap so the admin row is
    # always present. The module-level call inside ``backend.core.auth`` is
    # best-effort and may have been skipped on a fresh DB.
    try:
        from backend.core import auth as _auth_mod

        _auth_mod._migrate_local_snapshot_into_db()
        _auth_mod._bootstrap_admin_once()
    except Exception:
        logger.warning("auth_lifespan_bootstrap_failed", exc_info=True)

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

    # Non-blocking startup self-check: a deprecated study-materials model id fails every
    # LLM call permanently, so surface it as one loud log line instead of per-step timeouts.
    self_check_task: Optional[asyncio.Task] = None
    if _study_materials_model_self_check_enabled():
        self_check_task = asyncio.create_task(_run_study_materials_model_self_check())

    stop = asyncio.Event()
    worker_task: Optional[asyncio.Task] = None
    cleanup_task: Optional[asyncio.Task] = None
    if env_bool(
        "QUESTION_LIBRARY_WORKER_ENABLED", default=env_bool("QUESTION_LIBRARY_AUTO_SCORE", default=False)
    ):
        worker_task = asyncio.create_task(run_question_library_scoring_worker(stop=stop))
    if env_bool("GENERATED_FILES_CLEANUP_ENABLED", default=True):
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
        if self_check_task is not None:
            try:
                await asyncio.wait_for(self_check_task, timeout=2.0)
            except asyncio.TimeoutError:
                self_check_task.cancel()
            except asyncio.CancelledError:
                logger.info("study_materials_model_self_check_cancelled")
            except Exception:
                logger.exception("study_materials_model_self_check_shutdown_failed")
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

    # Browsers reject `Access-Control-Allow-Origin: *` on credentialed requests, so
    # allow_credentials=True + "*" silently breaks cross-site cookie auth.
    if "*" in cors_origins:
        logger.warning(
            "cors_star_with_credentials_invalid",
            extra={
                "hint": "CORS_ORIGINS contains '*'; with allow_credentials=True browsers reject "
                "credentialed requests. Set an explicit origin allowlist for cross-site cookie auth."
            },
        )

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
        # 流式 generate/continue 响应通过 X-Task-Id 头暴露新任务 id，浏览器跨源读取需显式 expose。
        expose_headers=["X-Task-Id"],
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

        allow_override = env_bool("LLM_API_KEY_OVERRIDE_ENABLED", default=False)
        require_admin = env_bool("LLM_API_KEY_OVERRIDE_REQUIRE_ADMIN", default=True)
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
