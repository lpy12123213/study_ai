"""Zujuan search APIs (keyword/knowledge)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from backend.crawler.zujuan.utils import (
    _safe_float,
    _safe_int,
)
from backend.core.subjects import (
    DIFFICULTY_LEVELS,
    SUBJECTS,
)


async def search_by_keyword(
    self,
    keyword: str,
    subject: str = "",
    edu_level: str = "",
    limit: int = 20,
    difficulty: str = "",
    question_type: str = "",
    learn_grade: str = "",
    learn_grade_id: int = 0,
    textbook_version: str = "",
    max_pages: int = 2,
    year: int = 0,
    province: str = "",
    province_id: int = -1,
    paper_type_id: int = 0,
    term: int = 0,
    order_by: int = 2,
    source_contains: str = "",
    stem_contains: str = "",
    knowledge_contains: str = "",
    difficulty_value_min: Optional[float] = None,
    difficulty_value_max: Optional[float] = None,
    require_difficulty_value: bool = False,
    require_difficulty: bool = False,
    strict_subject: bool = True,
    elective_mode: str = "",
    elective_keywords: Optional[List[str]] = None,
    exclude_elective: bool = False,
    dedup_by_stem: bool = False,
    min_quality_score: int = 0,
    with_quality: bool = True,
    parse_content: bool = True,
) -> Dict[str, Any]:
    """
    关键词搜索（无需登录）：SSE 得到推荐参数 -> question/list 获取题目列表。

    - parse_content=True：解析较完整的题干内容（包含公式转换，开销更大）
    - parse_content=False：快速解析题干预览（不做公式转换，显著降低 CPU/IO），用于候选池预取/筛选
    """
    try:
        resolved_subject, difficulty = self._apply_search_constraints(
            subject=subject,
            edu_level=edu_level,
            difficulty=difficulty,
            require_difficulty=require_difficulty,
            strict_subject=strict_subject,
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "available_subjects": list(SUBJECTS.keys()),
            "allowed_difficulties": sorted(DIFFICULTY_LEVELS),
        }

    limit = _safe_int(limit, 20)
    # Batch crawl use-case: allow bigger caps than the old quick-preview defaults.
    limit = max(1, min(200, limit))

    max_pages = _safe_int(max_pages, 2)
    max_pages = max(1, min(50, max_pages))

    if difficulty_value_min is not None:
        difficulty_value_min = _safe_float(difficulty_value_min)
    if difficulty_value_max is not None:
        difficulty_value_max = _safe_float(difficulty_value_max)

    meta_task = None
    if (
        (question_type or "").strip()
        or (learn_grade or "").strip()
        or _safe_int(learn_grade_id, 0) > 0
        or (textbook_version or "").strip()
    ) and self.client is not None:
        # 按需加载题型/年级/教材版本映射，并与 AI 搜索并行以减少等待
        meta_task = asyncio.create_task(self._ensure_bank_meta_loaded())

    province_id = _safe_int(province_id, -1)
    province = (province or "").strip()
    if province and province_id in (-1, 0) and self.client is not None:
        resolved = await self._resolve_province_id(province)
        if resolved is None:
            return {
                "success": False,
                "error": "province_not_found",
                "province": province,
                "hint": "请先调用 get_available_filters 获取 provinces 或改用 province_id 传参。",
            }
        province_id = resolved

    # 站内 SSE 搜索是“全站意图识别”，不带学科时容易跑到其他学科/学段，
    # strict_subject 模式下自动补齐学科前缀以减少跨学科命中。
    sse_query = (keyword or "").strip()
    if strict_subject and resolved_subject:
        cfg = SUBJECTS.get(resolved_subject) or {}
        short_name = (cfg.get("short_name") or "").strip()
        if resolved_subject not in sse_query and (not short_name or short_name not in sse_query):
            sse_query = f"{resolved_subject} {sse_query}".strip()

    ai_result = await self._ai_search(sse_query)
    if not ai_result.get("success"):
        if meta_task:
            await meta_task
        return await self._fallback_question_list(
            keyword=keyword,
            limit=limit,
            difficulty=difficulty,
            question_type=question_type,
            learn_grade=learn_grade,
            learn_grade_id=learn_grade_id,
            textbook_version=textbook_version,
            max_pages=max_pages,
            year=year,
            province=province,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            source_contains=source_contains,
            stem_contains=stem_contains,
            knowledge_contains=knowledge_contains,
            elective_mode=elective_mode,
            elective_keywords=elective_keywords,
            exclude_elective=exclude_elective,
            difficulty_value_min=difficulty_value_min,
            difficulty_value_max=difficulty_value_max,
            require_difficulty_value=bool(require_difficulty_value),
            dedup_by_stem=dedup_by_stem,
            min_quality_score=min_quality_score,
            with_quality=with_quality,
        )

    payload = ai_result["payload"]
    target = self._parse_target_from_payload(payload)
    if not target:
        if meta_task:
            await meta_task
        return await self._fallback_question_list(
            keyword=keyword,
            limit=limit,
            difficulty=difficulty,
            question_type=question_type,
            learn_grade=learn_grade,
            learn_grade_id=learn_grade_id,
            textbook_version=textbook_version,
            max_pages=max_pages,
            year=year,
            province=province,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            source_contains=source_contains,
            stem_contains=stem_contains,
            knowledge_contains=knowledge_contains,
            elective_mode=elective_mode,
            elective_keywords=elective_keywords,
            exclude_elective=exclude_elective,
            difficulty_value_min=difficulty_value_min,
            difficulty_value_max=difficulty_value_max,
            require_difficulty_value=bool(require_difficulty_value),
            dedup_by_stem=dedup_by_stem,
            min_quality_score=min_quality_score,
            with_quality=with_quality,
        )

    if meta_task:
        await meta_task

    resolved_textbook_category_id = self._resolve_textbook_category_id(textbook_version)
    resolved_learn_grade_id = self._resolve_learn_grade_id(learn_grade, learn_grade_id)

    # 部分学科会返回 zsd0（未指定知识点/目录），此时用当前学科默认分类兜底，
    # 避免 categoryId=0 导致的“跟随 cookie 的题库”混入。
    if _safe_int(target.get("category_id"), 0) == 0 and getattr(self, "category_id", ""):
        target["category_id_original"] = target.get("category_id")
        if resolved_textbook_category_id:
            target["category_id"] = resolved_textbook_category_id
            target["textbook_version_applied"] = textbook_version
        else:
            target["category_id"] = str(self.category_id)

    # 严格学科约束：搜索结果必须落在当前学科 bankId 下。
    # 组卷网的 /zujuan-api/search（SSE）偶发返回其他学科的 bank_id，导致跨学段混入。
    expected_bank_id = _safe_int(getattr(self, "bank_id", 0), 0)
    target_bank_id = _safe_int(target.get("bank_id"), 0)
    bank_id_for_request = target_bank_id or expected_bank_id
    bank_id_mismatch = False
    if strict_subject and expected_bank_id:
        if target_bank_id and target_bank_id != expected_bank_id:
            bank_id_mismatch = True
        bank_id_for_request = expected_bank_id
        # SSE 给出的 categoryId 通常属于其 bank_id；当 bank 不一致时直接用
        # 当前学科默认分类，避免无结果/跨库混入。
        if bank_id_mismatch and getattr(self, "category_id", ""):
            target["category_id_original"] = target.get("category_id")
            target["category_id"] = resolved_textbook_category_id or str(self.category_id)

    target["bank_id_expected"] = expected_bank_id
    target["bank_id_for_request"] = bank_id_for_request
    if bank_id_mismatch:
        target["bank_id_mismatch"] = True

    expected_course_id = _safe_int(getattr(self, "course_id", 0), 0)
    target_course_id = _safe_int(target.get("course_id"), 0)
    course_id_for_request = target_course_id or expected_course_id
    if bank_id_mismatch and strict_subject:
        course_id_for_request = expected_course_id
    if course_id_for_request:
        target["course_id_for_request"] = course_id_for_request

    year = _safe_int(year, 0)
    province_id = _safe_int(province_id, -1)
    paper_type_id = _safe_int(paper_type_id, 0)
    term = _safe_int(term, 0)
    order_by = _safe_int(order_by, 2)

    selected_questions: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_stem_fps: set[str] = set()
    debug_pages = []
    target_question_type_id = _safe_int(target.get("question_type_id"), 0)
    question_type_id_for_request = target_question_type_id if not (question_type or "").strip() else 0
    min_quality_score = _safe_int(min_quality_score, 0)
    for page_idx in range(1, max_pages + 1):
        questions, dbg = await self._fetch_question_list(
            page_name=target["page_name"],
            bank_id=bank_id_for_request,
            category_id=target["category_id"],
            course_id=course_id_for_request,
            course_id_py=str(target.get("course_id_py") or ""),
            cur_page=page_idx,
            difficulty=difficulty,
            question_type=question_type,
            question_type_id=question_type_id_for_request,
            learn_grade_id=resolved_learn_grade_id,
            year=year,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            parse_content=bool(parse_content),
        )
        for q in questions:
            qid = (q.get("question_id") or "").strip()
            if not qid or qid in seen_ids:
                continue
            seen_ids.add(qid)
            if self._matches_local_filters(
                q,
                source_contains=source_contains,
                stem_contains=stem_contains,
                knowledge_contains=knowledge_contains,
                elective_mode=elective_mode,
                elective_keywords=elective_keywords,
                exclude_elective=exclude_elective,
                year=year,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                require_difficulty_value=bool(require_difficulty_value),
            ):
                score, flags = self._quality_score(q)
                if with_quality:
                    q["quality_score"] = score
                    if flags:
                        q["quality_flags"] = flags
                if min_quality_score > 0 and score < min_quality_score:
                    continue
                if dedup_by_stem:
                    fp = self._stem_fingerprint(q.get("stem") or "")
                    if fp and fp in seen_stem_fps:
                        continue
                    if fp:
                        seen_stem_fps.add(fp)
                selected_questions.append(q)
        debug_pages.append(dbg)
        if len(selected_questions) >= limit or (dbg.get("raw_count", 0) == 0):
            break

    # 如果 SSE 返回了错误学科的 bankId 且强制校正后没有结果，降级到兜底路径：
    # 直接用当前学科默认 categoryId 拉取，至少保证学科/学段不会混入。
    if not selected_questions and debug_pages:
        page_errors = [str(d.get("error") or "").strip() for d in debug_pages if isinstance(d, dict)]
        first_blocker = next((e for e in page_errors if e in {"login_page", "js_challenge"}), "")
        if first_blocker:
            return {
                "success": False,
                "error": first_blocker,
                "keyword": keyword,
                "login_required": first_blocker == "login_page",
                "cookie_expired": first_blocker == "login_page",
                "trace": {"pages": debug_pages},
                "instructions": [
                    "题库请求被登录页/反爬拦截。可能原因：Cookie 过期、风控或网络环境异常。",
                    "建议：双击运行 scripts/登录组卷网.bat 重新登录并保存 Cookie，然后重试。",
                ],
            }

    if bank_id_mismatch and not selected_questions:
        return await self._fallback_question_list(
            keyword=keyword,
            limit=limit,
            difficulty=difficulty,
            question_type=question_type,
            learn_grade=learn_grade,
            learn_grade_id=learn_grade_id,
            textbook_version=textbook_version,
            max_pages=max_pages,
            year=year,
            province=province,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            source_contains=source_contains,
            stem_contains=stem_contains,
            knowledge_contains=knowledge_contains,
            elective_mode=elective_mode,
            elective_keywords=elective_keywords,
            exclude_elective=exclude_elective,
            difficulty_value_min=difficulty_value_min,
            difficulty_value_max=difficulty_value_max,
            require_difficulty_value=bool(require_difficulty_value),
            dedup_by_stem=dedup_by_stem,
            min_quality_score=min_quality_score,
            with_quality=with_quality,
        )

    return {
        "success": True,
        "keyword": keyword,
        "count": len(selected_questions[:limit]),
        "questions": selected_questions[:limit],
        "trace": {
            "target": target,
            "filters": {
                "learn_grade_id": resolved_learn_grade_id,
                "textbook_version": (textbook_version or "").strip(),
                "year": year,
                "province_id": province_id,
                "paper_type_id": paper_type_id,
                "term": term,
                "order_by": order_by,
                "source_contains": (source_contains or "").strip(),
                "stem_contains": (stem_contains or "").strip(),
                "knowledge_contains": (knowledge_contains or "").strip(),
                "exclude_elective": bool(exclude_elective),
                "elective_mode": self._normalize_elective_mode(elective_mode, exclude_elective),
                "dedup_by_stem": bool(dedup_by_stem),
                "min_quality_score": min_quality_score,
                "with_quality": bool(with_quality),
                "difficulty_value_min": difficulty_value_min,
                "difficulty_value_max": difficulty_value_max,
                "require_difficulty_value": bool(require_difficulty_value),
                "parse_content": bool(parse_content),
            },
            "pages": debug_pages,
        },
    }


async def search_by_knowledge(
    self,
    knowledge_point: str,
    subject: str,
    edu_level: str = "",
    limit: int = 20,
    difficulty: str = "",
    question_type: str = "",
    learn_grade: str = "",
    learn_grade_id: int = 0,
    textbook_version: str = "",
    max_pages: int = 2,
    year: int = 0,
    province: str = "",
    province_id: int = -1,
    paper_type_id: int = 0,
    term: int = 0,
    order_by: int = 2,
    source_contains: str = "",
    stem_contains: str = "",
    knowledge_contains: str = "",
    difficulty_value_min: Optional[float] = None,
    difficulty_value_max: Optional[float] = None,
    require_difficulty_value: bool = False,
    require_difficulty: bool = False,
    strict_subject: bool = True,
    elective_mode: str = "",
    elective_keywords: Optional[List[str]] = None,
    exclude_elective: bool = False,
    dedup_by_stem: bool = False,
    min_quality_score: int = 0,
    with_quality: bool = True,
    parse_content: bool = True,
) -> Dict[str, Any]:
    """
    通过知识点搜索（内部复用关键词搜索）。
    """
    return await self.search_by_keyword(
        keyword=knowledge_point,
        subject=subject,
        edu_level=edu_level,
        limit=limit,
        difficulty=difficulty,
        question_type=question_type,
        learn_grade=learn_grade,
        learn_grade_id=learn_grade_id,
        textbook_version=textbook_version,
        max_pages=max_pages,
        year=year,
        province=province,
        province_id=province_id,
        paper_type_id=paper_type_id,
        term=term,
        order_by=order_by,
        source_contains=source_contains,
        stem_contains=stem_contains,
        knowledge_contains=knowledge_contains,
        difficulty_value_min=difficulty_value_min,
        difficulty_value_max=difficulty_value_max,
        require_difficulty_value=require_difficulty_value,
        require_difficulty=require_difficulty,
        strict_subject=strict_subject,
        elective_mode=elective_mode,
        elective_keywords=elective_keywords,
        exclude_elective=exclude_elective,
        dedup_by_stem=dedup_by_stem,
        min_quality_score=min_quality_score,
        with_quality=with_quality,
        parse_content=parse_content,
    )
