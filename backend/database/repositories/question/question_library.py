from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Literal, Optional

from sqlalchemy import String, and_, cast, delete, desc, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.repositories.user_ids import normalize_user_id
from backend.database.schema import GaokaoQuestionSource, QuestionCache, QuestionLibraryItem
from backend.shared.question_thinking import extract_thinking_depth

HiddenFilter = Literal["0", "1", "all"]
LibraryAreaFilter = Literal["general", "gaokao", "all"]


def _normalize_user_id(user_id: str) -> str:
    return normalize_user_id(user_id)


def _require_user_id(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("missing_user_id")
    return uid


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default)


def _with_thinking_depth_fields(item: Dict[str, Any], dimensions_json: Any) -> Dict[str, Any]:
    depth = extract_thinking_depth(dimensions_json)
    item["thinking_depth_score"] = depth.get("score")
    item["thinking_method_family"] = depth.get("method_family") or ""
    item["thinking_method_signature"] = depth.get("method_signature") or ""
    item["thinking_method_rarity"] = depth.get("method_rarity") or ""
    item["thinking_method_count"] = depth.get("similar_method_count")
    item["thinking_depth_comment"] = depth.get("comment") or ""
    return item


def _clean_filter(value: Any) -> str:
    return str(value or "").strip()


def _like_filter(columns: Iterable[Any], value: Any) -> Any | None:
    needle = _clean_filter(value)
    if not needle:
        return None
    like = f"%{needle}%"
    return or_(*(col.like(like) for col in columns))


def _difficulty_aliases(value: Any) -> List[str]:
    v = _clean_filter(value)
    if not v:
        return []
    aliases = {
        "容易": ["容易", "简单"],
        "简单": ["简单", "容易"],
        "适中": ["适中", "中等", "普通"],
        "中等": ["中等", "适中", "普通"],
        "普通": ["普通", "中等", "适中"],
        "困难": ["困难", "较难", "难"],
        "较难": ["较难", "困难", "难"],
    }
    return aliases.get(v, [v])


def _question_type_aliases(value: Any) -> List[str]:
    v = _clean_filter(value)
    if not v:
        return []
    aliases = {
        "单选题": ["单选题", "单项选择题"],
        "多选题": ["多选题", "多项选择题"],
        "选择题": ["选择题", "单选题", "单项选择题", "多选题", "多项选择题"],
        "解答题": ["解答题", "简答题", "问答题"],
        "简答题": ["简答题", "解答题", "问答题"],
        "概念填空": ["概念填空", "填空题"],
        "填空题": ["填空题", "概念填空"],
    }
    return list(dict.fromkeys(aliases.get(v, [v])))


def _question_type_filter(value: Any) -> Any | None:
    values = _question_type_aliases(value)
    if not values:
        return None
    return or_(*(QuestionCache.question_type.like(f"%{alias}%") for alias in values))


