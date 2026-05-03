from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.crawler.manager import get_crawler
from backend.database.repositories.content.study_archives import (
    get_latest_study_archive,
    get_latest_study_archive_for_subject,
)
from backend.database.repositories.question.question_cache import get_question_cache, upsert_question_cache
from backend.database.repositories.question.question_library import list_question_library_items, upsert_question_library_items
from backend.generation.agentic.task_specs import (
    agentic_task_meta,
    build_agent_run_spec_for_task,
    build_agentic_starter_event,
)
from backend.llm.client import is_llm_configured
from backend.question_library.generation import (
    analyze_reference_questions,
    build_ai_question_id,
    build_source_pack,
    collect_reference_questions,
    enrich_source_pack_with_reference,
    generate_questions,
)
from backend.question_library.preview_store import (
    find_preview_by_session_id,
    load_preview,
    load_session,
    new_preview_id,
    new_session_id,
    save_preview,
    save_session,
)
from backend.question_library.session_utils import (
    draft_identity,
    merge_drafts,
    normalize_draft_questions,
    normalize_review_status,
)
from backend.question_library.scoring import apply_score_and_hide, score_stem_with_llm
from backend.question_library.stages import build_stage_progress_payload, get_question_generation_stage
from backend.shared.tasks import RuntimeTask, task_runtime

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)



def _ensure_session(
    *,
    session_id: str,
    user_id: str,
    preview_id: str,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    mode: str,
    count: int,
    use_study_archive: bool,
    use_reference_questions: bool,
    reference_source: str,
    reference_year_range: str,
    grade_id: str,
    textbook_version_id: str,
    knowledge_point_ids: List[str],
    knowledge_points: List[str],
    task_id: str,
    stream_reasoning: bool,
) -> dict:
    existing = load_session(session_id) if session_id else None
    session = dict(existing or {})
    sid = str(session_id or session.get("session_id") or "").strip() or new_session_id()
    pid = str(preview_id or session.get("preview_id") or "").strip()
    if not pid:
        pid = new_preview_id()

    preview_ids = list(session.get("preview_ids") or []) if isinstance(session.get("preview_ids"), list) else []
    if pid and pid not in preview_ids:
        preview_ids.append(pid)
    session["preview_id"] = pid
    session["preview_ids"] = preview_ids

    session["session_id"] = sid
    session["user_id"] = str(user_id or "").strip()
    session["status"] = str(session.get("status") or "pending_review").strip() or "pending_review"
    session["mode"] = str(mode or session.get("mode") or "standard").strip() or "standard"
    session["subject"] = subject
    session["topic"] = topic
    session["difficulty"] = difficulty
    session["question_type"] = question_type
    session["count"] = int(count or 0)
    session["use_study_archive"] = bool(use_study_archive)
    session["use_reference_questions"] = bool(use_reference_questions)
    session["reference_source"] = str(reference_source or "any").strip() or "any"
    session["reference_year_range"] = str(reference_year_range or "all").strip() or "all"
    session["grade_id"] = str(grade_id or "").strip()
    session["textbook_version_id"] = str(textbook_version_id or "").strip()
    session["knowledge_point_ids"] = [str(item or "").strip() for item in (knowledge_point_ids or []) if str(item or "").strip()]
    session["knowledge_points"] = [str(item or "").strip() for item in (knowledge_points or []) if str(item or "").strip()]
    session["stream_reasoning"] = bool(stream_reasoning)
    session["stop_requested"] = False if task_id else bool(session.get("stop_requested"))

    task_ids = list(session.get("task_ids") or []) if isinstance(session.get("task_ids"), list) else []
    if task_id and task_id not in task_ids:
        task_ids.append(task_id)
    session["task_ids"] = task_ids
    session["latest_task_id"] = task_ids[-1] if task_ids else ""

    session.setdefault("reasoning_blocks", [])
    session.setdefault("draft_questions", [])
    session.setdefault("confirmed_question_ids", [])
    return save_session(session)


