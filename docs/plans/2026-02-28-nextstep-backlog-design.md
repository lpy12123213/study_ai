# Nextstep Backlog Execution Design (2026-02-28)

This design document describes how we will execute the full `nextstep.csv` backlog in priority order (P0 → P1 → P2),
while keeping the system runnable at every stage and preserving backward compatibility for existing UI flows.

## Goals

- Complete the tracked backlog items in `nextstep.csv`, prioritizing P0 first.
- Improve reliability of long-running SSE tasks (study-materials and paper-compose) with resumability and consistent event shapes.
- Improve study-materials quality via explicit, configurable adaptive policy (iteration budget, auto-research, auto-revise, graceful degradation).
- Improve paper-compose selection quality and reduce repeated crawler work via caching and lightweight content review.
- Ensure the repo remains verifiable: compile/import, backend unit tests, and frontend lint/build where applicable.

## Non-Goals (for initial pass)

- Large-scale product redesigns not requested by `nextstep.csv`.
- Rewriting the entire system into a new architecture; changes should be incremental and scoped.

## Key Principles

1. **Back-compat first**: new APIs/events must not break existing UI; provide dual-field output during migration.
2. **Resumable by design**: all long-running tasks should support reconnect and replay using `seq`.
3. **Fail-soft**: optional steps (LaTeX compile, diagrams, external providers) should degrade without killing core outputs.
4. **Deterministic testing**: introduce record/replay where external network/API calls make tests flaky.
5. **Configurable policy**: move “magic heuristics” into explicit policy modules with env knobs.

## System Areas & Design Decisions

### 1) Unified SSE Envelope (cross-cutting)

Problem: study-materials emits `{event,data,task_id,seq}` while paper-compose emits `{type,step,taskId,seq}`.
This prevents reuse of the same frontend SSE hook and increases integration drift.

Design:

- Define a canonical envelope with:
  - `seq: number`
  - `taskId: string`
  - `type: string` (event kind)
  - `data: object` (payload)
- During migration:
  - backend continues emitting legacy fields **in addition** to canonical fields
  - frontend parser accepts both and normalizes into one internal representation

### 2) Study-Materials: Continue/Resume semantics

We separate two meanings of “continue”:

- **Resume streaming**: reconnect to an existing task stream and keep receiving new events.
- **Continue iteration**: after completion (or certain failures), run another bounded improvement pass.

Design:

- Task manager stores:
  - events (for replay)
  - status: running/completed/failed
  - minimal continuation state: `working_memory` snapshot + `iteration` counter + export artifacts
- New endpoint:
  - `POST /api/study-materials/tasks/{task_id}/continue` with `mode`:
    - `improve`, `deepen_research`, `fix_export`, `skip_export`

### 3) Study-Materials: Explicit Adaptive Policy

Problem: auto-research/auto-revise/iteration stopping rules are scattered.

Design:

- Introduce `backend/agent/policy.py` (StudyMaterialsPolicy):
  - `iteration_budget(...)` chooses iteration count by preset + continuation mode, with caps
  - `missing_kps_for_auto_research(...)` parses heuristic review issues and returns bounded KP list
  - `issues_for_auto_revise(...)` provides bounded issues list for one-shot revise flow
  - state is persisted in `ctx.working_memory["_study_policy"]`

### 4) Caching & Speed Improvements

- Cache web search and browse page text by URL/query hash.
- Cache question metadata (stem/quality_score/difficulty_value) in SQLite and reuse when composing papers.
- Reduce redundant crawler parse work by caching “questionId → parsed stem” locally.

### 5) Record/Replay Test Mode

Goal: make tests runnable without network and avoid regressions.

Design:

- Add record/replay layer for:
  - HTTP crawler responses
  - LLM client responses (where applicable)
- Persist fixtures under `.local/fixtures/` keyed by deterministic request fingerprints.
- Add env toggles:
  - `REPLAY=1` to force using fixtures
  - `RECORD=1` to capture and persist new fixtures (dev-only)

### 6) Global Hardening

- Add a simple rate limit middleware to backend (IP/user based) with conservative defaults.
- Introduce structured logging (standard `logging` + JSON-ish formatter) replacing scattered `print()`.
- Add Alembic migrations to track DB schema evolution.

## Execution Plan (phased)

1. **P0 fixes first**: unblock imports/tests; implement study-materials continue/reconnect baseline; improve compose quality scoring.
2. **P1 improvements**: UX bugs, policy refinements, caching, hook stability, moderate refactors (file splits).
3. **P2 foundations**: SSE unification, migrations, record/replay, observability, larger refactors, local knowledge reuse.

## Verification Checklist

Required before final push:

- Backend: `python -m py_compile` critical modules; `python -m unittest discover -s backend/tests -p "test_*.py"`.
- Frontend: `npm run lint` and `npm run build` (or project doctor script if available).
- Functional smoke checks:
  - Study-materials: start task → refresh → resume; completed → continue iteration; export failure → fix/skip.
  - Paper-compose: compose stream emits progress/steps; selection quality filters out login-required/broken stems.