async def upsert_question_library_items(
    *,
    user_id: str,
    items: List[dict],
    session: Optional[AsyncSession] = None,
) -> int:
    uid = _require_user_id(user_id)
    entries = [x for x in (items or []) if isinstance(x, dict)]
    if not entries:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            n = await upsert_question_library_items(user_id=uid, items=entries, session=session)
            await session.commit()
            return n

    n = 0
    for it in entries:
        qid = str(it.get("question_id") or "").strip()
        if not qid:
            continue

        values: Dict[str, Any] = {
            "user_id": uid,
            "question_id": qid,
            "subject": "",
            "origin": "crawled",
            "hidden": 0,
            "starred": 0,
            "ai_verdict": "",
            "ai_dimensions_json": "",
            "ai_summary": "",
        }
        update_cols: Dict[str, Any] = {}
        subj = str(it.get("subject") or "").strip()
        if subj:
            values["subject"] = subj
            update_cols["subject"] = subj
        origin = str(it.get("origin") or "").strip()
        if origin:
            values["origin"] = origin
            update_cols["origin"] = origin
        if "hidden" in it:
            values["hidden"] = 1 if bool(it.get("hidden")) else 0
            update_cols["hidden"] = values["hidden"]
        if "starred" in it:
            values["starred"] = 1 if bool(it.get("starred")) else 0
            update_cols["starred"] = values["starred"]

        if "ai_score" in it:
            try:
                values["ai_score"] = int(it.get("ai_score")) if it.get("ai_score") is not None else None
            except (TypeError, ValueError):
                values["ai_score"] = None
            update_cols["ai_score"] = values["ai_score"]
        if "ai_verdict" in it:
            values["ai_verdict"] = str(it.get("ai_verdict") or "").strip()
            update_cols["ai_verdict"] = values["ai_verdict"]
        if "ai_dimensions_json" in it:
            values["ai_dimensions_json"] = str(it.get("ai_dimensions_json") or "").strip()
            update_cols["ai_dimensions_json"] = values["ai_dimensions_json"]
        if "ai_summary" in it:
            values["ai_summary"] = str(it.get("ai_summary") or "").strip()
            update_cols["ai_summary"] = values["ai_summary"]

        stmt = sqlite_insert(QuestionLibraryItem).values(**values)
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "question_id"],
                set_=update_cols,
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "question_id"])
        await session.execute(stmt)
        n += 1

    await session.flush()
    return n