def normalize_topic_key(topic: str) -> str:
    raw = str(topic or "").strip()
    if not raw:
        return ""

    for marker in ("输出要求", "LaTeX 公式规范", "LaTeX公式规范", "Output requirements"):
        idx = raw.find(marker)
        if idx >= 0:
            raw = raw[:idx].strip()
            break

    first_line = ""
    for ln in raw.splitlines():
        line = ln.strip()
        if line:
            first_line = line
            break
    if not first_line:
        first_line = raw
    return first_line[:120].strip()


def infer_question_type_from_topic(topic: str) -> str:
    raw = str(topic or "")
    if "选择题" in raw and "解答题" in raw:
        return "选择题+解答题"
    for hint in ("选择题", "解答题", "填空题", "判断题", "证明题", "综合题", "问答题"):
        if hint in raw:
            return hint
    return ""


class RunnerError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = str(detail or "runner_error")
        self.status_code = int(status_code or 400)


def _clamp_int(value: Any, *, default: int, min_v: int, max_v: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(int(min_v), min(int(max_v), parsed))


def _clamp_float(value: Any, *, default: Optional[float], min_v: float, max_v: float) -> Optional[float]:
    if value is None:
        return default
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(float(min_v), min(float(max_v), parsed))


def _now_iso_z() -> str:
    return _utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _emit_event(
    task: RuntimeTask,
    *,
    event_type: str,
    data: Dict[str, Any],
    user_id: str = "",
    persist_task_id: str = "",
    progress: Optional[float] = None,
) -> None:
    _ = user_id, persist_task_id, progress
    await task_runtime.append_event(task, {"type": str(event_type or "").strip() or "event", "data": dict(data or {})})


def _merge_reasoning_block(session: dict, *, task_id: str, payload: dict) -> dict:
    if not isinstance(session, dict):
        return session

    stage_id = str(payload.get("stage_id") or "").strip() or "default"
    stage_label = str(payload.get("stage_label") or "").strip() or stage_id
    source = str(payload.get("source") or "").strip() or "trace"
    content = str(payload.get("content") or "").strip()
    if not content:
        return session

    blocks = list(session.get("reasoning_blocks") or []) if isinstance(session.get("reasoning_blocks"), list) else []
    if (
        blocks
        and isinstance(blocks[-1], dict)
        and str(blocks[-1].get("task_id") or "").strip() == str(task_id or "").strip()
        and str(blocks[-1].get("stage_id") or "").strip() == stage_id
        and str(blocks[-1].get("source") or "").strip() == source
    ):
        blocks[-1]["content"] = str(blocks[-1].get("content") or "").rstrip() + content
    else:
        blocks.append(
            {
                "id": f"reason-{uuid.uuid4().hex[:12]}",
                "task_id": str(task_id or "").strip(),
                "stage_id": stage_id,
                "stage_label": stage_label,
                "source": source,
                "content": content,
                "created_at": _now_iso_z(),
            }
        )

    session = dict(session)
    session["reasoning_blocks"] = blocks[-200:]
    return session


def _append_reasoning_status(session: dict, *, task_id: str, payload: dict) -> dict:
    if not isinstance(session, dict):
        return session

    stage_id = str(payload.get("stage_id") or "").strip() or "default"
    stage_label = str(payload.get("stage_label") or "").strip() or stage_id
    mode = str(payload.get("mode") or "").strip() or "trace"
    message = str(payload.get("message") or "").strip()
    if not message:
        return session

    statuses = (
        list(session.get("reasoning_statuses") or []) if isinstance(session.get("reasoning_statuses"), list) else []
    )
    statuses.append(
        {
            "task_id": str(task_id or "").strip(),
            "stage_id": stage_id,
            "stage_label": stage_label,
            "mode": mode,
            "message": message,
            "created_at": _now_iso_z(),
        }
    )

    session = dict(session)
    session["reasoning_statuses"] = statuses[-200:]
    return session


def _materialize_drafts(
    drafts: List[dict],
    *,
    existing_drafts: List[dict],
    draft_key_to_id: Dict[str, str],
) -> Tuple[List[dict], Dict[str, str]]:
    for item in normalize_draft_questions(existing_drafts):
        key = draft_identity(item)
        qid = str(item.get("question_id") or "").strip()
        if key and qid:
            draft_key_to_id.setdefault(key, qid)

    out: List[dict] = []
    for item in drafts or []:
        if not isinstance(item, dict):
            continue
        stem = str(item.get("stem") or "").strip()
        answer = str(item.get("answer") or "").strip()
        analysis = str(item.get("analysis") or "").strip()
        if not stem or not answer or not analysis:
            continue
        diagrams = item.get("diagrams")
        normalized_diagrams = [d for d in diagrams if isinstance(d, dict)][:6] if isinstance(diagrams, list) else None
        key = draft_identity({"stem": stem, "answer": answer, "analysis": analysis})
        qid = str(item.get("question_id") or "").strip() or draft_key_to_id.get(key) or build_ai_question_id(
            suffix=uuid.uuid4().hex[:8]
        )
        draft_key_to_id[key] = qid
        out.append(
            {
                "question_id": qid,
                "stem": stem,
                "answer": answer,
                "analysis": analysis,
                "keep": bool(item.get("keep", True)),
                "review_status": normalize_review_status(item.get("review_status")),
                "review": dict(item.get("review") or {}) if isinstance(item.get("review"), dict) else None,
                **({"diagrams": normalized_diagrams} if normalized_diagrams is not None else {}),
            }
        )
    return out, draft_key_to_id


async def create_crawl_task(*, user_id: str, request: Dict[str, Any]) -> RuntimeTask:
    req = dict(request or {})
    subject = str(req.get("subject") or "").strip()
    edu_level = str(req.get("edu_level") or "").strip()
    query = str(req.get("query") or "").strip()
    if not query:
        raise RunnerError("query_required", status_code=400)

    difficulty = str(req.get("difficulty") or "").strip()
    question_type = str(req.get("question_type") or "").strip()
    limit = _clamp_int(req.get("limit"), default=30, min_v=1, max_v=200)
    max_pages = _clamp_int(req.get("max_pages"), default=2, min_v=1, max_v=50)
    min_quality_score = _clamp_int(req.get("min_quality_score"), default=0, min_v=0, max_v=100)
    difficulty_value_min = _clamp_float(req.get("difficulty_value_min"), default=None, min_v=0.0, max_v=1.0)
    difficulty_value_max = _clamp_float(req.get("difficulty_value_max"), default=None, min_v=0.0, max_v=1.0)
    if difficulty_value_min is not None and difficulty_value_max is not None and difficulty_value_min > difficulty_value_max:
        difficulty_value_min, difficulty_value_max = difficulty_value_max, difficulty_value_min
    require_difficulty_value = bool(req.get("require_difficulty_value")) and (
        difficulty_value_min is not None or difficulty_value_max is not None
    )

    task_id = str(req.get("task_id") or "").strip() or f"ql_crawl_{uuid.uuid4().hex[:12]}"

    async def runner_factory(task: RuntimeTask) -> None:
        try:
            await task_runtime.append_event(
                task,
                {
                    "type": "step",
                    "step": {
                        "id": "crawl",
                        "title": "爬取入库",
                        "status": "running",
                        "startTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "toolName": "question_library_crawl",
                        "input": {
                            "taskId": task.task_id,
                            "subject": subject,
                            "edu_level": edu_level,
                            "query": query,
                            "difficulty": difficulty,
                            "question_type": question_type,
                            "limit": limit,
                            "max_pages": max_pages,
                            "min_quality_score": min_quality_score,
                            "difficulty_value_min": difficulty_value_min,
                            "difficulty_value_max": difficulty_value_max,
                            "require_difficulty_value": require_difficulty_value,
                        },
                    },
                },
            )

            crawler = await get_crawler(subject=subject, edu_level=edu_level, strict=True)
            res = await crawler.search_by_keyword(
                keyword=query,
                subject=subject,
                edu_level=edu_level,
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                max_pages=max_pages,
                min_quality_score=min_quality_score,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                require_difficulty_value=require_difficulty_value,
                parse_content=True,
            )
            if not bool(res.get("success")):
                raise RuntimeError(str(res.get("error") or "crawl_failed"))

            questions = res.get("questions") if isinstance(res.get("questions"), list) else []
            total = len(questions)
            inserted = 0
            qids: list[str] = []

            for i, q in enumerate(questions, start=1):
                if task.status != "running":
                    break
                if not isinstance(q, dict):
                    continue

                qid = str(q.get("question_id") or "").strip()
                stem = str(q.get("stem") or "").strip()
                if not qid or not stem:
                    continue

                await upsert_question_cache(
                    [
                        {
                            "question_id": qid,
                            "stem": stem,
                            "answer": str(q.get("answer") or "").strip(),
                            "analysis": str(q.get("analysis") or "").strip(),
                            "difficulty": str(q.get("difficulty") or "").strip(),
                            "question_type": str(q.get("question_type") or "").strip(),
                            "source": str(q.get("source") or "").strip(),
                            "date": str(q.get("date") or "").strip(),
                        }
                    ]
                )
                await upsert_question_library_items(
                    user_id=user_id,
                    items=[{"question_id": qid, "subject": subject, "origin": "crawled"}],
                )

                inserted += 1
                qids.append(qid)

                await task_runtime.append_event(
                    task,
                    {
                        "type": "item_saved",
                        "data": {
                            "item": {
                                "question_id": qid,
                                "subject": subject,
                                "origin": "crawled",
                                "hidden": False,
                                "stem": stem,
                            }
                        },
                    },
                )

                pct = int((i / max(1, total)) * 100)
                await task_runtime.append_event(task, {"type": "progress", "data": {"progress": pct}})

            await task_runtime.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "inserted": inserted,
                        "subject": subject,
                        "count": len(qids),
                        "question_ids": qids,
                    },
                },
            )
            await task_runtime.complete_task(task)
        except asyncio.CancelledError:
            await task_runtime.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_crawl",
        title=f"题库抓取：{subject or query or 'crawl'}",
        request=req,
        runner_factory=runner_factory,
    )


