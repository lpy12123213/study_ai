# 本地题库（爬取自动入库 + AI 评分优选 + AI 出题）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把“爬取题自动入库 + 本地浏览 + AI 评分自动隐藏低分 + 基于自学资料的 AI 出题（含解析）”落到现有 FastAPI + React 工程中。

**Architecture:** 新增 `question_library` 表承载“题库语义”（来源/隐藏/评分），复用既有 `question_cache` 存题干/解析快照；后端提供 crawl/list/detail/hide/generate/score API；后台 worker 按批次对未评分题做 LLM 评分并自动隐藏低分；AI 出题采用 `Spec Tree Search`，先在 `QuestionSpec` 空间做 beam search，再把高分 spec 落成题干，并经过 solver / ambiguity checker / judge 校验。

**Tech Stack:** FastAPI、SQLAlchemy(Async+SQLite)、Pydantic、React(Vite)+shadcn/ui、Axios、unittest

---

## Global defaults (assumptions)

- 低分隐藏阈值：`70`（`QUESTION_LIBRARY_HIDE_THRESHOLD` 可覆盖）
- 爬取题：只存 `stem`（不存答案解析）
- AI 出题：必须存 `stem + answer + analysis`
- `question_id`（AI）：`ai_<yyyyMMddHHmm>_<uuid8>`，长度 < 50
- 前端页面：`/question-library` 采用全屏 Studio（保留 Header，隐藏 HistorySidebar）
- 长任务：`crawl` / `generate` / `score` 必须支持 `taskId` + SSE 进度流
- 出题默认 preset：`balanced-creative`
- `Spec Tree Search` 默认配置：

```yaml
depth: 4
beam_width: 6
expand_budget: 54
skill_branch_factor: 3
reasoning_branch_factor: 4
trap_branch_factor: 2
surface_branch_factor: 2
difficulty_match_weight: 0.24
novelty_weight: 0.24
ambiguity_penalty: 0.26
template_penalty: 0.16
judge_pass_score: 80
difficulty_tolerance: 0.22
solver_consensus_n: 2
max_repair_rounds: 1
drafts_per_spec: 2
```

## Local verification commands

- Backend unit tests: `python -m unittest discover -s backend/tests -p "test_*.py"`
- Doctor smoke check: `start.bat doctor`
- Backend run: `python -m uvicorn backend.app:app --reload --port 8000`
- Frontend run: `cd frontend && npm run dev`

---

### Task 1: Add `question_library` DB model

**Files:**
- Modify: `backend/database/schema.py` (around `class QuestionCache` at ~L155)
- Modify: `backend/database/models.py`
- Test: `backend/tests/test_question_library_repository.py` (new)

**Step 1: Write the failing test**

Create `backend/tests/test_question_library_repository.py`:

```python
import tempfile
import unittest

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.schema import Base


class TestQuestionLibraryRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_schema_includes_question_library_table(self) -> None:
        async with self.engine.begin() as conn:
            rows = (await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        names = {r[0] for r in rows}
        self.assertIn("question_library", names)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_repository.TestQuestionLibraryRepository.test_schema_includes_question_library_table -v`  
Expected: FAIL (`question_library` table missing)

**Step 3: Write minimal implementation**

In `backend/database/schema.py`, add:

```python
class QuestionLibraryItem(Base):
    __tablename__ = "question_library"

    user_id = Column(String(64), primary_key=True)
    question_id = Column(String(50), primary_key=True)
    subject = Column(String(100), default="", index=True)
    origin = Column(String(20), default="crawled", index=True)  # crawled|ai

    hidden = Column(Integer, default=0, index=True)  # 0/1

    ai_score = Column(Integer)
    ai_verdict = Column(String(20), default="")
    ai_dimensions_json = Column(Text, default="")
    ai_summary = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

In `backend/database/models.py`, export the new model:

```python
from backend.database.schema import QuestionLibraryItem
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_repository.TestQuestionLibraryRepository.test_schema_includes_question_library_table -v`  
Expected: PASS

**Step 5: Commit (optional)**

```bash
git add backend/database/schema.py backend/database/models.py backend/tests/test_question_library_repository.py
git commit -m "feat(database): add question_library table"
```

---

### Task 2: Implement repository CRUD for `question_library`

**Files:**
- Create: `backend/database/repositories/question_library.py`
- Modify: `backend/database/models.py`
- Test: `backend/tests/test_question_library_repository.py`

**Step 1: Write the failing test (CRUD + user scoping)**

Extend `backend/tests/test_question_library_repository.py`:

```python
from unittest.mock import patch

from backend.database.repositories import question_cache as cache_repo
from backend.database.repositories import question_library as lib_repo


class TestQuestionLibraryRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # keep existing engine/session_maker creation...
        self.patches = [
            patch.object(lib_repo, "async_session_maker", self.session_maker),
            patch.object(cache_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        # keep existing dispose/cleanup...

    async def test_upsert_and_list_scoped_by_user(self) -> None:
        await cache_repo.upsert_question_cache(
            [
                {"question_id": "q1", "subject": "高中数学", "stem": "stem 1"},
                {"question_id": "q2", "subject": "高中数学", "stem": "stem 2"},
            ]
        )

        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[
                {"question_id": "q1", "subject": "高中数学", "origin": "crawled"},
                {"question_id": "q2", "subject": "高中数学", "origin": "ai"},
            ],
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-b",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )

        list_a = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="0", limit=10)
        list_b = await lib_repo.list_question_library_items(user_id="user-b", subject="高中数学", hidden="0", limit=10)

        self.assertEqual({it["question_id"] for it in list_a["items"]}, {"q1", "q2"})
        self.assertEqual({it["question_id"] for it in list_b["items"]}, {"q1"})

        q1 = next(it for it in list_a["items"] if it["question_id"] == "q1")
        self.assertEqual(q1.get("stem"), "stem 1")

    async def test_hide_unhide(self) -> None:
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )
        ok_hide = await lib_repo.set_hidden(user_id="user-a", question_id="q1", hidden=True)
        self.assertTrue(ok_hide)

        visible = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="0", limit=10)
        self.assertEqual(len(visible["items"]), 0)

        hidden_list = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="1", limit=10)
        self.assertEqual(len(hidden_list["items"]), 1)

        ok_unhide = await lib_repo.set_hidden(user_id="user-a", question_id="q1", hidden=False)
        self.assertTrue(ok_unhide)

    async def test_partial_update_does_not_wipe_fields(self) -> None:
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "q1", "subject": "高中数学", "origin": "crawled"}],
        )
        await lib_repo.upsert_question_library_items(
            user_id="user-a",
            items=[{"question_id": "q1", "ai_score": 80, "ai_verdict": "好题"}],
        )
        rows = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="all", limit=10)
        self.assertEqual(len(rows["items"]), 1)
        it = rows["items"][0]
        self.assertEqual(it.get("subject"), "高中数学")
        self.assertEqual(it.get("origin"), "crawled")
        self.assertEqual(it.get("ai_score"), 80)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_repository -v`  
Expected: FAIL (`question_library` repo missing)

**Step 3: Write minimal implementation**

Create `backend/database/repositories/question_library.py`:

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from sqlalchemy import desc, func, or_, select

from backend.database.engine import async_session_maker
from backend.database.schema import QuestionCache, QuestionLibraryItem


HiddenFilter = Literal["0", "1", "all"]


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "").strip()[:64] or "1"


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


async def upsert_question_library_items(*, user_id: str, items: List[dict]) -> int:
    uid = _normalize_user_id(user_id)
    entries = [x for x in (items or []) if isinstance(x, dict)]
    if not entries:
        return 0

    async with async_session_maker() as session:
        n = 0
        for it in entries:
            qid = str(it.get("question_id") or "").strip()
            if not qid:
                continue
            result = await session.execute(
                select(QuestionLibraryItem).where(QuestionLibraryItem.user_id == uid, QuestionLibraryItem.question_id == qid)
            )
            row = result.scalar_one_or_none() or QuestionLibraryItem(user_id=uid, question_id=qid)

            subj = str(it.get("subject") or "").strip()
            if subj:
                row.subject = subj
            origin = str(it.get("origin") or "").strip()
            if origin:
                row.origin = origin
            if "hidden" in it:
                row.hidden = 1 if bool(it.get("hidden")) else 0

            if "ai_score" in it:
                try:
                    row.ai_score = int(it.get("ai_score")) if it.get("ai_score") is not None else None
                except Exception:
                    row.ai_score = None
            if "ai_verdict" in it:
                row.ai_verdict = str(it.get("ai_verdict") or "").strip()
            if "ai_dimensions_json" in it:
                row.ai_dimensions_json = str(it.get("ai_dimensions_json") or "").strip()
            if "ai_summary" in it:
                row.ai_summary = str(it.get("ai_summary") or "").strip()

            session.add(row)
            n += 1
        await session.commit()
        return n


async def list_question_library_items(
    *,
    user_id: str,
    subject: str = "",
    origin: str = "",
    hidden: HiddenFilter = "0",
    q: str = "",
    min_score: Optional[int] = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    uid = _normalize_user_id(user_id)
    subj = str(subject or "").strip()
    origin_v = str(origin or "").strip()
    qv = str(q or "").strip()
    lim = max(1, min(_as_int(limit, 50), 200))
    off = max(0, _as_int(offset, 0))

    async with async_session_maker() as session:
        stmt = (
            select(
                QuestionLibraryItem.question_id,
                QuestionLibraryItem.subject,
                QuestionLibraryItem.origin,
                QuestionLibraryItem.hidden,
                QuestionLibraryItem.ai_score,
                QuestionLibraryItem.ai_verdict,
                QuestionLibraryItem.ai_summary,
                QuestionLibraryItem.updated_at,
                QuestionCache.stem,
            )
            .select_from(QuestionLibraryItem)
            .join(QuestionCache, QuestionCache.question_id == QuestionLibraryItem.question_id, isouter=True)
            .where(QuestionLibraryItem.user_id == uid)
        )

        if subj:
            stmt = stmt.where(QuestionLibraryItem.subject == subj)
        if origin_v:
            stmt = stmt.where(QuestionLibraryItem.origin == origin_v)
        if hidden in {"0", "1"}:
            stmt = stmt.where(QuestionLibraryItem.hidden == (1 if hidden == "1" else 0))
        if min_score is not None:
            stmt = stmt.where(QuestionLibraryItem.ai_score >= int(min_score))
        if qv:
            like = f"%{qv}%"
            stmt = stmt.where(or_(QuestionCache.stem.like(like), QuestionLibraryItem.question_id.like(like)))

        sort_key = sort.strip().lower()
        order_key = order.strip().lower()
        col = QuestionLibraryItem.updated_at if sort_key != "ai_score" else QuestionLibraryItem.ai_score
        stmt = stmt.order_by(desc(col) if order_key != "asc" else col.asc())

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await session.execute(total_stmt)).scalar() or 0)

        rows = (await session.execute(stmt.limit(lim).offset(off))).all()

    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "question_id": r[0],
                "subject": r[1] or "",
                "origin": r[2] or "",
                "hidden": bool(r[3]),
                "ai_score": r[4],
                "ai_verdict": r[5] or "",
                "ai_summary": r[6] or "",
                "updated_at": r[7].isoformat() if r[7] else "",
                "stem": (r[8] or ""),
            }
        )

    return {"total": total, "items": items, "limit": lim, "offset": off}


async def set_hidden(*, user_id: str, question_id: str, hidden: bool) -> bool:
    uid = _normalize_user_id(user_id)
    qid = str(question_id or "").strip()
    if not qid:
        return False

    async with async_session_maker() as session:
        result = await session.execute(
            select(QuestionLibraryItem).where(QuestionLibraryItem.user_id == uid, QuestionLibraryItem.question_id == qid)
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        row.hidden = 1 if hidden else 0
        session.add(row)
        await session.commit()
        return True
```

