from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.auth import require_auth
from backend.api.canvas_schemas import CanvasBoardCreate, CanvasBoardUpdate
from backend.config import DEFAULT_SUBJECT
from backend.crawler_manager import get_crawler
from backend.database.models import (
    create_canvas_board,
    create_canvas_board_version,
    get_canvas_board,
    get_canvas_board_version,
    list_canvas_board_versions,
    list_canvas_boards,
    update_canvas_board,
)
from backend.subjects import resolve_subject

router = APIRouter(prefix="/canvas", dependencies=[Depends(require_auth)])


def _parse_snapshot(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _snapshot_max_bytes() -> int:
    raw = str(os.getenv("CANVAS_SNAPSHOT_MAX_BYTES") or "").strip()
    try:
        value = int(raw) if raw else 2 * 1024 * 1024
    except Exception:
        value = 2 * 1024 * 1024
    return max(1024, min(value, 20 * 1024 * 1024))


def _serialize_snapshot(snapshot: Dict[str, Any]) -> str:
    try:
        raw = json.dumps(snapshot, ensure_ascii=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_snapshot: {str(exc)}")

    if len(raw.encode("utf-8")) > _snapshot_max_bytes():
        raise HTTPException(status_code=413, detail="snapshot_too_large")
    return raw


def _normalize_asset_url(raw: str, base_url: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/"):
        return f"{base_url.rstrip('/')}{raw}"
    return raw


def _is_safe_http_url(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    return bool(parsed.netloc)


def _sanitize_question_html(html: str, *, base_url: str) -> str:
    """
    Sanitize and rewrite question stem HTML for safe rendering in the frontend.

    - Removes potentially dangerous tags.
    - Strips inline event handlers (onClick, etc.).
    - Rewrites <img> sources to `/api/media/proxy?url=...` for on-demand download + cache.
    """
    html = html or ""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "iframe", "object", "embed", "link", "meta"]):
        tag.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag.attrs[attr]

    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or "").strip()
        if not src:
            img.decompose()
            continue
        full = _normalize_asset_url(src, base_url)
        if not full or not _is_safe_http_url(full):
            img.decompose()
            continue
        img.attrs = {"src": f"/api/media/proxy?url={quote(full, safe='')}", "loading": "lazy"}

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = _normalize_asset_url(href, base_url)
        if not full or not _is_safe_http_url(full):
            # Keep the text, but prevent scriptable/unsafe links.
            if "href" in a.attrs:
                del a.attrs["href"]
            if "target" in a.attrs:
                del a.attrs["target"]
            if "rel" in a.attrs:
                del a.attrs["rel"]
            continue
        a.attrs = {
            **{k: v for k, v in a.attrs.items() if k not in {"href", "target", "rel"}},
            "href": full,
            "target": "_blank",
            "rel": "noreferrer noopener",
        }

    container = soup.body if soup.body else soup
    return container.decode_contents()


class CanvasPickQuestionsRequest(BaseModel):
    requirement: str = Field(min_length=1, max_length=800)
    subject: Optional[str] = Field(default=None, max_length=100)
    edu_level: Optional[str] = Field(default=None, max_length=50)
    count: int = Field(default=3, ge=1, le=10)
    model: Optional[str] = Field(default=None, max_length=200)
    limit: int = Field(default=25, ge=5, le=50)
    max_pages: int = Field(default=2, ge=1, le=8)


@router.get("/boards")
async def list_boards(limit: int = Query(50, ge=1, le=200), q: str = Query(""), user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    boards = await list_canvas_boards(user_id=user_id, limit=limit, query=q)
    return {"success": True, "boards": boards}


@router.post("/boards")
async def create_board(payload: CanvasBoardCreate, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    snapshot_raw = ""
    if payload.snapshot is not None:
        snapshot_raw = _serialize_snapshot(payload.snapshot)

    board = await create_canvas_board(
        user_id=user_id,
        title=(payload.title or "").strip(),
        subject=(payload.subject or "").strip(),
        snapshot=snapshot_raw,
    )
    return {"success": True, "board": board}


@router.get("/boards/{board_id}")
async def get_board(board_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    board = await get_canvas_board(user_id=user_id, board_id=board_id)
    if not board:
        raise HTTPException(status_code=404, detail="board_not_found")

    snapshot = _parse_snapshot(board.get("snapshot", ""))
    out = dict(board)
    out["snapshot"] = snapshot
    return {"success": True, "board": out}


@router.put("/boards/{board_id}")
async def put_board(board_id: int, payload: CanvasBoardUpdate, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    snapshot_raw = None
    if payload.snapshot is not None:
        snapshot_raw = _serialize_snapshot(payload.snapshot)

    result = await update_canvas_board(
        user_id,
        board_id,
        title=payload.title,
        subject=payload.subject,
        snapshot=snapshot_raw,
        expected_revision=payload.expected_revision,
    )

    if not result.get("success") and result.get("conflict"):
        server_board = result.get("server_board") or {}
        server_board["snapshot"] = _parse_snapshot(server_board.get("snapshot", ""))
        return {"success": False, "conflict": True, "server_board": server_board}

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "update_failed")

    board = result.get("board") or {}
    board["snapshot"] = _parse_snapshot(board.get("snapshot", ""))
    return {"success": True, "board": board}


@router.get("/boards/{board_id}/versions")
async def get_versions(board_id: int, limit: int = Query(30, ge=1, le=200), user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    versions = await list_canvas_board_versions(user_id=user_id, board_id=board_id, limit=limit)
    return {"success": True, "versions": versions}


@router.post("/boards/{board_id}/versions")
async def create_version(board_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    result = await create_canvas_board_version(user_id=user_id, board_id=board_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "board_not_found")
    return result


@router.get("/boards/{board_id}/versions/{version_id}")
async def get_version(board_id: int, version_id: int, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    version = await get_canvas_board_version(user_id=user_id, board_id=board_id, version_id=version_id)
    if not version:
        raise HTTPException(status_code=404, detail="version_not_found")
    snapshot = _parse_snapshot(version.get("snapshot", ""))
    out = dict(version)
    out["snapshot"] = snapshot
    return {"success": True, "version": out}


@router.post("/boards/{board_id}/pick-questions")
async def pick_questions(board_id: int, payload: CanvasPickQuestionsRequest, user: dict = Depends(require_auth)) -> dict:
    """
    Use crawler + MCP sub-AI selector to pick questions, then return render-ready HTML.

    Notes:
    - Formula rendering: inline SVG (no svg2latex).
    - Images: rewritten to `/api/media/proxy` for on-demand download + cache.
    """
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    board = await get_canvas_board(user_id=user_id, board_id=board_id)
    if not board:
        raise HTTPException(status_code=404, detail="board_not_found")

    requirement = (payload.requirement or "").strip()
    if not requirement:
        raise HTTPException(status_code=400, detail="requirement_required")

    subject_input = (payload.subject or board.get("subject") or DEFAULT_SUBJECT).strip()
    edu_level = (payload.edu_level or "").strip()

    try:
        subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)

    search_result = await crawler.search_by_keyword(
        keyword=requirement,
        edu_level=edu_level,
        limit=max(int(payload.limit), int(payload.count) * 6),
        max_pages=int(payload.max_pages),
        require_difficulty=True,
        strict_subject=True,
    )
    if not search_result.get("success"):
        return {"success": False, "error": "search_failed", "details": search_result}

    candidates = search_result.get("questions") or []
    # Stable de-dupe while preserving order
    seen_ids = set()
    candidate_questions: List[Dict[str, Any]] = []
    for q in candidates:
        if not isinstance(q, dict):
            continue
        qid = (q.get("question_id") or "").strip()
        if not qid or qid in seen_ids:
            continue
        seen_ids.add(qid)
        candidate_questions.append(q)

    if not candidate_questions:
        return {
            "success": False,
            "error": "no_candidates",
            "details": {"subject": subject, "edu_level": edu_level, "search_result": search_result},
        }

    # MCP sub-AI selector (picks one from 2-8 candidates each round)
    from backend.mcp.sub_ai_selector import select_best_question

    selected_ids: List[str] = []
    selection: List[Dict[str, Any]] = []
    remaining = list(candidate_questions)

    for _ in range(int(payload.count)):
        if not remaining:
            break

        subset = remaining[: min(len(remaining), 8)]
        if len(subset) == 1:
            chosen_id = str(subset[0].get("question_id") or "").strip()
            if chosen_id:
                selected_ids.append(chosen_id)
                selection.append(
                    {
                        "selected_question_id": chosen_id,
                        "reason": "候选不足，直接选取",
                        "analysis": "",
                    }
                )
                remaining = [q for q in remaining if (q.get("question_id") or "").strip() != chosen_id]
            continue

        req = requirement
        if selected_ids:
            req = f"{requirement}\n已选题目ID：{', '.join(selected_ids)}。请不要重复选择已选题。"

        sel = await select_best_question(questions=subset, requirement=req, model=payload.model)
        if not sel.get("success"):
            return {"success": False, "error": "select_failed", "details": sel}

        chosen_id = str(sel.get("selected_question_id") or "").strip()
        if not chosen_id:
            return {"success": False, "error": "select_failed_empty_id", "details": sel}

        selection.append(sel)
        selected_ids.append(chosen_id)
        remaining = [q for q in remaining if (q.get("question_id") or "").strip() != chosen_id]

    if not selected_ids:
        return {"success": False, "error": "select_failed_no_results", "details": selection}

    tasks = [
        crawler.get_question_detail(qid, formula_mode="svg", stem_mode="html") for qid in selected_ids
    ]
    details = await asyncio.gather(*tasks, return_exceptions=True)

    reason_by_id = {
        str(s.get("selected_question_id") or "").strip(): (s.get("reason") or "")
        for s in selection
        if isinstance(s, dict)
    }

    out_questions: List[Dict[str, Any]] = []
    for qid, detail in zip(selected_ids, details):
        if isinstance(detail, Exception):
            out_questions.append(
                {
                    "question_id": qid,
                    "success": False,
                    "error": str(detail),
                    "select_reason": reason_by_id.get(qid, ""),
                }
            )
            continue

        if not isinstance(detail, dict) or not detail.get("success"):
            out_questions.append(
                {
                    "question_id": qid,
                    "success": False,
                    "error": (detail or {}).get("error") if isinstance(detail, dict) else "detail_failed",
                    "detail": detail,
                    "select_reason": reason_by_id.get(qid, ""),
                }
            )
            continue

        stem_html = _sanitize_question_html(detail.get("stem_html", ""), base_url=getattr(crawler, "base_url", ""))
        meta_parts = []
        if (detail.get("type") or "").strip():
            meta_parts.append(str(detail.get("type")).strip())
        if (detail.get("difficulty") or "").strip():
            meta_parts.append(str(detail.get("difficulty")).strip())
        meta = " · ".join(meta_parts)

        out_questions.append(
            {
                "success": True,
                "question_id": detail.get("question_id") or qid,
                "title": f"题目 {detail.get('question_id') or qid}",
                "meta": meta,
                "stem_html": stem_html,
                "type": detail.get("type") or "",
                "difficulty": detail.get("difficulty") or "",
                "knowledge_points": detail.get("knowledge_points") or "",
                "source": detail.get("source") or "",
                "url": detail.get("url") or "",
                "select_reason": reason_by_id.get(qid, ""),
            }
        )

    return {
        "success": True,
        "subject": subject,
        "edu_level": edu_level,
        "requirement": requirement,
        "candidate_count": len(candidate_questions),
        "selected_ids": selected_ids,
        "questions": out_questions,
        "selection": selection,
    }


@router.get("/questions/{question_id}/render")
async def render_question(
    question_id: str,
    subject: str = Query("", max_length=100),
    edu_level: str = Query("", max_length=50),
) -> dict:
    """Render a single question as HTML with inline SVG formulas and cached images."""
    subject_input = (subject or DEFAULT_SUBJECT).strip()
    edu_level = (edu_level or "").strip()
    try:
        resolved = resolve_subject(subject_input, edu_level=edu_level, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    crawler = await get_crawler(subject=resolved, edu_level=edu_level, strict=True)
    detail = await crawler.get_question_detail(question_id, formula_mode="svg", stem_mode="html")
    if not detail.get("success"):
        raise HTTPException(status_code=400, detail=detail.get("error") or "render_failed")

    stem_html = _sanitize_question_html(detail.get("stem_html", ""), base_url=getattr(crawler, "base_url", ""))
    return {"success": True, "question": {**detail, "stem_html": stem_html}}