async def create_score_task(*, user_id: str, request: Dict[str, Any]) -> RuntimeTask:
    req = dict(request or {})
    if not is_llm_configured():
        raise RunnerError("llm_not_configured", status_code=500)

    subject = str(req.get("subject") or "").strip()
    if not subject:
        raise RunnerError("subject_required", status_code=400)

    limit = _clamp_int(req.get("limit"), default=50, min_v=1, max_v=500)
    only_unscored = bool(req.get("only_unscored"))
    task_id = str(req.get("task_id") or "").strip() or f"ql_score_{uuid.uuid4().hex[:12]}"

    threshold = _clamp_int(os.getenv("QUESTION_LIBRARY_HIDE_THRESHOLD") or 70, default=70, min_v=0, max_v=100)
    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini"
    agent_spec = build_agent_run_spec_for_task(task_type="question_library_score", request=req)

    async def runner_factory(task: RuntimeTask) -> None:
        try:
            await task_runtime.append_event(task, {"type": "progress", "data": {"progress": 5, "stage": "Load"}})

            batch = await list_question_library_items(
                user_id=user_id,
                subject=subject,
                origin="crawled",
                hidden="0",
                limit=min(200, max(50, limit)),
                offset=0,
                sort="updated_at",
                order="desc",
            )
            items = batch.get("items") if isinstance(batch, dict) else []
            if not isinstance(items, list):
                items = []

            qids: list[str] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                qid = str(it.get("question_id") or "").strip()
                if not qid:
                    continue
                if only_unscored and it.get("ai_score") is not None:
                    continue
                qids.append(qid)
                if len(qids) >= limit:
                    break

            if not qids:
                await task_runtime.append_event(
                    task,
                    {"type": "done", "data": {"success": True, "scored": 0, "hidden": 0, "subject": subject, "count": 0}},
                )
                await task_runtime.complete_task(task)
                return

            cache = await get_question_cache(question_ids=qids)
            scored = 0
            hidden_n = 0
            total = len(qids)
            await task_runtime.append_event(task, {"type": "progress", "data": {"progress": 10, "stage": "Score"}})

            for idx, qid in enumerate(qids, start=1):
                if task.status != "running":
                    break
                stem = str((cache.get(qid) or {}).get("stem") or "").strip()
                if not stem:
                    continue

                res = await score_stem_with_llm(subject=subject, stem=stem, model=model)
                overall = int(res.get("overall_score") or 0)
                verdict = str(res.get("verdict") or "").strip()
                dims = list(res.get("dimensions") or [])
                summary = str(res.get("summary") or "").strip()

                await apply_score_and_hide(
                    user_id=user_id,
                    question_id=qid,
                    overall_score=overall,
                    verdict=verdict,
                    dimensions=[x for x in dims if isinstance(x, dict)],
                    summary=summary,
                    threshold=threshold,
                )

                scored += 1
                if overall < threshold:
                    hidden_n += 1

                await task_runtime.append_event(
                    task,
                    {
                        "type": "item_saved",
                        "data": {
                            "item": {
                                "question_id": qid,
                                "subject": subject,
                                "origin": "crawled",
                                "ai_score": overall,
                                "ai_verdict": verdict,
                                "ai_summary": summary,
                                "hidden": overall < threshold,
                                "stem": stem,
                            }
                        },
                    },
                )

                pct = 10 + int((idx / max(1, total)) * 88)
                await task_runtime.append_event(
                    task, {"type": "progress", "data": {"progress": min(98, pct), "stage": "Score"}}
                )

            await task_runtime.append_event(
                task,
                {
                    "type": "done",
                    "data": {
                        "success": True,
                        "subject": subject,
                        "count": scored,
                        "scored": scored,
                        "hidden": hidden_n,
                        "threshold": threshold,
                    },
                },
            )
            await task_runtime.complete_task(task)
        except asyncio.CancelledError:
            await task_runtime.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_score",
        title=f"题库评分：{subject or 'score'}",
        request=req,
        runner_factory=runner_factory,
        meta=agentic_task_meta(agent_spec),
        starter_event=build_agentic_starter_event(spec=agent_spec, title="开始题库评分", tool_name="question_library_score")
        if agent_spec is not None
        else None,
    )


