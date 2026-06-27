# Study Materials Codex Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the study-materials Codex one-shot completion path with a backend-owned staged workflow that requires research evidence and an independent passing review before completing the task.

**Architecture:** Add pure workflow-state and quality-gate modules, a stage-specific Codex adapter, and a backend tool adapter over the existing `Executor`/`ContextManager`. The orchestrator delegates only the Codex study-material branch to the new workflow, persists each checkpoint into `resume_working_memory`, and retains task-level completion authority.

**Tech Stack:** Python 3.13, FastAPI task runtime, asyncio, SQLAlchemy/SQLite, Codex CLI runtime, unittest

---

## File Structure

- Create `backend/generation/study_materials/quality_gate.py`: versioned workflow state, preset profiles, source normalization, draft hashing, deterministic gate reports, and archive acceptance validation.
- Create `backend/generation/study_materials/codex_stages.py`: stage prompts, strict stage payload normalization, and `result`-event execution through the existing Codex runtime.
- Create `backend/generation/study_materials/tool_executor.py`: initialize an existing agent context and execute backend research/review tools without running the legacy autonomous loop.
- Create `backend/generation/study_materials/workflow.py`: backend-owned stage transitions, retries, checkpoints, events, and final accepted result.
- Modify `backend/generation/agentic/claude_code.py`: allow a caller-supplied prompt and result schema while preserving current defaults.
- Modify `backend/generation/agentic/codex_runtime.py`: re-export any new shared runner types needed by the stage adapter.
- Modify `backend/generation/study_materials/orchestrator.py`: replace direct Codex `done -> complete_task` handling with the staged workflow and revalidate local archives.
- Modify `backend/generation/study_materials/resume.py`: preserve/map the versioned workflow state for continuation modes.
- Modify `backend/database/schema.py`, `backend/database/migrations.py`, and `backend/database/repositories/content/study_archives.py`: persist and read archive acceptance records.
- Modify `docs/API.md`: document the stronger meaning of study-material completion and additive quality events.
- Create `backend/tests/test_study_materials_quality_gate.py`: pure quality-policy and archive-acceptance tests.
- Create `backend/tests/test_study_materials_codex_stages.py`: stage protocol and malformed/early completion tests.
- Create `backend/tests/test_study_materials_workflow.py`: staged workflow, retry, budget, recovery, and event tests.
- Modify `backend/tests/test_codex_runtime_runner.py`: caller-supplied prompt/schema compatibility tests.
- Modify `backend/tests/test_study_materials_agentic_flow.py`: orchestrator, local-archive, completion-authority, and continuation regressions.
- Create `backend/tests/test_study_archive_acceptance.py`: repository and SQLite migration coverage for acceptance metadata.

### Task 1: Add the deterministic quality gate

**Files:**
- Create: `backend/generation/study_materials/quality_gate.py`
- Create: `backend/tests/test_study_materials_quality_gate.py`

- [ ] **Step 1: Write failing profile, source, draft, and acceptance tests**

Cover all preset thresholds, duplicate source identities, missing knowledge points,
stale review hashes, and stale archive policy versions. The central assertion is:

```python
report = evaluate_acceptance(
    state=state_with_complete_research_and_markdown(),
    review={"passed": True, "draft_hash": draft_hash(markdown), "dimensions": {}},
)
self.assertTrue(report["passed"])

state["research"]["kp-1"] = []
report = evaluate_acceptance(state=state, review=review)
self.assertFalse(report["passed"])
self.assertIn("research_evidence_missing:kp-1", report["failed_checks"])
```

- [ ] **Step 2: Run the new module and verify RED**

```powershell
python -m unittest backend.tests.test_study_materials_quality_gate -v
```

Expected: import failure because `quality_gate.py` does not exist.

- [ ] **Step 3: Implement versioned profiles and pure gate functions**

Define stable constants and functions:

```python
WORKFLOW_VERSION = 1
QUALITY_POLICY_VERSION = 1
REVIEW_SCHEMA_VERSION = 1

PRESET_PROFILES = {
    "quick": {"min_sources": 1, "min_source_classes": 1, "min_dimensions": 3, "max_review_cycles": 1},
    "standard": {"min_sources": 2, "min_source_classes": 2, "min_dimensions": 5, "max_review_cycles": 2},
    "deep": {"min_sources": 3, "min_source_classes": 2, "min_dimensions": 6, "max_review_cycles": 3},
    "research": {"min_sources": 4, "min_source_classes": 3, "min_dimensions": 8, "max_review_cycles": 4},
}

def draft_hash(markdown: str) -> str:
    return hashlib.sha256(str(markdown or "").encode("utf-8")).hexdigest()

def evaluate_acceptance(*, state: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    preset = str(state.get("preset") or "standard")
    profile = PRESET_PROFILES[preset]
    markdown = str(state.get("markdown") or "")
    failed_checks: list[str] = []
    per_knowledge_point: dict[str, Any] = {}
    for point in state.get("plan", {}).get("knowledge_points", []):
        point_id = str(point["id"])
        evidence = normalize_evidence(state.get("research", {}).get(point_id, []))
        source_classes = {str(item["source_class"]) for item in evidence}
        point_failures: list[str] = []
        if len(evidence) < profile["min_sources"]:
            point_failures.append(f"research_evidence_missing:{point_id}")
        if len(source_classes) < profile["min_source_classes"]:
            point_failures.append(f"source_classes_missing:{point_id}")
        if str(point.get("title") or "").strip() not in markdown:
            point_failures.append(f"draft_coverage_missing:{point_id}")
        failed_checks.extend(point_failures)
        per_knowledge_point[point_id] = {"passed": not point_failures, "failed_checks": point_failures}

    current_hash = draft_hash(markdown)
    dimensions = review.get("dimensions") if isinstance(review.get("dimensions"), dict) else {}
    covered_dimensions = sum(1 for value in dimensions.values() if bool(value))
    if not markdown.strip():
        failed_checks.append("markdown_missing")
    if not bool(review.get("passed")):
        failed_checks.append("independent_review_failed")
    if str(review.get("draft_hash") or "") != current_hash:
        failed_checks.append("review_draft_mismatch")
    if covered_dimensions < profile["min_dimensions"]:
        failed_checks.append("review_dimensions_missing")
    return {
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "per_knowledge_point": per_knowledge_point,
        "draft_hash": current_hash,
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "review_schema_version": REVIEW_SCHEMA_VERSION,
    }

def acceptance_record_is_current(*, archive: dict[str, Any], preset: str, markdown: str) -> bool:
    record = archive.get("acceptance") if isinstance(archive.get("acceptance"), dict) else {}
    return bool(record.get("accepted")) and all(
        (
            str(record.get("preset") or "") == str(preset or "standard"),
            str(record.get("draft_hash") or "") == draft_hash(markdown),
            int(record.get("quality_policy_version") or 0) == QUALITY_POLICY_VERSION,
            int(record.get("review_schema_version") or 0) == REVIEW_SCHEMA_VERSION,
        )
    )
```

`normalize_evidence()` must deduplicate by canonical URL, falling back to a hash
of source class/title/snippet, and must reject empty snippets/summaries.

- [ ] **Step 4: Run the quality-gate tests and verify GREEN**

```powershell
python -m unittest backend.tests.test_study_materials_quality_gate -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the pure policy layer**

```powershell
git add -- backend/generation/study_materials/quality_gate.py backend/tests/test_study_materials_quality_gate.py docs/superpowers/plans/2026-06-27-study-materials-codex-workflow.md
git commit -m "feat(study-materials): add versioned quality gate"
```

### Task 2: Add a stage-specific Codex protocol

**Files:**
- Create: `backend/generation/study_materials/codex_stages.py`
- Create: `backend/tests/test_study_materials_codex_stages.py`
- Modify: `backend/generation/agentic/claude_code.py`
- Modify: `backend/generation/agentic/codex_runtime.py`
- Modify: `backend/tests/test_codex_runtime_runner.py`

- [ ] **Step 1: Write failing shared-runner override tests**

Assert that a caller-supplied prompt is sent to stdin, a caller-supplied schema is
passed through command construction, and existing callers still receive the
current default prompt/result behavior.

```python
events = [
    event
    async for event in run_codex_runtime_agent_events(
        task_type="study_materials",
        request={},
        user_id="u-1",
        task_id="stage-1",
        spec=_spec(),
        prompt_override="STAGE PROMPT",
        result_schema=stage_schema,
        final_event_type="result",
        process_factory=factory,
    )
]
self.assertIn(b"STAGE PROMPT", process.stdin.chunks)
self.assertEqual(events[-1]["type"], "result")
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m unittest backend.tests.test_codex_runtime_runner -q
```

Expected: the new test fails because the override parameters are unsupported.

- [ ] **Step 3: Add backward-compatible override parameters**

Extend `run_codex_runtime_agent_events()` with:

```python
prompt_override: str = "",
result_schema: Optional[Dict[str, Any]] = None,
```

Use `prompt_override` only when non-empty and use
`result_schema or CODEX_RUNTIME_RESULT_SCHEMA` for command construction. Do not
change any other caller or event mapping.

- [ ] **Step 4: Write failing stage normalization tests**

Test valid `plan`, `draft`, and `revise` payloads plus wrong-stage, missing
payload, direct task completion, and runtime error cases:

```python
with self.assertRaisesRegex(StageResultError, "invalid_stage_result"):
    normalize_stage_result("draft", {"stage": "accept", "stage_status": "completed", "payload": {}})