Update `backend/database/models.py` to re-export:

```python
from backend.database.repositories.question_library import (
    list_question_library_items,
    set_hidden,
    upsert_question_library_items,
)
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_repository -v`  
Expected: PASS

**Step 5: Commit (optional)**

```bash
git add backend/database/repositories/question_library.py backend/database/models.py backend/tests/test_question_library_repository.py
git commit -m "feat(database): add question library repository"
```

---

### Task 3: Add Question Library API router (list/hide)

**Files:**
- Create: `backend/api/question_library.py`
- Create: `backend/api/question_library_schemas.py`
- Modify: `backend/api/router.py` (around includes at ~L23-L38)
- Test: `backend/tests/test_question_library_api.py` (new)

**Step 1: Write the failing test (router mounted)**

Create `backend/tests/test_question_library_api.py`:

```python
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app


class TestQuestionLibraryApi(unittest.TestCase):
    def test_router_is_mounted(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/question-library/items")
        # Auth will block; we only assert that it's not a 404.
        self.assertNotEqual(resp.status_code, 404)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_api -v`  
Expected: FAIL (404)

**Step 3: Write minimal implementation**

Create `backend/api/question_library_schemas.py`:

```python
from __future__ import annotations

from typing import List, Optional, Literal

from pydantic import BaseModel, Field


HiddenFilter = Literal["0", "1", "all"]


class QuestionLibraryListResponseItem(BaseModel):
    question_id: str = ""
    subject: str = ""
    origin: str = ""
    hidden: bool = False
    ai_score: Optional[int] = None
    ai_verdict: str = ""
    ai_summary: str = ""
    updated_at: str = ""
    stem: str = ""


class QuestionLibraryListResponse(BaseModel):
    total: int = 0
    limit: int = 50
    offset: int = 0
    items: List[QuestionLibraryListResponseItem] = Field(default_factory=list)
```

Create `backend/api/question_library.py`:

```python
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth import require_auth
from backend.database.models import list_question_library_items, set_hidden

router = APIRouter(prefix="/question-library", tags=["question-library"], dependencies=[Depends(require_auth)])


@router.get("/items", response_model=dict)
async def list_items(
    subject: str = Query(""),
    origin: str = Query(""),
    hidden: str = Query("0"),
    q: str = Query(""),
    min_score: Optional[int] = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    limit: int = Query(50),
    offset: int = Query(0),
    user: dict = Depends(require_auth),
) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    return await list_question_library_items(
        user_id=user_id,
        subject=subject,
        origin=origin,
        hidden=hidden if hidden in {"0", "1", "all"} else "0",
        q=q,
        min_score=min_score,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.post("/items/{question_id}/hide", response_model=dict)
async def hide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}


@router.post("/items/{question_id}/unhide", response_model=dict)
async def unhide_item(question_id: str, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ok = await set_hidden(user_id=user_id, question_id=question_id, hidden=False)
    if not ok:
        raise HTTPException(status_code=404, detail="not_found")
    return {"success": True}
```

Modify `backend/api/router.py`:

```python
from backend.api.question_library import router as question_library_router
# ...
api_router.include_router(question_library_router)
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_api -v`  
Expected: PASS (401/403 but not 404)

**Step 5: Commit (optional)**

```bash
git add backend/api/question_library.py backend/api/question_library_schemas.py backend/api/router.py backend/tests/test_question_library_api.py
git commit -m "feat(api): add question library list/hide routes"
```

---

### Task 4: Add crawl task stream + incremental save endpoint

**Files:**
- Create: `backend/question_library/task_manager.py`
- Modify: `backend/api/question_library.py`
- Modify: `backend/api/question_library_schemas.py` (add request/response)
- Test: `backend/tests/test_question_library_crawl.py` (new, minimal)

**Step 1: Write failing test**

Create `backend/tests/test_question_library_crawl.py`:

```python
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app


class TestQuestionLibraryCrawl(unittest.TestCase):
    def test_crawl_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.post("/api/question-library/crawl", json={"subject": "高中数学", "query": "函数"})
        self.assertNotEqual(resp.status_code, 404)

    def test_task_stream_endpoint_exists(self) -> None:
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/question-library/tasks/test-task/stream")
        self.assertNotEqual(resp.status_code, 404)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_crawl -v`  
Expected: FAIL (404)

**Step 3: Implement task manager + endpoint**

Follow the streaming patterns already used in:

- `backend/api/study_materials.py`
- `backend/api/tasks.py`
- `backend/api/papers.py`

Add to `backend/api/question_library_schemas.py`:

```python
class QuestionLibraryCrawlRequest(BaseModel):
    subject: str = ""
    edu_level: str = ""
    query: str = ""
    difficulty: str = ""
    question_type: str = ""
    limit: int = 30
    max_pages: int = 2
    min_quality_score: int = 0
    task_id: str = ""


class QuestionLibraryCrawlResponse(BaseModel):
    success: bool = True
    inserted: int = 0
    subject: str = ""
    count: int = 0
    question_ids: List[str] = Field(default_factory=list)
    error: str = ""
```

Create `backend/question_library/task_manager.py` to store:

- `task_id`
- `user_id`
- `kind = crawl | generate | score`
- `status`
- appended SSE events

In `backend/api/question_library.py`, add:

- `POST /crawl` — starts the task and returns SSE stream
- `GET /tasks/{task_id}/stream` — replay/resume task events
- `GET /tasks/{task_id}` — task status summary

`POST /crawl` should:

- accept optional `taskId`
- emit `step` / `progress` / `item_saved` / `done` / `error`
- crawl page-by-page and save incrementally

For each crawled question:

- `upsert_question_cache` with `stem` only
- `upsert_question_library_items(origin=crawled)`
- emit `item_saved` so the frontend can update the list immediately

Important: keep `answer/analysis` empty for crawled items.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_crawl -v`  
Expected: PASS (auth error but not 404)

**Step 5: Commit (optional)**

```bash
git add backend/question_library/task_manager.py backend/api/question_library.py backend/api/question_library_schemas.py backend/tests/test_question_library_crawl.py
git commit -m "feat(api): add question library crawl task stream"
```

---

### Task 5: Add scoring module (persist score + auto-hide)

**Files:**
- Create: `backend/question_library/scoring.py`
- Test: `backend/tests/test_question_library_scoring.py` (new)

**Step 1: Write failing test (score → hidden flips)**

Create `backend/tests/test_question_library_scoring.py`:

```python
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.database.schema import Base
from backend.database.repositories import question_cache as cache_repo
from backend.database.repositories import question_library as lib_repo