async def create_generate_task(*, user_id: str, request: Dict[str, Any]) -> RuntimeTask:
    req = dict(request or {})
    if not is_llm_configured():
        raise RunnerError("llm_not_configured", status_code=500)

    subject = str(req.get("subject") or "").strip()
    topic_raw = str(req.get("topic") or "").strip()
    if not subject:
        raise RunnerError("subject_required", status_code=400)
    if not topic_raw:
        raise RunnerError("topic_required", status_code=400)

    difficulty = str(req.get("difficulty") or "").strip()
    question_type = str(req.get("question_type") or "").strip()
    if not question_type:
        inferred = infer_question_type_from_topic(topic_raw)
        if inferred:
            question_type = inferred

    count = _clamp_int(req.get("count"), default=5, min_v=1, max_v=10)
    mode = str(req.get("mode") or "standard").strip() or "standard"
    if mode not in {"standard", "infinite"}:
        mode = "standard"
    append_mode = bool(req.get("append"))
    stream_reasoning = bool(req.get("stream_reasoning"))
    use_archive = bool(req.get("use_study_archive"))
    use_reference_questions = bool(req.get("use_reference_questions"))
    reference_source = str(req.get("reference_source") or "any").strip() or "any"
    if reference_source not in {"any", "gaokao", "mock", "joint"}:
        reference_source = "any"
    reference_year_range = str(req.get("reference_year_range") or "all").strip() or "all"
    if reference_year_range not in {"all", "3", "5"}:
        reference_year_range = "all"
    session_id = str(req.get("session_id") or "").strip()
    grade_id = str(req.get("grade_id") or "").strip()
    textbook_version_id = str(req.get("textbook_version_id") or "").strip()
    knowledge_point_ids = [str(item or "").strip() for item in (req.get("knowledge_point_ids") or []) if str(item or "").strip()]
    knowledge_points = [str(item or "").strip() for item in (req.get("knowledge_points") or []) if str(item or "").strip()]

    task_id = str(req.get("task_id") or "").strip() or f"ql_gen_{uuid.uuid4().hex[:12]}"
    topic_key = normalize_topic_key(topic_raw) or topic_raw
    agent_spec = build_agent_run_spec_for_task(task_type="question_library_generate", request=req)

    existing_session = load_session(session_id) if session_id else None
    if session_id and existing_session and str(existing_session.get("user_id") or "").strip() != str(user_id or "").strip():
        raise RunnerError("session_not_found", status_code=404)
    if not session_id:
        session_id = new_session_id()

    existing_preview = find_preview_by_session_id(user_id, session_id) if append_mode and session_id else None
    preview_id = (
        str((existing_session or {}).get("preview_id") or "").strip() if append_mode and isinstance(existing_session, dict) else ""
    ) or str((existing_preview or {}).get("preview_id") or "").strip() or new_preview_id()

    current_session = _ensure_session(
        session_id=session_id,
        user_id=user_id,
        preview_id=preview_id,
        subject=subject,
        topic=topic_raw,
        difficulty=difficulty,
        question_type=question_type,
        mode=mode,
        count=count,
        use_study_archive=use_archive,
        use_reference_questions=use_reference_questions,
        reference_source=reference_source,
        reference_year_range=reference_year_range,
        grade_id=grade_id,
        textbook_version_id=textbook_version_id,
        knowledge_point_ids=knowledge_point_ids,
        knowledge_points=knowledge_points,
        task_id=task_id,
        stream_reasoning=stream_reasoning,
    )
    current_session["status"] = "running"
    save_session(current_session)

    async def runner_factory(task: RuntimeTask) -> None:
        draft_key_to_id: Dict[str, str] = {}
        progress_drafts = normalize_draft_questions(
            ((existing_preview or {}).get("draft_questions") if isinstance(existing_preview, dict) else [])
            or ((current_session or {}).get("draft_questions") if isinstance(current_session, dict) else [])
        )

        def _save_snapshot(*, session_status: str, preview_status: str, new_drafts: Optional[List[dict]] = None) -> None:
            nonlocal progress_drafts
            if new_drafts:
                progress_drafts = merge_drafts(progress_drafts, new_drafts)

            session = load_session(session_id) or {}
            if isinstance(session, dict):
                session = dict(session)
                session["status"] = str(session_status or "").strip() or session.get("status") or "running"
                session["draft_questions"] = progress_drafts
                session.setdefault("reasoning_blocks", [])
                save_session(session)

            save_preview(
                {
                    "preview_id": preview_id,
                    "session_id": session_id,
                    "mode": mode,
                    "status": str(preview_status or "").strip() or "running",
                    "user_id": str(user_id or "").strip(),
                    "task_id": str(task_id or "").strip(),
                    "subject": subject,
                    "topic": topic_raw,
                    "difficulty": difficulty,
                    "question_type": question_type,
                    "use_reference_questions": bool(use_reference_questions),
                    "reference_source": reference_source,
                    "reference_year_range": reference_year_range,
                    "study_markdown": "",
                    "draft_questions": progress_drafts,
                }
            )

        async def _emit_progress(stage_id: str, *, progress: float, stats: Optional[dict] = None, sample: Optional[dict] = None) -> None:
            payload = build_stage_progress_payload(
                stage_id,
                progress=float(progress),
                stats=stats if isinstance(stats, dict) else None,
                sample=sample if isinstance(sample, dict) else None,
            )
            await _emit_event(task, event_type="progress", data=payload, user_id=user_id, persist_task_id=task_id, progress=progress)

        async def _on_stage_event(payload: dict) -> None:
            if not isinstance(payload, dict):
                return
            phase = str(payload.get("phase") or "").strip()
            if not phase:
                return
            await _emit_progress(
                phase,
                progress=float(payload.get("progress") or 0.0),
                stats=payload.get("stats") if isinstance(payload.get("stats"), dict) else None,
                sample=payload.get("sample") if isinstance(payload.get("sample"), dict) else None,
            )

        async def _on_candidate_accepted(candidate: dict) -> None:
            if not isinstance(candidate, dict):
                return
            materialized, _ = _materialize_drafts(
                [candidate],
                existing_drafts=progress_drafts,
                draft_key_to_id=draft_key_to_id,
            )
            if materialized:
                _save_snapshot(session_status="running", preview_status="running", new_drafts=materialized)

        async def _on_reasoning_event(payload: dict) -> None:
            if not isinstance(payload, dict):
                return
            event_type = str(payload.get("type") or "").strip()
            if not event_type:
                return
            data = dict(payload)
            data.pop("type", None)

            if event_type in {"reasoning_delta", "reasoning_status"}:
                await _emit_event(task, event_type=event_type, data=data, user_id=user_id, persist_task_id=task_id)

            session = load_session(session_id) or {}
            if isinstance(session, dict):
                session = dict(session)
                if event_type == "reasoning_delta":
                    session = _merge_reasoning_block(session, task_id=task_id, payload=data)
                elif event_type == "reasoning_status":
                    session = _append_reasoning_status(session, task_id=task_id, payload=data)
                save_session(session)

        async def _stop_requested() -> bool:
            session = load_session(session_id) or {}
            if isinstance(session, dict) and bool(session.get("stop_requested")):
                return True
            return task.status != "running"

        try:
            _save_snapshot(session_status="running", preview_status="running")
            await _emit_progress("source_pack", progress=5.0, stats={"use_study_archive": bool(use_archive)})

            study_markdown = ""
            if use_archive:
                try:
                    archive = await get_latest_study_archive(user_id=user_id, subject=subject, topic=topic_key)
                except Exception:
                    archive = None
                if not isinstance(archive, dict):
                    try:
                        archive = await get_latest_study_archive_for_subject(user_id=user_id, subject=subject)
                    except Exception:
                        archive = None
                if isinstance(archive, dict):
                    study_markdown = str(archive.get("markdown") or "")

            source_pack = await build_source_pack(
                study_markdown,
                subject,
                topic_key,
                stream_reasoning=stream_reasoning,
                on_reasoning_event=_on_reasoning_event,
            )
            await _emit_progress("source_pack", progress=10.0, stats={"study_markdown_chars": len(study_markdown)})

            if use_reference_questions and not await _stop_requested():
                await _emit_progress("reference_crawl", progress=14.0, stats={"enabled": True})
                reference_result = await collect_reference_questions(
                    user_id=user_id,
                    subject=subject,
                    topic=topic_key,
                    difficulty=difficulty,
                    question_type=question_type,
                    knowledge_point_ids=knowledge_point_ids,
                    knowledge_points=knowledge_points,
                    desired_count=max(5, min(10, count + 3)),
                    reference_source=reference_source,
                    reference_year_range=reference_year_range,
                )
                reference_questions = (
                    [dict(item) for item in (reference_result.get("questions") or []) if isinstance(item, dict)]
                    if isinstance(reference_result, dict)
                    else []
                )
                await _emit_progress("reference_crawl", progress=18.0, stats={"reference_count": len(reference_questions)})

                await _emit_progress("reference_analysis", progress=22.0, stats={"enabled": True})
                if reference_questions:
                    reference_analysis = await analyze_reference_questions(
                        subject=subject,
                        topic=topic_key,
                        difficulty=difficulty,
                        question_type=question_type,
                        reference_questions=reference_questions,
                        stream_reasoning=stream_reasoning,
                        on_reasoning_event=_on_reasoning_event,
                    )
                    source_pack = enrich_source_pack_with_reference(source_pack, reference_analysis, reference_questions)
                    await _emit_progress("reference_analysis", progress=26.0, stats={"reference_count": len(reference_questions)})
                else:
                    await _emit_progress("reference_analysis", progress=26.0, stats={"skipped": True})

            batches = 0
            while True:
                if await _stop_requested():
                    break
                batches += 1
                try:
                    finals = await generate_questions(
                        source_pack=source_pack,
                        count=count,
                        difficulty=difficulty,
                        question_type=question_type,
                        user_id=user_id,
                        on_stage_event=_on_stage_event,
                        on_reasoning_event=_on_reasoning_event,
                        on_candidate_accepted=_on_candidate_accepted,
                        on_generation_snapshot=None,
                        stream_reasoning=stream_reasoning,
                        config=None,
                    )
                except Exception as exc:
                    await _on_reasoning_event(
                        {
                            "type": "reasoning_status",
                            "stage_id": "draft_realization",
                            "stage_label": get_question_generation_stage("draft_realization").label,
                            "mode": "trace",
                            "message": f"批次生成异常，将重试: {str(exc)[:220]}",
                        }
                    )
                    if mode == "infinite":
                        await asyncio.sleep(0.2)
                        continue
                    raise

                finals = [dict(x) for x in (finals or []) if isinstance(x, dict)]
                if not finals:
                    if mode == "infinite":
                        await asyncio.sleep(0.2)
                        continue
                    break

                materialized, _ = _materialize_drafts(finals, existing_drafts=progress_drafts, draft_key_to_id=draft_key_to_id)
                if materialized:
                    _save_snapshot(session_status="running", preview_status="running", new_drafts=materialized)

                if mode != "infinite":
                    break

            final_session_status = "pending_review"
            if mode == "infinite":
                final_session_status = "stopped" if await _stop_requested() else "pending_review"
            _save_snapshot(session_status=final_session_status, preview_status="pending_review")

            await _emit_progress("pending_review", progress=96.0, stats={"draft_count": len(progress_drafts), "batches": batches})
            await _emit_event(
                task,
                event_type="done",
                data={
                    "success": True,
                    "session_id": session_id,
                    "preview_id": preview_id,
                    "subject": subject,
                    "topic": topic_key,
                    "count": len(progress_drafts),
                },
                user_id=user_id,
                persist_task_id=task_id,
            )
            await task_runtime.complete_task(
                task, result={"success": True, "session_id": session_id, "preview_id": preview_id}
            )
        except asyncio.CancelledError:
            # External controllers (e.g. app shutdown) may set a terminal status
            # before cancelling the runner. Respect that state and avoid
            # overwriting DB error payloads with a generic "Task cancelled".
            if task.status != "running":
                async with task.cond:
                    task.cond.notify_all()
                raise

            await task_runtime.fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            try:
                # Preserve any accepted drafts for the review UI, even when the
                # pipeline fails mid-way (e.g., judge stage crash).
                if progress_drafts:
                    _save_snapshot(session_status="partial_failure", preview_status="pending_review")
                else:
                    _save_snapshot(session_status="failed", preview_status="pending_review")
            except Exception:
                logger.warning(
                    "question_library_snapshot_save_failed",
                    extra={"user_id": user_id, "task_id": task_id},
                    exc_info=True,
                )
            await task_runtime.fail_task(task, str(exc))
        finally:
            if task.status == "running":
                await task_runtime.fail_task(task, "Task ended unexpectedly")

    return await task_runtime.create_task(
        task_id=task_id,
        user_id=user_id,
        task_type="question_library_generate",
        title=f"AI 出题：{subject} {topic_key}".strip(),
        request=req,
        runner_factory=runner_factory,
        meta=agentic_task_meta(agent_spec),
        starter_event=build_agentic_starter_event(spec=agent_spec, title="开始 AI 出题", tool_name="question_library_generate")
        if agent_spec is not None
        else None,
    )
