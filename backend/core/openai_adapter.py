"""Compatibility entrypoint for the OpenAI Function Calling adapter.

The canonical routes live in `backend.api.integrations.openai_adapter` and are
included by the main FastAPI app through the integrations domain. This module
only preserves the old standalone `python -m backend.core.openai_adapter` server.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

if __package__ is None or __package__ == "":
    # Allow running as a script: `python backend/core/openai_adapter.py`
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.api.integrations.openai_adapter import router as openai_adapter_router
from backend.integrations.crawler.manager import close_crawler as close_subject_crawlers
from backend.database.engine import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await close_subject_crawlers()


def create_app() -> FastAPI:
    app = FastAPI(
        title="组卷助手 - OpenAI API",
        description="为 OpenAI Function Calling 提供的题目搜索 API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(openai_adapter_router, prefix="/api")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
