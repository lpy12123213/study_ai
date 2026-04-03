from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.crawler.manager import get_crawler
from backend.database.models import get_question_cache, list_question_library_items
from backend.question_library.gen_common import _clip_unique

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_CACHE_DIR = (_REPO_ROOT / ".local" / "reference_cache").resolve()


def _normalize_reference_source(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"gaokao", "高考", "exam"}:
        return "gaokao"
    if raw in {"mock", "模考", "模拟", "moni"}:
        return "mock"
    if raw in {"joint", "联考", "joint_exam"}:
        return "joint"
    return "any"


def _normalize_reference_year_range(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"3", "3y", "last3", "近3年"}:
        return "3"
    if raw in {"5", "5y", "last5", "近5年"}:
        return "5"
    return "all"


def _reference_source_label(value: Any) -> str:
    normalized = _normalize_reference_source(value)
    if normalized == "gaokao":
        return "高考真题"
    if normalized == "mock":
        return "模考题"
    if normalized == "joint":
        return "联考题"
    return "不限"


def _reference_year_range_label(value: Any) -> str:
    normalized = _normalize_reference_year_range(value)
    if normalized == "3":
        return "近3年"
    if normalized == "5":
        return "近5年"
    return "不限"


def _reference_source_token(value: Any) -> str:
    normalized = _normalize_reference_source(value)
    if normalized == "gaokao":
        return "高考"
    if normalized == "mock":
        return "模考"
    if normalized == "joint":
        return "联考"
    return ""


def _reference_year_threshold(value: Any) -> int:
    normalized = _normalize_reference_year_range(value)
    if normalized not in {"3", "5"}:
        return 0
    try:
        years = int(normalized)
    except Exception:
        return 0
    return max(0, time.localtime().tm_year - years + 1)


def _extract_reference_year(item: dict) -> int:
    if not isinstance(item, dict):
        return 0
    candidates = [
        str(item.get("date") or "").strip(),
        str(item.get("source") or "").strip(),
        str(item.get("url") or "").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        match = re.search(r"(20\\d{2})", candidate)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                continue
    return 0


def _parse_knowledge_points_json(value: Any) -> List[str]:
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except Exception:
            parts = [part.strip() for part in re.split(r"[，,;；、|/]+", text) if part.strip()]
            return _clip_unique(parts, 8)
    if isinstance(raw, list):
        return _clip_unique([str(item or "").strip() for item in raw if str(item or "").strip()], 8)
    return []


def _reference_query_candidates(topic: str, knowledge_points: List[str]) -> List[str]:
    out: List[str] = []
    topic_text = str(topic or "").strip()
    for item in knowledge_points or []:
        text = str(item or "").strip()
        if text:
            out.append(text[:48])
    if topic_text:
        first_line = topic_text.splitlines()[0].strip()
        if first_line:
            out.append(first_line[:60])
        normalized = re.sub(r"[，,;；|/]+", " ", first_line or topic_text)
        parts = [part.strip() for part in normalized.split() if part.strip()]
        if len(parts) > 1:
            out.extend(part[:32] for part in parts[:4])
    return _clip_unique(out, 5)


def _normalize_reference_question(item: dict, preview: Optional[dict] = None) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    preview_obj = preview if isinstance(preview, dict) else {}
    question_id = str(item.get("question_id") or preview_obj.get("question_id") or "").strip()
    stem = str(item.get("stem") or preview_obj.get("stem") or "").strip()
    if not question_id or not stem:
        return None
    source = str(item.get("source") or preview_obj.get("source") or "").strip()
    date = str(item.get("date") or preview_obj.get("date") or "").strip()
    knowledge_points = str(
        item.get("knowledge_points")
        or preview_obj.get("knowledge_points")
        or preview_obj.get("knowledge_point")
        or ""
    ).strip()
    question_type = str(
        item.get("question_type")
        or item.get("type")
        or preview_obj.get("question_type")
        or preview_obj.get("type")
        or ""
    ).strip()
    difficulty = str(item.get("difficulty") or preview_obj.get("difficulty") or "").strip()
    answer = str(item.get("answer") or preview_obj.get("answer") or "").strip()
    analysis = str(item.get("analysis") or preview_obj.get("analysis") or "").strip()
    url = str(item.get("url") or item.get("source_url") or preview_obj.get("url") or preview_obj.get("source_url") or "").strip()

    origin = str(item.get("origin") or preview_obj.get("origin") or "").strip() or "crawled"
    return {
        "question_id": question_id,
        "stem": stem,
        "answer": answer,
        "analysis": analysis,
        "difficulty": difficulty,
        "question_type": question_type,
        "knowledge_points": knowledge_points,
        "source": source,
        "date": date,
        "origin": origin,
        "url": url,
    }


def _reference_matches_constraints(item: dict, reference_source: str, reference_year_range: str) -> bool:
    if not isinstance(item, dict):
        return False
    source_token = _reference_source_token(reference_source)
    source_text = str(item.get("source") or "").strip()
    if source_token and source_text and source_token not in source_text:
        return False
    year_threshold = _reference_year_threshold(reference_year_range)
    if year_threshold > 0:
        year = _extract_reference_year(item)
        if year > 0 and year < year_threshold:
            return False
    return True


def _reference_cache_key(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    knowledge_point_ids: List[str],
    knowledge_points: List[str],
    reference_source: str,
    reference_year_range: str,
) -> str:
    payload = {
        "subject": str(subject or "").strip(),
        "topic": str(topic or "").strip(),
        "difficulty": str(difficulty or "").strip(),
        "question_type": str(question_type or "").strip(),
        "knowledge_point_ids": [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()],
        "knowledge_points": [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()],
        "reference_source": _normalize_reference_source(reference_source),
        "reference_year_range": _normalize_reference_year_range(reference_year_range),
    }
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:24]


