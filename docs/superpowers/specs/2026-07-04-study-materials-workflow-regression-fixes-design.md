# Study-materials workflow regression fixes

## Scope

Repair four regressions introduced by the staged Codex study-materials workflow:

1. failed workflows must deliver a terminal error event to live clients;
2. generation options must reach planning, drafting, revision, research, and archive reuse;
3. `fix_export` and `skip_export` must retain their documented continuation semantics; and
4. `resume_failed_stage` must restart the stage that actually failed.

The change preserves the existing task API, event envelope, persisted workflow version, and legacy AgentCore fallback boundary. It does not add a new public endpoint or database migration.

## Design

### Terminal failures

`WorkflowFailure` continues to emit `recovery_available` with structured recovery metadata. The orchestrator then calls `fail_task` with terminal event emission enabled so every failed task also produces the existing canonical `error` event. `StageResultError` follows the same terminal contract. This keeps the frontend compatible with its existing `done`/`error` state machine while retaining richer recovery events for future UI use.

### Generation options

The workflow accepts a normalized options dictionary in addition to its explicit `preset` and `requirements` arguments. It stores those options in resume memory and forwards them to each Codex stage specification and prompt input. Backend research execution also receives the same options so `enable_extra_tools`, `with_questions`, `with_diagrams`, and `max_points` are not silently dropped.

Explicit `preset` and `requirements` arguments remain authoritative for backward compatibility. The merged options object uses those values after normalization.

### Export continuation modes

Continuation handling validates the persisted acceptance record against the current preset and Markdown before creating a child task.

- `fix_export`: if acceptance is current, republish the accepted Markdown and complete with refreshed `md_url` and `md_filename` values. It does not rerun research, drafting, or review.
- `skip_export`: if acceptance is current, complete from the accepted Markdown without attempting publication.
- If acceptance is missing or stale, both modes fail with a recoverable `accepted_content_required` error rather than silently running an unrelated stage.

The export-only behavior is handled by the orchestrator because media publication is already an orchestration responsibility and does not belong in the content-quality workflow.

### Failed-stage recovery

When a Codex stage raises `StageResultError`, the workflow records a structured `last_failure` containing the current stage, error code, and detail, then checkpoints before re-raising. `resume_failed_stage` uses that persisted stage. For legacy snapshots without `last_failure`, it prefers the nested workflow's current stage before applying the existing legacy stage mapping.

## Error handling

All terminal errors use the canonical task-runtime error event. Structured database error payloads retain `code`, `stage`, `detail` or `issues`, and `recoverable` fields. Export continuation validation errors are deterministic and do not invoke Codex or the legacy fallback.

## Testing

Tests are added before production changes and must demonstrate the current failures:

- frontend stream state becomes failed after a backend terminal error;
- all generation options cross the orchestrator/workflow/stage boundaries;
- `fix_export` republishes accepted Markdown and `skip_export` does not publish;
- stale or missing acceptance blocks both export modes; and
- a draft-stage `StageResultError` checkpoints `last_failure.stage=draft` and resumes at `draft`.

Verification includes focused backend and frontend tests, backend compilation, frontend production build, and `git diff --check`.
