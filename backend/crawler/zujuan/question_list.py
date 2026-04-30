from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from backend.crawler.zujuan.utils import _safe_float, _safe_int


async def fallback_question_list(
    self,
    keyword: str = "",
    limit: int = 20,
    difficulty: str = "",
    question_type: str = "",
    learn_grade: str = "",
    learn_grade_id: int = 0,
    textbook_version: str = "",
    max_pages: int = 3,
    year: int = 0,
    province: str = "",
    province_id: int = -1,
    paper_type_id: int = 0,
    term: int = 0,
    order_by: int = 2,
    source_contains: str = "",
    stem_contains: str = "",
    knowledge_contains: str = "",
    elective_mode: str = "",
    elective_keywords: Optional[List[str]] = None,
    exclude_elective: bool = False,
    difficulty_value_min: Optional[float] = None,
    difficulty_value_max: Optional[float] = None,
    require_difficulty_value: bool = False,
    dedup_by_stem: bool = False,
    min_quality_score: int = 0,
    with_quality: bool = True,
) -> Dict[str, Any]:
    """
    官方 AI 搜索无法解析意图时的兜底：直接访问 question/list。
    使用当前学科配置的 bankId 和 categoryId。
    """
    limit = _safe_int(limit, 20)
    limit = max(1, min(200, limit))

    max_pages = _safe_int(max_pages, 3)
    max_pages = max(1, min(50, max_pages))

    year = _safe_int(year, 0)
    paper_type_id = _safe_int(paper_type_id, 0)
    term = _safe_int(term, 0)
    order_by = _safe_int(order_by, 2)

    if difficulty_value_min is not None:
        difficulty_value_min = _safe_float(difficulty_value_min)
    if difficulty_value_max is not None:
        difficulty_value_max = _safe_float(difficulty_value_max)

    if question_type and not self.ques_type_map and self.client is not None:
        await self._ensure_base_meta_loaded()
    await self._ensure_bank_meta_loaded()
    page_name = "zsd"
    bank_id = self.bank_id
    category_id = self._resolve_textbook_category_id(textbook_version) or str(self.category_id)
    resolved_learn_grade_id = self._resolve_learn_grade_id(learn_grade, learn_grade_id)
    province_id = _safe_int(province_id, -1)
    province = (province or "").strip()
    if province and province_id in (-1, 0):
        resolved = await self._resolve_province_id(province)
        if resolved is not None:
            province_id = resolved

    all_questions: List[Dict[str, Any]] = []
    debug_pages = []
    for page_idx in range(1, max_pages + 1):
        questions, dbg = await self._fetch_question_list(
            page_name=page_name,
            bank_id=bank_id,
            category_id=category_id,
            cur_page=page_idx,
            difficulty=difficulty,
            question_type=question_type,
            learn_grade_id=resolved_learn_grade_id,
            year=year,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            parse_content=True,
        )
        all_questions.extend(questions)
        debug_pages.append(dbg)
        if len(all_questions) >= limit or (dbg.get("raw_count", 0) == 0):
            break

    if not all_questions:
        return {
            "success": False,
            "error": "fallback_list_empty",
            "trace": {"method": "fallback", "pages": debug_pages},
        }

    selected_questions: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_stem_fps: set[str] = set()
    min_quality_score = _safe_int(min_quality_score, 0)

    for q in all_questions:
        qid = (q.get("question_id") or "").strip()
        if not qid or qid in seen_ids:
            continue
        seen_ids.add(qid)

        if not self._matches_local_filters(
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
            continue

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
        if len(selected_questions) >= limit:
            break

    return {
        "success": True,
        "keyword": keyword,
        "count": len(selected_questions[:limit]),
        "questions": selected_questions[:limit],
        "trace": {
            "method": "fallback",
            "target": {
                "page_name": page_name,
                "bank_id": bank_id,
                "category_id": category_id,
            },
            "filters": {
                "learn_grade_id": resolved_learn_grade_id,
                "year": _safe_int(year, 0),
                "province_id": _safe_int(province_id, -1),
                "paper_type_id": _safe_int(paper_type_id, 0),
                "term": _safe_int(term, 0),
                "order_by": _safe_int(order_by, 2),
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
            },
            "pages": debug_pages,
        },
    }


async def fetch_question_list(
    self,
    page_name: str,
    bank_id: int,
    category_id: str,
    course_id: int = 0,
    course_id_py: str = "",
    cur_page: int = 1,
    difficulty: str = "",
    question_type: str = "",
    question_type_id: int = 0,
    learn_grade_id: int = 0,
    year: int = 0,
    province_id: int = -1,
    paper_type_id: int = 0,
    term: int = 0,
    order_by: int = 2,
    parse_content: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    调用 /zujuan-api/question/list，解析题目信息。
    返回 (题目列表, 调试信息)
    parse_content=True 时解析完整题目内容，False 时只返回ID
    """
    if not self.client:
        return [], {"error": "client not initialized"}

    use_multi = self._use_multi_difficulty_codes()
    if use_multi:
        difficulty_codes = self._difficulty_codes(difficulty)
    else:
        code = self._difficulty_code(difficulty)
        difficulty_codes = [code] if code else []
    if not difficulty_codes:
        difficulty_codes = [0]
    # If "all" is included, keep it as a single code to avoid ambiguous semantics.
    if 0 in difficulty_codes and len(difficulty_codes) > 1:
        difficulty_codes = [0]

    year = _safe_int(year, 0)
    province_id = _safe_int(province_id, -1)
    paper_type_id = _safe_int(paper_type_id, 0)
    term = _safe_int(term, 0)
    order_by = _safe_int(order_by, 2)
    question_type_id = _safe_int(question_type_id, 0)
    ques_type_code = question_type_id or self._question_type_code(question_type)
    learn_grade_id = _safe_int(learn_grade_id, 0)

    # Ensure /zujuan-api/base has been loaded so courseId/courseIdPy are available.
    await self._ensure_bank_meta_loaded()
    resolved_course_id = _safe_int(course_id, 0) or _safe_int(getattr(self, "course_id", 0), 0)

    resolved_course_id_py = str(course_id_py or getattr(self, "course_id_py", "") or "").strip()

    cache_key = (
        f"qlist:{page_name}:{bank_id}:{resolved_course_id}:{resolved_course_id_py}:{category_id}:{cur_page}:{difficulty}:"
        f"{ques_type_code}:{year}:{province_id}:{paper_type_id}:{term}:{order_by}:"
        f"{learn_grade_id}:{int(parse_content)}"
    )
    cached = self._cache_get(cache_key)
    if isinstance(cached, tuple) and len(cached) == 2:
        return cached  # type: ignore[return-value]

    referer_page = (page_name or "").strip() or "zsd"
    if referer_page in {"zh", "zhangjie"}:
        referer_page = "zj"
    referer_url = (
        f"{self.base_url}/{resolved_course_id_py}/{referer_page}{category_id}/"
        if resolved_course_id_py and str(category_id).strip()
        else f"{self.base_url.rstrip('/')}/"
    )

    data_fields: List[Tuple[str, str]] = [
        ("pageName", page_name),
        ("bankId", str(bank_id or 0)),
        ("courseId", str(resolved_course_id or 0)),
        ("categoryId", str(category_id)),
        ("canCategoryId", "true"),
        ("categoryIds[0]", "0"),
        ("quesType", str(ques_type_code)),
        ("quesYear", str(year or 0)),
        ("paperTypeId", str(paper_type_id or 0)),
        ("scenarioizedTypeId", "0"),
        ("tagId", "0"),
        ("provinceId", str(province_id)),
        ("learngrade", str(learn_grade_id or 0)),
        ("term", str(term or 0)),
        ("orderBy", str(order_by or 2)),
        ("curPage", str(cur_page)),
        ("quesAttributeId", "0"),
        ("examMethodId", "0"),
        ("isFresh", "0"),
        ("catelogTokpointId", "0"),
    ]

    # Prefer multi-select `quesDiffs` when multiple codes are requested.
    if len(difficulty_codes) <= 1:
        data_fields.append(("quesDiff", str(difficulty_codes[0] if difficulty_codes else 0)))
    else:
        data_fields.append(("quesDiff", "0"))
        for dc in difficulty_codes:
            data_fields.append(("quesDiffs", str(_safe_int(dc, 0))))

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": self.base_url,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer_url,
        "User-Agent": self.user_agent,
    }

    # NOTE: httpx>=0.28 treats an iterable passed to `data=` as a *streaming body*.
    # For AsyncClient this becomes a SyncByteStream and raises:
    # "Attempted to send an sync request with an AsyncClient instance."
    # We therefore pre-encode form fields ourselves.
    body = urllib.parse.urlencode(data_fields)

    resp = await self.client.post(
        f"{self.base_url}/zujuan-api/question/list",
        content=body,
        headers=headers,
    )

    try:
        resp_json = resp.json()
        code = str(resp_json.get("code") or "").strip()
        if code and code not in {"0", "200"}:
            dbg = {
                "error": "api_code_not_ok",
                "raw_count": 0,
                "page": cur_page,
                "status": resp.status_code,
                "code": code,
            }
            self._cache_set(cache_key, ([], dbg), ttl=60)
            return [], dbg
        html = resp_json.get("data", {}).get("html", "")
    except Exception:
        text = ""
        try:
            text = (resp.text or "").strip()
        except Exception:
            text = ""
        lowered = text.lower()
        is_js_challenge = (
            '<body onload="check()">' in lowered
            or "alicfw_gfver" in lowered
            or "aliyun_waf_aa" in lowered
            or "aliyun_waf_bb" in lowered
            or "acw_sc__v2" in lowered
        )
        is_login_page = "login.css" in lowered or "login-popup.css" in lowered
        dbg = {
            "error": "js_challenge" if is_js_challenge else ("login_page" if is_login_page else "json_parse_failed"),
            "raw_count": 0,
            "page": cur_page,
            "status": resp.status_code,
            "content_type": (resp.headers.get("Content-Type") or ""),
            "body_prefix": text[:200].replace("\r", "").replace("\n", "\\n") if text else "",
        }
        self._cache_set(cache_key, ([], dbg), ttl=60)
        return [], dbg

    if not html:
        dbg = {
            "error": "empty_html",
            "raw_count": 0,
            "page": cur_page,
            "status": resp.status_code,
        }
        self._cache_set(cache_key, ([], dbg), ttl=60)
        return [], dbg

    seen_ids: set[str] = set()
    all_questions: List[Dict[str, Any]] = []

    parsed_questions = await self._parse_questions_from_html(html, bank_id, parse_content=parse_content)
    total_raw_count = len(parsed_questions)
    for q in parsed_questions:
        qid = str(q.get("question_id") or "").strip()
        if not qid or qid in seen_ids:
            continue
        seen_ids.add(qid)
        all_questions.append(q)

    # 兜底：若站点未按 quesDiff 过滤（偶发），这里再按解析出的难度文案过滤一次
    accepted_labels = self._requested_difficulty_buckets(difficulty)
    if accepted_labels:
        all_questions = [q for q in all_questions if (q.get("difficulty") or "").strip() in accepted_labels]

    debug_info = {
        "raw_count": total_raw_count,
        "returned_count": len(all_questions),
        "page": cur_page,
        "difficulty_mode": "multi" if use_multi else "single",
        "course_id": resolved_course_id,
        "ques_type_code": ques_type_code,
        "learn_grade_id": learn_grade_id,
        "year": year,
        "province_id": province_id,
        "paper_type_id": paper_type_id,
        "term": term,
        "order_by": order_by,
    }
    if len(difficulty_codes) > 1:
        debug_info["difficulty_codes"] = difficulty_codes
        debug_info["difficulty_multi_param"] = "quesDiffs"

    result = (all_questions, debug_info)
    self._cache_set(cache_key, result, ttl=8 * 60 if parse_content else 10 * 60)
    return result
