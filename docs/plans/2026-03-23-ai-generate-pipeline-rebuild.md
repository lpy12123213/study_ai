# AI 出题生成链路重构 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the AI question generation pipeline so it runs faster, preserves partial progress during failures, restores running sessions after refresh, and produces more diverse questions that better match requested difficulty.

**Architecture:** Keep the existing `question-library/generate` API and session schema mostly intact, but refactor `backend/question_library/generation.py` into a concurrent, snapshot-aware pipeline. Add incremental session persistence in `backend/api/question_library.py`, then update the AI generate studio to poll running sessions for recovery when SSE state is unavailable.

**Tech Stack:** FastAPI, asyncio, unittest, React 19, TypeScript, TanStack Query

---

### Task 1: Add failing backend tests for generation pipeline behavior

**Files:**
- Modify: `backend/tests/test_question_library_generation_pipeline.py`

**Step 1: Write the failing test**

Add tests for:

- concurrent realize keeps working when one spec fails
- difficulty prompt changes with requested difficulty
- final selection enforces multi-dimension diversity
- difficulty mismatch is penalized during judge filtering

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: FAIL because the current pipeline is still serial and does not enforce the new diversity/difficulty behavior.

**Step 3: Write minimal implementation**

- Do not touch API code yet.
- Change only `backend/question_library/generation.py` enough to satisfy one failing test at a time.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: PASS for the newly added cases.

### Task 2: Refactor runtime search config and difficulty-aware prompting

**Files:**
- Modify: `backend/question_library/generation.py`
- Modify: `backend/core/settings.py`

**Step 1: Write the failing test**

Add targeted tests covering:

- count-based beam/draft defaults
- `QUESTION_LIBRARY_JUDGE_MODEL` override for lightweight stages
- prompt text differs between simple / medium / hard

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: FAIL because the defaults and prompt are still static.

**Step 3: Write minimal implementation**

- Add runtime config normalization helper.
- Add separate model selection helper for solve/ambiguity.
- Update `build_generation_messages()` to emit difficulty-specific system content.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: PASS

### Task 3: Refactor spec expansion, scoring, beam, and final selection for diversity

**Files:**
- Modify: `backend/question_library/generation.py`
- Modify: `backend/tests/test_question_library_generation_pipeline.py`

**Step 1: Write the failing test**

Add tests proving:

- `_expand_field()` no longer always returns the same first N options
- `beam_select()` preserves multiple buckets
- `select_final()` filters duplicates across `skill + reasoning + surface`

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: FAIL with duplicate-heavy outputs.

**Step 3: Write minimal implementation**

- Randomize/snapshot option selection.
- Add score perturbation plus diversity-aware beam bucket selection.
- Expand final-selection duplicate key from one dimension to three.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: PASS

### Task 4: Refactor realize stage to bounded concurrency

**Files:**
- Modify: `backend/question_library/generation.py`

**Step 1: Write the failing test**

Add an async test that:

- schedules multiple specs
- makes one `realize_drafts()` call fail
- verifies others still complete
- verifies concurrency path still returns candidates

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: FAIL because realize still runs serially.

**Step 3: Write minimal implementation**

- Extract realize worker helper.
- Add semaphore-bounded `asyncio.gather`.
- Preserve stage-event accounting and failure counters.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: PASS

### Task 5: Refactor judge stage to bounded concurrency and difficulty filtering

**Files:**
- Modify: `backend/question_library/generation.py`

**Step 1: Write the failing test**

Add tests covering:

- solve consensus runs concurrently
- solve and ambiguity run in parallel per candidate
- judge uses difficulty estimate to penalize mismatches

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: FAIL because judge path is serial and ignores difficulty estimate.

**Step 3: Write minimal implementation**

- Extract candidate-evaluation worker.
- Run solve/ambiguity concurrently.
- Run candidate workers with a judge semaphore.
- Apply difficulty mismatch penalty or reject logic using `difficulty_tolerance`.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline`
Expected: PASS

### Task 6: Add API-level tests for incremental session persistence and partial failure recovery

**Files:**
- Modify: `backend/tests/test_question_library_api.py`

**Step 1: Write the failing test**

Add tests proving:

- accepted drafts are persisted before task completion
- exceptions preserve partial drafts and set session to `partial_failure`
- cancelled/running sessions remain recoverable

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_api`
Expected: FAIL because session persistence currently happens only at the end.