def _reference_cache_path(cache_key: str) -> Path:
    return (_REFERENCE_CACHE_DIR / f"{str(cache_key or '').strip()}.json").resolve()


def load_reference_cache(cache_key: str) -> Optional[dict]:
    key = str(cache_key or "").strip()
    if not key:
        return None
    path = _reference_cache_path(key)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw) if raw else {}
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    try:
        crawled_at_s = float(obj.get("crawled_at_s") or 0.0)
    except Exception:
        crawled_at_s = 0.0
    if crawled_at_s <= 0 or (time.time() - crawled_at_s) > 24 * 60 * 60:
        return None
    questions = []
    for item in obj.get("questions") or []:
        normalized = _normalize_reference_question(item if isinstance(item, dict) else {})
        if normalized is not None:
            questions.append(normalized)
    if not questions:
        return None
    return {
        "success": True,
        "source": "cache",
        "cache_hit": True,
        "degraded": False,
        "fallback_used": "",
        "error": "",
        "questions": questions,
        "count": len(questions),
    }


def save_reference_cache(cache_key: str, questions: List[dict]) -> Optional[dict]:
    key = str(cache_key or "").strip()
    if not key:
        return None
    normalized_questions = []
    for item in questions or []:
        normalized = _normalize_reference_question(item if isinstance(item, dict) else {})
        if normalized is not None:
            normalized_questions.append(normalized)
    if not normalized_questions:
        return None
    _REFERENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_key": key,
        "crawled_at_s": time.time(),
        "questions": normalized_questions,
    }
    path = _reference_cache_path(key)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


