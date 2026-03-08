from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.crawler_manager import get_crawler
from backend.subjects import get_all_subjects, resolve_subject

router = APIRouter()
_SUBJECT_FILTERS_CACHE: dict[str, tuple[float, dict]] = {}


def clear_subject_filters_cache() -> None:
    _SUBJECT_FILTERS_CACHE.clear()


def _subject_filters_cache_ttl_s() -> float:
    raw = str(os.getenv("SUBJECT_FILTERS_CACHE_TTL_S") or "").strip()
    try:
        ttl = float(raw) if raw else 10 * 60.0
    except Exception:
        ttl = 10 * 60.0
    return max(0.0, min(ttl, 24.0 * 60.0 * 60.0))


@router.get("/subjects")
async def get_subjects_list() -> dict:
    """获取支持的学科列表"""
    return {"subjects": get_all_subjects()}


@router.get("/subjects/{subject_code}/filters")
async def get_subject_filters(subject_code: str, user: dict = Depends(require_auth)) -> dict:
    """
    获取某学科可用筛选项（年级/教材版本/地区/题型等）。

    前端期望字段：grades/textbookVersions/provinces/paperTypes/questionTypes。
    """
    _ = user  # auth gate (avoid anonymous crawling)

    subject_input = (subject_code or "").strip()
    if not subject_input:
        raise HTTPException(status_code=400, detail="missing_subject")

    try:
        subject = resolve_subject(subject_input, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ttl_s = _subject_filters_cache_ttl_s()
    cached = _SUBJECT_FILTERS_CACHE.get(subject)
    if ttl_s > 0 and cached and (time.time() - cached[0]) <= ttl_s:
        return dict(cached[1])

    crawler = await get_crawler(subject=subject, edu_level="", strict=True)
    result = await crawler.get_available_filters()
    if not isinstance(result, dict) or not result.get("success"):
        raise HTTPException(status_code=500, detail=str((result or {}).get("error") or "filters_failed"))

    grades = result.get("grades") or []
    textbook_versions = result.get("textbook_versions") or []
    provinces = result.get("provinces") or []
    question_types = result.get("question_types") or []

    paper_types: list = []
    paper_types_by_grade = result.get("paper_types_by_grade") or {}
    if isinstance(paper_types_by_grade, dict):
        seen = set()
        for _gid, items in paper_types_by_grade.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                pid = it.get("id")
                name = it.get("name")
                if pid is None or name is None:
                    continue
                key = str(pid)
                if key in seen:
                    continue
                seen.add(key)
                paper_types.append({"id": int(pid), "name": str(name)})

    def _keep_id_name_list(items):
        out = []
        if not isinstance(items, list):
            return out
        for it in items:
            if not isinstance(it, dict):
                continue
            if "id" not in it or "name" not in it:
                continue
            out.append({"id": it.get("id"), "name": it.get("name")})
        return out

    payload = {
        "grades": _keep_id_name_list(grades),
        "textbookVersions": _keep_id_name_list(textbook_versions),
        "provinces": _keep_id_name_list(provinces),
        "paperTypes": paper_types,
        "questionTypes": _keep_id_name_list(question_types),
    }
    if ttl_s > 0:
        _SUBJECT_FILTERS_CACHE[subject] = (time.time(), dict(payload))
        if len(_SUBJECT_FILTERS_CACHE) > 128:
            oldest_key = min(_SUBJECT_FILTERS_CACHE, key=lambda key: _SUBJECT_FILTERS_CACHE[key][0])
            _SUBJECT_FILTERS_CACHE.pop(oldest_key, None)
    return payload