class TestQuestionLibraryScoring(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        self.session_maker = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.patches = [
            patch.object(cache_repo, "async_session_maker", self.session_maker),
            patch.object(lib_repo, "async_session_maker", self.session_maker),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_score_updates_and_hides(self) -> None:
        await cache_repo.upsert_question_cache([{"question_id": "q1", "subject": "高中数学", "stem": "stem 1"}])
        await lib_repo.upsert_question_library_items(user_id="u1", items=[{"question_id": "q1", "subject": "高中数学"}])

        from backend.question_library.scoring import apply_score_and_hide

        await apply_score_and_hide(user_id="u1", question_id="q1", overall_score=60, verdict="差题", dimensions=[], summary="bad", threshold=70)

        hidden_list = await lib_repo.list_question_library_items(user_id="u1", subject="高中数学", hidden="1", limit=10)
        self.assertEqual(len(hidden_list["items"]), 1)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_scoring -v`  
Expected: FAIL (module missing)

**Step 3: Implement helper**

Create `backend/question_library/scoring.py`:

```python
from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.database.repositories.question_library import set_hidden, upsert_question_library_items


def _to_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value or [], ensure_ascii=False)
    except Exception:
        return "[]"


async def apply_score_and_hide(
    *,
    user_id: str,
    question_id: str,
    overall_score: int,
    verdict: str,
    dimensions: List[Dict[str, Any]],
    summary: str,
    threshold: int,
) -> None:
    await upsert_question_library_items(
        user_id=user_id,
        items=[
            {
                "question_id": question_id,
                "ai_score": int(overall_score),
                "ai_verdict": str(verdict or "").strip(),
                "ai_dimensions_json": _to_json_str(dimensions),
                "ai_summary": str(summary or "").strip(),
            }
        ],
    )
    if int(overall_score) < int(threshold):
        await set_hidden(user_id=user_id, question_id=question_id, hidden=True)
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_scoring -v`  
Expected: PASS

**Step 5: Commit (optional)**

```bash
git add backend/question_library/scoring.py backend/tests/test_question_library_scoring.py
git commit -m "feat(question-library): add scoring persistence helper"
```

---

### Task 6: Background scoring worker (skeleton)

**Files:**
- Create: `backend/question_library/worker.py`
- Modify: `backend/app.py` (lifespan around ~L54)

**Step 1: Implement worker skeleton**

Create `backend/question_library/worker.py`:

```python
from __future__ import annotations

import asyncio
import os

from backend.core.llm_client import is_llm_configured


def _env_truthy(name: str, *, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


async def run_question_library_scoring_worker(*, stop: asyncio.Event) -> None:
    if not _env_truthy("QUESTION_LIBRARY_AUTO_SCORE", default=False):
        return
    if not is_llm_configured():
        return

    interval_s = float(os.getenv("QUESTION_LIBRARY_SCORE_INTERVAL_S") or "20")

    while not stop.is_set():
        # TODO: pick unscored items, call LLM scoring, apply_score_and_hide
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(1.0, interval_s))
        except asyncio.TimeoutError:
            continue
```

**Step 2: Wire to `backend/app.py`**

In `backend/app.py`, update `lifespan` to start/stop the worker task (cancel-safe).

**Step 3: Smoke check**

Run: `python -m compileall backend -q`  
Expected: no output

**Step 4: Commit (optional)**

```bash
git add backend/question_library/worker.py backend/app.py
git commit -m "feat(question-library): add background worker skeleton"
```

---

### Task 7: AI question generation pipeline (`Spec Tree Search`)

**Files:**
- Create: `backend/question_library/generation.py`
- Modify: `backend/api/question_library.py` (add `/generate`)
- Test: `backend/tests/test_question_library_generate.py` (new)

**Step 1: Write failing test**

Create `backend/tests/test_question_library_generate.py`:

```python
import unittest


class TestQuestionLibraryGenerate(unittest.TestCase):
    def test_build_ai_question_id(self) -> None:
        from backend.question_library.generation import build_ai_question_id

        qid = build_ai_question_id(now_ts=0, suffix="a1b2c3d4")
        self.assertTrue(qid.startswith("ai_"))
        self.assertLessEqual(len(qid), 50)
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_generate -v`  
Expected: FAIL (module missing)

**Step 3: Implement minimal helper**

Create `backend/question_library/generation.py`:

```python
from __future__ import annotations

import time


def build_ai_question_id(*, now_ts: float | None = None, suffix: str = "") -> str:
    ts = time.localtime(now_ts if now_ts is not None else time.time())
    stamp = time.strftime("%Y%m%d%H%M", ts)
    suf = (suffix or "").strip() or "00000000"
    suf = suf[:8]
    return f"ai_{stamp}_{suf}"[:50]
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_generate -v`  
Expected: PASS

**Step 5: Implement pipeline skeleton (LLM mocked in tests)**

Add functions (all JSON-only IO):

- `build_source_pack(study_markdown, subject, topic) -> dict`
- `seed_root_specs(source_pack, count, difficulty, question_type) -> list[dict]`
- `expand_skill_layer(specs, config) -> list[dict]`
- `expand_reasoning_layer(specs, config) -> list[dict]`
- `expand_trap_layer(specs, config) -> list[dict]`
- `expand_surface_layer(specs, config) -> list[dict]`
- `score_spec(spec, source_pack, config) -> dict`
- `beam_select(specs, config) -> list[dict]`
- `realize_drafts(spec, n=2) -> list[dict]`
- `solve_draft(stem, options) -> dict`
- `check_ambiguity(draft) -> dict`
- `judge_draft(draft, spec) -> dict`
- `refine_draft(draft, judge) -> dict`
- `select_final(candidates, count) -> list[dict]`

LLM calling conventions:

- use `backend.core.llm_client.chat_completion_text`
- `response_format={"type":"json_object"}`
- `reasoning={"effort":"high","exclude": True}` where supported

Add a config object in `backend/question_library/generation.py`:

```python
DEFAULT_SEARCH_CONFIG = {
    "preset": "balanced-creative",
    "depth": 4,
    "beam_width": 6,
    "expand_budget": 54,
    "skill_branch_factor": 3,
    "reasoning_branch_factor": 4,
    "trap_branch_factor": 2,
    "surface_branch_factor": 2,
    "difficulty_match_weight": 0.24,
    "novelty_weight": 0.24,
    "ambiguity_penalty": 0.26,
    "template_penalty": 0.16,
    "judge_pass_score": 80,
    "difficulty_tolerance": 0.22,
    "solver_consensus_n": 2,
    "max_repair_rounds": 1,
    "drafts_per_spec": 2,
}
```

The first implementation should keep only one public preset (`balanced-creative`) and should not expose all knobs to the frontend yet.

**Step 6: Add `/api/question-library/generate`**

Endpoint responsibilities:

1. 接受或生成 `taskId`
2. 拉取最新 `StudyArchive`（`backend.database.repositories.study_archives.get_latest_study_archive`）
3. build `SourcePack`
4. run 4-layer spec search (`skill -> reasoning -> trap -> surface`)
5. only realize the top specs into drafts
6. run `solver + ambiguity checker + judge`
7. generate `count` 道题（限制 `count<=10`）
8. 写入 `question_cache`（AI 题写 `answer/analysis`）
9. 写入 `question_library(origin=ai)`
10. 逐阶段发 SSE：
   - `progress(stage="SourcePack")`
   - `progress(stage="Spec Search")`
   - `progress(stage="Draft Realization")`
   - `progress(stage="Solver")`
   - `progress(stage="Judge")`
   - `item_saved`
   - `done`

If the route stays stream-first, it should reuse the replay path added in Task 4:

- `GET /api/question-library/tasks/{task_id}/stream`

**Step 7: Commit (optional)**

```bash
git add backend/question_library/generation.py backend/api/question_library.py backend/tests/test_question_library_generate.py
git commit -m "feat(question-library): add AI generation skeleton"
```

---

### Task 8: Frontend API client for Question Library + task streams

**Files:**
- Create: `frontend/src/api/questionLibrary.ts`

**Step 1: Implement API module**

Create `frontend/src/api/questionLibrary.ts` (Axios + typed adapters), and include:

- `listQuestionLibrary(...)`
- `getQuestionLibraryItem(questionId)`
- `hideQuestion(questionId)`
- `unhideQuestion(questionId)`
- `crawlQuestions(payload)`
- `generateQuestions(payload)`
- `scoreQuestionLibraryBatch(payload)`
- `streamQuestionLibraryTask(taskId, afterSeq, handlers)`
- `normalizeQuestionLibraryTaskEvent(...)`

Reuse:

- `frontend/src/api/client.ts`
- `frontend/src/lib/sse.ts`

**Step 2: Build check**

Run: `cd frontend && npm run build`  
Expected: PASS

---

### Task 9: Frontend full-screen Question Library Studio page + route

**Files:**
- Create: `frontend/src/pages/QuestionLibraryPage.tsx`
- Create: `frontend/src/pages/questionLibrary/QuestionLibraryStudio.tsx`
- Create: `frontend/src/pages/questionLibrary/QuestionFilterPane.tsx`
- Create: `frontend/src/pages/questionLibrary/QuestionListPane.tsx`
- Create: `frontend/src/pages/questionLibrary/QuestionDetailPane.tsx`
- Modify: `frontend/src/App.tsx` (add lazy import + route; `question-evaluate` is at ~L44)
- Modify: `frontend/src/components/layout/Header.tsx` (navItems at ~L36)
- Modify: `frontend/src/components/layout/ManusLayout.tsx`

**Step 1: Add route**

In `frontend/src/App.tsx`:

- add `const QuestionLibraryPage = lazy(() => import('@/pages/QuestionLibraryPage'))`
- add `<Route path="question-library" element={<QuestionLibraryPage />} />`

**Step 2: Add nav item**

In `frontend/src/components/layout/Header.tsx`, add:

- `{ path: '/question-library', label: '本地题库', icon: BookOpen }`

**Step 3: Make the route render as Studio**

In `frontend/src/components/layout/ManusLayout.tsx`:

- treat `/question-library` as a Studio page
- keep Header
- hide `HistorySidebar`
- remove max-width constraint
- let the page own its internal scroll

**Step 4: Implement page shell**

Create `frontend/src/pages/QuestionLibraryPage.tsx` and the `questionLibrary/*` components with:

- left filter pane
- center question feed
- right detail pane
- empty / loading / error states

Use shadcn components following `frontend/src/pages/QuestionEvaluatePage.tsx` patterns.

**Step 5: Build check**

Run: `cd frontend && npm run build`  
Expected: PASS

**Step 6: Commit (optional)**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Header.tsx frontend/src/components/layout/ManusLayout.tsx frontend/src/pages/QuestionLibraryPage.tsx frontend/src/pages/questionLibrary frontend/src/api/questionLibrary.ts
git commit -m "feat(frontend): add question library studio shell"
```

---

### Task 10: LLM scoring (rubric) + manual batch endpoint

**Files:**
- Modify: `backend/question_library/scoring.py`
- Modify: `backend/api/question_library.py`
- Test: `backend/tests/test_question_library_score_llm.py` (new, mock LLM)

**Step 1: Write failing test**

Create `backend/tests/test_question_library_score_llm.py`:

```python
import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.question_library.scoring import score_stem_with_llm


class TestQuestionLibraryScoreLlm(unittest.IsolatedAsyncioTestCase):
    async def test_score_parses_json(self) -> None:
        fake = json.dumps(
            {
                "verdict": "好题",
                "overall_score": 85,
                "dimensions": [{"name": "思维含量", "score": 9, "comment": "ok"}],
                "highlights": ["清晰"],
                "issues": [],
                "summary": "good",
            },
            ensure_ascii=False,
        )
        with patch("backend.question_library.scoring.chat_completion_text", new=AsyncMock(return_value=fake)):
            out = await score_stem_with_llm(subject="高中数学", stem="题干", model="dummy")
        self.assertEqual(out["overall_score"], 85)
        self.assertEqual(out["verdict"], "好题")
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_score_llm -v`  
Expected: FAIL (function missing)

**Step 3: Implement `score_stem_with_llm`**

In `backend/question_library/scoring.py`, add:

```python
import re
from backend.core.llm_client import chat_completion_text


def _extract_json_obj(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\\s*", "", raw).lstrip()
        raw = re.sub(r"\\s*```$", "", raw).rstrip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def score_stem_with_llm(*, subject: str, stem: str, model: str, requirements: str = "") -> dict:
    payload = {
        "subject": subject,
        "requirements": (requirements or "").strip(),
        "question": {"stem": (stem or "").strip()[:1500]},
        "output_schema": {
            "verdict": "string (好题|普通题|差题)",
            "overall_score": "int 0-100",
            "dimensions": [{"name": "string", "score": "int 1-10", "comment": "string"}],
            "highlights": "string[]",
            "issues": "string[]",
            "summary": "string",
        },
    }
    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": "你是资深教研员，擅长鉴别试题质量。请严格输出 JSON object。"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=model,
        temperature=0.2,
        max_tokens=1800,
        response_format={"type": "json_object"},
        reasoning={"effort": "high", "exclude": True},
        stream=False,
        raise_on_fail=False,
        retries=2,
        req_id_prefix="ql_score",
    )
    obj = _extract_json_obj(text)
    return {
        "verdict": str(obj.get("verdict") or "").strip(),
        "overall_score": int(obj.get("overall_score") or 0),
        "dimensions": list(obj.get("dimensions") or []),
        "highlights": list(obj.get("highlights") or []),
        "issues": list(obj.get("issues") or []),
        "summary": str(obj.get("summary") or "").strip(),
    }
```

**Step 4: Add manual endpoint**

In `backend/api/question_library.py`, add `POST /score`:

- select a batch of unscored items for the current user
- for each item: fetch `stem` from `question_cache`, call `score_stem_with_llm`, then `apply_score_and_hide`
- when called from the Studio UI, emit progress events so the frontend can show `已评分 / 总数 / 已隐藏`

**Step 5: Run tests**

Run: `python -m unittest backend.tests.test_question_library_score_llm -v`  
Expected: PASS

---

### Task 11: Worker + repo query for unscored batch

**Files:**
- Modify: `backend/database/repositories/question_library.py`
- Modify: `backend/question_library/worker.py`
- Test: `backend/tests/test_question_library_worker_once.py` (new, mock LLM)

**Step 1: Add repo helper**

In `backend/database/repositories/question_library.py`, add:

```python
async def list_unscored_question_ids(*, user_id: str, subject: str = "", limit: int = 50) -> List[str]:
    uid = _normalize_user_id(user_id)
    subj = str(subject or "").strip()
    lim = max(1, min(_as_int(limit, 50), 500))

    async with async_session_maker() as session:
        stmt = select(QuestionLibraryItem.question_id).where(QuestionLibraryItem.user_id == uid, QuestionLibraryItem.ai_score.is_(None))
        if subj:
            stmt = stmt.where(QuestionLibraryItem.subject == subj)
        stmt = stmt.limit(lim)
        rows = (await session.execute(stmt)).scalars().all()
        return [str(x).strip() for x in rows if str(x or "").strip()]
```

**Step 2: Implement `score_batch_once`**

In `backend/question_library/worker.py`, add a pure function:

```python
from backend.database.repositories.question_cache import get_question_cache
from backend.database.repositories.question_library import list_unscored_question_ids
from backend.question_library.scoring import apply_score_and_hide, score_stem_with_llm


async def score_batch_once(*, user_id: str, subject: str, model: str, threshold: int, limit: int) -> int:
    qids = await list_unscored_question_ids(user_id=user_id, subject=subject, limit=limit)
    if not qids:
        return 0
    cache = await get_question_cache(question_ids=qids)
    scored = 0
    for qid in qids:
        stem = str((cache.get(qid) or {}).get("stem") or "").strip()
        if not stem:
            continue
        res = await score_stem_with_llm(subject=subject, stem=stem, model=model)
        await apply_score_and_hide(
            user_id=user_id,
            question_id=qid,
            overall_score=int(res.get("overall_score") or 0),
            verdict=str(res.get("verdict") or ""),
            dimensions=list(res.get("dimensions") or []),
            summary=str(res.get("summary") or ""),
            threshold=threshold,
        )
        scored += 1
    return scored
```

Then worker loop calls `score_batch_once(...)` each tick.

---

### Task 12: Add detail endpoint + implement detail pane

**Files:**
- Modify: `backend/api/question_library.py`
- Create: `frontend/src/pages/questionLibrary/QuestionDetailPane.tsx`
- Create: `frontend/src/pages/questionLibrary/hooks/useQuestionLibrary.ts`
- Modify: `frontend/src/pages/QuestionLibraryPage.tsx`

**Step 1: Backend detail endpoint**

Add `GET /api/question-library/items/{question_id}`:

- read `question_library` row (ensure user scoping)
- read `question_cache` row
- return combined payload

**Step 2: Frontend detail panel**

- Clicking list item selects it and fetches detail
- Render:
  - `stem` (full)
  - If `origin===ai`: show `answer` + `analysis`
  - Score breakdown (dimensions JSON)
  - hide / unhide action
- Keep list selection and detail fetching logic in `useQuestionLibrary`

---

### Task 13: Wire “爬取入库 / AI 出题” actions + realtime Run Panel

**Files:**
- Modify: `frontend/src/pages/QuestionLibraryPage.tsx`
- Modify: `frontend/src/api/questionLibrary.ts`
- Create: `frontend/src/pages/questionLibrary/RunPanel.tsx`
- Create: `frontend/src/pages/questionLibrary/CrawlDialog.tsx`
- Create: `frontend/src/pages/questionLibrary/GenerateDialog.tsx`
- Create: `frontend/src/pages/questionLibrary/hooks/useQuestionLibraryTasks.ts`
- Modify: `frontend/src/stores/useTaskStore.ts` (only if current model needs a new `taskType`)

**Step 1: Add buttons + dialogs**

- Add “爬取入库” button → opens dialog (subject/query/difficulty/limit/maxPages)
- Add “AI 出题” button → opens dialog (subject/topic/difficulty/type/count, toggle useStudyArchive)
- Add optional “手动评分” action for the visible subject

**Step 2: Connect tasks to SSE**

In `useQuestionLibraryTasks.ts`:

- follow the same pattern as `frontend/src/hooks/useBlueprint.ts`
- create/start task with `taskId`
- subscribe to task stream with `useSSE` / `fetchSSERequest`
- normalize events through `normalizeSseEnvelope`
- write steps/progress into `useTaskStore`
- on `item_saved`, patch the in-memory list immediately
- on `done`, invalidate/refetch the library list

**Step 3: Implement Run Panel**

Create `RunPanel.tsx`:

- render at the bottom of the Studio
- show current running task first
- display stage label + percent + step timeline
- support `crawl`, `generate`, `score`
- auto-expand while a task is running

Reuse ideas from:

- `frontend/src/components/layout/TaskPanel.tsx`
- `frontend/src/stores/useTaskStore.ts`

**Step 4: Build check**

Run: `cd frontend && npm run build`  
Expected: PASS

---

## Execution handoff

Plan complete. Two execution options:

1. **Subagent-Driven (this session)** — dispatch tasks one-by-one and review between tasks.
2. **Parallel Session (separate)** — open a new session using `superpowers:executing-plans` and run tasks with checkpoints.

Which approach do you want?
