from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.crawler.manager import get_crawler
from backend.core.subjects import get_all_subjects, resolve_subject

router = APIRouter()
logger = get_logger(__name__)
_SUBJECT_FILTERS_CACHE: dict[str, tuple[float, dict]] = {}
_KNOWLEDGE_TREE_CACHE: dict[str, tuple[float, dict]] = {}

_DEFAULT_KNOWLEDGE_TREE: dict[str, list[tuple[str, list[str]]]] = {
    "高中数学": [
        ("函数与导数", ["函数概念", "单调性", "导数应用", "极值与最值", "数形结合"]),
        ("代数与不等式", ["数列", "不等式", "方程与函数综合", "参数讨论"]),
        ("解析几何与向量", ["圆锥曲线", "直线与圆", "平面向量", "坐标运算"]),
        ("概率统计", ["排列组合", "概率", "统计图表", "随机变量"]),
    ],
    "初中数学": [
        ("数与式", ["整式运算", "分式", "二次根式", "因式分解"]),
        ("方程与函数", ["一次函数", "反比例函数", "二次函数", "方程应用"]),
        ("图形与几何", ["三角形", "四边形", "圆", "相似与全等"]),
        ("统计与概率", ["数据分析", "概率初步", "综合应用"]),
    ],
    "高中物理": [
        ("力学", ["受力分析", "牛顿定律", "运动学", "动量与能量"]),
        ("电磁学", ["电场", "电路", "磁场", "电磁感应"]),
        ("选修专题", ["振动与波", "热学", "近代物理"]),
    ],
    "高中化学": [
        ("基础理论", ["物质结构", "化学键", "氧化还原", "离子反应"]),
        ("反应与平衡", ["化学平衡", "电化学", "反应速率", "溶液平衡"]),
        ("元素化学", ["金属及其化合物", "非金属及其化合物", "实验综合"]),
    ],
    "高中生物": [
        ("细胞与代谢", ["细胞结构", "酶与ATP", "光合作用", "呼吸作用"]),
        ("遗传与进化", ["遗传规律", "伴性遗传", "变异与育种", "生物进化"]),
        ("稳态与生态", ["人体稳态", "神经调节", "生态系统", "种群与群落"]),
    ],
    "高中语文": [
        ("现代文阅读", ["论述类文本", "文学类文本", "实用类文本"]),
        ("古诗文", ["文言文阅读", "古诗词鉴赏", "名句默写"]),
        ("表达与写作", ["语言文字运用", "作文立意", "写作表达"]),
    ],
    "高中英语": [
        ("语言知识", ["词汇", "语法填空", "短文改错"]),
        ("阅读能力", ["阅读理解", "七选五", "完形填空"]),
        ("表达能力", ["应用文写作", "读后续写", "听说能力"]),
    ],
}


def clear_subject_filters_cache() -> None:
    _SUBJECT_FILTERS_CACHE.clear()


def _subject_filters_cache_ttl_s() -> float:
    raw = str(os.getenv("SUBJECT_FILTERS_CACHE_TTL_S") or "").strip()
    try:
        ttl = float(raw) if raw else 10 * 60.0
    except Exception:
        ttl = 10 * 60.0
    return max(0.0, min(ttl, 24.0 * 60.0 * 60.0))


def _knowledge_tree_cache_key(subject: str, grade_id: str, textbook_version_id: str) -> str:
    return f"{subject}::{grade_id}::{textbook_version_id}"


def _lookup_name(items: list[dict], raw_id: str) -> str:
    target = str(raw_id or "").strip()
    if not target:
        return ""
    for item in items or []:
        if str(item.get("id") or "").strip() == target:
            return str(item.get("name") or "").strip()
    return ""


def _fallback_tree(subject: str, grade_name: str, textbook_name: str) -> list[dict]:
    groups = _DEFAULT_KNOWLEDGE_TREE.get(subject) or [
        ("核心专题", ["基础概念", "能力应用", "综合探究", "实验与实践"]),
    ]
    prefix = " / ".join([value for value in [grade_name, textbook_name] if value]).strip()
    root_name = prefix or f"{subject}知识点"

    nodes: list[dict] = []
    for chapter_index, (chapter_name, leaves) in enumerate(groups, start=1):
        chapter_id = f"{subject}-chapter-{chapter_index}"
        nodes.append(
            {
                "id": chapter_id,
                "label": chapter_name,
                "type": "chapter",
                "children": [
                    {
                        "id": f"{chapter_id}-kp-{leaf_index}",
                        "label": leaf_label,
                        "type": "knowledge_point",
                        "selectable": True,
                        "children": [],
                    }
                    for leaf_index, leaf_label in enumerate(leaves, start=1)
                ],
            }
        )

    return [
        {
            "id": f"{subject}-root",
            "label": root_name,
            "type": "root",
            "children": nodes,
        }
    ]


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
        err = str((result or {}).get("error") or "").strip()
        logger.warning("subject_filters_failed", extra={"subject": subject, "error": err[:200]})
        raise HTTPException(status_code=500, detail="filters_failed")

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


@router.get("/subjects/{subject_code}/knowledge-tree")
async def get_subject_knowledge_tree(
    subject_code: str,
    grade_id: str = "",
    textbook_version_id: str = "",
    user: dict = Depends(require_auth),
) -> dict:
    _ = user

    subject_input = (subject_code or "").strip()
    if not subject_input:
        raise HTTPException(status_code=400, detail="missing_subject")

    try:
        subject = resolve_subject(subject_input, strict=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    cache_key = _knowledge_tree_cache_key(subject, str(grade_id or "").strip(), str(textbook_version_id or "").strip())
    ttl_s = _subject_filters_cache_ttl_s()
    cached = _KNOWLEDGE_TREE_CACHE.get(cache_key)
    if ttl_s > 0 and cached and (time.time() - cached[0]) <= ttl_s:
        return dict(cached[1])

    crawler_nodes: list = []
    grade_name = ""
    textbook_name = ""
    try:
        crawler = await get_crawler(subject=subject, edu_level="", strict=True)
        # Try fetching the real knowledge tree from 组卷网.
        tree_result = await crawler.get_knowledge_tree()
        if isinstance(tree_result, dict) and tree_result.get("success"):
            crawler_nodes = tree_result.get("nodes") or []
        # Also fetch filters for grade/textbook name resolution.
        filters = await crawler.get_available_filters()
        if isinstance(filters, dict):
            grades = filters.get("grades") or []
            textbook_versions = filters.get("textbook_versions") or []
            grade_name = _lookup_name(grades if isinstance(grades, list) else [], grade_id)
            textbook_name = _lookup_name(textbook_versions if isinstance(textbook_versions, list) else [], textbook_version_id)
    except Exception:
        pass

    nodes = crawler_nodes if crawler_nodes else _fallback_tree(subject, grade_name, textbook_name)

    payload = {
        "success": True,
        "subject": subject,
        "grade_id": str(grade_id or "").strip(),
        "textbook_version_id": str(textbook_version_id or "").strip(),
        "nodes": nodes,
        "source": "zujuan" if crawler_nodes else "fallback",
    }
    if ttl_s > 0:
        _KNOWLEDGE_TREE_CACHE[cache_key] = (time.time(), dict(payload))
        if len(_KNOWLEDGE_TREE_CACHE) > 128:
            oldest_key = min(_KNOWLEDGE_TREE_CACHE, key=lambda key: _KNOWLEDGE_TREE_CACHE[key][0])
            _KNOWLEDGE_TREE_CACHE.pop(oldest_key, None)
    return payload
