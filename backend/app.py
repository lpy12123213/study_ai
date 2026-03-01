"""
FastAPI 后端服务入口。

API 路由在 `backend/api/` 下；此文件负责：
- CORS 等中间件
- 应用生命周期（初始化数据库）
- 生产环境静态文件托管（`frontend/dist`）
"""

from __future__ import annotations

import os
import sys
import asyncio
import hashlib
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

if __package__ is None or __package__ == "":
    # Allow running as a script: `python backend/app.py`
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.api.router import api_router
from backend.crawler_manager import close_crawler
from backend.core.llm_client import (
    reset_llm_api_key_override,
    reset_moonshot_api_key_override,
    set_llm_api_key_override,
    set_moonshot_api_key_override,
)
from backend.database.models import init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = PROJECT_ROOT / "frontend" / "dist"

# NOTE: This app includes the new `/api/study-materials/*` routes via `backend/api/router.py`.


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await close_crawler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="智能组卷辅助系统",
        description="基于AI的组卷网题目搜索和筛选系统",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS: restrict origins in production; allow localhost for dev.
    cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    cors_origins = [o.strip() for o in cors_origins if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rate_limit_max = int(os.getenv("API_RATE_LIMIT_MAX_REQUESTS") or "300")
    rate_limit_window_s = float(os.getenv("API_RATE_LIMIT_WINDOW_S") or "60")
    rate_limit_max = max(0, min(rate_limit_max, 50_000))
    rate_limit_window_s = max(1.0, min(rate_limit_window_s, 3600.0))

    _rate_lock = asyncio.Lock()
    _rate_hits: dict[str, deque[float]] = defaultdict(deque)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if rate_limit_max <= 0:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)

        key = ""
        auth = str(request.headers.get("Authorization") or "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
                key = f"token:{digest}"

        if not key:
            host = (request.client.host if request.client else "") or "unknown"
            key = f"ip:{host}"

        now = time.monotonic()
        async with _rate_lock:
            bucket = _rate_hits[key]
            while bucket and (now - bucket[0]) > rate_limit_window_s:
                bucket.popleft()
            if len(bucket) >= rate_limit_max:
                return JSONResponse(status_code=429, content={"detail": "rate_limited"})
            bucket.append(now)

            # Best-effort pruning to avoid unbounded memory in long-running processes.
            if len(_rate_hits) > 10_000:
                for k in list(_rate_hits.keys())[:2000]:
                    b = _rate_hits.get(k)
                    if not b:
                        _rate_hits.pop(k, None)

        return await call_next(request)

    @app.middleware("http")
    async def llm_api_key_override_middleware(request: Request, call_next):
        """
        Allow the frontend to supply an LLM API key per request (saved in browser localStorage).

        Security notes:
        - The key is only held in-memory for the duration of the request (ContextVar).
        - Never persist/log the key (tasks snapshots, events, db, etc.).
        """

        llm_key_header = request.headers.get("X-LLM-API-Key", "")
        moonshot_key_header = request.headers.get("X-Moonshot-API-Key", "")

        llm_token = set_llm_api_key_override(llm_key_header)
        moonshot_token = set_moonshot_api_key_override(moonshot_key_header)
        try:
            return await call_next(request)
        finally:
            reset_llm_api_key_override(llm_token)
            reset_moonshot_api_key_override(moonshot_token)

    app.include_router(api_router)

    assets_path = DIST_PATH / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

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
