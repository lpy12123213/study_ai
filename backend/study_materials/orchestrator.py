from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.core import AgentCore
from backend.agent.types import agent_event
from backend.core.logging_utils import get_logger
from backend.database.repositories.content.study_archives import (
    get_study_archive_by_fingerprint,
    upsert_study_archive,
)
from backend.database.repositories.system.tasks import get_task as db_get_task
from backend.database.repositories.system.tasks import list_task_events as db_list_task_events
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text
from backend.shared.tasks import RuntimeTask, task_runtime

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

    if t in {"aggregate_knowledge", "synthesize_sources", "detect_knowledge_type"}:
        return "aggregate"

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

    keep_keys = {"split_knowledge_points", "review_knowledge_points", "study_options"}

    drop_keys: set[str] = set()
    if stage == "search":
        drop_keys |= {
            "web_search_knowledge",
            "browse_web_pages",
            "wikipedia_search",
            "mediawiki_search",
            "github_search",
            "stackexchange_search",
            "search_questions_by_knowledge",
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
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
        }
    elif stage == "write":
        drop_keys |= {
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
            "latex_tex",
            "_latex_compile_round",
            "_latex_last_compile_error",
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

    out: Dict[str, Any] = {}
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


def _refresh_resume_meta(*, meta: Dict[str, Any]) -> None:
    """Refresh resumable metadata based on the latest working_memory snapshot (best-effort)."""

    wm = meta.get("resume_working_memory") if isinstance(meta, dict) else None
    wm = wm if isinstance(wm, dict) else {}

    state = _derive_resume_state(wm)
    if isinstance(state.get("last_success_step"), dict):
        meta["last_success_step"] = dict(state.get("last_success_step") or {})
    if isinstance(state.get("last_failed_step"), dict):
        meta["last_failed_step"] = dict(state.get("last_failed_step") or {})
    meta["last_success_stage"] = str(state.get("last_success_stage") or "").strip()
    meta["last_failed_stage"] = str(state.get("last_failed_stage") or "").strip()

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
                if kp:
                    out[kp] = dict(it)
            return out
        kp = str(blob.get("knowledge_point") or "").strip()
        return {kp: dict(blob)} if kp else {}

    web_map = _map_by_kp(wm.get("web_search_knowledge"))
    search_summary_by_kp: Dict[str, Any] = {}
    for kp, it in web_map.items():
        provider = str(it.get("provider") or "").strip()
        query = str(it.get("query") or it.get("base_query") or "").strip()
        results = it.get("results") if isinstance(it.get("results"), list) else []
        summarized: List[Dict[str, Any]] = []
        for r in [x for x in results if isinstance(x, dict)][:8]:
            url = str(r.get("url") or "").strip()
            if not url:
                continue
            summarized.append(
                {
                    "title": str(r.get("title") or "").strip(),
                    "url": url,
                    "snippet": _clip_text(str(r.get("snippet") or ""), max_chars=240),
                    "source_query": str(r.get("source_query") or r.get("sourceQuery") or "").strip(),
                }
            )
        search_summary_by_kp[kp] = {"provider": provider, "query": query, "results": summarized}
    meta["search_summary_by_kp"] = search_summary_by_kp

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
    meta["per_kp_state"] = per_kp_state


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
class StudyMaterialsTaskView:
    task_id: str
    query: str
    user_id: str
    subject: str = ""
    options: Dict[str, Any] = field(default_factory=dict)

    status: str = "running"
    error: Optional[str] = None
    created_at_s: float = 0.0
    updated_at_s: float = 0.0

    parent_task_id: Optional[str] = None
    resume_working_memory: Dict[str, Any] = field(default_factory=dict)
    iteration_offset: int = 0
    max_iterations: Optional[int] = None
    iterations_done: int = 0

    last_success_step: Optional[Dict[str, Any]] = None
    last_failed_step: Optional[Dict[str, Any]] = None
    last_success_stage: str = ""
    last_failed_stage: str = ""
    per_kp_state: Dict[str, Any] = field(default_factory=dict)
    search_summary_by_kp: Dict[str, Any] = field(default_factory=dict)

    first_seq: int = 1
    last_seq: int = 0


class StudyMaterialsTaskManager:
    def __init__(self, *, task_ttl_s: int = 60 * 60) -> None:
        self._task_ttl_s = max(60, int(task_ttl_s or (60 * 60)))

    def _snapshot_path(self, task_id: str) -> Path:
        tid = str(task_id or "").strip()
        return _TASK_SNAPSHOTS_DIR / f"{tid}.json"

    def _load_snapshot(self, task_id: str) -> Optional[dict]:
        try:
            path = self._snapshot_path(task_id)
            if not path.exists():
                return None
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw.strip() else {}
            return obj if isinstance(obj, dict) else None
        except Exception:
            logger.debug("study_materials_snapshot_load_failed", extra={"task_id": task_id}, exc_info=True)
            return None

    def _persist_snapshot(self, task: RuntimeTask, *, force: bool = False) -> None:
        meta = task.meta if isinstance(task.meta, dict) else {}
        now = _now_s()
        persisted_at_s = float(meta.get("_persisted_at_s") or 0.0)
        if not force and (now - persisted_at_s) < 0.8 and task.status == "running":
            return

        try:
            _TASK_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            path = self._snapshot_path(task.task_id)

            req = task.request if isinstance(task.request, dict) else {}
            wm = meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {}
            payload = json.dumps(
                {
                    "task_id": task.task_id,
                    "user_id": task.user_id,
                    "query": str(req.get("query") or "").strip(),
                    "subject": str(req.get("subject") or "").strip(),
                    "options": req.get("options") if isinstance(req.get("options"), dict) else {},
                    "parent_task_id": task.parent_task_id,
                    "created_at_s": float(task.created_at_s or 0.0),
                    "updated_at_s": float(task.updated_at_s or 0.0),
                    "resume_working_memory": wm,
                    "iteration_offset": int(meta.get("iteration_offset") or 0),
                    "max_iterations": meta.get("max_iterations"),
                    "iterations_done": int(meta.get("iterations_done") or 0),
                    "last_success_step": meta.get("last_success_step")
                    if isinstance(meta.get("last_success_step"), dict)
                    else None,
                    "last_failed_step": meta.get("last_failed_step") if isinstance(meta.get("last_failed_step"), dict) else None,
                    "last_success_stage": str(meta.get("last_success_stage") or "").strip(),
                    "last_failed_stage": str(meta.get("last_failed_stage") or "").strip(),
                    "per_kp_state": meta.get("per_kp_state") if isinstance(meta.get("per_kp_state"), dict) else {},
                    "search_summary_by_kp": meta.get("search_summary_by_kp")
                    if isinstance(meta.get("search_summary_by_kp"), dict)
                    else {},
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )

            tmp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    delete=False,
                    dir=str(_TASK_SNAPSHOTS_DIR),
                    prefix=f"{task.task_id}-",
                    suffix=".json.tmp",
                ) as f:
                    f.write(payload)
                    tmp_path = Path(f.name)
                if tmp_path is not None:
                    tmp_path.replace(path)
            finally:
                try:
                    if tmp_path is not None and tmp_path.exists():
                        tmp_path.unlink(missing_ok=True)
                except Exception:
                    logger.debug(
                        "study_materials_snapshot_tmp_cleanup_failed",
                        extra={"task_id": task.task_id, "tmp_path": str(tmp_path) if tmp_path is not None else ""},
                        exc_info=True,
                    )

            meta["_persisted_at_s"] = now
        except Exception:
            logger.warning(
                "study_materials_snapshot_persist_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id},
                exc_info=True,
            )

    def _cleanup_snapshots(self) -> int:
        try:
            if not _TASK_SNAPSHOTS_DIR.exists():
                return 0
            now = _now_s()
            deleted = 0
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
                        deleted += 1
                    except Exception:
                        logger.debug("study_materials_snapshot_delete_failed", extra={"path": str(path)}, exc_info=True)
            return deleted
        except Exception:
            logger.debug("study_materials_snapshot_cleanup_failed", exc_info=True)
            return 0

    async def restore_tasks_from_disk(self) -> None:
        # Back-compat entrypoint: we only keep resumable snapshots and delete expired ones.
        self._cleanup_snapshots()

    async def shutdown(self, *, reason: str = "server_shutdown") -> None:
        _ = reason

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
    ) -> RuntimeTask:
        q = str(query or "").strip()
        uid = str(user_id or "").strip() or "anonymous"
        subj = str(subject or "").strip()
        opts = options if isinstance(options, dict) else {}
        parent = str(parent_task_id or "").strip() or None

        try:
            iteration_offset_n = max(0, int(iteration_offset or 0))
        except Exception:
            iteration_offset_n = 0

        wm = resume_working_memory if isinstance(resume_working_memory, dict) else {}
        task_id = uuid.uuid4().hex

        meta: Dict[str, Any] = {
            "resume_working_memory": dict(wm),
            "iteration_offset": iteration_offset_n,
            "max_iterations": max_iterations,
            "iterations_done": 0,
        }
        if wm:
            _refresh_resume_meta(meta=meta)

        req = {
            "taskId": task_id,
            "query": q,
            "subject": subj,
            "options": dict(opts),
            "parentTaskId": parent,
        }

        starter_event = {
            "type": "task_started",
            "data": {
                "taskId": task_id,
                "status": "running",
                "query": q,
                "subject": subj,
                "options": dict(opts),
                "parentTaskId": parent,
            },
        }

        async def runner_factory(task: RuntimeTask) -> None:
            await self._run_task(task)

        task = await task_runtime.create_task(
            task_id=task_id,
            user_id=uid,
            task_type="study_materials",
            title=(q[:200] or "学习资料生成"),
            request=req,
            parent_task_id=parent,
            meta=meta,
            starter_event=starter_event,
            runner_factory=runner_factory,
        )
        self._persist_snapshot(task, force=True)
        return task

    async def continue_task(self, *, task_id: str, user_id: str, mode: str) -> RuntimeTask:
        tid = str(task_id or "").strip()
        uid = str(user_id or "").strip() or "anonymous"
        mode_norm = str(mode or "").strip().lower() or "improve"
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

        snap = self._load_snapshot(tid)
        if not snap or str(snap.get("user_id") or "").strip() != uid:
            raise ValueError("task_not_found")

        # "running" is determined by the DB task row (source of truth across restarts).
        try:
            db_task = await db_get_task(user_id=uid, task_id=tid, include_events=False)
        except Exception:
            db_task = None
        if isinstance(db_task, dict) and str(db_task.get("status") or "") == "running":
            raise ValueError("task_running")

        resume_wm = snap.get("resume_working_memory") if isinstance(snap.get("resume_working_memory"), dict) else {}
        if not resume_wm:
            raise ValueError("task_not_resumable")

        options = snap.get("options") if isinstance(snap.get("options"), dict) else {}
        options = dict(options)
        options["continue_mode"] = mode_norm

        preset = str(options.get("preset") or "standard").strip().lower() or "standard"
        if mode_norm == "deepen_research" and preset not in {"deep", "research"}:
            options["preset"] = "research"

        max_iters = 1

        if mode_norm in {"resume_failed_stage", "retry_search", "replan_from_failure"}:
            failed_stage = str(snap.get("last_failed_stage") or "").strip()
            if not failed_stage:
                derived = _derive_resume_state(resume_wm)
                failed_stage = str(derived.get("last_failed_stage") or "").strip()
            resume_wm = _prune_resume_working_memory(resume_wm, mode=mode_norm, last_failed_stage=failed_stage)

        try:
            iteration_offset_n = int(snap.get("iterations_done") or 0)
        except Exception:
            iteration_offset_n = 0

        return await self.create_task(
            query=str(snap.get("query") or "").strip(),
            user_id=uid,
            subject=str(snap.get("subject") or "").strip(),
            options=options,
            parent_task_id=tid,
            resume_working_memory=resume_wm,
            iteration_offset=max(0, iteration_offset_n),
            max_iterations=max_iters,
        )

    async def get_task(self, task_id: str, *, user_id: Optional[str] = None) -> Optional[StudyMaterialsTaskView]:
        tid = str(task_id or "").strip()
        if not tid:
            return None

        snap = self._load_snapshot(tid)
        if not snap:
            return None

        snap_user = str(snap.get("user_id") or "").strip()
        if user_id is not None and str(user_id or "").strip() != snap_user:
            return None

        runtime_task = await task_runtime.get_task(tid)
        status = str(runtime_task.status or "") if runtime_task else ""
        error = str(runtime_task.error or "") if runtime_task else ""
        first_seq = runtime_task.seq_offset + 1 if runtime_task else 1
        last_seq = int(runtime_task.last_seq or 0) if runtime_task else 0

        if not runtime_task:
            try:
                db_task = await db_get_task(user_id=snap_user, task_id=tid, include_events=False)
            except Exception:
                db_task = None
            if isinstance(db_task, dict):
                status = str(db_task.get("status") or "") or status
                try:
                    last_seq = max(last_seq, int(db_task.get("last_seq") or 0))
                except Exception:
                    pass
                err_obj = db_task.get("error") if isinstance(db_task.get("error"), dict) else {}
                if not error:
                    error = str(err_obj.get("message") or err_obj.get("error") or "").strip()

        resume_wm = snap.get("resume_working_memory") if isinstance(snap.get("resume_working_memory"), dict) else {}

        meta: Dict[str, Any] = {
            "resume_working_memory": resume_wm,
            "last_success_step": snap.get("last_success_step"),
            "last_failed_step": snap.get("last_failed_step"),
            "last_success_stage": snap.get("last_success_stage"),
            "last_failed_stage": snap.get("last_failed_stage"),
            "per_kp_state": snap.get("per_kp_state"),
            "search_summary_by_kp": snap.get("search_summary_by_kp"),
        }
        if resume_wm and (not str(meta.get("last_failed_stage") or "") or not isinstance(meta.get("search_summary_by_kp"), dict)):
            _refresh_resume_meta(meta=meta)

        return StudyMaterialsTaskView(
            task_id=tid,
            query=str(snap.get("query") or "").strip(),
            user_id=snap_user,
            subject=str(snap.get("subject") or "").strip(),
            options=dict(snap.get("options") or {}) if isinstance(snap.get("options"), dict) else {},
            status=status or "unknown",
            error=error or None,
            created_at_s=float(snap.get("created_at_s") or 0.0),
            updated_at_s=float(snap.get("updated_at_s") or 0.0),
            parent_task_id=str(snap.get("parent_task_id") or "").strip() or None,
            resume_working_memory=resume_wm,
            iteration_offset=int(snap.get("iteration_offset") or 0),
            max_iterations=snap.get("max_iterations"),
            iterations_done=int(snap.get("iterations_done") or 0),
            last_success_step=meta.get("last_success_step") if isinstance(meta.get("last_success_step"), dict) else None,
            last_failed_step=meta.get("last_failed_step") if isinstance(meta.get("last_failed_step"), dict) else None,
            last_success_stage=str(meta.get("last_success_stage") or "").strip(),
            last_failed_stage=str(meta.get("last_failed_stage") or "").strip(),
            per_kp_state=meta.get("per_kp_state") if isinstance(meta.get("per_kp_state"), dict) else {},
            search_summary_by_kp=meta.get("search_summary_by_kp") if isinstance(meta.get("search_summary_by_kp"), dict) else {},
            first_seq=int(first_seq or 1),
            last_seq=int(last_seq or 0),
        )

    async def stream(
        self,
        task_id: str,
        *,
        user_id: str,
        after_seq: int = 0,
        heartbeat_s: float = 4.0,
    ) -> AsyncIterator[dict]:
        tid = str(task_id or "").strip()
        uid = str(user_id or "").strip()
        if not tid or not uid:
            yield {"taskId": tid or "", "seq": int(after_seq or 0), "type": "error", "data": {"error": "missing_task_id"}}
            return

        runtime_task = await task_runtime.get_task(tid)
        if runtime_task and str(runtime_task.user_id or "") == uid:
            async for event in task_runtime.stream(tid, after_seq=after_seq, heartbeat_s=heartbeat_s):
                yield event
            return

        last_sent = max(0, int(after_seq or 0))
        last_ping_at = 0.0
        while True:
            task = await db_get_task(user_id=uid, task_id=tid, include_events=False)
            if not task:
                yield {"taskId": tid, "seq": last_sent, "type": "error", "data": {"error": "task_not_found"}}
                return

            events = await db_list_task_events(user_id=uid, task_id=tid, after_seq=last_sent, limit=500)
            for evt in events:
                seq = int(evt.get("seq") or 0)
                if seq <= last_sent:
                    continue
                last_sent = seq
                yield evt

            if str(task.get("status") or "") != "running":
                return

            now = _now_s()
            if now - last_ping_at >= max(1.0, float(heartbeat_s or 4.0)):
                last_ping_at = now
                yield {"taskId": tid, "seq": last_sent, "type": "ping", "data": {"status": "running", "last_seq": last_sent}}

            await asyncio.sleep(0.5)

    async def _run_task(self, task: RuntimeTask) -> None:
        meta = task.meta if isinstance(task.meta, dict) else {}
        req = task.request if isinstance(task.request, dict) else {}

        query = str(req.get("query") or "").strip()
        subject = str(req.get("subject") or "").strip()
        options = req.get("options") if isinstance(req.get("options"), dict) else {}
        parent_task_id = str(task.parent_task_id or "").strip() or None

        resume_wm = meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {}
        iteration_offset = int(meta.get("iteration_offset") or 0)
        max_iterations = meta.get("max_iterations")

        agent = AgentCore()

        def _capture_resume_snapshot(*, force: bool) -> None:
            try:
                ctx = getattr(agent, "last_context", None)
                wm = getattr(ctx, "working_memory", None) if ctx is not None else None
                if isinstance(wm, dict) and wm:
                    meta["resume_working_memory"] = dict(wm)
                    _refresh_resume_meta(meta=meta)
                    self._persist_snapshot(task, force=force)
            except Exception:
                logger.debug("study_materials_resume_snapshot_failed", extra={"task_id": task.task_id}, exc_info=True)

        async def _maybe_reuse_local_archive() -> bool:
            if parent_task_id or resume_wm:
                return False
            if not query or not subject:
                return False

            preset = str(options.get("preset") or "standard").strip().lower() or "standard"
            requirements = str(options.get("requirements") or "").strip()

            prefer_opt = (
                options.get("preferLocalArchive")
                if "preferLocalArchive" in options
                else options.get("prefer_local_archive")
                if "prefer_local_archive" in options
                else None
            )
            if prefer_opt is None:
                env_raw = os.getenv("STUDY_ARCHIVE_PREFER_LOCAL")
                prefer = preset in {"quick", "standard"} if not str(env_raw or "").strip() else _truthy(env_raw)
            else:
                prefer = bool(prefer_opt)
            if not prefer:
                return False

            try:
                archive = await get_study_archive_by_fingerprint(
                    user_id=task.user_id,
                    subject=subject,
                    topic=query,
                    requirements=requirements,
                )
            except Exception:
                archive = None
            if not isinstance(archive, dict):
                return False

            markdown = str(archive.get("markdown") or "").strip()
            if not markdown:
                return False

            sections = archive.get("sections") if isinstance(archive.get("sections"), list) else []
            exported = await _export_markdown_to_media(markdown=markdown, user_id=task.user_id)

            meta["resume_working_memory"] = {
                "study_options": {"preset": preset, "requirements": requirements},
                "assemble_study_archive": markdown,
                "markdown": markdown,
                "generate_study_material": {
                    "topic": query,
                    "subject": subject,
                    "preset": preset,
                    "requirements": requirements,
                    "sections": sections,
                },
                "md_url": exported.get("md_url"),
                "md_filename": exported.get("md_filename"),
            }
            meta["iterations_done"] = 1
            _refresh_resume_meta(meta=meta)
            self._persist_snapshot(task, force=True)

            await task_runtime.append_event(
                task,
                agent_event(
                    "status",
                    {
                        "content": (
                            "本地知识库命中：发现相同主题的历史归档，已直接复用"
                            "（如需重新联网检索，可设置 preferLocalArchive=false）。"
                        )
                    },
                ),
            )
            await task_runtime.append_event(
                task,
                agent_event(
                    "done",
                    {
                        "material": {
                            "topic": query,
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
            await task_runtime.complete_task(task, result={"reused_local_archive": True, **exported})
            return True

        try:
            if await _maybe_reuse_local_archive():
                return

            preferences: Dict[str, Any] = {}
            if subject:
                preferences["subject"] = subject

            async for evt in agent.run(
                query,
                user_id=task.user_id,
                preferences=preferences,
                options=options,
                resume_working_memory=resume_wm if resume_wm else None,
                iteration_offset=iteration_offset,
                max_iterations=max_iterations,
            ):
                if task.status != "running":
                    break

                await task_runtime.append_event(task, evt)

                kind = str(evt.get("event") or evt.get("type") or "")
                if kind in {"done", "error"}:
                    _capture_resume_snapshot(force=True)

                if kind == "done":
                    data = evt.get("data")
                    if isinstance(data, dict):
                        material = data.get("material")
                        if isinstance(material, dict):
                            try:
                                meta["iterations_done"] = int(material.get("iteration") or meta.get("iterations_done") or 0)
                            except Exception:
                                pass

                    try:
                        wm = meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {}
                        markdown = str(wm.get("assemble_study_archive") or wm.get("markdown") or "").strip()
                        material = wm.get("generate_study_material") if isinstance(wm.get("generate_study_material"), dict) else {}
                        sections = material.get("sections") if isinstance(material.get("sections"), list) else []
                        preset = str(options.get("preset") or "").strip() or str(material.get("preset") or "")
                        requirements = str(options.get("requirements") or "").strip() or str(material.get("requirements") or "")
                        topic = str(material.get("topic") or query or "").strip()
                        subj = str(material.get("subject") or subject or "").strip()
                        if markdown and topic and subj:
                            await upsert_study_archive(
                                user_id=task.user_id,
                                subject=subj,
                                topic=topic,
                                preset=preset,
                                requirements=requirements,
                                markdown=markdown,
                                sections=[x for x in sections if isinstance(x, dict)],
                            )
                    except Exception:
                        logger.debug("study_materials_archive_upsert_failed", extra={"task_id": task.task_id}, exc_info=True)

                    await task_runtime.complete_task(task, result=data if isinstance(data, dict) else {"result": data})
                    return

                if kind == "error":
                    data = evt.get("data")
                    msg = str(data.get("message") or data.get("error") or "").strip() if isinstance(data, dict) else ""
                    await task_runtime.fail_task(
                        task,
                        msg or "Generation failed",
                        error={"message": msg or "Generation failed"},
                        emit_event=False,
                    )
                    return

                _capture_resume_snapshot(force=False)
        except asyncio.CancelledError:
            if task.status in {"paused", "canceled", "cancelled"}:
                return
            await task_runtime.fail_task(task, "Task cancelled", error={"message": "Task cancelled"})
            raise
        except Exception as exc:  # pragma: no cover
            await task_runtime.fail_task(task, str(exc), error={"message": str(exc)})
        finally:
            _capture_resume_snapshot(force=True)
            if task.status == "running":
                await task_runtime.fail_task(
                    task,
                    "Task ended unexpectedly",
                    error={"message": "Task ended unexpectedly"},
                )
