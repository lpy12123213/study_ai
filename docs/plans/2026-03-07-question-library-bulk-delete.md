# 本地题库批量删除（按用户维度）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在“本地题库 / AI 出题”列表中支持批量选择并删除题库条目（按用户维度删除 `question_library` 记录）。

**Architecture:** 后端新增 bulk-delete API，repository 提供按 `user_id` 的批量删除函数；前端增加批量模式与选中状态，调用 bulk-delete 后刷新列表与详情。

**Tech Stack:** FastAPI、SQLAlchemy(Async+SQLite)、unittest、React(Vite)+TypeScript、shadcn/ui、Axios

---

### Task 1: Repository 批量删除

**Files:**
- Modify: `backend/database/repositories/question_library.py`
- Test: `backend/tests/test_question_library_repository.py`

**Step 1: Write the failing test**

在 `backend/tests/test_question_library_repository.py` 追加测试：

```python
async def test_bulk_delete_scoped_by_user(self) -> None:
    await cache_repo.upsert_question_cache(
        [
            {"question_id": "q1", "subject": "高中数学", "stem": "stem 1"},
            {"question_id": "q2", "subject": "高中数学", "stem": "stem 2"},
        ]
    )
    await lib_repo.upsert_question_library_items(
        user_id="user-a",
        items=[{"question_id": "q1", "subject": "高中数学"}, {"question_id": "q2", "subject": "高中数学"}],
    )
    await lib_repo.upsert_question_library_items(
        user_id="user-b",
        items=[{"question_id": "q1", "subject": "高中数学"}],
    )

    deleted = await lib_repo.bulk_delete_question_library_items(user_id="user-a", question_ids=["q1", "q2"])
    self.assertEqual(deleted, 2)

    a = await lib_repo.list_question_library_items(user_id="user-a", subject="高中数学", hidden="all", limit=10)
    b = await lib_repo.list_question_library_items(user_id="user-b", subject="高中数学", hidden="all", limit=10)
    self.assertEqual(len(a["items"]), 0)
    self.assertEqual({it["question_id"] for it in b["items"]}, {"q1"})
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_repository.TestQuestionLibraryRepository.test_bulk_delete_scoped_by_user -v`  
Expected: FAIL（`bulk_delete_question_library_items` 未定义）

**Step 3: Write minimal implementation**

在 `backend/database/repositories/question_library.py` 新增：

```python
from sqlalchemy import delete

async def bulk_delete_question_library_items(*, user_id: str, question_ids: List[str]) -> int:
    uid = _normalize_user_id(user_id)
    ids = [str(x or "").strip() for x in (question_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0
    async with async_session_maker() as session:
        stmt = delete(QuestionLibraryItem).where(
            QuestionLibraryItem.user_id == uid,
            QuestionLibraryItem.question_id.in_(ids),
        )
        result = await session.execute(stmt)
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_repository.TestQuestionLibraryRepository.test_bulk_delete_scoped_by_user -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add backend/database/repositories/question_library.py backend/tests/test_question_library_repository.py
git commit -m "feat(question-library): add bulk delete repository"
```

---

### Task 2: API 增加 bulk-delete 路由

**Files:**
- Modify: `backend/api/question_library_schemas.py`
- Modify: `backend/api/question_library.py`
- Test: `backend/tests/test_question_library_api.py`

**Step 1: Write the failing test**

在 `backend/tests/test_question_library_api.py` 添加：

```python
def test_bulk_delete_endpoint_exists(self) -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.post("/api/question-library/items/bulk-delete", json={"question_ids": ["q1"]})
    self.assertNotIn(resp.status_code, {404, 405})
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_api.TestQuestionLibraryApi.test_bulk_delete_endpoint_exists -v`  
Expected: FAIL（404 或 405）

**Step 3: Write minimal implementation**

1) 在 `backend/api/question_library_schemas.py` 增加：

```python
class QuestionLibraryBulkDeleteRequest(BaseModel):
    question_ids: List[str] = Field(default_factory=list)
```

2) 在 `backend/api/question_library.py` 增加路由：

```python
@router.post("/items/bulk-delete", response_model=dict)
async def bulk_delete_items(request: QuestionLibraryBulkDeleteRequest, user: dict = Depends(require_auth)) -> dict:
    user_id = str((user or {}).get("user_id") or "").strip() or "1"
    ids = [str(x or "").strip() for x in (request.question_ids or []) if str(x or "").strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(status_code=400, detail="question_ids_required")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="too_many_ids")
    deleted = await bulk_delete_question_library_items(user_id=user_id, question_ids=ids)
    return {"success": True, "deleted": deleted}
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_api.TestQuestionLibraryApi.test_bulk_delete_endpoint_exists -v`  
Expected: PASS（通常为 401，且非 404/405）

**Step 5: Commit**

```bash
git add backend/api/question_library_schemas.py backend/api/question_library.py backend/tests/test_question_library_api.py
git commit -m "feat(question-library): add bulk delete API"
```

---

### Task 3: 前端 API 增加 bulk-delete 调用

**Files:**
- Modify: `frontend/src/api/questionLibrary.ts`

**Step 1: Add API function**

```ts
export async function bulkDeleteQuestionLibraryItems(questionIds: string[]): Promise<{ success: boolean; deleted: number }> {
  const ids = Array.from(new Set((questionIds || []).map((x) => String(x || '').trim()).filter(Boolean)))
  if (ids.length === 0) throw new Error('question_ids_required')
  const resp = await apiClient.post('/question-library/items/bulk-delete', { question_ids: ids })
  return resp.data as any
}
```

**Step 2: Build**

Run: `cd frontend && npm run build`  
Expected: PASS

**Step 3: Commit**

```bash
git add frontend/src/api/questionLibrary.ts
git commit -m "feat(frontend): add question library bulk delete api"
```

---

### Task 4: 本地题库页面增加批量模式 UI

**Files:**
- Modify: `frontend/src/pages/questionLibrary/QuestionLibraryCard.tsx`
- Modify: `frontend/src/pages/questionLibrary/QuestionLibraryBrowser.tsx`

**Step 1: Card 支持选中态**

为 `QuestionLibraryCard` 增加可选 `bulk` props（enabled/selected/onToggle），选中时高亮卡片，并渲染“选择/已选”按钮。

**Step 2: Browser 增加批量工具条**

在 `QuestionLibraryBrowser` 增加：
- `bulkMode`、`selectedIds` 状态
- `全选本页 / 清空 / 删除(n)` 操作（删除前 `confirm`）
- 删除成功后 `refreshList/refreshDetail`，并清空选择

**Step 3: Build**

Run: `cd frontend && npm run build`  
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/pages/questionLibrary/QuestionLibraryCard.tsx frontend/src/pages/questionLibrary/QuestionLibraryBrowser.tsx
git commit -m "feat(frontend): add bulk delete mode in question library browser"
```

---

### Task 5: AI 出题页面复用批量删除

**Files:**
- Modify: `frontend/src/pages/aiGenerate/AiGenerateWorkspace.tsx`

**Step 1: 增加批量工具条**

复用与本地题库相同的 `bulkMode/selectedIds` 逻辑与卡片选择能力，删除后刷新列表。

**Step 2: Build**

Run: `cd frontend && npm run build`  
Expected: PASS

**Step 3: Commit**

```bash
git add frontend/src/pages/aiGenerate/AiGenerateWorkspace.tsx
git commit -m "feat(frontend): add bulk delete mode in ai generate page"
```

---

### Task 6: 全量验证

Run:
- `python -m unittest discover -s backend/tests -p "test_*.py"`
- `cd frontend && npm run build`

Expected: PASS