async def list_question_library_items(
    *,
    user_id: str,
    subject: str = "",
    origin: str = "",
    area: LibraryAreaFilter = "all",
    hidden: HiddenFilter = "0",
    q: str = "",
    exam_scene: str = "",
    question_type: str = "",
    difficulty: str = "",
    category: str = "",
    year: str = "",
    region: str = "",
    grade: str = "",
    semester: str = "",
    method: str = "",
    only_new: bool = False,
    min_score: Optional[int] = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    include_total: bool = True,
    session: Optional[AsyncSession] = None,
) -> dict:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    origin_v = str(origin or "").strip()
    qv = str(q or "").strip()
    lim = max(1, min(_as_int(limit, 50), 200))
    off = max(0, _as_int(offset, 0))

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_question_library_items(
                user_id=uid,
                subject=subject,
                origin=origin,
                area=area,
                hidden=hidden,
                q=q,
                exam_scene=exam_scene,
                question_type=question_type,
                difficulty=difficulty,
                category=category,
                year=year,
                region=region,
                grade=grade,
                semester=semester,
                method=method,
                only_new=only_new,
                min_score=min_score,
                sort=sort,
                order=order,
                limit=limit,
                offset=offset,
                include_total=include_total,
                session=session,
            )

    area_v = str(area or "all").strip().lower()
    if area_v not in {"general", "gaokao", "all"}:
        area_v = "all"

    gaokao_join = and_(
        GaokaoQuestionSource.user_id == QuestionLibraryItem.user_id,
        GaokaoQuestionSource.question_id == QuestionLibraryItem.question_id,
    )
    where = [QuestionLibraryItem.user_id == uid]
    if area_v == "general":
        where.append(GaokaoQuestionSource.question_id.is_(None))
    elif area_v == "gaokao":
        where.append(GaokaoQuestionSource.question_id.is_not(None))
    if subj:
        where.append(QuestionLibraryItem.subject == subj)
    if origin_v:
        where.append(QuestionLibraryItem.origin == origin_v)
    if hidden in {"0", "1"}:
        where.append(QuestionLibraryItem.hidden == (1 if hidden == "1" else 0))
    if min_score is not None:
        where.append(QuestionLibraryItem.ai_score >= int(min_score))
    if only_new:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        where.append(QuestionLibraryItem.updated_at >= cutoff)

    source_columns = (
        QuestionCache.source,
        QuestionCache.stem,
        GaokaoQuestionSource.paper_name,
        GaokaoQuestionSource.paper_variant,
        GaokaoQuestionSource.region,
    )
    broad_columns = (
        QuestionCache.source,
        QuestionCache.stem,
        QuestionCache.knowledge_point,
        QuestionCache.knowledge_points_json,
    )
    for extra_filter in (
        _like_filter(source_columns, exam_scene),
        _question_type_filter(question_type),
        _like_filter(broad_columns, category),
        _like_filter(
            (QuestionCache.source, QuestionCache.date, QuestionCache.stem, cast(GaokaoQuestionSource.exam_year, String)),
            year,
        ),
        _like_filter(source_columns, region),
        _like_filter(source_columns, grade),
        _like_filter((QuestionCache.source, QuestionCache.date, QuestionCache.stem), semester),
        _like_filter((*broad_columns, QuestionLibraryItem.ai_summary, QuestionLibraryItem.ai_dimensions_json), method),
    ):
        if extra_filter is not None:
            where.append(extra_filter)

    difficulty_values = _difficulty_aliases(difficulty)
    if difficulty_values:
        where.append(QuestionCache.difficulty.in_(difficulty_values))

    q_filter = None
    if qv:
        like = f"%{qv}%"
        q_filter = or_(QuestionCache.stem.like(like), QuestionLibraryItem.question_id.like(like))

    stmt = (
        select(
            QuestionLibraryItem.question_id,
            QuestionLibraryItem.subject,
            QuestionLibraryItem.origin,
            QuestionLibraryItem.hidden,
            QuestionLibraryItem.starred,
            QuestionLibraryItem.ai_score,
            QuestionLibraryItem.ai_verdict,
            QuestionLibraryItem.ai_dimensions_json,
            QuestionLibraryItem.ai_summary,
            QuestionLibraryItem.updated_at,
            QuestionCache.stem,
            QuestionCache.question_type,
            QuestionCache.difficulty,
            QuestionCache.difficulty_value,
            QuestionCache.knowledge_point,
            QuestionCache.knowledge_points_json,
            QuestionCache.source_url,
            QuestionCache.quality_score,
            QuestionCache.source,
            QuestionCache.date,
            func.length(func.trim(func.coalesce(QuestionCache.answer, ""))),
            func.length(func.trim(func.coalesce(QuestionCache.analysis, ""))),
            GaokaoQuestionSource.question_id,
            GaokaoQuestionSource.exam_year,
            GaokaoQuestionSource.region,
            GaokaoQuestionSource.paper_name,
            GaokaoQuestionSource.paper_variant,
            GaokaoQuestionSource.question_number,
            GaokaoQuestionSource.source_url,
            GaokaoQuestionSource.source_note,
            GaokaoQuestionSource.verified,
        )
        .select_from(QuestionLibraryItem)
        .join(QuestionCache, QuestionCache.question_id == QuestionLibraryItem.question_id, isouter=True)
        .join(GaokaoQuestionSource, gaokao_join, isouter=True)
        .where(*where)
    )
    if q_filter is not None:
        stmt = stmt.where(q_filter)

    sort_key = sort.strip().lower()
    order_key = order.strip().lower()
    col = QuestionLibraryItem.updated_at if sort_key != "ai_score" else QuestionLibraryItem.ai_score
    tie_breaker = QuestionLibraryItem.question_id.asc() if order_key == "asc" else QuestionLibraryItem.question_id.desc()
    stmt = stmt.order_by(desc(col) if order_key != "asc" else col.asc(), tie_breaker)

    total: Optional[int] = None
    if include_total:
        total_stmt = (
            select(func.count())
            .select_from(QuestionLibraryItem)
            .join(QuestionCache, QuestionCache.question_id == QuestionLibraryItem.question_id, isouter=True)
            .join(GaokaoQuestionSource, gaokao_join, isouter=True)
        )
        if q_filter is not None:
            total_stmt = total_stmt.where(*where, q_filter)
        else:
            total_stmt = total_stmt.where(*where)
        total = int((await session.execute(total_stmt)).scalar() or 0)

    rows = (await session.execute(stmt.limit(lim).offset(off))).all()

    items: List[Dict[str, Any]] = []
    for r in rows:
        has_answer = int(r[20] or 0) > 0
        has_analysis = int(r[21] or 0) > 0
        gaokao_source = None
        if r[22] is not None:
            gaokao_source = {
                "exam_year": int(r[23]),
                "region": r[24] or "",
                "paper_name": r[25] or "",
                "paper_variant": r[26] or "",
                "question_number": r[27] or "",
                "source_url": r[28] or "",
                "source_note": r[29] or "",
                "verified": bool(r[30]),
            }
        item = {
            "question_id": r[0],
            "subject": r[1] or "",
            "origin": r[2] or "",
            "hidden": bool(r[3]),
            "starred": bool(r[4]),
            "ai_score": r[5],
            "ai_verdict": r[6] or "",
            "ai_dimensions_json": r[7] or "",
            "ai_summary": r[8] or "",
            "updated_at": r[9].isoformat() if r[9] else "",
            "stem": (r[10] or ""),
            "question_type": r[11] or "",
            "difficulty": r[12] or "",
            "difficulty_value": r[13],
            "knowledge_point": r[14] or "",
            "knowledge_points_json": r[15] or "",
            "source_url": r[16] or "",
            "quality_score": int(r[17] or 0),
            "source": r[18] or "",
            "date": r[19] or "",
            "has_answer": has_answer,
            "has_analysis": has_analysis,
            "library_area": "gaokao" if gaokao_source is not None else "general",
            "gaokao_source": gaokao_source,
        }
        items.append(_with_thinking_depth_fields(item, r[7] or ""))

    return {"total": total, "include_total": bool(include_total), "items": items, "limit": lim, "offset": off}


