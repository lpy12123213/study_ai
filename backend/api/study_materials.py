"""Study materials streaming API endpoints."""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.agent.core import AgentCore
from backend.api.auth import get_current_user
from backend.api.study_materials_schemas import StudyMaterialsGenerateRequest


router = APIRouter(prefix="/study-materials", tags=["study-materials"])

_agent = AgentCore()


def _env_truthy(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _clip_text(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    t = (text or "")
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


@router.post("/generate")
async def generate_study_materials(
    request: StudyMaterialsGenerateRequest,
    user: Optional[dict] = Depends(get_current_user),
):
    """Generate study materials using Plan-Act-Reflect with streaming SSE."""

    user_id = (user.get("user_id") if user else None) or "anonymous"
    # Default-on tracing so the backend command line shows tool I/O + assistant output.
    # Set `STUDY_MATERIALS_TRACE=0` to disable.
    raw_trace = os.getenv("STUDY_MATERIALS_TRACE")
    trace = True if raw_trace is None else _env_truthy("STUDY_MATERIALS_TRACE")
    trace_stream = _env_truthy("STUDY_MATERIALS_TRACE_STREAM")
    try:
        max_md_chars = int(os.getenv("STUDY_MATERIALS_TRACE_MARKDOWN_MAX_CHARS") or "8000")
    except ValueError:
        max_md_chars = 8000
    max_md_chars = max(0, min(max_md_chars, 200000))

    async def event_generator():
        assistant_chunks: list[str] = []

        def _p(line: str) -> None:
            if not trace:
                return
            try:
                print(line, flush=True)
            except Exception:
                pass

        if trace:
            _p(f"[study-materials] start user_id={user_id} query={request.query!r}")

        async for event in _agent.run(request.query, user_id=user_id):
            if trace:
                kind = str(event.get("event") or "")
                data = event.get("data") if isinstance(event.get("data"), dict) else {}

                if kind == "thinking":
                    content = str(data.get("content") or "")
                    _p(f"[study-materials] thinking: {_clip_text(content, max_chars=400)}")
                elif kind == "tool_call":
                    name = str(data.get("name") or "")
                    step_id = str(data.get("step_id") or "")
                    args = data.get("arguments")
                    try:
                        args_json = json.dumps(args, ensure_ascii=False)
                    except Exception:
                        args_json = str(args)
                    _p(
                        f"[study-materials] tool_call: {name} step_id={step_id} "
                        f"args={_clip_text(args_json, max_chars=2000)}"
                    )
                elif kind == "tool_result":
                    name = str(data.get("name") or "")
                    step_id = str(data.get("step_id") or "")
                    success = bool(data.get("success") is True)
                    elapsed_ms = data.get("elapsed_ms")
                    err = str(data.get("error") or "")
                    out = data.get("output")
                    try:
                        out_json = json.dumps(out, ensure_ascii=False)
                    except Exception:
                        out_json = str(out)
                    meta = f"success={success}"
                    if elapsed_ms is not None:
                        meta += f" elapsed_ms={elapsed_ms}"
                    if err:
                        meta += f" error={_clip_text(err, max_chars=300)}"
                    _p(
                        f"[study-materials] tool_result: {name} step_id={step_id} {meta} "
                        f"output={_clip_text(out_json, max_chars=2000)}"
                    )
                elif kind == "content":
                    chunk = str(data.get("content") or "")
                    if chunk:
                        assistant_chunks.append(chunk)
                        if trace_stream:
                            try:
                                print(chunk, end="", flush=True)
                            except Exception:
                                pass
                elif kind == "done":
                    material = data.get("material") if isinstance(data.get("material"), dict) else {}
                    md = str(material.get("markdown") or "")
                    if not md:
                        md = "".join(assistant_chunks)
                    archive_path = str(material.get("archive_path") or "")
                    _p(f"[study-materials] done: archive_path={archive_path!r} markdown_chars={len(md)}")
                    if max_md_chars > 0 and md:
                        _p("[study-materials] assistant_markdown:")
                        _p(_clip_text(md, max_chars=max_md_chars))
                elif kind == "error":
                    msg = str(data.get("message") or "")
                    _p(f"[study-materials] error: {_clip_text(msg, max_chars=800)}")

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