```

- [ ] **Step 5: Implement the stage adapter**

Expose:

```python
StageEventSink = Callable[[Dict[str, Any]], Awaitable[None]]

async def run_codex_stage(
    *,
    stage: str,
    task_id: str,
    user_id: str,
    topic: str,
    subject: str,
    preset: str,
    payload: Dict[str, Any],
    event_sink: StageEventSink,
) -> Dict[str, Any]:
    final_result: Dict[str, Any] = {}
    async for event in run_codex_runtime_agent_events(
        task_type="study_materials",
        request={"stage": stage, "payload": payload},
        user_id=user_id,
        task_id=f"{task_id}-{stage}",
        spec=build_stage_spec(topic=topic, subject=subject, preset=preset, stage=stage),
        prompt_override=build_stage_prompt(stage=stage, topic=topic, subject=subject, preset=preset, payload=payload),
        result_schema=STAGE_RESULT_SCHEMA,
        final_event_type="result",
    ):
        event_type = str(event.get("type") or event.get("event") or "")
        if event_type == "error":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            raise StageResultError(str(data.get("code") or "codex_stage_failed"))
        if event_type == "result":
            final_result = event.get("result") if isinstance(event.get("result"), dict) else {}
            continue
        await event_sink(event)
    return normalize_stage_result(stage, final_result)
```

The adapter builds a stage-only prompt, calls the shared runner with
`final_event_type="result"`, forwards nonterminal events, validates
`result.stage`, `stage_status`, `stage_version`, and the stage payload, and never
returns a task-level `done` event.

- [ ] **Step 6: Run stage and runtime tests**

```powershell
python -m unittest backend.tests.test_study_materials_codex_stages backend.tests.test_codex_runtime_runner -q
```

Expected: both modules pass.

- [ ] **Step 7: Commit the stage protocol**

```powershell
git add -- backend/generation/agentic/claude_code.py backend/generation/agentic/codex_runtime.py backend/generation/study_materials/codex_stages.py backend/tests/test_codex_runtime_runner.py backend/tests/test_study_materials_codex_stages.py
git commit -m "feat(study-materials): add Codex stage protocol"
```

### Task 3: Reuse backend research and review tools

**Files:**
- Create: `backend/generation/study_materials/tool_executor.py`
- Modify: `backend/tests/test_study_materials_workflow.py`

- [ ] **Step 1: Write failing adapter tests with a fake `Executor`**

Verify plan-derived knowledge points are placed in working memory; `quick` runs
web search, `standard` adds Wikipedia, `deep/research` deep-read selected URLs;
each `StepResult` updates context through `ContextManager.on_step_result`; and
review uses the current Markdown and returns the exact `review_content` output.

- [ ] **Step 2: Implement the adapter over existing agent primitives**

Build a `CompressedContext` with `UserProfile`, `study_options`,
`split_knowledge_points`, and restored working memory. Execute `PlanStep` values
through `Executor.execute_step()` and then call
`ContextManager.on_step_result()`:

```python
result = await self.executor.execute_step(step, context=self.context, emit_event=event_sink)
await self.context_manager.on_step_result(self.context, step=step, result=result)
```

Expose `research(plan, preset, event_sink)`, `review(markdown, event_sink)`,
`working_memory`, and `step_results`. Normalize web/Wikipedia/MediaWiki/page
outputs through `quality_gate.normalize_evidence()`.

- [ ] **Step 3: Run adapter tests**

```powershell
python -m unittest backend.tests.test_study_materials_workflow.StudyMaterialsToolExecutorTests -v
```

Expected: all adapter tests pass without network access.

- [ ] **Step 4: Commit the tool adapter**

```powershell
git add -- backend/generation/study_materials/tool_executor.py backend/tests/test_study_materials_workflow.py
git commit -m "feat(study-materials): reuse backend research tools"
```

### Task 4: Implement the backend-owned workflow state machine

**Files:**
- Create: `backend/generation/study_materials/workflow.py`
- Modify: `backend/tests/test_study_materials_workflow.py`

- [ ] **Step 1: Write the premature-completion regression first**

Use injected stage/tool runners. Make the draft stage immediately return Markdown
while research evidence and review are missing, then assert the workflow does not
return an accepted result:

```python
with self.assertRaisesRegex(WorkflowFailure, "quality_gate_not_met"):
    await workflow.run()
