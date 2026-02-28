from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.crawler_manager import get_crawler
from backend.subjects import get_all_subjects, resolve_subject

router = APIRouter()


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

    return {
        "grades": _keep_id_name_list(grades),
        "textbookVersions": _keep_id_name_list(textbook_versions),
        "provinces": _keep_id_name_list(provinces),
        "paperTypes": paper_types,
        "questionTypes": _keep_id_name_list(question_types),
    }