async def bulk_delete_question_library_items(
    *,
    user_id: str,
    question_ids: List[str],
    session: Optional[AsyncSession] = None,
) -> int:
    uid = _require_user_id(user_id)
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0

    own = session is None
    if own:
        async with async_session_maker() as session:
            n = await bulk_delete_question_library_items(user_id=uid, question_ids=ids, session=session)
            await session.commit()
            return n

    await session.execute(
        delete(GaokaoQuestionSource).where(
            GaokaoQuestionSource.user_id == uid,
            GaokaoQuestionSource.question_id.in_(ids),
        )
    )
    stmt = delete(QuestionLibraryItem).where(
        QuestionLibraryItem.user_id == uid, QuestionLibraryItem.question_id.in_(ids)
    )
    result = await session.execute(stmt)
    await session.flush()
    try:
        return int(getattr(result, "rowcount", 0) or 0)
    except (TypeError, ValueError):
        return 0


async def set_hidden(
    *,
    user_id: str,
    question_id: str,
    hidden: bool,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await set_hidden(user_id=uid, question_id=qid, hidden=hidden, session=session)
            await session.commit()
            return ok

    result = await session.execute(
        select(QuestionLibraryItem).where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id == qid,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.hidden = 1 if hidden else 0
    session.add(row)
    await session.flush()
    return True


async def set_starred(
    *,
    user_id: str,
    question_id: str,
    starred: bool,
    session: Optional[AsyncSession] = None,
) -> bool:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await set_starred(user_id=uid, question_id=qid, starred=starred, session=session)
            await session.commit()
            return ok

    result = await session.execute(
        select(QuestionLibraryItem).where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id == qid,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.starred = 1 if starred else 0
    session.add(row)
    await session.flush()
    return True


async def get_question_library_item(
    *,
    user_id: str,
    question_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[dict]:
    uid = _require_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return None

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_question_library_item(user_id=uid, question_id=qid, session=session)

    source_join = and_(
        GaokaoQuestionSource.user_id == QuestionLibraryItem.user_id,
        GaokaoQuestionSource.question_id == QuestionLibraryItem.question_id,
    )
    result = await session.execute(
        select(QuestionLibraryItem, GaokaoQuestionSource)
        .join(GaokaoQuestionSource, source_join, isouter=True)
        .where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id == qid,
        )
    )
    pair = result.one_or_none()

    if not pair:
        return None
    row, source = pair

    gaokao_source = None
    if source is not None:
        gaokao_source = {
            "exam_year": int(source.exam_year),
            "region": source.region or "",
            "paper_name": source.paper_name or "",
            "paper_variant": source.paper_variant or "",
            "question_number": source.question_number or "",
            "source_url": source.source_url or "",
            "source_note": source.source_note or "",
            "verified": bool(source.verified),
        }

    item = {
        "question_id": row.question_id,
        "subject": row.subject or "",
        "origin": row.origin or "",
        "hidden": bool(row.hidden),
        "starred": bool(getattr(row, "starred", 0)),
        "ai_score": row.ai_score,
        "ai_verdict": row.ai_verdict or "",
        "ai_dimensions_json": row.ai_dimensions_json or "",
        "ai_summary": row.ai_summary or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "library_area": "gaokao" if gaokao_source is not None else "general",
        "gaokao_source": gaokao_source,
    }
    return _with_thinking_depth_fields(item, row.ai_dimensions_json or "")


async def list_unscored_question_ids(
    *,
    user_id: str,
    subject: str = "",
    limit: int = 50,
    session: Optional[AsyncSession] = None,
) -> List[str]:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    lim = max(1, min(_as_int(limit, 50), 500))

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_unscored_question_ids(user_id=uid, subject=subj, limit=lim, session=session)

    stmt = select(QuestionLibraryItem.question_id).where(
        QuestionLibraryItem.user_id == uid,
        QuestionLibraryItem.origin == "crawled",
        QuestionLibraryItem.ai_score.is_(None),
    )
    if subj:
        stmt = stmt.where(QuestionLibraryItem.subject == subj)
    stmt = stmt.limit(lim)
    rows = (await session.execute(stmt)).scalars().all()
    return [str(x).strip() for x in rows if str(x or "").strip()]


async def list_thinking_method_stats(
    *,
    user_id: str,
    subject: str = "",
    limit: int = 5000,
    session: Optional[AsyncSession] = None,
) -> List[Dict[str, Any]]:
    uid = _require_user_id(user_id)
    subj = str(subject or "").strip()
    lim = max(1, min(_as_int(limit, 5000), 20000))

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await list_thinking_method_stats(user_id=uid, subject=subj, limit=lim, session=session)

    stmt = (
        select(QuestionLibraryItem.question_id, QuestionLibraryItem.ai_dimensions_json)
        .where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.ai_dimensions_json != "",
        )
        .limit(lim)
    )
    if subj:
        stmt = stmt.where(QuestionLibraryItem.subject == subj)

    rows = (await session.execute(stmt)).all()
    by_family: Dict[str, Dict[str, Any]] = {}
    for qid, dims_json in rows:
        depth = extract_thinking_depth(dims_json or "")
        family = str(depth.get("method_family") or "").strip()
        if not family:
            continue
        key = family.lower()
        row = by_family.setdefault(
            key,
            {
                "method_family": family,
                "count": 0,
                "method_rarity": str(depth.get("method_rarity") or "").strip(),
                "method_signature": str(depth.get("method_signature") or "").strip(),
                "example_question_ids": [],
            },
        )
        row["count"] = int(row.get("count") or 0) + 1
        examples = row.get("example_question_ids") if isinstance(row.get("example_question_ids"), list) else []
        q = str(qid or "").strip()
        if q and q not in examples and len(examples) < 5:
            examples.append(q)
        row["example_question_ids"] = examples

    out = list(by_family.values())
    out.sort(key=lambda x: (-int(x.get("count") or 0), str(x.get("method_family") or "")))
    return out