self.assertNotEqual(workflow.state["stage"], "completed")
self.assertFalse(workflow.state.get("acceptance", {}).get("accepted", False))
```

- [ ] **Step 2: Run the regression and verify RED**

```powershell
python -m unittest backend.tests.test_study_materials_workflow.StudyMaterialsWorkflowTests.test_codex_cannot_complete_before_review -v
```

Expected: import or assertion failure because the workflow does not exist.

- [ ] **Step 3: Implement versioned state and transitions**

`StudyMaterialsWorkflow.run()` must advance only through:

```python
PLAN = "plan"
RESEARCH = "research"
DRAFT = "draft"
REVIEW = "review"
REVISE = "revise"
ACCEPT = "accept"
COMPLETED = "completed"
```

Dependencies are injected:

```python
class CodexStageRunner(Protocol):
    async def __call__(
        self,
        *,
        stage: str,
        task_id: str,
        user_id: str,
        topic: str,
        subject: str,
        preset: str,
        payload: Dict[str, Any],
        event_sink: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Dict[str, Any]:
        raise NotImplementedError

CheckpointSink = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[None]]
EventSink = Callable[[Dict[str, Any]], Awaitable[None]]
```

Checkpoint after every successful/failed stage and backend tool result. Mirror
the latest Markdown, research working memory, review result, acceptance record,
and `step_results` into resume working memory.

- [ ] **Step 4: Implement review/revise limits and failure semantics**

Use `PRESET_PROFILES[preset]["max_review_cycles"]`. A failed review invokes the
Codex `revise` stage and returns to review. Exhaustion raises:

```python
WorkflowFailure(
    code="quality_gate_not_met",
    stage="review",
    issues=gate_report["failed_checks"] + review.get("issues", []),
    recoverable=True,
)
```

No code path may convert this exception into a successful result.

- [ ] **Step 5: Add successful, retry, malformed-stage, cancellation, and resume tests**

Assert the exact stage order, one final acceptance record, current-draft review
hash, checkpoint calls, additive workflow events, and restart from persisted
`stage`/attempt counters.

- [ ] **Step 6: Run the workflow module**

```powershell
python -m unittest backend.tests.test_study_materials_workflow -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the workflow engine**

```powershell
git add -- backend/generation/study_materials/workflow.py backend/tests/test_study_materials_workflow.py
git commit -m "feat(study-materials): enforce staged acceptance workflow"
```

### Task 5: Persist archive acceptance records

**Files:**
- Modify: `backend/database/schema.py`
- Modify: `backend/database/migrations.py`
- Modify: `backend/database/repositories/content/study_archives.py`
- Create: `backend/tests/test_study_archive_acceptance.py`

- [ ] **Step 1: Write failing repository and migration tests**

Create a legacy SQLite `study_archives` table without the new column, run
`sync_migrate_db_schema()`, and assert `acceptance_json` exists. Upsert an archive
with an acceptance record and assert fingerprint lookup returns the same record.

- [ ] **Step 2: Add the schema and idempotent migration**

Add:

```python
acceptance_json = Column(Text, default="{}")
```

and in the existing `study_archives` migration block:

```python
_add_col(conn, table="study_archives", name="acceptance_json", ddl="TEXT NOT NULL DEFAULT '{}'", existing_cols=sa_cols)
```

- [ ] **Step 3: Extend repository serialization**

Add optional `acceptance: Optional[Dict[str, Any]] = None` to
`upsert_study_archive()`, serialize it defensively, and include parsed
`acceptance` in every archive-to-dict response. Invalid historical JSON returns
an empty dict and never passes validation.

- [ ] **Step 4: Run persistence tests**

```powershell
python -m unittest backend.tests.test_study_archive_acceptance -v
```

Expected: repository and idempotent migration tests pass.

- [ ] **Step 5: Commit persistence changes**

```powershell
git add -- backend/database/schema.py backend/database/migrations.py backend/database/repositories/content/study_archives.py backend/tests/test_study_archive_acceptance.py
git commit -m "feat(study-materials): persist archive acceptance records"
```

### Task 6: Integrate the workflow into the orchestrator and continuation paths

**Files:**
- Modify: `backend/generation/study_materials/orchestrator.py`
- Modify: `backend/generation/study_materials/resume.py`
- Modify: `backend/tests/test_study_materials_agentic_flow.py`
- Modify: `backend/tests/test_study_materials_resume_state.py`

- [ ] **Step 1: Replace old success expectations with failing authority tests**