**Step 3: Write minimal implementation**

- Only after the red test is verified, patch `backend/api/question_library.py`.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_api`
Expected: PASS

### Task 7: Implement incremental session snapshot persistence in the generate API

**Files:**
- Modify: `backend/api/question_library.py`
- Modify: `backend/api/question_library_schemas.py`

**Step 1: Write the failing test**

Extend API tests to validate:

- `partial_failure` session status is serialized
- running sessions expose latest drafts/task events for recovery

**Step 2: Run test to verify it fails**

Run: `python -m unittest backend.tests.test_question_library_api`
Expected: FAIL because the current serializer and runner do not expose the new states consistently.

**Step 3: Write minimal implementation**

- Add helpers to persist merged drafts during generation.
- Save accepted and fallback raw drafts inside `except`/`finally`.
- Preserve `task_events` and `reasoning_blocks` loading behavior.

**Step 4: Run test to verify it passes**

Run: `python -m unittest backend.tests.test_question_library_api`
Expected: PASS

### Task 8: Add failing frontend tests for running-session recovery

**Files:**
- Modify: `frontend/src/pages/aiGenerate/__tests__/AiGenerateStudioPage.test.tsx`
- Modify: `frontend/src/pages/aiGenerate/__tests__/useAiGenerateSession.test.ts`

**Step 1: Write the failing test**

Add tests proving:

- a `running` session is polled and restored after refresh
- polled drafts appear in the stream without a done preview
- polling stops when the session reaches a terminal state

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- AiGenerateStudioPage useAiGenerateSession`
Expected: FAIL because the page currently hydrates once and does not poll running sessions.

**Step 3: Write minimal implementation**

- Only after RED is verified, patch the studio page and local session reducer.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- AiGenerateStudioPage useAiGenerateSession`
Expected: PASS

### Task 9: Implement running-session polling and recovery in the studio page

**Files:**
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Modify: `frontend/src/pages/aiGenerate/useAiGenerateSession.ts`
- Modify: `frontend/src/pages/questionLibrary/hooks/useQuestionLibraryTasks.ts`

**Step 1: Write the failing test**

Extend the recovery tests to verify:

- local SSE state and server session state do not clobber each other
- `partial_failure` and `running` status labels render sensibly

**Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- AiGenerateStudioPage useAiGenerateSession`
Expected: FAIL before the recovery logic is implemented.

**Step 3: Write minimal implementation**

- Add `refetchInterval` / manual polling for running sessions.
- Merge server session drafts into local session state.
- Stop polling when session leaves `running`.

**Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- AiGenerateStudioPage useAiGenerateSession`
Expected: PASS

### Task 10: Run focused verification and then broader health checks

**Files:**
- Modify: `backend/question_library/generation.py`
- Modify: `backend/api/question_library.py`
- Modify: `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
- Modify: `frontend/src/pages/aiGenerate/useAiGenerateSession.ts`
- Modify: `frontend/src/pages/questionLibrary/hooks/useQuestionLibraryTasks.ts`
- Modify: `backend/tests/test_question_library_generation_pipeline.py`
- Modify: `backend/tests/test_question_library_api.py`
- Modify: `frontend/src/pages/aiGenerate/__tests__/AiGenerateStudioPage.test.tsx`
- Modify: `frontend/src/pages/aiGenerate/__tests__/useAiGenerateSession.test.ts`

**Step 1: Run focused backend tests**

Run: `python -m unittest backend.tests.test_question_library_generation_pipeline backend.tests.test_question_library_api`
Expected: PASS

**Step 2: Run focused frontend tests**

Run: `cd frontend && npm run test -- AiGenerateStudioPage useAiGenerateSession`
Expected: PASS

**Step 3: Run build verification**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 4: Run repo smoke check if still needed**

Run: `./start.sh doctor` or `start.bat doctor`
Expected: PASS or only unrelated pre-existing issues.
