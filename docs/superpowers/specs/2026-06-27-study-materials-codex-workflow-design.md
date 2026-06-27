# Study Materials Codex Workflow Design

## Problem

The current Codex path treats a successful Codex process result as a successful
study-material task. Codex receives role IDs, allowed tool names, budgets, and a
Markdown output request, but those declarations do not force it to execute the
backend research, review, and revision tools. A response containing Markdown and
top-level `status=completed` therefore becomes a task-level `done` event even
when there is no evidence that coverage, source depth, or independent review
requirements were met.

The local-archive shortcut has the same trust problem: a matching Markdown
archive is currently marked as passed without validating it against the current
quality policy. Increasing the Codex budget or strengthening the prompt would
make early completion less likely, but would not remove either bypass.

## Goals

- Make the backend workflow, rather than Codex, the sole authority that can
  complete a study-material task.
- Require every preset, including `quick`, to pass an independent review.
- Reuse the existing research, content-review, revision, archive, and resume
  capabilities instead of rebuilding them in prompts.
- Preserve the existing public task/SSE API and the current continuation modes.
- Persist enough stage state that a failed or interrupted run can resume without
  discarding completed research or a usable draft.
- Treat budget exhaustion and failed quality gates as recoverable failures, not
  successful partial results.

## Non-goals

- Redesigning the frontend task flow.
- Reworking LaTeX/PDF export, which remains a deferred workflow after Markdown
  content acceptance.
- Changing other Codex-backed domains.
- Removing the explicit legacy fallback compatibility switch.

## Chosen Architecture

Introduce a backend-owned state machine for the Codex study-material path:

```text
plan -> research -> draft -> review --passed--> accept -> completed
                              |
                              +--failed--> revise --retry--> review
```

Codex is a stage worker. It may plan, draft, and revise, but a Codex process
result only completes that stage. The backend executes research and deterministic
checks, runs an independent manuscript review, evaluates the final acceptance
gate, and alone calls `task_runtime.complete_task()`.

The implementation should introduce three focused modules:

- `backend/generation/study_materials/workflow.py`: state transitions, stage
  execution, retry limits, persistence checkpoints, and final completion.
- `backend/generation/study_materials/quality_gate.py`: deterministic preset
  requirements and the acceptance report.
- `backend/generation/study_materials/codex_stages.py`: stage-specific Codex
  prompts, schemas, and normalization.

`orchestrator.py` remains responsible for task creation, SSE forwarding,
snapshots, cancellation, and selecting the Codex or legacy branch. Existing
domain tools should be reached through a thin adapter over the current tool
dispatcher/context rather than copied into the new modules.

## Stage Contracts

### 1. Plan

Codex returns structured knowledge points, prerequisite order, research queries,
and requested content dimensions. A focused topic may remain one knowledge point;
broad topics must be decomposed. The backend validates non-empty identifiers,
unique knowledge points, and usable queries before advancing.

### 2. Research

The backend executes the planned retrieval with the existing search and browsing
tools. Tool outputs are normalized into facts, source references, source classes,
and per-knowledge-point quality metrics. Codex cannot satisfy this stage merely
by saying that research was performed.

If a knowledge point misses the active preset threshold, the backend retries only
that point with changed queries or source classes. Exhausting the research budget
produces a recoverable `quality_gate_not_met` failure with the missing coverage
in the error payload.

### 3. Draft

Codex receives the validated plan and normalized research bundle and returns
Markdown plus a knowledge-point coverage map. It must not declare the task
complete or fabricate tool traces. The backend rejects an empty document,
malformed Markdown, missing required sections, or a coverage map that does not
match the plan.

### 4. Review

Review is a separate invocation from writing. It receives the Markdown, source
facts, and deterministic coverage report, but not the writer's self-assessment.
The existing `review_content` checks remain the base and return `passed`, concrete
issues, suggestions, and dimension coverage.

A review passes only when both conditions hold:

1. deterministic quality checks pass; and
2. the independent manuscript reviewer returns `passed=true` with valid output.

A missing, malformed, or skipped review is a failure, never an implicit pass.

### 5. Revise

Codex receives the current Markdown and the exact failed checks. It returns the
complete revised Markdown and a short issue-resolution map. The workflow then
returns to review. Unrelated rewriting is discouraged so that verified material
and citations remain stable.

### 6. Accept

The backend recomputes the gate from persisted evidence. Acceptance requires:

- the plan covers the requested topic;
- every planned knowledge point meets its research threshold;
- the Markdown and coverage map are complete;
- deterministic checks pass;
- an independent review from the current draft version passes; and
- the review/gate policy version matches the current policy.

Only this stage may emit the task-level `done` event and call
`task_runtime.complete_task()`.

## Preset Quality Profiles

Budgets are ceilings, not evidence of completion. The initial policy is:

| Preset | Minimum research evidence | Required content | Maximum revise/review cycles |
| --- | --- | --- | ---: |
| `quick` | At least one usable source per knowledge point | Definition, key conclusion, one example or boundary, independent review | 1 |
| `standard` | At least two usable sources from two source classes per knowledge point | Core dimensions, example, boundary/condition, misconception, review | 2 |
| `deep` | At least three usable sources from two source classes per knowledge point; deep-read a primary page when available | At least six review dimensions, derivation or rationale where applicable | 3 |
| `research` | At least four usable sources from three source classes per knowledge point; retry any point below high quality | At least eight review dimensions and explicit source-grounding notes | 4 |