Change the Codex tests so a raw one-shot `done` cannot call `complete_task`.
Add a mocked `run_study_materials_workflow()` result and assert only its accepted
result causes archive upsert and task completion. Assert
`WorkflowFailure(code="quality_gate_not_met")` calls `fail_task` with
`recoverable=true` and preserves resume state.

- [ ] **Step 2: Run orchestrator tests and verify RED**

```powershell
python -m unittest backend.tests.test_study_materials_agentic_flow -q
```

Expected: failures show the orchestrator still completes on a raw Codex `done`.

- [ ] **Step 3: Delegate the Codex branch to the workflow**

Replace the direct `run_codex_runtime_agent_events()` terminal loop with a call
that receives `meta`, request fields, event/checkpoint sinks, and the restored
workflow state. The checkpoint sink must update
`meta["resume_working_memory"]`, `meta["study_materials_workflow"]`, refresh
resume metadata, and persist the snapshot.

Only after the workflow returns an accepted result should the orchestrator:

```python
await self._upsert_archive_from_resume_state(task, meta=meta, query=query, subject=subject, options=options)
self._persist_snapshot(task, force=True)
await task_runtime.complete_task(task, result=accepted_result)
```

- [ ] **Step 4: Revalidate local archive candidates**

If `acceptance_record_is_current()` passes, the current fast path may complete.
Otherwise seed the archive Markdown into resume/workflow state at `review` and
continue through the workflow. Remove the unconditional `passed=True` shortcut.

- [ ] **Step 5: Preserve continuation modes**

Store the workflow state inside `resume_working_memory` under
`study_materials_workflow`. Update pruning so `retry_search` sets the nested
stage to `research`, `replan_from_failure` sets it to `plan`,
`resume_failed_stage` keeps the failed stage, `improve` starts at `review`, and
`fix_export`/`skip_export` require a current accepted-content record.

- [ ] **Step 6: Run orchestrator and resume tests**

```powershell
python -m unittest backend.tests.test_study_materials_agentic_flow backend.tests.test_study_materials_resume_state -q
```

Expected: all tests pass, including streamed-tool recovery and the existing
legacy fallback boundary.

- [ ] **Step 7: Commit integration changes**

```powershell
git add -- backend/generation/study_materials/orchestrator.py backend/generation/study_materials/resume.py backend/tests/test_study_materials_agentic_flow.py backend/tests/test_study_materials_resume_state.py
git commit -m "fix(study-materials): prevent premature Codex completion"
```

### Task 7: Document and verify the complete chain

**Files:**
- Modify: `docs/API.md`
- Verify: all files from Tasks 1-6

- [ ] **Step 1: Document completion and events**

State that `study_materials` completion means current-policy acceptance, list
`workflow_stage`, `quality_report`, `revision_required`, and
`recovery_available`, and document recoverable `quality_gate_not_met` failures.

- [ ] **Step 2: Run focused backend tests**

```powershell
python -m unittest backend.tests.test_study_materials_quality_gate backend.tests.test_study_materials_codex_stages backend.tests.test_study_materials_workflow backend.tests.test_study_archive_acceptance backend.tests.test_study_materials_agentic_flow backend.tests.test_study_materials_resume_state backend.tests.test_codex_runtime_runner backend.tests.test_tasks_api_contract -q
```

Expected: no failures or errors.

- [ ] **Step 3: Run all study-material tests**

```powershell
python -m unittest discover -s backend/tests -p "test_study_materials*.py" -q
```

Expected: no failures or errors.

- [ ] **Step 4: Compile and inspect touched paths**

```powershell
python -m py_compile backend/generation/agentic/claude_code.py backend/generation/agentic/codex_runtime.py backend/generation/study_materials/quality_gate.py backend/generation/study_materials/codex_stages.py backend/generation/study_materials/tool_executor.py backend/generation/study_materials/workflow.py backend/generation/study_materials/orchestrator.py backend/generation/study_materials/resume.py backend/database/schema.py backend/database/migrations.py backend/database/repositories/content/study_archives.py
git diff --check -- backend/generation backend/database backend/tests docs/API.md
```

Expected: both commands exit 0.

- [ ] **Step 5: Run live smoke tests when runtime credentials are available**

Run one `quick` and one `standard` self-study request. Confirm the event order
contains research evidence and a passing review before the only task-level
`done`. If credentials/providers are unavailable, report the live smoke as
blocked rather than claiming it passed.

- [ ] **Step 6: Commit docs and any final test corrections**

```powershell
git add -- docs/API.md backend/generation backend/database backend/tests
git commit -m "docs: describe accepted study-material completion"
```

Expected: the final commit contains only scoped documentation or verification
corrections; unrelated user files remain unstaged.
