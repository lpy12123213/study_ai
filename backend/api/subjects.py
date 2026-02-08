from __future__ import annotations

from fastapi import APIRouter

from backend.subjects import get_all_subjects

router = APIRouter()


@router.get("/subjects")
async def get_subjects_list() -> dict:
    """获取支持的学科列表"""
    return {"subjects": get_all_subjects()}

