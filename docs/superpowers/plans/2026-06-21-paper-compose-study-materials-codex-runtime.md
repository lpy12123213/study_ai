# Paper Compose and Study Materials Codex Runtime Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the paper-compose review state machine and make study-materials tolerate recoverable Codex stream diagnostics without completing, failing, or falling back incorrectly.

**Architecture:** Keep Codex CLI process/result normalization in `backend/generation/agentic/claude_code.py`, and keep task-specific terminal decisions in the paper-compose and study-materials orchestrators. Treat CLI retry diagnostics as non-terminal status events; only a terminal Codex result/error may settle a task. Preserve TaskCenter's existing post-review detail and list refetch behavior.

**Tech Stack:** Python 3.13, asyncio, FastAPI task runtime, unittest, React/Vite/Vitest.

---

### Task 1: Normalize recoverable Codex stream diagnostics

**Files:**
- Modify: `backend/generation/agentic/claude_code.py`
- Test: `backend/tests/test_codex_runtime_runner.py`

- [x] Add a regression test proving a CLI `type=error` reconnect notice maps to a warning/status event rather than a terminal task error.
- [x] Run the focused test and confirm it fails on the current adapter.
- [x] Implement the minimal stream-event normalization and rerun the test.

### Task 2: Close paper-compose terminal and fallback boundaries

**Files:**
- Modify: `backend/generation/paper_compose/agentic_workflow.py`
- Test: `backend/tests/test_paper_compose_agentic_workflow.py`

- [x] Add tests proving explicit Codex errors never enter legacy and an exhausted non-terminal Codex stream only enters legacy when fallback is enabled.
- [x] Run the focused tests and confirm the current fallback logic fails them.
- [x] Track terminal events separately from stream exhaustion and implement the minimal boundary fix.

### Task 3: Keep study-materials alive through recoverable stream errors

**Files:**
- Modify: `backend/generation/study_materials/orchestrator.py`
- Test: `backend/tests/test_study_materials_agentic_flow.py`

- [x] Add a regression test where a recoverable error event is followed by a valid `done` event.
- [x] Run it and confirm the current orchestrator fails the task too early.
- [x] Defer error settlement until stream exhaustion while preserving resume snapshots and preventing explicit errors from falling back.

### Task 4: Verify backend and TaskCenter review refresh

**Files:**
- Verify: `backend/api/tasks.py`
- Verify: `backend/tasks/runners.py`
- Verify: `frontend/src/features/taskCenter/hooks/useTaskCenter.ts`
- Test: `backend/tests/test_tasks_api_contract.py`
- Test: `frontend/src/pages/__tests__/TaskCenterPage.test.tsx`

- [x] Run focused backend runtime/review tests.
- [x] Run the TaskCenter Vitest and frontend TypeScript check.
- [x] Run Python compile checks and touched-path `git diff --check`.
- [x] Report the live Codex smoke result separately from deterministic regression results and list untested scenarios.
