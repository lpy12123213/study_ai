from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.core import AgentCore
from backend.agent.types import agent_event
from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_iso_z, utcnow_naive
from backend.database.models import get_study_archive_by_fingerprint, upsert_study_archive
from backend.database.repositories.tasks import (
    append_task_event as db_append_task_event,
)
from backend.database.repositories.tasks import (
    update_task_status as db_update_task_status,
)
from backend.database.repositories.tasks import (
    upsert_task as db_upsert_task,
)
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text

logger = get_logger(__name__)


def _now_s() -> float:
    return time.time()


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASK_SNAPSHOTS_DIR = (_REPO_ROOT / ".local" / "study_materials" / "tasks").resolve()


def _truthy(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _clip_text(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = str(text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def _infer_stage_from_tool(tool_name: str) -> str:
    """Map a tool name to a coarse stage label used for resumable/continue UX."""

    t = str(tool_name or "").strip()
    if not t:
        return ""

    # Retrieval/search stage
    if t in {
        "web_search_knowledge",
        "browse_web_pages",
        "wikipedia_search",
        "mediawiki_search",
        "github_search",
        "stackexchange_search",
        "search_questions_by_knowledge",
    }:
        return "search"

    # Aggregation/synthesis stage (still "pre-write")
    if t in {"aggregate_knowledge", "synthesize_sources", "detect_knowledge_type"}:
        return "aggregate"

    # Writing/review stage
    if t in {
        "generate_outline",
        "generate_study_material",
        "critique_draft",
        "refine_draft",
        "generate_diagrams",
        "assemble_study_archive",
        "review_content",
        "revise_markdown",
    }:
        return "write"

    # Export stage
    if t in {"export_study_markdown", "convert_markdown_to_latex", "refine_latex", "compile_latex_to_pdf"}:
        return "export"

    return ""


def _derive_resume_state(wm: Dict[str, Any]) -> Dict[str, Any]:
    """Derive best-effort resume metadata from a working_memory snapshot."""

    step_results = wm.get("step_results") if isinstance(wm, dict) else None
    step_results = step_results if isinstance(step_results, list) else []

    last_success_step: Dict[str, Any] = {}
    last_failed_step: Dict[str, Any] = {}
    last_success_stage = ""
    last_failed_stage = ""

    for it in step_results:
        if not isinstance(it, dict):
            continue
        tool = str(it.get("tool") or "").strip()
        if not tool:
            continue
        success = bool(it.get("success"))
        stage = _infer_stage_from_tool(tool)
        record = {
            "step_id": str(it.get("step_id") or "").strip(),
            "tool": tool,
            "success": success,
            "error": str(it.get("error") or "").strip() or None,
        }
        if success:
            last_success_step = record
            last_success_stage = stage or last_success_stage
        else:
            last_failed_step = record
            last_failed_stage = stage or last_failed_stage

    out: Dict[str, Any] = {}
    if last_success_step:
        out["last_success_step"] = last_success_step
    if last_failed_step:
        out["last_failed_step"] = last_failed_step
    if last_success_stage:
        out["last_success_stage"] = last_success_stage
    if last_failed_stage:
        out["last_failed_stage"] = last_failed_stage
    return out


def _prune_resume_working_memory(
    wm: Dict[str, Any],
    *,
    mode: str,
    last_failed_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a pruned working_memory snapshot for stage-based continuation modes."""

    mode_norm = str(mode or "").strip().lower()
    stage = str(last_failed_stage or "").strip().lower()
    if mode_norm == "retry_search":
        stage = "search"
    elif mode_norm == "resume_failed_stage" and not stage:
        stage = "write"

    # Always keep knowledge-point split & options; everything else can be recomputed.
    keep_keys = {"split_knowledge_points", "review_knowledge_points", "study_options"}

    drop_keys: set[str] = set()
    if stage == "search":
        drop_keys |= {
            # Retrieval
            "web_search_knowledge",
            "browse_web_pages",
            "wikipedia_search",
            "mediawiki_search",
            "github_search",
            "stackexchange_search",
            "search_questions_by_knowledge",
            # Aggregation/synthesis
            "aggregate_knowledge",
            "aggregated",
            "aggregate",
            "source_briefs",
            "source_facts",
            "knowledge_types",
            "outlines",
            # Draft/write/export artifacts
            "generate_outline",
            "generate_study_material",
            "study_material",
            "critique_draft",
            "refine_draft",
            "diagrams",
            "assemble_study_archive",
            "review_content",
            "revise_markdown",
            "markdown",
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
            # LaTeX state
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }
    elif stage == "aggregate":
        drop_keys |= {
            "aggregate_knowledge",
            "aggregated",
            "aggregate",
            "source_briefs",
            "source_facts",
            "knowledge_types",
            "outlines",
            "generate_outline",
            "generate_study_material",
            "study_material",
            "critique_draft",
            "refine_draft",
            "diagrams",
            "assemble_study_archive",
            "review_content",
            "revise_markdown",
            "markdown",
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
        }
    elif stage == "write":
        drop_keys |= {
            "outlines",
            "generate_outline",
            "generate_study_material",
            "study_material",
            "critique_draft",
            "refine_draft",
            "diagrams",
            "assemble_study_archive",
            "review_content",
            "revise_markdown",
            "markdown",
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
        }
    elif stage == "export":
        drop_keys |= {
            "md_url",
            "md_filename",
            "tex_url",
            "tex_filename",
            "pdf_url",
            "pdf_filename",
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }

    out = {}
    for k, v in (wm or {}).items():
        key = str(k or "").strip()
        if not key:
            continue
        if key in keep_keys:
            out[key] = v
            continue
        if key in drop_keys:
            continue
        out[key] = v
    return out


def _refresh_task_resume_meta(task: "StudyMaterialsTask") -> None:
    """Best-effort: refresh resume metadata based on the latest working_memory snapshot."""

    try:
        wm = dict(task.resume_working_memory or {}) if isinstance(task.resume_working_memory, dict) else {}
    except Exception:
        wm = {}

    state = _derive_resume_state(wm)
    try:
        task.last_success_step = state.get("last_success_step") if isinstance(state.get("last_success_step"), dict) else None
        task.last_failed_step = state.get("last_failed_step") if isinstance(state.get("last_failed_step"), dict) else None
        task.last_success_stage = str(state.get("last_success_stage") or "").strip()
        task.last_failed_stage = str(state.get("last_failed_stage") or "").strip()
    except Exception:
        # Never block snapshotting.
        pass

    def _extract_kps() -> List[str]:
        split_res = wm.get("split_knowledge_points")
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            kps = [str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()]
            if kps:
                return kps[:15]
        return []

    def _map_by_kp(blob: Any) -> Dict[str, Dict[str, Any]]:
        if not isinstance(blob, dict):
            return {}
        if isinstance(blob.get("items"), list):
            out: Dict[str, Dict[str, Any]] = {}
            for it in blob.get("items") or []:
                if not isinstance(it, dict):
                    continue
                kp = str(it.get("knowledge_point") or "").strip()
                if not kp:
                    continue
                out[kp] = dict(it)
            return out
        kp = str(blob.get("knowledge_point") or "").strip()
        return {kp: dict(blob)} if kp else {}

    # Compact search summary for UI buttons / debug.
    web_map = _map_by_kp(wm.get("web_search_knowledge"))
    search_summary_by_kp: Dict[str, Any] = {}
    for kp, it in web_map.items():
        provider = str(it.get("provider") or "").strip()
        query = str(it.get("query") or it.get("base_query") or "").strip()
        results = it.get("results") if isinstance(it.get("results"), list) else []
        summarized_results: List[Dict[str, Any]] = []
        for r in [x for x in results if isinstance(x, dict)][:8]:
            url = str(r.get("url") or "").strip()
            if not url:
                continue
            summarized_results.append(
                {
                    "title": str(r.get("title") or "").strip(),
                    "url": url,
                    "snippet": _clip_text(str(r.get("snippet") or ""), max_chars=240),
                    "source_query": str(r.get("source_query") or r.get("sourceQuery") or "").strip(),
                }
            )
        search_summary_by_kp[kp] = {
            "provider": provider,
            "query": query,
            "results": summarized_results,
        }
    task.search_summary_by_kp = search_summary_by_kp

    # Per-knowledge-point coarse status for stage-based continue.
    kps = _extract_kps() or list(search_summary_by_kp.keys())[:15]
    aggregated_map = _map_by_kp(wm.get("aggregated") or wm.get("aggregate_knowledge"))
    wiki_map = _map_by_kp(wm.get("wikipedia_search"))
    mw_map = _map_by_kp(wm.get("mediawiki_search"))

    material_blob = wm.get("generate_study_material") if isinstance(wm.get("generate_study_material"), dict) else None
    if material_blob is None:
        material_blob = wm.get("study_material") if isinstance(wm.get("study_material"), dict) else {}
    sections_blob = material_blob.get("sections") if isinstance(material_blob, dict) else None
    sections_list = [s for s in (sections_blob or []) if isinstance(s, dict)] if isinstance(sections_blob, list) else []
    sec_by_kp: Dict[str, Dict[str, Any]] = {}
    for sec in sections_list:
        kp = str(sec.get("knowledge_point") or "").strip()
        if kp and kp not in sec_by_kp:
            sec_by_kp[kp] = sec

    per_kp_state: Dict[str, Any] = {}
    for kp in kps:
        web = web_map.get(kp) or {}
        web_results = web.get("results") if isinstance(web.get("results"), list) else []
        web_n = len([x for x in web_results if isinstance(x, dict)])

        wiki = wiki_map.get(kp) or {}
        mw = mw_map.get(kp) or {}
        wiki_has = bool(str(wiki.get("summary") or wiki.get("content") or "").strip())
        mw_has = bool(str(mw.get("summary") or mw.get("content") or "").strip())

        search_ok = web_n > 0 or wiki_has or mw_has
        aggregate_ok = bool(aggregated_map.get(kp))
        sec = sec_by_kp.get(kp) or {}
        write_ok = bool(str(sec.get("explanation_markdown") or "").strip())

        per_kp_state[kp] = {
            "knowledge_point": kp,
            "search": search_ok,
            "aggregate": aggregate_ok,
            "write": write_ok,
            "web_results": web_n,
        }
    task.per_kp_state = per_kp_state


async def _export_markdown_to_media(*, markdown: str, user_id: str) -> Dict[str, Any]:
    published = await publish_generated_text(
        markdown,
        user_id=user_id,
        ext=".md",
        file_type="md",
        ttl_s=default_generated_media_ttl_s(),
    )
    return {
        "md_url": published.get("url") or "",
        "md_filename": published.get("filename") or "",
        "sha256": published.get("sha256") or "",
        "bytes": int(published.get("bytes") or 0),
        "expires_at": published.get("expires_at") or "",
    }


@dataclass
class StudyMaterialsTask:
    task_id: str
    query: str
    user_id: str
    subject: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    created_at_s: float = field(default_factory=_now_s)
    updated_at_s: float = field(default_factory=_now_s)
    status: str = "running"  # running|paused|completed|failed|canceled
    error: Optional[str] = None

    # Continuation support (for "completed -> continue iteration" flows).
    parent_task_id: Optional[str] = None
    resume_working_memory: Dict[str, Any] = field(default_factory=dict)
    iteration_offset: int = 0
    max_iterations: Optional[int] = None
    iterations_done: int = 0

    # Resume metadata for failure-stage continuation UX.
    last_success_step: Optional[Dict[str, Any]] = None
    last_failed_step: Optional[Dict[str, Any]] = None
    last_success_stage: str = ""
    last_failed_stage: str = ""
    per_kp_state: Dict[str, Any] = field(default_factory=dict)
    search_summary_by_kp: Dict[str, Any] = field(default_factory=dict)

    # seq starts at 1; `events[i-1]["seq"] == i`.
    events: List[Dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    seq_offset: int = 0  # number of dropped events; first stored seq is seq_offset + 1

    # Notified when events/status change.
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    # Runner task (created by manager).
    runner: Optional[asyncio.Task] = None
    persisted_at_s: float = 0.0
    needs_db_reconcile: bool = False


class StudyMaterialsTaskManager:
    """In-memory study-materials task manager with SSE replay support.

    Goals:
    - Allow browser refresh/reconnect without losing progress.
    - Keep the generation running even if the client disconnects.
    - Provide heartbeats for long-running tool calls (handled by stream()).
    """

    def __init__(
        self,
        *,
        max_tasks: int = 50,
        task_ttl_s: int = 60 * 60,
        max_events_per_task: int = 5000,
    ) -> None:
        self._tasks: Dict[str, StudyMaterialsTask] = {}
        self._lock = asyncio.Lock()
        self._max_tasks = max(1, int(max_tasks))
        self._task_ttl_s = max(60, int(task_ttl_s))
        self._max_events_per_task = max(100, int(max_events_per_task))
        self._restore_cleanup_count = 0
        self._restore_tasks_from_disk()

    def _snapshot_path(self, task_id: str) -> Path:
        tid = (task_id or "").strip()
        return _TASK_SNAPSHOTS_DIR / f"{tid}.json"

    def _delete_snapshot(self, task_id: str) -> None:
        try:
            path = self._snapshot_path(task_id)
            if path.exists():
                path.unlink(missing_ok=True)  # py3.8+ on Windows supports missing_ok
        except Exception:
            return

    def _persist_snapshot(self, task: StudyMaterialsTask, *, force: bool = False) -> None:
        if not isinstance(task, StudyMaterialsTask):
            return
        now = _now_s()
        if not force and (now - float(task.persisted_at_s or 0.0)) < 0.8 and task.status == "running":
            return

        try:
            _TASK_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            path = self._snapshot_path(task.task_id)
            tmp = path.with_suffix(".json.tmp")

            data = {
                "task_id": task.task_id,
                "query": task.query,
                "user_id": task.user_id,
                "subject": task.subject,
                "options": dict(task.options or {}),
                "created_at_s": float(task.created_at_s or 0.0),
                "updated_at_s": float(task.updated_at_s or 0.0),
                "status": task.status,
                "error": task.error,
                "parent_task_id": task.parent_task_id,
                "resume_working_memory": dict(task.resume_working_memory or {}),
                "iteration_offset": int(task.iteration_offset or 0),
                "max_iterations": task.max_iterations,
                "iterations_done": int(task.iterations_done or 0),
                "last_success_step": dict(task.last_success_step or {}) if isinstance(task.last_success_step, dict) else None,
                "last_failed_step": dict(task.last_failed_step or {}) if isinstance(task.last_failed_step, dict) else None,
                "last_success_stage": str(task.last_success_stage or ""),
                "last_failed_stage": str(task.last_failed_stage or ""),
                "per_kp_state": dict(task.per_kp_state or {}) if isinstance(task.per_kp_state, dict) else {},
                "search_summary_by_kp": dict(task.search_summary_by_kp or {})
                if isinstance(task.search_summary_by_kp, dict)
                else {},
                "events": list(task.events or [])[-self._max_events_per_task :],
                "last_seq": int(task.last_seq or 0),
                "seq_offset": int(task.seq_offset or 0),
            }
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
            task.persisted_at_s = now
        except Exception:
            return

    def _task_from_snapshot(self, obj: Dict[str, Any]) -> Optional[StudyMaterialsTask]:
        try:
            tid = str(obj.get("task_id") or "").strip()
            query = str(obj.get("query") or "").strip()
            user_id = str(obj.get("user_id") or "").strip() or "anonymous"
            if not tid or not query:
                return None

            events_raw = obj.get("events") if isinstance(obj.get("events"), list) else []
            events_raw = [e for e in events_raw if isinstance(e, dict)]
            events = [self._normalize_event_payload(task_id=tid, event=e) for e in events_raw]
            last_seq = int(obj.get("last_seq") or 0) if str(obj.get("last_seq") or "").strip() else 0
            if last_seq <= 0 and events:
                try:
                    last_seq = int(events[-1].get("seq") or 0)
                except Exception:
                    last_seq = 0

            task = StudyMaterialsTask(
                task_id=tid,
                query=query,
                user_id=user_id,
                subject=str(obj.get("subject") or "").strip(),
                options=dict(obj.get("options") or {}) if isinstance(obj.get("options"), dict) else {},
                created_at_s=float(obj.get("created_at_s") or 0.0) or _now_s(),
                updated_at_s=float(obj.get("updated_at_s") or 0.0) or _now_s(),
                status=str(obj.get("status") or "completed").strip() or "completed",
                error=str(obj.get("error") or "").strip() or None,
                parent_task_id=str(obj.get("parent_task_id") or "").strip() or None,
                resume_working_memory=dict(obj.get("resume_working_memory") or {})
                if isinstance(obj.get("resume_working_memory"), dict)
                else {},
                iteration_offset=int(obj.get("iteration_offset") or 0),
                max_iterations=obj.get("max_iterations"),
                iterations_done=int(obj.get("iterations_done") or 0),
                events=events,
                last_seq=max(0, last_seq),
                seq_offset=int(obj.get("seq_offset") or 0),
            )

            task.last_success_step = (
                dict(obj.get("last_success_step") or {}) if isinstance(obj.get("last_success_step"), dict) else None
            )
            task.last_failed_step = (
                dict(obj.get("last_failed_step") or {}) if isinstance(obj.get("last_failed_step"), dict) else None
            )
            task.last_success_stage = str(obj.get("last_success_stage") or "").strip()
            task.last_failed_stage = str(obj.get("last_failed_stage") or "").strip()
            task.per_kp_state = dict(obj.get("per_kp_state") or {}) if isinstance(obj.get("per_kp_state"), dict) else {}
            task.search_summary_by_kp = (
                dict(obj.get("search_summary_by_kp") or {}) if isinstance(obj.get("search_summary_by_kp"), dict) else {}
            )
            if task.resume_working_memory and (not task.last_failed_stage or not task.search_summary_by_kp):
                _refresh_task_resume_meta(task)

            # A "running" task cannot continue after restart; mark as failed with a clear reason.
            if task.status == "running":
                task.status = "failed"
                task.error = task.error or "server_restarted"
                task.updated_at_s = _now_s()
                task.needs_db_reconcile = True
                task.last_seq += 1
                task.events.append(
                    {
                        "taskId": task.task_id,
                        "seq": task.last_seq,
                        "type": "warning",
                        "data": {
                            "taskId": task.task_id,
                            "message": "Server restarted; this task can no longer stream. You can start a new task or continue if resumable.",
                        },
                    }
                )
            return task
        except Exception:
            return None

    async def shutdown(self, *, reason: str = "server_shutdown") -> None:
        """Best-effort graceful shutdown: cancel running tasks and persist terminal state."""

        msg = str(reason or "server_shutdown").strip() or "server_shutdown"

        async with self._lock:
            running = [t for t in self._tasks.values() if isinstance(t, StudyMaterialsTask) and t.status == "running"]

        for task in running:
            # Avoid the runner's CancelledError handler overwriting our requested state:
            # set a terminal-ish state before cancelling the task.
            task.status = "canceled"
            task.error = msg
            task.updated_at_s = _now_s()

            try:
                await self._append_event(
                    task,
                    agent_event(
                        "warning",
                        {
                            "taskId": task.task_id,
                            "message": "Task canceled due to server shutdown.",
                            "reason": msg,
                        },
                    ),
                )
            except Exception:
                logger.debug("study_material_task_shutdown_event_failed", extra={"task_id": task.task_id}, exc_info=True)

            try:
                await db_update_task_status(
                    user_id=task.user_id,
                    task_id=task.task_id,
                    status="canceled",
                    error={"message": msg},
                    ended_at=utcnow_naive(),
                )
            except Exception:
                logger.debug(
                    "study_material_task_shutdown_status_write_failed",
                    extra={"task_id": task.task_id, "user_id": task.user_id},
                    exc_info=True,
                )

            try:
                self._persist_snapshot(task, force=True)
            except Exception:
                logger.debug(
                    "study_material_task_shutdown_snapshot_failed",
                    extra={"task_id": task.task_id, "user_id": task.user_id},
                    exc_info=True,
                )

            if task.runner and not task.runner.done():
                task.runner.cancel()

            async with task.cond:
                task.cond.notify_all()

    def _restore_tasks_from_disk(self) -> None:
        try:
            if not _TASK_SNAPSHOTS_DIR.exists():
                return

            now = _now_s()
            cleanup_count = 0
            snaps: List[Dict[str, Any]] = []
            for path in list(_TASK_SNAPSHOTS_DIR.glob("*.json"))[:2000]:
                try:
                    raw = path.read_text(encoding="utf-8")
                    obj = json.loads(raw) if raw.strip() else {}
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                updated = float(obj.get("updated_at_s") or obj.get("created_at_s") or 0.0)
                if updated and (now - updated) > float(self._task_ttl_s):
                    try:
                        path.unlink(missing_ok=True)
                        cleanup_count += 1
                    except Exception:
                        logger.debug(
                            "study_material_task_snapshot_cleanup_failed",
                            extra={"path": str(path)},
                            exc_info=True,
                        )
                    continue
                snaps.append(obj)

            snaps.sort(key=lambda o: float(o.get("updated_at_s") or o.get("created_at_s") or 0.0), reverse=True)
            snaps = snaps[: self._max_tasks]

            for obj in snaps:
                task = self._task_from_snapshot(obj)
                if not task:
                    continue
                self._tasks[task.task_id] = task
                # Best-effort: persist again if we normalized state (e.g. running -> failed).
                if task.status != str(obj.get("status") or ""):
                    self._persist_snapshot(task, force=True)
            self._restore_cleanup_count = cleanup_count
        except Exception:
            return

    async def create_task(
        self,
        *,
        query: str,
        user_id: str,
        subject: str = "",
        options: Optional[Dict[str, Any]] = None,
        parent_task_id: Optional[str] = None,
        resume_working_memory: Optional[Dict[str, Any]] = None,
        iteration_offset: int = 0,
        max_iterations: Optional[int] = None,
    ) -> StudyMaterialsTask:
        query = (query or "").strip()
        user_id = (user_id or "").strip() or "anonymous"
        subject = (subject or "").strip()
        options = options if isinstance(options, dict) else {}

        parent_task_id = (parent_task_id or "").strip() or None
        resume_working_memory = resume_working_memory if isinstance(resume_working_memory, dict) else {}
        try:
            iteration_offset = int(iteration_offset or 0)
        except Exception:
            iteration_offset = 0
        iteration_offset = max(0, iteration_offset)

        task_id = uuid.uuid4().hex
        task = StudyMaterialsTask(
            task_id=task_id,
            query=query,
            user_id=user_id,
            subject=subject,
            options=dict(options),
            parent_task_id=parent_task_id,
            resume_working_memory=dict(resume_working_memory),
            iteration_offset=iteration_offset,
            max_iterations=max_iterations,
        )

        async with self._lock:
            self._gc_locked()
            if len(self._tasks) >= self._max_tasks:
                self._drop_oldest_locked()
            self._tasks[task_id] = task

        try:
            await db_upsert_task(
                user_id=task.user_id,
                task_id=task.task_id,
                task_type="study_materials",
                title=str(task.query or "").strip()[:200],
                status="running",
                progress=0.0,
                request={
                    "query": task.query,
                    "subject": task.subject,
                    "options": dict(task.options or {}),
                    "parentTaskId": task.parent_task_id,
                },
                started_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "study_material_task_upsert_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id},
            )

        await self._append_event(
            task,
            {
                "type": "task_started",
                "data": {
                    "taskId": task_id,
                    "status": "running",
                    "query": query,
                    "subject": subject,
                    "options": options,
                    "parentTaskId": parent_task_id,
                },
            },
        )

        task.runner = asyncio.create_task(self._run_task(task))
        return task

    async def get_task(self, task_id: str) -> Optional[StudyMaterialsTask]:
        tid = (task_id or "").strip()
        if not tid:
            return None
        async with self._lock:
            self._gc_locked()
            return self._tasks.get(tid)

    async def pause_task(self, *, task_id: str, user_id: str) -> bool:
        tid = (task_id or "").strip()
        uid = (user_id or "").strip()
        if not tid or not uid:
            return False

        task = await self.get_task(tid)
        if not task or task.user_id != uid:
            return False
        if task.status != "running":
            return True

        task.status = "paused"
        task.updated_at_s = _now_s()
        await self._append_event(
            task,
            agent_event(
                "step",
                {
                    "step": {
                        "id": "task_paused",
                        "title": "任务已暂停",
                        "status": "paused",
                        "startTime": utcnow_iso_z(),
                        "toolName": "study_materials",
                    }
                },
            ),
        )

        try:
            await db_update_task_status(user_id=uid, task_id=tid, status="paused", error={})
        except Exception:
            logger.exception("study_material_task_pause_write_failed", extra={"task_id": tid, "user_id": uid})

        if task.runner and not task.runner.done():
            task.runner.cancel()

        async with task.cond:
            task.cond.notify_all()

        return True

    async def resume_task(self, *, task_id: str, user_id: str) -> bool:
        tid = (task_id or "").strip()
        uid = (user_id or "").strip()
        if not tid or not uid:
            return False

        task = await self.get_task(tid)
        if not task or task.user_id != uid:
            return False
        if task.status == "running":
            return True
        if task.status != "paused":
            return False

        task.status = "running"
        task.error = None
        task.updated_at_s = _now_s()

        await self._append_event(
            task,
            agent_event(
                "step",
                {
                    "step": {
                        "id": "task_resumed",
                        "title": "任务继续执行",
                        "status": "running",
                        "startTime": utcnow_iso_z(),
                        "toolName": "study_materials",
                    }
                },
            ),
        )

        try:
            await db_update_task_status(user_id=uid, task_id=tid, status="running", error={})
        except Exception:
            logger.exception("study_material_task_resume_write_failed", extra={"task_id": tid, "user_id": uid})

        if task.runner and not task.runner.done():
            return True

        task.runner = asyncio.create_task(self._run_task(task))
        return True

    async def cancel_task(self, *, task_id: str, user_id: str) -> bool:
        tid = (task_id or "").strip()
        uid = (user_id or "").strip()
        if not tid or not uid:
            return False

        task = await self.get_task(tid)
        if not task or task.user_id != uid:
            return False

        if task.status in {"completed", "failed", "canceled", "cancelled"}:
            return True

        task.status = "canceled"
        task.error = "Task cancelled"
        task.updated_at_s = _now_s()

        await self._append_event(
            task,
            agent_event(
                "step",
                {
                    "step": {
                        "id": "task_canceled",
                        "title": "任务已取消",
                        "status": "failed",
                        "startTime": utcnow_iso_z(),
                        "toolName": "study_materials",
                        "error": "Task cancelled",
                    }
                },
            ),
        )

        try:
            await db_update_task_status(
                user_id=uid,
                task_id=tid,
                status="canceled",
                error={"message": "Task cancelled"},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception("study_material_task_cancel_write_failed", extra={"task_id": tid, "user_id": uid})

        if task.runner and not task.runner.done():
            task.runner.cancel()

        async with task.cond:
            task.cond.notify_all()

        return True

    async def stream(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        heartbeat_s: float = 4.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        tid = (task_id or "").strip()
        if not tid:
            yield {"taskId": "", "seq": 0, "type": "error", "data": {"error": "Missing taskId"}}
            return

        task = await self.get_task(tid)
        if not task:
            yield {"taskId": tid, "seq": 0, "type": "error", "data": {"error": f"Task not found: {tid}"}}
            return

        last_sent_seq = max(0, int(after_seq or 0))
        while True:
            # Flush backlog first.
            if task.last_seq > last_sent_seq:
                first_seq = task.seq_offset + 1
                if last_sent_seq < first_seq - 1:
                    # The client is too far behind (events were dropped); emit a soft error so
                    # the UI can restart the generation if needed.
                    yield {
                        "taskId": tid,
                        "seq": int(task.last_seq or 0),
                        "type": "warning",
                        "data": {
                            "message": "Event backlog truncated; please restart if output looks incomplete.",
                            "first_seq": first_seq,
                            "last_seq": task.last_seq,
                        },
                    }
                    last_sent_seq = first_seq - 1

                start_idx = max(0, last_sent_seq - task.seq_offset)
                batch = task.events[start_idx:]
                for evt in batch:
                    seq = int(evt.get("seq") or 0)
                    if seq <= last_sent_seq:
                        continue
                    last_sent_seq = seq
                    yield evt
                continue

            if task.status != "running":
                # Completed/failed and no more events to replay.
                return

            # Wait for new events, but keep the connection alive with pings.
            async with task.cond:
                try:
                    await asyncio.wait_for(
                        task.cond.wait_for(lambda: task.last_seq > last_sent_seq or task.status != "running"),
                        timeout=max(0.5, float(heartbeat_s or 4.0)),
                    )
                except asyncio.TimeoutError:
                    yield {
                        "taskId": tid,
                        "seq": int(task.last_seq or 0),
                        "type": "ping",
                        "data": {
                            "status": task.status,
                            "last_seq": task.last_seq,
                            "updated_at_s": task.updated_at_s,
                        },
                    }

    async def continue_task(
        self,
        *,
        task_id: str,
        user_id: str,
        mode: str,
    ) -> StudyMaterialsTask:
        """Create a new task that continues a completed/failed task with a bounded iteration budget."""

        tid = (task_id or "").strip()
        uid = (user_id or "").strip() or "anonymous"
        mode_norm = (mode or "").strip().lower() or "improve"
        if mode_norm not in {
            "improve",
            "deepen_research",
            "fix_export",
            "skip_export",
            "resume_failed_stage",
            "retry_search",
            "replan_from_failure",
        }:
            mode_norm = "improve"

        parent = await self.get_task(tid)
        if not parent or parent.user_id != uid:
            raise ValueError("task_not_found")

        if parent.status == "running":
            raise ValueError("task_running")

        if not parent.resume_working_memory:
            raise ValueError("task_not_resumable")

        options = dict(parent.options or {})
        options["continue_mode"] = mode_norm

        # `deepen_research` implies a stronger preset (unless already deep/research).
        preset = str(options.get("preset") or "").strip().lower()
        if mode_norm == "deepen_research" and preset not in {"deep", "research"}:
            options["preset"] = "research"

        # Continuations should be snappy: one Plan-Act-Reflect loop per click by default.
        max_iters = 1

        resume_wm = parent.resume_working_memory
        if mode_norm in {"resume_failed_stage", "retry_search", "replan_from_failure"}:
            failed_stage = str(parent.last_failed_stage or "").strip()
            if not failed_stage:
                derived = _derive_resume_state(resume_wm)
                failed_stage = str(derived.get("last_failed_stage") or "").strip()
            resume_wm = _prune_resume_working_memory(resume_wm, mode=mode_norm, last_failed_stage=failed_stage)

        return await self.create_task(
            query=parent.query,
            user_id=uid,
            subject=parent.subject,
            options=options,
            parent_task_id=parent.task_id,
            resume_working_memory=resume_wm,
            iteration_offset=int(parent.iterations_done or 0),
            max_iterations=max_iters,
        )

    def _normalize_event_payload(self, *, task_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize SSE events to a shared envelope: {taskId, seq, type, data}."""

        raw = dict(event or {})
        raw.pop("seq", None)
        raw.pop("task_id", None)
        raw.pop("taskId", None)

        event_type = str(raw.get("type") or raw.get("event") or "").strip() or "unknown"
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}

        if event_type == "task_started":
            tid = str(data.get("taskId") or data.get("task_id") or task_id).strip() or task_id
            data = dict(data)
            data["taskId"] = tid
            data.pop("task_id", None)
            if "parent_task_id" in data and "parentTaskId" not in data:
                data["parentTaskId"] = data.get("parent_task_id")
            data.pop("parent_task_id", None)

        if event_type == "error":
            msg = str((data or {}).get("error") or (data or {}).get("message") or "").strip()
            if msg and isinstance(data, dict) and "error" not in data:
                data = dict(data)
                data["error"] = msg

        return {"taskId": task_id, "type": event_type, "data": data}

    async def _append_event(self, task: StudyMaterialsTask, event: Dict[str, Any]) -> None:
        payload = self._normalize_event_payload(task_id=task.task_id, event=event)

        seq = 0
        async with task.cond:
            task.last_seq += 1
            seq = int(task.last_seq or 0)
            payload["seq"] = task.last_seq
            task.events.append(payload)
            task.updated_at_s = _now_s()

            # Prevent unbounded memory if something goes wrong.
            if len(task.events) > self._max_events_per_task:
                drop_n = len(task.events) - self._max_events_per_task
                if drop_n > 0:
                    task.events = task.events[drop_n:]
                    task.seq_offset += drop_n

            task.cond.notify_all()

        try:
            # Persist to DB (best-effort). `payload["data"]` is the SSE `data` object.
            event_type = str(payload.get("type") or "").strip() or "unknown"
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            progress = None
            if event_type == "progress":
                try:
                    progress = float((data or {}).get("progress") or 0.0)
                except Exception:
                    progress = None
            await db_append_task_event(
                user_id=task.user_id,
                task_id=task.task_id,
                event_type=event_type,
                payload=data if isinstance(data, dict) else {},
                seq=seq if seq > 0 else None,
                progress=progress,
            )
        except Exception:
            logger.exception(
                "study_material_task_event_write_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id, "event_type": event_type},
            )
        try:
            force = str(payload.get("type") or "") in {"task_started", "done", "result", "error"}
            self._persist_snapshot(task, force=force or task.status != "running")
        except Exception:
            logger.exception(
                "study_material_task_snapshot_persist_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id},
            )

    async def _fail_task(self, task: StudyMaterialsTask, message: str) -> None:
        task.status = "failed"
        task.error = message
        await self._append_event(task, {"type": "error", "data": {"error": message}})
        try:
            await db_update_task_status(
                user_id=task.user_id,
                task_id=task.task_id,
                status="failed",
                error={"message": message},
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "study_material_task_fail_write_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id},
            )
        async with task.cond:
            task.cond.notify_all()

    async def _complete_task(self, task: StudyMaterialsTask) -> None:
        task.status = "completed"
        task.updated_at_s = _now_s()
        self._persist_snapshot(task, force=True)
        try:
            await db_update_task_status(
                user_id=task.user_id,
                task_id=task.task_id,
                status="completed",
                progress=100.0,
                ended_at=utcnow_naive(),
            )
        except Exception:
            logger.exception(
                "study_material_task_complete_write_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id},
            )
        async with task.cond:
            task.cond.notify_all()

    async def _run_task(self, task: StudyMaterialsTask) -> None:
        async def _maybe_reuse_local_archive() -> bool:
            # Only reuse for fresh "generate" tasks (not continuation).
            if task.parent_task_id or task.resume_working_memory:
                return False

            topic = (task.query or "").strip()
            subject = (task.subject or "").strip()
            if not topic or not subject:
                return False

            opts = dict(task.options or {})
            preset = str(opts.get("preset") or "standard").strip().lower() or "standard"
            requirements = str(opts.get("requirements") or "").strip()

            prefer_opt = (
                opts.get("preferLocalArchive")
                if "preferLocalArchive" in opts
                else opts.get("prefer_local_archive")
                if "prefer_local_archive" in opts
                else None
            )
            if prefer_opt is None:
                env_raw = os.getenv("STUDY_ARCHIVE_PREFER_LOCAL")
                if env_raw is None or not str(env_raw).strip():
                    prefer = preset in {"quick", "standard"}
                else:
                    prefer = _truthy(env_raw)
            else:
                prefer = bool(prefer_opt)

            if not prefer:
                return False

            try:
                archive = await get_study_archive_by_fingerprint(
                    user_id=task.user_id,
                    subject=subject,
                    topic=topic,
                    requirements=requirements,
                )
            except Exception:
                archive = None

            if not isinstance(archive, dict):
                return False

            markdown = str(archive.get("markdown") or "").strip()
            sections = archive.get("sections") if isinstance(archive.get("sections"), list) else []
            if not markdown:
                return False

            exported = await _export_markdown_to_media(markdown=markdown, user_id=task.user_id)

            task.resume_working_memory = {
                "study_options": {"preset": preset, "requirements": requirements},
                "assemble_study_archive": markdown,
                "markdown": markdown,
                "generate_study_material": {
                    "topic": topic,
                    "subject": subject,
                    "preset": preset,
                    "requirements": requirements,
                    "sections": sections,
                },
                "md_url": exported.get("md_url"),
                "md_filename": exported.get("md_filename"),
            }
            task.iterations_done = 1

            await self._append_event(
                task,
                agent_event(
                    "status",
                    {
                        "content": "本地知识库命中：发现相同主题的历史归档，已直接复用（如需重新联网检索，可在请求中设置 preferLocalArchive=false）。"
                    },
                ),
            )
            await self._append_event(
                task,
                agent_event(
                    "done",
                    {
                        "material": {
                            "topic": topic,
                            "archive_path": "",
                            "md_url": exported.get("md_url") or "",
                            "md_filename": exported.get("md_filename") or "",
                            "tex_url": "",
                            "tex_filename": "",
                            "pdf_url": "",
                            "pdf_filename": "",
                            "iteration": 1,
                            "passed": True,
                            "issues": [],
                            "error": None,
                        },
                        "per_kp_report": [],
                        "timing_report": {"reused_local_archive": True},
                    },
                ),
            )

            await self._complete_task(task)
            return True

        agent = AgentCore()

        def _capture_resume_snapshot() -> None:
            try:
                ctx = getattr(agent, "last_context", None)
                wm = getattr(ctx, "working_memory", None) if ctx is not None else None
                if isinstance(wm, dict) and wm:
                    # Shallow copy; values are expected to be JSON-ish.
                    task.resume_working_memory = dict(wm)
                    _refresh_task_resume_meta(task)
            except Exception:
                logger.debug(
                    "study_material_task_resume_snapshot_failed",
                    extra={"task_id": task.task_id, "user_id": task.user_id},
                    exc_info=True,
                )

        try:
            if await _maybe_reuse_local_archive():
                return

            preferences = {}
            if (task.subject or "").strip():
                preferences["subject"] = str(task.subject or "").strip()

            async for evt in agent.run(
                task.query,
                user_id=task.user_id,
                preferences=preferences,
                options=task.options,
                resume_working_memory=task.resume_working_memory if task.resume_working_memory else None,
                iteration_offset=int(task.iteration_offset or 0),
                max_iterations=task.max_iterations,
            ):
                # If the task already failed (e.g. due to server shutdown), stop.
                if task.status != "running":
                    break
                await self._append_event(task, evt)

                kind = str(evt.get("event") or "")
                if kind == "done":
                    data = evt.get("data")
                    if isinstance(data, dict):
                        material = data.get("material")
                        if isinstance(material, dict):
                            try:
                                task.iterations_done = int(material.get("iteration") or task.iterations_done or 0)
                            except Exception:
                                logger.debug(
                                    "study_material_task_iteration_parse_failed",
                                    extra={"task_id": task.task_id, "user_id": task.user_id},
                                    exc_info=True,
                                )
                    _capture_resume_snapshot()
                    try:
                        wm = dict(task.resume_working_memory or {})
                        markdown = str(wm.get("assemble_study_archive") or wm.get("markdown") or "").strip()
                        material = (
                            wm.get("generate_study_material")
                            if isinstance(wm.get("generate_study_material"), dict)
                            else {}
                        )
                        sections = material.get("sections") if isinstance(material.get("sections"), list) else []
                        preset = str((task.options or {}).get("preset") or "").strip() or str(
                            material.get("preset") or ""
                        )
                        requirements = str((task.options or {}).get("requirements") or "").strip() or str(
                            material.get("requirements") or ""
                        )
                        topic = str(material.get("topic") or task.query or "").strip()
                        subject = str(material.get("subject") or task.subject or "").strip()
                        if markdown and topic and subject:
                            await upsert_study_archive(
                                user_id=task.user_id,
                                subject=subject,
                                topic=topic,
                                preset=preset,
                                requirements=requirements,
                                markdown=markdown,
                                sections=[x for x in sections if isinstance(x, dict)],
                            )
                    except Exception:
                        logger.exception(
                            "study_material_archive_upsert_failed",
                            extra={"task_id": task.task_id, "user_id": task.user_id},
                        )
                    await self._complete_task(task)
                elif kind == "error":
                    msg = ""
                    data = evt.get("data")
                    if isinstance(data, dict):
                        msg = str(data.get("message") or "").strip()
                    _capture_resume_snapshot()
                    task.status = "failed"
                    task.error = msg or "Generation failed"
                    self._persist_snapshot(task, force=True)
                    async with task.cond:
                        task.cond.notify_all()
        except asyncio.CancelledError:
            # TaskCenter operations set `task.status` first, then cancel the runner.
            # In that case, do not overwrite the requested terminal state.
            if task.status in {"paused", "canceled", "cancelled"}:
                async with task.cond:
                    task.cond.notify_all()
                raise

            await self._fail_task(task, "Task cancelled")
            raise
        except Exception as exc:  # pragma: no cover
            await self._fail_task(task, str(exc))
        finally:
            # Capture a best-effort continuation snapshot for "continue iteration" calls.
            _capture_resume_snapshot()
            if task.status == "running":
                # If we exited without a terminal event, mark as failed so clients stop waiting forever.
                await self._fail_task(task, "Task ended unexpectedly")

    def _gc_locked(self) -> None:
        now = _now_s()
        expired: List[str] = []
        for tid, task in self._tasks.items():
            age_s = now - float(task.updated_at_s or task.created_at_s or now)
            if age_s > self._task_ttl_s:
                expired.append(tid)

        for tid in expired:
            task = self._tasks.pop(tid, None)
            self._delete_snapshot(tid)
            if task and task.runner and not task.runner.done():
                task.runner.cancel()

    def _drop_oldest_locked(self) -> None:
        if not self._tasks:
            return
        oldest = min(self._tasks.values(), key=lambda t: float(t.updated_at_s or t.created_at_s or 0.0))
        tid = oldest.task_id
        task = self._tasks.pop(tid, None)
        self._delete_snapshot(tid)
        if task and task.runner and not task.runner.done():
            task.runner.cancel()
