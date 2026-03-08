# Product Foundation Implementation Plan (Tasks 161–182)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `nextstep.csv` items 161–182 with a shared backend+frontend foundation (tasks, metadata, search, settings, sharing, UX).

**Architecture:** Persist unified tasks/events in SQLite and expose `/api/tasks` for a global task center; add generic metadata, settings sync, share links, search, drafts, templates, annotations, learning plans, exports, wrongbook, diff/rollback and dashboard.

**Tech Stack:** FastAPI + async SQLAlchemy + SQLite; Vite + React + TypeScript + Zustand + React Query + shadcn/ui.

---

### Task 1: Add DB tables + repositories

**Files:**
- Modify: `backend/database/schema.py`
- Modify: `backend/database/legacy_migrations.py`
- Create: `backend/database/repositories/tasks.py`
- Create: `backend/database/repositories/item_meta.py`
- Create: `backend/database/repositories/user_settings.py`
- Create: `backend/database/repositories/share_links.py`
- Create: `backend/database/repositories/learning_plans.py`
- Create: `backend/database/repositories/annotations.py`
- Create: `backend/database/repositories/feedback.py`
- Create: `backend/database/repositories/templates.py`
- Create: `backend/database/repositories/wrongbook.py`

**Verify:**
- Run: `python -m compileall . -q`

---

### Task 2: Expand `/api/tasks` into unified task center API

**Files:**
- Modify: `backend/api/tasks.py`
- Modify: `backend/api/router.py`

**API surface:**
- `GET /api/tasks` (filters: status/type/time)
- `GET /api/tasks/{id}` (+ recent events)
- `GET /api/tasks/{id}/stream` (SSE replay + heartbeat)
- `POST /api/tasks/{id}/pause|resume|retry|cancel`

---

### Task 3: Integrate existing features to write tasks/events

**Files:**
- Modify: `backend/api/study_materials.py`
- Modify: `backend/study_materials/task_manager.py`
- Modify: `backend/api/papers.py` + compose workflow hooks
- Modify: `backend/api/lesson_plan.py`
- Modify: `backend/api/deepthink.py`

**Verify:**
- Run: `python -m unittest discover -s backend/tests -p "test_*.py"`

---

### Task 4: Metadata + search APIs (162/169)

**Files:**
- Modify/Create: `backend/api/system.py` (or new `backend/api/search.py`)
- Create: `backend/api/item_meta.py`

**Verify:**
- Basic perf checks (indexes exist; query limited to top 50)

---

### Task 5: Frontend task center + notifications + progress/ETA (161/165/166/182)

**Files:**
- Create: `frontend/src/pages/TaskCenterPage.tsx`
- Create: `frontend/src/pages/DashboardPage.tsx`
- Create: `frontend/src/components/task/TaskProgressBar.tsx`
- Create: `frontend/src/stores/useTaskStore.ts`
- Create: `frontend/src/components/shared/NotificationCenter.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/components/layout/HistorySidebar.tsx`
- Modify: `frontend/src/App.tsx` (routes)

**Verify:**
- Run: `cd frontend && npm run lint && npm run build`

---

### Task 6: Drafts/templates/onboarding/shortcuts/settings sync (163/164/167/168/173/174/178)

**Files:**
- Create: `frontend/src/hooks/useDraft.ts`
- Modify: `frontend/src/pages/BlueprintPage.tsx` / `frontend/src/pages/studyMaterials/*` / `frontend/src/pages/LessonPlansPage.tsx`
- Create: `frontend/src/components/shared/CommandPalette.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`

---

### Task 7: Share/offline/exports/annotations/learning plan/feedback/wrongbook/diff (170/171/172/175/176/177/180/181)

**Files:**
- Create: pages under `frontend/src/pages/*` as needed
- Extend existing detail pages to expose actions (share/export/annotate/diff/rollback)

---

### Task 8: Verify + mark CSV complete

**Verify:**
- Run: `start.bat doctor`
- Run: `cd frontend && npm run lint && npm run build`

**Finish:**
- Update `nextstep.csv` rows 136–182 to `是否完成=yes` after verification.