async def collect_reference_questions(
    *,
    user_id: str,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    knowledge_point_ids: Optional[List[str]] = None,
    knowledge_points: Optional[List[str]] = None,
    desired_count: int = 5,
    reference_source: str = "any",
    reference_year_range: str = "all",
) -> dict:
    kp_ids = [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()]
    kp_labels = [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()]
    target_count = max(5, min(10, int(desired_count or 5)))
    cache_key = _reference_cache_key(
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        knowledge_point_ids=kp_ids,
        knowledge_points=kp_labels,
        reference_source=reference_source,
        reference_year_range=reference_year_range,
    )
    cached = load_reference_cache(cache_key)
    if isinstance(cached, dict) and cached.get("questions"):
        cached["trace"] = {"cache_key": cache_key, "queries": []}
        return cached

    queries = _reference_query_candidates(topic, kp_labels)
    source_token = _reference_source_token(reference_source)
    preview_by_id: Dict[str, dict] = {}
    crawler_errors: List[str] = []

    try:
        crawler = await get_crawler(subject=subject, strict=True)
        selected_ids: List[str] = []
        for query in queries:
            try:
                search_result = await crawler.search_by_keyword(
                    keyword=query,
                    subject=subject,
                    difficulty=difficulty,
                    question_type=question_type,
                    limit=max(10, target_count * 2),
                    max_pages=2,
                    source_contains=source_token,
                    parse_content=False,
                )
            except Exception as exc:
                crawler_errors.append(str(exc))
                continue
            candidates = search_result.get("questions") if isinstance(search_result, dict) else []
            if not isinstance(candidates, list):
                candidates = []
            for candidate in candidates:
                normalized_preview = _normalize_reference_question(candidate if isinstance(candidate, dict) else {})
                if normalized_preview is None:
                    continue
                if not _reference_matches_constraints(normalized_preview, reference_source, reference_year_range):
                    continue
                qid = str(normalized_preview.get("question_id") or "").strip()
                if not qid or qid in preview_by_id:
                    continue
                preview_by_id[qid] = normalized_preview
                selected_ids.append(qid)
                if len(selected_ids) >= target_count:
                    break
            if len(selected_ids) >= target_count:
                break

        if preview_by_id:
            details_result = await crawler.batch_get_question_details(list(preview_by_id.keys())[:target_count], max_concurrent=4)
            detail_items = details_result.get("questions") if isinstance(details_result, dict) else []
            if not isinstance(detail_items, list):
                detail_items = []
            crawled_questions: List[dict] = []
            for detail in detail_items:
                normalized = _normalize_reference_question(
                    detail if isinstance(detail, dict) else {},
                    preview_by_id.get(str((detail or {}).get("question_id") or "").strip()),
                )
                if normalized is None:
                    continue
                if not _reference_matches_constraints(normalized, reference_source, reference_year_range):
                    continue
                crawled_questions.append(normalized)
            if crawled_questions:
                save_reference_cache(cache_key, crawled_questions)
                return {
                    "success": True,
                    "source": "crawler",
                    "cache_hit": False,
                    "degraded": False,
                    "fallback_used": "",
                    "error": "",
                    "questions": crawled_questions[:target_count],
                    "count": len(crawled_questions[:target_count]),
                    "trace": {"cache_key": cache_key, "queries": queries, "crawler_errors": crawler_errors},
                }
    except Exception as exc:
        crawler_errors.append(str(exc))

    local_candidates: List[tuple[int, dict]] = []
    if str(user_id or "").strip():
        try:
            local_batch = await list_question_library_items(
                user_id=str(user_id or "").strip(),
                subject=str(subject or "").strip(),
                hidden="0",
                limit=60,
                offset=0,
                sort="updated_at",
                order="desc",
            )
        except Exception:
            local_batch = {}
        local_items = local_batch.get("items") if isinstance(local_batch, dict) else []
        if not isinstance(local_items, list):
            local_items = []
        topic_queries = _reference_query_candidates(topic, kp_labels)
        for item in local_items:
            if not isinstance(item, dict):
                continue
            qid = str(item.get("question_id") or "").strip()
            if not qid:
                continue
            source_text = str(item.get("source") or "").strip()
            date_text = str(item.get("date") or "").strip()
            normalized_meta = {
                "question_id": qid,
                "source": source_text,
                "date": date_text,
            }
            if not _reference_matches_constraints(normalized_meta, reference_source, reference_year_range):
                continue
            knowledge_candidates = [str(item.get("knowledge_point") or "").strip()]
            knowledge_candidates.extend(_parse_knowledge_points_json(item.get("knowledge_points_json")))
            stem_text = str(item.get("stem") or "").strip()
            score = 0
            if source_text:
                score += 1
            if date_text:
                score += 1
            if str(item.get("quality_score") or "").strip():
                try:
                    score += max(0, min(5, int(item.get("quality_score") or 0) // 20))
                except Exception:
                    score += 0
            for label in kp_labels[:6]:
                if label and any(label in candidate for candidate in knowledge_candidates if candidate):
                    score += 3
            for query in topic_queries[:4]:
                if query and (query in stem_text or any(query in candidate for candidate in knowledge_candidates if candidate)):
                    score += 2
            if score > 0:
                local_candidates.append((score, dict(item)))
        local_candidates.sort(key=lambda pair: pair[0], reverse=True)
        local_ids = [str(item.get("question_id") or "").strip() for _, item in local_candidates[: target_count * 2]]
        local_ids = [item for item in local_ids if item]
        if local_ids:
            try:
                cache_records = await get_question_cache(question_ids=local_ids)
            except Exception:
                cache_records = {}
            normalized_local_questions: List[dict] = []
            for _, item in local_candidates[: target_count * 2]:
                qid = str(item.get("question_id") or "").strip()
                cache_record = cache_records.get(qid) if isinstance(cache_records, dict) else None
                if not isinstance(cache_record, dict):
                    continue
                normalized = _normalize_reference_question(
                    {
                        "question_id": qid,
                        "stem": cache_record.get("stem"),
                        "answer": cache_record.get("answer"),
                        "analysis": cache_record.get("analysis"),
                        "difficulty": cache_record.get("difficulty") or item.get("difficulty"),
                        "question_type": cache_record.get("question_type") or item.get("question_type"),
                        "knowledge_points": cache_record.get("knowledge_points_json")
                        or cache_record.get("knowledge_point")
                        or item.get("knowledge_points_json")
                        or item.get("knowledge_point"),
                        "source": cache_record.get("source") or item.get("source") or "本地题库",
                        "date": cache_record.get("date") or item.get("date"),
                        "source_url": cache_record.get("source_url") or item.get("source_url"),
                        "origin": item.get("origin") or "local",
                    }
                )
                if normalized is None:
                    continue
                normalized["url"] = str(cache_record.get("source_url") or item.get("source_url") or "").strip()
                normalized_local_questions.append(normalized)
                if len(normalized_local_questions) >= target_count:
                    break
            if normalized_local_questions:
                return {
                    "success": True,
                    "source": "local_library",
                    "cache_hit": False,
                    "degraded": True,
                    "fallback_used": "local_library",
                    "error": crawler_errors[0] if crawler_errors else "reference_crawl_empty",
                    "questions": normalized_local_questions,
                    "count": len(normalized_local_questions),
                    "trace": {"cache_key": cache_key, "queries": queries, "crawler_errors": crawler_errors},
                }

    return {
        "success": False,
        "source": "none",
        "cache_hit": False,
        "degraded": True,
        "fallback_used": "",
        "error": crawler_errors[0] if crawler_errors else "reference_crawl_empty",
        "questions": [],
        "count": 0,
        "trace": {"cache_key": cache_key, "queries": queries, "crawler_errors": crawler_errors},
    }