A source is usable only when the existing retrieval normalizer records relevant,
non-empty evidence. Duplicate URLs or repeated snippets do not count as distinct
sources. If network or provider configuration prevents the threshold from being
met, the task preserves its partial state and fails recoverably.

## Codex Result Protocol

The study-material workflow should use a domain-specific stage schema. The
generic Codex top-level `status=completed` means only that the subprocess
completed its assigned stage. The payload must include:

```json
{
  "status": "completed",
  "result": {
    "stage": "draft",
    "stage_status": "completed",
    "stage_version": 1,
    "payload": {}
  }
}
```

The stage runner requests a `result` event rather than a task-level `done` event.
The workflow validates the expected stage and schema before updating state. A
Codex result for the wrong stage, a missing payload, or a direct task-completion
claim is rejected as `invalid_stage_result`.

The generic Codex runner must accept an optional output schema and prompt builder
for this domain while retaining its existing defaults for other callers.

## Workflow State and Persistence

Persist a versioned `study_materials_workflow` object in task metadata after
every stage and every backend tool result. It contains:

- current and last successful stage;
- plan and per-knowledge-point research evidence;
- Markdown draft and a stable draft hash/version;
- latest review and deterministic gate report;
- review/revision attempt counters and budget use;
- last failure code, failed stage, and recoverable next actions; and
- policy/schema versions.

Continue mirroring compatible material, URLs, and `step_results` into
`resume_working_memory` so existing API and export paths keep working.

Continuation modes map to stages as follows:

| Mode | Resume stage |
| --- | --- |
| `improve` | `review`, then `revise` when issues exist |
| `deepen_research` | `research`, preserving the plan and draft as prior evidence |
| `fix_export` | deferred export, only after a valid content acceptance record |
| `skip_export` | complete only when the content acceptance record is valid |
| `resume_failed_stage` | the persisted failed stage |
| `retry_search` | `research` for failed knowledge points only |
| `replan_from_failure` | `plan`, preserving prior evidence for reuse where compatible |

Existing Codex subprocess errors and streamed-tool snapshot recovery remain
compatible. A subprocess-level successful result is deliberately reinterpreted
as stage completion and no longer forwarded as a task-level `done`. The legacy
fallback is still allowed only at the existing pre-terminal boundary when
explicitly enabled; a quality-gate failure must not silently switch to the old
one-shot flow.

## Local Archive Reuse

A fingerprint match makes a local archive a candidate draft, not proof of
quality. It may bypass review only when the archive stores a passing acceptance
record whose request fingerprint, draft hash, preset, quality-policy version,
and review-schema version all match the current request. Otherwise the workflow
starts at `review` and persists a fresh acceptance record if it passes.

This keeps fast reuse for already-verified archives without preserving the
current unconditional `passed=true` shortcut.

## Events and User-visible Status

Keep existing SSE compatibility and add structured data to status events:

- `workflow_stage`: current stage and attempt;
- `quality_report`: per-knowledge-point coverage and failed checks;
- `revision_required`: reviewer issues and remaining attempts; and
- `recovery_available`: failed stage and supported continuation modes.

Intermediate Codex text/tool events may still stream for observability, but they
cannot carry task completion semantics. The final `done` event retains the
existing material shape and additionally includes the passing quality report and
review summary.

## Error Handling

- Codex launch, timeout, or malformed output fails the current stage and saves
  the latest workflow snapshot.
- Backend tool errors are recorded per knowledge point and retried within the
  preset budget using a changed query or provider.
- Review failure enters `revise` while attempts remain.
- Exhausted research or revision budgets fail with
  `quality_gate_not_met`, include actionable issues, and remain resumable.
- Cancellation and pause preserve the current stage without fabricating a final
  error or completion event.
- Export failure cannot invalidate an accepted Markdown document, but export
  completion must not be claimed until the export-specific continuation passes.

## Testing

Add focused tests for:

1. state transitions and the rule that only `accept` completes the RuntimeTask;
2. a Codex stage that immediately returns `completed` without research/review;
3. preset thresholds, duplicate-source handling, and missing coverage;
4. review failure followed by targeted revision and a passing re-review;
5. exhausted revision/research budgets returning a recoverable failure;
6. snapshots and every existing continuation mode;
7. streamed Codex tool-result recovery remaining intact;
8. local archives with valid, missing, stale, and mismatched acceptance records;
9. legacy fallback remaining limited to its current explicit boundary; and
10. the final SSE/result contract, including the quality report.

Verification should include the focused study-material and Codex runtime test
modules, Python compilation, and touched-file diff checks. A live smoke run for
each preset should confirm that the event trace contains research evidence and a
passing review before `done`.

## Rollout and Compatibility

The new state machine replaces the current Codex one-shot branch for
`study_materials`; it is not an optional prompt variant. Other Codex domains and
the explicit legacy runtime remain unchanged. Existing task requests, response
shapes, and continuation endpoints remain compatible, with additive workflow and
quality metadata.

Documentation should state that `completed` now means accepted Markdown content,
not merely a successful Codex subprocess. Historical archives without acceptance
metadata are automatically re-reviewed on first reuse.

## Rejected Alternatives

- Prompt and schema changes alone cannot prove that backend tools ran or that an
  independent reviewer passed the current draft.
- Giving Codex unrestricted autonomous control through new MCP tools adds a
  larger permission and lifecycle surface while still requiring a backend final
  gate.
- Treating budget consumption as progress encourages waste and still does not
  establish quality; budgets remain upper bounds only.
