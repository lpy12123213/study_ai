# Study-materials Workflow Regression Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore terminal failure delivery, generation-option propagation, export continuation semantics, and exact failed-stage recovery in the staged study-materials workflow.

**Architecture:** Keep the existing workflow version and public API. Normalize options once in `StudyMaterialsWorkflow`, pass them through Codex stage boundaries and tool execution, handle export-only continuations in the orchestrator, and persist stage failures before re-raising them.

**Tech Stack:** Python 3.13, FastAPI task runtime, `unittest`/`AsyncMock`, React/TypeScript/Vitest, Vite.

---

## File map

- `backend/generation/study_materials/orchestrator.py`: terminal task events and export-only continuation handling.
- `backend/generation/study_materials/workflow.py`: normalized option ownership and stage-failure checkpointing.
- `backend/generation/study_materials/codex_stages.py`: option forwarding into stage specs and prompts.
- `backend/generation/study_materials/tool_executor.py`: option persistence and optional research-tool selection.
- `backend/generation/study_materials/resume.py`: failed-stage fallback behavior.
- `backend/tests/test_study_materials_agentic_flow.py`: orchestrator terminal, option, and export continuation regression tests.
- `backend/tests/test_study_materials_workflow.py`: workflow option and stage-error checkpoint tests.
- `backend/tests/test_study_materials_codex_stages.py`: Codex stage option contract test.
- `backend/tests/test_study_materials_resume_state.py`: exact nested-stage recovery test.

### Task 1: Restore canonical terminal failure events

**Files:**
- Modify: `backend/tests/test_study_materials_agentic_flow.py`
- Modify: `backend/generation/study_materials/orchestrator.py:987-1009`

- [ ] **Step 1: Write failing orchestrator tests**

Extend the existing quality-gate failure test and add a stage-result failure test:

```python
self.assertTrue(fail.await_args.kwargs.get("emit_event", True))

failure = StageResultError("invalid_stage_result", stage="draft", detail="stage_contract_mismatch")
# Run manager._run_task with run_study_materials_workflow raising failure.
self.assertTrue(fail.await_args.kwargs.get("emit_event", True))
self.assertEqual(fail.await_args.kwargs["error"]["stage"], "draft")
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest backend.tests.test_study_materials_agentic_flow -v`

Expected: both assertions fail because `emit_event=False` is currently passed.

- [ ] **Step 3: Enable terminal event emission**

Remove `emit_event=False` from both new-workflow failure calls so `task_runtime.fail_task` emits the canonical `error` envelope while preserving the structured database error payload.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest backend.tests.test_study_materials_agentic_flow -v`

Expected: all tests pass.

### Task 2: Propagate generation options through every workflow boundary

**Files:**
- Modify: `backend/tests/test_study_materials_agentic_flow.py`
- Modify: `backend/tests/test_study_materials_workflow.py`
- Modify: `backend/tests/test_study_materials_codex_stages.py`
- Modify: `backend/generation/study_materials/orchestrator.py:975-986`
- Modify: `backend/generation/study_materials/workflow.py:63-187`
- Modify: `backend/generation/study_materials/codex_stages.py:96-175`
- Modify: `backend/generation/study_materials/tool_executor.py:14-220`

- [ ] **Step 1: Write failing boundary tests**

Use one options fixture at each boundary:

```python
options = {
    "preset": "standard",
    "requirements": "保留要求",
    "with_questions": True,
    "with_diagrams": False,
    "enable_extra_tools": True,
    "max_points": 2,
}
```

Assert the orchestrator passes `options`; the workflow stage runner receives the same normalized dictionary; resume memory stores it under `study_options`; and `run_codex_stage` passes it to both `build_study_materials_agent_spec` and `build_stage_prompt`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest backend.tests.test_study_materials_agentic_flow backend.tests.test_study_materials_workflow backend.tests.test_study_materials_codex_stages -v`

Expected: failures show that `options` is missing from workflow and stage-runner arguments.

- [ ] **Step 3: Implement normalized option ownership**

Add `options: Optional[Dict[str, Any]] = None` to workflow constructors/functions and normalize with explicit values authoritative:

```python
self.options = dict(options or {})
self.options["preset"] = self.preset
self.options["requirements"] = self.requirements
```

Pass `options=self.options` to the tool executor and each stage runner. Include `options` in stage prompt input and build the stage agent spec with the complete dictionary plus `workflow_stage`.

- [ ] **Step 4: Honor option-dependent research behavior**

Store the complete options object in `StudyMaterialsToolExecutor.context.working_memory["study_options"]`. When `enable_extra_tools` is true, append `stackexchange_search` and `github_search` to the research tool list. Treat their `results` arrays like web results in `_evidence_from_result` so evidence remains normalized.

- [ ] **Step 5: Run tests and confirm GREEN**

Run: `python -m unittest backend.tests.test_study_materials_agentic_flow backend.tests.test_study_materials_workflow backend.tests.test_study_materials_codex_stages -v`

Expected: all tests pass and option assertions match.

