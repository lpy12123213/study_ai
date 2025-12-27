"""
FastAPI 后端服务入口。

API 路由在 `backend/api/` 下；此文件负责：
- CORS 等中间件
- 应用生命周期（初始化数据库）
- 生产环境静态文件托管（`frontend/dist`）
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

if __package__ is None or __package__ == "":
    # Allow running as a script: `python backend/app.py`
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.api.router import api_router
from database.models import init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_PATH = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="智能组卷辅助系统",
        description="基于AI的组卷网题目搜索和筛选系统",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    assets_path = DIST_PATH / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

    @app.get("/{full_path:path}")
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
            return FileResponse(index_path)
        return {"message": "Frontend not found. Please run 'npm run build' in frontend directory."}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True, log_level="info")
