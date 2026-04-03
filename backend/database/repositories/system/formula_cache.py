from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import async_session_maker
from backend.database.schema import FormulaLatexCache


def _normalize_hash(value: str) -> str:
    return str(value or "").strip().lower()[:32]


async def get_formula_latex(
    *,
    formula_hash: str,
    session: Optional[AsyncSession] = None,
) -> str:
    key = _normalize_hash(formula_hash)
    if not key:
        return ""

    own = session is None
    if own:
        async with async_session_maker() as session:
            return await get_formula_latex(formula_hash=key, session=session)

    res = await session.execute(select(FormulaLatexCache).where(FormulaLatexCache.formula_hash == key))
    row = res.scalar_one_or_none()
    return str(row.latex or "").strip() if row else ""


async def upsert_formula_latex(
    *,
    formula_hash: str,
    latex: str,
    session: Optional[AsyncSession] = None,
) -> bool:
    key = _normalize_hash(formula_hash)
    value = str(latex or "").strip()
    if not key or not value:
        return False

    own = session is None
    if own:
        async with async_session_maker() as session:
            ok = await upsert_formula_latex(formula_hash=key, latex=value, session=session)
            await session.commit()
            return ok

    res = await session.execute(select(FormulaLatexCache).where(FormulaLatexCache.formula_hash == key))
    existing = res.scalar_one_or_none()
    if existing:
        existing.latex = value
        session.add(existing)
        await session.flush()
        return True

    row = FormulaLatexCache(formula_hash=key, latex=value)
    session.add(row)
    await session.flush()
    return True