### Task 3: Persist and resume the exact failed stage

**Files:**
- Modify: `backend/tests/test_study_materials_workflow.py`
- Modify: `backend/tests/test_study_materials_resume_state.py`
- Modify: `backend/generation/study_materials/workflow.py:177-187`
- Modify: `backend/generation/study_materials/resume.py:229-260`

- [ ] **Step 1: Write failing checkpoint and resume tests**

Create a stage runner that raises `StageResultError` in `draft`, capture checkpoints, and assert:

```python
self.assertEqual(checkpoints[-1]["last_failure"]["stage"], "draft")
self.assertEqual(checkpoints[-1]["last_failure"]["detail"], "stage_contract_mismatch")
```

Add a legacy-snapshot test with nested `stage="draft"` and empty `last_failure`, then assert `_set_workflow_resume_stage(..., mode="resume_failed_stage")` keeps `draft`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest backend.tests.test_study_materials_workflow backend.tests.test_study_materials_resume_state -v`

Expected: no stage-error checkpoint exists and the fallback returns `review`.

- [ ] **Step 3: Checkpoint stage errors at their source**

Wrap `self.stage_runner` in `_run_codex`:

```python
try:
    return await self.stage_runner(...)
except StageResultError as exc:
    self.state["last_failure"] = {
        "code": exc.code,
        "stage": exc.stage or stage,
        "detail": exc.detail,
        "recoverable": True,
    }
    self.state["stage"] = exc.stage or stage
    await self._checkpoint()
    raise
```

Import `StageResultError` into `workflow.py`.

- [ ] **Step 4: Prefer the nested current stage for legacy snapshots**

In `_set_workflow_resume_stage`, after checking `last_failure.stage`, use the current nested stage when it is one of `plan`, `research`, `draft`, `review`, `revise`, or `accept`; only then fall back to the legacy mapping/default.

- [ ] **Step 5: Run tests and confirm GREEN**

Run: `python -m unittest backend.tests.test_study_materials_workflow backend.tests.test_study_materials_resume_state -v`

Expected: all tests pass.

### Task 4: Implement accepted-content export continuations

**Files:**
- Modify: `backend/tests/test_study_materials_agentic_flow.py`
- Modify: `backend/generation/study_materials/orchestrator.py:778-960`

- [ ] **Step 1: Write failing continuation tests**

Build runtime tasks with `continue_mode` and an accepted nested workflow. Assert:

```python
# fix_export
export.assert_awaited_once_with(markdown=markdown, user_id="u-1")
self.assertEqual(complete.await_args.kwargs["result"]["md_url"], "/media/generated/refreshed.md")
run_workflow.assert_not_awaited()

# skip_export
export.assert_not_awaited()
self.assertEqual(complete.await_args.kwargs["result"]["material"]["markdown"], markdown)
run_workflow.assert_not_awaited()
```

For stale acceptance, assert `fail_task` receives `accepted_content_required`, emits an error event, and neither export nor Codex workflow runs.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest backend.tests.test_study_materials_agentic_flow -v`

Expected: `fix_export` never calls the publisher and invalid acceptance is not rejected deterministically.

- [ ] **Step 3: Add an orchestrator export-continuation branch**

Before local archive reuse or Codex execution, read `options["continue_mode"]`. For `fix_export` and `skip_export`, obtain Markdown and nested workflow acceptance from resume memory, call `acceptance_record_is_current`, and fail with `accepted_content_required` when invalid.

For valid content, construct a result preserving `material`, `acceptance`, `workflow`, and `resume_working_memory`. Only `fix_export` calls `_export_markdown_to_media`; merge its fields into resume memory and the task result. Append `done`, persist the snapshot, and complete the task.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m unittest backend.tests.test_study_materials_agentic_flow -v`

Expected: all export-mode tests pass.

### Task 5: Full verification

**Files:**
- Verify only; no new production changes unless a failing check identifies a regression.

- [ ] **Step 1: Run focused backend suite**

Run:

```powershell
python -m unittest backend.tests.test_study_materials_quality_gate backend.tests.test_study_materials_codex_stages backend.tests.test_study_materials_workflow backend.tests.test_study_materials_agentic_flow backend.tests.test_study_materials_resume_state backend.tests.test_study_archive_acceptance -v
```

Expected: all tests pass.

- [ ] **Step 2: Run backend syntax verification**

Run: `python -m compileall -q backend`

Expected: exit code 0 with no output.

- [ ] **Step 3: Run relevant frontend tests**

Run:

```powershell
cd frontend
npm run test -- --run src/features/generation/studyMaterials/__tests__/useStudyMaterialsStreamRunner.test.tsx src/features/generation/studyMaterials/__tests__/StudyMaterialsWorkspace.test.tsx
```

Expected: both files pass.

- [ ] **Step 4: Run frontend production build**

Run: `cd frontend && npm run build`

Expected: TypeScript and Vite complete successfully.

- [ ] **Step 5: Check patch hygiene**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; status lists only the plan, tests, and implementation files in this scope.

