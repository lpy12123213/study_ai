from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from backend.agent.core import AgentCore
from backend.agent.types import agent_event
from backend.core.logging_utils import get_logger
from backend.database.repositories.content.study_archives import (
    get_study_archive_by_fingerprint,
    upsert_study_archive,
)
from backend.database.repositories.system.tasks import get_task as db_get_task
from backend.database.repositories.system.tasks import list_task_events as db_list_task_events
from backend.generation.agentic.codex_runtime import legacy_agent_fallback_enabled
from backend.generation.agentic.study_materials import build_study_materials_agent_spec
from backend.generation.study_materials.author.figures import FigureForge
from backend.generation.study_materials.author.pipeline import AuthorPipelineContext, run_author_pipeline
from backend.generation.study_materials.author.research_tools import ResearchToolbox
from backend.generation.study_materials.codex_stages import StageResultError
from backend.generation.study_materials.coverage import split_sections_by_kp
from backend.generation.study_materials.quality_gate import (
    WORKFLOW_VERSION,
    acceptance_record_is_current,
)
from backend.generation.study_materials.resume import (
    _derive_resume_state,
    _prune_resume_working_memory,
    _refresh_resume_meta,
    _set_workflow_resume_stage,
    _truthy,
)
from backend.generation.study_materials.resume import (
    _infer_stage_from_tool as _infer_stage_from_tool,
)
from backend.generation.study_materials.workflow import WorkflowFailure, run_study_materials_workflow
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text
from backend.shared.tasks import RuntimeTask, task_runtime

logger = get_logger(__name__)


_CODEX_RUNTIME_NAMES = {"codex", "codex_runtime", "codexruntime", "claude", "claude_code", "claudecode"}


def _study_materials_codex_enabled() -> bool:
    """仅当显式设置 ``STUDY_MATERIALS_AGENT_RUNTIME`` 为 codex 系取值时，
    才启用 Codex staged workflow（plan/draft/revise 由 Codex CLI 执行）。
    """

    raw = str(os.getenv("STUDY_MATERIALS_AGENT_RUNTIME") or "").strip().lower().replace("-", "_")
    return raw in _CODEX_RUNTIME_NAMES


_AUTHOR_RUNTIME_NAMES = {"author"}
_LEGACY_RUNTIME_NAMES = {"legacy"}


def _study_materials_author_enabled() -> bool:
    """作者流水线（author/pipeline.py）是默认 runtime。

    ``STUDY_MATERIALS_AGENT_RUNTIME`` 未设置（或取值为 author / 未识别值）时启用；
    显式设为 legacy 或 codex 系取值时分别回退到 AgentCore / Codex staged 路径。
    """

    raw = str(os.getenv("STUDY_MATERIALS_AGENT_RUNTIME") or "").strip().lower().replace("-", "_")
    if not raw or raw in _AUTHOR_RUNTIME_NAMES:
        return True
    return raw not in _CODEX_RUNTIME_NAMES and raw not in _LEGACY_RUNTIME_NAMES


def _now_s() -> float:
    return time.time()


def _iso_to_epoch(value: Any) -> float:
    """Best-effort ISO-8601/epoch 秒转换；无法解析时返回 0.0。"""

    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return parsed.timestamp()


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASK_SNAPSHOTS_DIR = (_REPO_ROOT / ".local" / "study_materials" / "tasks").resolve()

_STEP_RESULTS_CAP = 300
_CONTINUE_MODES = {
    "improve",
    "deepen_research",
    "fix_export",
    "skip_export",
    "resume_failed_stage",
    "retry_search",
    "replan_from_failure",
}


def _archive_max_age_s() -> float:
    """归档复用的新鲜度预算（秒）。默认 14 天；0 表示不做时间过期。"""

    raw = str(os.getenv("STUDY_MATERIALS_ARCHIVE_MAX_AGE_S") or "").strip()
    if not raw:
        return 1209600.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 1209600.0


def _stream_compact_threshold() -> int:
    """SSE 追赶压缩阈值：落后事件数超过该值时折叠瞬态/快照类事件。0 关闭。"""

    raw = str(os.getenv("STUDY_MATERIALS_STREAM_COMPACT_THRESHOLD") or "").strip()
    if not raw:
        return 800
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 800


def study_materials_trace_ttl_s() -> float:
    """全量 trace 事件的保留时长（秒）。默认 0 表示不清理。

    清理器尚未实现；该 helper 仅集中读取开关，供后续清理任务复用。
    """

    raw = str(os.getenv("STUDY_MATERIALS_TRACE_TTL_S") or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


# 追赶阶段只保留各自最新一条的事件类型：
# thinking/status 是每秒数条的瞬态文本；text_delta 是完整文档快照（可达几十 KB）；
# quality_report/progress 只有最新值有意义。全量回放数千条会让重连极慢。
_CATCHUP_LATEST_ONLY_TYPES = frozenset(
    {"thinking", "thinking_delta", "reasoning_delta", "status", "text_delta", "quality_report", "progress"}
)

# author 流水线的结构化 trace 事件是「完整 trace 永不丢失」的载体：
# 即使未来被误加入 _CATCHUP_LATEST_ONLY_TYPES，追赶压缩也不得折叠它们。
_NEVER_COMPACT_EVENT_TYPES = frozenset({"note_write", "todo_update", "figure_trace", "section_fill"})


def _compact_catchup_events(events: list) -> tuple:
    """折叠追赶事件流：瞬态/快照类只留最新一条，状态演进类（tool/subagent/stage/done 等）全量保留。"""

    latest_only_types = _CATCHUP_LATEST_ONLY_TYPES - _NEVER_COMPACT_EVENT_TYPES
    latest_idx: Dict[str, int] = {}
    for idx, evt in enumerate(events):
        etype = str(evt.get("type") or "")
        if etype in latest_only_types:
            latest_idx[etype] = idx
    keep = set(latest_idx.values())
    compacted = [
        evt
        for idx, evt in enumerate(events)
        if idx in keep or str(evt.get("type") or "") not in latest_only_types
    ]
    return compacted, len(events) - len(compacted)


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


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _author_blueprint_summary(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    """done 载荷里的蓝图摘要：完整蓝图（10k+）在任务快照 notes/blueprint.md 与 todos.json。"""
    sections = [
        {"id": str(item.get("id") or ""), "title": str(item.get("title") or "")}
        for item in (blueprint.get("sections") or [])
        if isinstance(item, dict)
    ]
    figures = blueprint.get("figures")
    return {"sections": sections, "figures": len(figures) if isinstance(figures, list) else 0}


def _step_result_key(item: Dict[str, Any]) -> str:
    """B1: step_results 去重的稳定内容键——优先非空 step_id，否则用规范化 JSON 的 sha1。"""

    step_id = str(item.get("step_id") or "").strip()
    if step_id:
        return f"id:{step_id}"
    try:
        blob = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        blob = str(item)
    return "sha1:" + hashlib.sha1(blob.encode("utf-8", errors="ignore")).hexdigest()


def _resume_wm_from_result_payload(
    data: Dict[str, Any],
    *,
    query: str,
    subject: str,
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """Best-effort resume_working_memory from a persisted final result payload.

    B3 冷续作：DB 任务行的 ``result`` 是唯一事实来源。优先直接取结果里持久化的
    ``resume_working_memory``（codex 完成路径会写入）；否则从 material/markdown
    重建一个最小快照，保证 improve/fix_export 等续作仍可工作。
    """

    result = _dict(data.get("result"))
    for source in (data, result):
        wm = source.get("resume_working_memory")
        if isinstance(wm, dict) and wm:
            return dict(wm)

    material = _dict(data.get("material")) or _dict(result.get("material"))
    markdown = ""
    for source in (material, result, data):
        markdown = str(source.get("markdown") or source.get("assemble_study_archive") or "").strip()
        if markdown:
            break
    if not markdown:
        return {}

    preset = str(options.get("preset") or material.get("preset") or "standard").strip().lower() or "standard"
    requirements = str(options.get("requirements") or material.get("requirements") or "").strip()
    sections = material.get("sections") if isinstance(material.get("sections"), list) else []
    wm: Dict[str, Any] = {
        "study_options": {"preset": preset, "requirements": requirements},
        "assemble_study_archive": markdown,
        "markdown": markdown,
        "generate_study_material": {
            "topic": str(material.get("topic") or query or "").strip(),
            "subject": str(material.get("subject") or subject or "").strip(),
            "preset": preset,
            "requirements": requirements,
            "sections": [x for x in sections if isinstance(x, dict)],
        },
    }
    step_results = next(
        (source.get("step_results") for source in (data, result) if isinstance(source.get("step_results"), list)),
        None,
    )
    if step_results:
        wm["step_results"] = [x for x in step_results if isinstance(x, dict)]
    for key in ("md_url", "md_filename", "tex_url", "tex_filename", "pdf_url", "pdf_filename"):
        value = str(material.get(key) or result.get(key) or data.get(key) or "").strip()
        if value:
            wm[key] = value
    workflow_state = _dict(data.get("workflow")) or _dict(result.get("workflow"))
    if workflow_state:
        if not str(workflow_state.get("markdown") or "").strip() and markdown:
            # 瘦身后的 done 载荷不再重复携带 workflow.markdown；正文以 material 为准回填，
            # 保证 improve / fix_export 等冷续作的成稿判定不失真。
            workflow_state = {**workflow_state, "markdown": markdown}
        wm["study_materials_workflow"] = workflow_state
    return wm


def _merge_resume_working_memory(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge a final ``done``/``error`` resume snapshot into the streamed one.

    The streamed resume_working_memory (built tool-by-tool during execution) often
    carries metadata the final payload lacks: ``md_url``/``tex_url`` exports,
    ``step_results`` history, intermediate tool outputs. Replacing the whole dict
    on ``done`` would discard those and break ``fix_export``/``improve``
    continuations. We therefore prefer incoming values for the canonical content
    fields (``markdown`` / ``assemble_study_archive`` / ``generate_study_material``)
    while preserving any streamed metadata not present in the final payload.
    """

    if not isinstance(existing, dict) or not existing:
        return dict(incoming) if isinstance(incoming, dict) else {}
    if not isinstance(incoming, dict) or not incoming:
        return dict(existing)

    merged: Dict[str, Any] = dict(existing)
    for key, value in incoming.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        if key == "step_results" and isinstance(value, list):
            prior = merged.get("step_results") if isinstance(merged.get("step_results"), list) else []
            # B1: 用稳定内容键去重（prior 与 incoming 双向），重复键原地更新并保持顺序。
            ordered: Dict[str, Dict[str, Any]] = {}
            for item in [*prior, *value]:
                if not isinstance(item, dict):
                    continue
                ordered[_step_result_key(item)] = item
            records = list(ordered.values())
            dropped = max(0, len(records) - _STEP_RESULTS_CAP)
            if dropped:
                records = records[-_STEP_RESULTS_CAP:]
            merged["step_results"] = records
            if dropped:
                merged["_step_results_dropped"] = dropped
            continue
        if key == "generate_study_material" and isinstance(value, dict):
            prior = merged.get("generate_study_material") if isinstance(merged.get("generate_study_material"), dict) else {}
            merged["generate_study_material"] = {**prior, **value}
            continue
        merged[key] = value
    return merged


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
    # B6: 用户可见迭代（父链深度）与内部修订周期分开记账；iterations_done 保留为
    # user_iteration 的向后兼容别名。
    user_iteration: int = 0
    revision_cycles: int = 0
    iterations_done: int = 0

    last_success_step: Optional[Dict[str, Any]] = None
    last_failed_step: Optional[Dict[str, Any]] = None
    last_success_stage: str = ""
    last_failed_stage: str = ""
    per_kp_state: Dict[str, Any] = field(default_factory=dict)
    search_summary_by_kp: Dict[str, Any] = field(default_factory=dict)

    first_seq: int = 1
    last_seq: int = 0


@dataclass
class _TaskRunContext:
    """B2: _run_task 单次执行的共享上下文，代替散落在闭包里的局部变量。"""

    task: RuntimeTask
    meta: Dict[str, Any]
    query: str
    subject: str
    options: Dict[str, Any]
    parent_task_id: Optional[str]
    resume_wm: Dict[str, Any]
    iteration_offset: int
    max_iterations: Optional[int]
    agent: Optional[AgentCore] = None


class StudyMaterialsTaskManager:
    def __init__(self, *, task_ttl_s: int = 60 * 60) -> None:
        self._task_ttl_s = max(60, int(task_ttl_s or (60 * 60)))

    def _snapshot_path(self, task_id: str) -> Path:
        tid = str(task_id or "").strip()
        return _TASK_SNAPSHOTS_DIR / f"{tid}.json"

    def _record_persistence_warning(
        self,
        task: Optional[RuntimeTask],
        *,
        target: str,
        error: BaseException,
        meta: Optional[Dict[str, Any]] = None,
        task_id: str = "",
    ) -> None:
        """B4: 持久化失败不再静默——调用方负责带 exc_info 记日志；这里写 meta.warnings，并尽力广播 warning 事件。"""

        message = str(error or "").strip() or type(error).__name__
        if isinstance(meta, dict):
            warnings = meta.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append({"target": target, "error": message})
        if task is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return
        try:
            loop.create_task(
                task_runtime.append_event(
                    task,
                    agent_event("persistence_warning", {"target": target, "error": message}),
                )
            )
        except Exception:
            logger.warning(
                "study_materials_persistence_warning_event_failed",
                extra={"task_id": getattr(task, "task_id", ""), "target": target},
                exc_info=True,
            )

    def _load_snapshot(self, task_id: str) -> Optional[dict]:
        try:
            path = self._snapshot_path(task_id)
            if not path.exists():
                return None
            raw = path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw.strip() else {}
            return obj if isinstance(obj, dict) else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            # 此处尚无 task/meta 上下文（调用方随后会走 DB 兜底），只能先留日志。
            logger.warning("study_materials_snapshot_load_failed", extra={"task_id": task_id}, exc_info=True)
            self._record_persistence_warning(None, target="snapshot_load", error=exc, task_id=task_id)
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
                    "user_iteration": int(meta.get("user_iteration") or 0),
                    "revision_cycles": int(meta.get("revision_cycles") or 0),
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
                except OSError:
                    logger.warning(
                        "study_materials_snapshot_tmp_cleanup_failed",
                        extra={"task_id": task.task_id, "tmp_path": str(tmp_path) if tmp_path is not None else ""},
                        exc_info=True,
                    )

            meta["_persisted_at_s"] = now
        except Exception as exc:
            logger.warning(
                "study_materials_snapshot_persist_failed",
                extra={"task_id": getattr(task, "task_id", "")},
                exc_info=True,
            )
            self._record_persistence_warning(task, target="snapshot_persist", error=exc, meta=meta)

    def _cleanup_snapshots(self) -> int:
        try:
            if not _TASK_SNAPSHOTS_DIR.exists():
                return 0
            now = _now_s()
            deleted = 0
            for path in _TASK_SNAPSHOTS_DIR.glob("*.json"):
                try:
                    raw = path.read_text(encoding="utf-8")
                    obj = json.loads(raw) if raw.strip() else {}
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                updated = float(obj.get("updated_at_s") or obj.get("created_at_s") or 0.0)
                if updated and (now - updated) > float(self._task_ttl_s):
                    try:
                        path.unlink(missing_ok=True)
                        deleted += 1
                    except OSError:
                        logger.warning("study_materials_snapshot_delete_failed", extra={"path": str(path)}, exc_info=True)
            return deleted
        except OSError:
            logger.warning("study_materials_snapshot_cleanup_failed", exc_info=True)
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
        except (TypeError, ValueError):
            iteration_offset_n = 0

        wm = resume_working_memory if isinstance(resume_working_memory, dict) else {}
        task_id = uuid.uuid4().hex

        meta: Dict[str, Any] = {
            "resume_working_memory": dict(wm),
            "iteration_offset": iteration_offset_n,
            "max_iterations": max_iterations,
            # B6: user_iteration 是父链深度（用户可见迭代数）；iterations_done 为其别名。
            "user_iteration": iteration_offset_n,
            "revision_cycles": 0,
            "iterations_done": iteration_offset_n,
        }
        try:
            meta["agent_run_spec"] = build_study_materials_agent_spec(
                query=q,
                subject=subj,
                options=opts,
                resume_state={
                    "resume_working_memory": dict(wm),
                    "iteration_offset": iteration_offset_n,
                    "max_iterations": max_iterations,
                    "parent_task_id": parent,
                },
            ).to_dict()
        except Exception:
            logger.warning("study_materials_agent_spec_build_failed", extra={"task_id": task_id}, exc_info=True)
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
                "native_agentic": True,
                "agent_run_spec": meta.get("agent_run_spec") if isinstance(meta.get("agent_run_spec"), dict) else {},
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
        mode_raw = str(mode or "").strip().lower()
        if not mode_raw:
            mode_norm = "improve"
        elif mode_raw not in _CONTINUE_MODES:
            # B7: 未知续作模式必须显式报错，而不是静默改写成 improve。
            raise ValueError("invalid_continue_mode")
        else:
            mode_norm = mode_raw

        snap = self._load_snapshot(tid)
        if snap and str(snap.get("user_id") or "").strip() != uid:
            raise ValueError("task_not_found")

        # "running" 由 DB 任务行判定（跨重启的事实来源）；已完成/失败/取消的任务均可续作。
        db_task: Optional[Dict[str, Any]] = None
        try:
            db_task = await db_get_task(user_id=uid, task_id=tid, include_events=False)
        except Exception:
            logger.warning("study_materials_resume_db_task_lookup_failed", extra={"task_id": tid, "user_id": uid}, exc_info=True)
            db_task = None
        if isinstance(db_task, dict) and str(db_task.get("status") or "") == "running":
            raise ValueError("task_running")

        # B3: 快照只是缓存——缺失时从 DB 行/事件/归档重建续作上下文。
        if snap:
            source: Optional[Dict[str, Any]] = self._continue_source_from_snapshot(snap)
        else:
            source = await self._continue_source_from_db(tid, uid=uid, db_task=db_task)
        if source is None:
            # DB 行也不存在/无可重建内容时才是诚实的 404。
            raise ValueError("task_not_found")

        resume_wm = source.get("resume_working_memory") if isinstance(source.get("resume_working_memory"), dict) else {}
        if not resume_wm:
            raise ValueError("task_not_resumable")

        options = source.get("options") if isinstance(source.get("options"), dict) else {}
        options = dict(options)
        options["continue_mode"] = mode_norm

        preset = str(options.get("preset") or "standard").strip().lower() or "standard"
        if mode_norm == "deepen_research" and preset not in {"deep", "research"}:
            # B8: 研究广度按 research profile，但既有内容的验收仍沿用原 preset。
            options["acceptance_preset"] = preset
            options["preset"] = "research"

        max_iters = 1

        failed_stage = str(source.get("last_failed_stage") or "").strip()
        if mode_norm in {"resume_failed_stage", "retry_search", "replan_from_failure"}:
            if not failed_stage:
                derived = _derive_resume_state(resume_wm)
                failed_stage = str(derived.get("last_failed_stage") or "").strip()
            resume_wm = _prune_resume_working_memory(resume_wm, mode=mode_norm, last_failed_stage=failed_stage)
        resume_wm = _set_workflow_resume_stage(
            resume_wm,
            mode=mode_norm,
            last_failed_stage=failed_stage,
        )

        return await self.create_task(
            query=str(source.get("query") or "").strip(),
            user_id=uid,
            subject=str(source.get("subject") or "").strip(),
            options=options,
            parent_task_id=tid,
            resume_working_memory=resume_wm,
            iteration_offset=max(0, int(source.get("iteration_offset") or 0)),
            max_iterations=max_iters,
        )

    def _continue_source_from_snapshot(self, snap: Dict[str, Any]) -> Dict[str, Any]:
        # B6: 续作偏移优先取 user_iteration（父链深度）；旧快照回退 iterations_done。
        try:
            iteration_offset_n = int(snap.get("user_iteration"))
        except (TypeError, ValueError):
            try:
                iteration_offset_n = int(snap.get("iterations_done") or 0)
            except (TypeError, ValueError):
                iteration_offset_n = 0
        return {
            "query": str(snap.get("query") or "").strip(),
            "subject": str(snap.get("subject") or "").strip(),
            "options": dict(snap.get("options") or {}) if isinstance(snap.get("options"), dict) else {},
            "resume_working_memory": dict(snap.get("resume_working_memory") or {})
            if isinstance(snap.get("resume_working_memory"), dict)
            else {},
            "last_failed_stage": str(snap.get("last_failed_stage") or "").strip(),
            "iteration_offset": max(0, iteration_offset_n),
        }

    async def _continue_source_from_db(
        self,
        tid: str,
        *,
        uid: str,
        db_task: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """B3: 无磁盘快照时，从 DB 任务行重建续作上下文（事件溯源冷续作）。"""

        if not isinstance(db_task, dict):
            return None
        req = db_task.get("request") if isinstance(db_task.get("request"), dict) else {}
        query = str(req.get("query") or "").strip()
        subject = str(req.get("subject") or "").strip()
        options = dict(req.get("options") or {}) if isinstance(req.get("options"), dict) else {}
        result = db_task.get("result") if isinstance(db_task.get("result"), dict) else {}

        resume_wm = _resume_wm_from_result_payload(result, query=query, subject=subject, options=options)
        if not resume_wm:
            resume_wm = await self._archive_resume_working_memory(
                uid=uid,
                query=query,
                subject=subject,
                options=options,
            )
        if not resume_wm and str(db_task.get("status") or "") == "failed":
            resume_wm = await self._events_resume_working_memory(uid=uid, task_id=tid)
        if not resume_wm:
            return None

        derived = _derive_resume_state(resume_wm)
        return {
            "query": query,
            "subject": subject,
            "options": options,
            "resume_working_memory": resume_wm,
            "last_failed_stage": str(derived.get("last_failed_stage") or "").strip(),
            # 冷续作无法可靠还原父链深度，从 0 起算（诚实优于伪造）。
            "iteration_offset": 0,
        }

    async def _archive_resume_working_memory(
        self,
        *,
        uid: str,
        query: str,
        subject: str,
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        """B3: 已入档的成稿 → 逆变换 _upsert_archive_from_resume_state 还原最小 wm。"""

        if not query or not subject:
            return {}
        requirements = str(options.get("requirements") or "").strip()
        try:
            archive = await get_study_archive_by_fingerprint(
                user_id=uid,
                subject=subject,
                topic=query,
                requirements=requirements,
            )
        except Exception:
            logger.warning(
                "study_materials_resume_archive_lookup_failed",
                extra={"user_id": uid, "subject": subject, "topic": query},
                exc_info=True,
            )
            return {}
        if not isinstance(archive, dict):
            return {}
        markdown = str(archive.get("markdown") or "").strip()
        if not markdown:
            return {}
        preset = str(options.get("preset") or archive.get("preset") or "standard").strip().lower() or "standard"
        sections = [x for x in (archive.get("sections") or []) if isinstance(x, dict)]
        workflow_state = self._workflow_state_from_archive(
            archive,
            preset=preset,
            query=query,
            subject=subject,
            archive_current=acceptance_record_is_current(
                archive=archive,
                preset=preset,
                markdown=markdown,
                options=options,
                max_age_s=_archive_max_age_s(),
            ),
        )
        return {
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
            "study_materials_workflow": workflow_state,
        }

    async def _events_resume_working_memory(self, *, uid: str, task_id: str) -> Dict[str, Any]:
        """B3: 失败任务无结果载荷时，重放事件流找回最后的阶段上下文。"""

        try:
            events = await db_list_task_events(user_id=uid, task_id=task_id, after_seq=0, limit=500)
        except Exception:
            logger.warning(
                "study_materials_resume_events_lookup_failed",
                extra={"task_id": task_id, "user_id": uid},
                exc_info=True,
            )
            return {}
        stage = ""
        last_successful = ""
        failure: Dict[str, Any] = {}
        for evt in events:
            etype = str(evt.get("type") or "").strip()
            data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
            if etype == "workflow_stage":
                stage = str(data.get("stage") or "").strip() or stage
                last_successful = str(data.get("last_successful_stage") or "").strip() or last_successful
            elif etype == "recovery_available":
                failure = {
                    key: data.get(key)
                    for key in ("code", "stage", "detail", "recoverable")
                    if data.get(key) is not None
                }
                stage = str(data.get("stage") or "").strip() or stage
            elif etype == "error" and not failure:
                message = str(data.get("message") or data.get("error") or "").strip()
                if message:
                    failure = {"code": message, "stage": stage, "recoverable": True}
        if not stage and not failure:
            return {}
        workflow_state = {
            "version": WORKFLOW_VERSION,
            "stage": stage or "plan",
            "last_successful_stage": last_successful,
            "preset": "standard",
            "plan": {},
            "research": {},
            "markdown": "",
            "coverage_map": {},
            "review": {},
            "quality_report": {},
            "acceptance": {},
            "revision_attempts": 0,
            "last_failure": failure,
        }
        return {"study_materials_workflow": workflow_state}

    async def get_task(self, task_id: str, *, user_id: Optional[str] = None) -> Optional[StudyMaterialsTaskView]:
        tid = str(task_id or "").strip()
        if not tid:
            return None

        snap = self._load_snapshot(tid)
        if not snap:
            # B3: 快照只是缓存——DB 任务行才是事实来源；缓存缺失时从 DB 构建状态视图。
            return await self._get_task_view_from_db(tid, user_id=user_id)

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
                logger.warning(
                    "study_materials_task_db_lookup_failed",
                    extra={"task_id": tid, "user_id": snap_user},
                    exc_info=True,
                )
                db_task = None
            if isinstance(db_task, dict):
                status = str(db_task.get("status") or "") or status
                try:
                    last_seq = max(last_seq, int(db_task.get("last_seq") or 0))
                except (TypeError, ValueError):
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
            user_iteration=int(snap.get("user_iteration") or snap.get("iterations_done") or 0),
            revision_cycles=int(snap.get("revision_cycles") or 0),
            iterations_done=int(snap.get("user_iteration") or snap.get("iterations_done") or 0),
            last_success_step=meta.get("last_success_step") if isinstance(meta.get("last_success_step"), dict) else None,
            last_failed_step=meta.get("last_failed_step") if isinstance(meta.get("last_failed_step"), dict) else None,
            last_success_stage=str(meta.get("last_success_stage") or "").strip(),
            last_failed_stage=str(meta.get("last_failed_stage") or "").strip(),
            per_kp_state=meta.get("per_kp_state") if isinstance(meta.get("per_kp_state"), dict) else {},
            search_summary_by_kp=meta.get("search_summary_by_kp") if isinstance(meta.get("search_summary_by_kp"), dict) else {},
            first_seq=int(first_seq or 1),
            last_seq=int(last_seq or 0),
        )

    async def _get_task_view_from_db(self, tid: str, *, user_id: Optional[str]) -> Optional[StudyMaterialsTaskView]:
        """B3: 无磁盘快照时，从 DB 任务行构建状态视图（归属校验保持不变）。"""

        uid = str(user_id or "").strip()
        if not uid:
            # 无 user_id 无法做归属校验，宁可 404 也不能越权返回。
            return None
        try:
            db_task = await db_get_task(user_id=uid, task_id=tid, include_events=False)
        except Exception:
            logger.warning(
                "study_materials_task_db_lookup_failed",
                extra={"task_id": tid, "user_id": uid},
                exc_info=True,
            )
            return None
        if not isinstance(db_task, dict):
            return None

        req = db_task.get("request") if isinstance(db_task.get("request"), dict) else {}
        result = db_task.get("result") if isinstance(db_task.get("result"), dict) else {}
        err_obj = db_task.get("error") if isinstance(db_task.get("error"), dict) else {}
        query = str(req.get("query") or "").strip()
        subject = str(req.get("subject") or "").strip()
        options = dict(req.get("options") or {}) if isinstance(req.get("options"), dict) else {}

        # 无快照且无结果载荷时 resumable=False（API 层据 resume_working_memory 判定）。
        resume_wm = _resume_wm_from_result_payload(result, query=query, subject=subject, options=options)

        meta: Dict[str, Any] = {"resume_working_memory": resume_wm}
        if resume_wm:
            _refresh_resume_meta(meta=meta)

        try:
            last_seq = int(db_task.get("last_seq") or 0)
        except (TypeError, ValueError):
            last_seq = 0

        return StudyMaterialsTaskView(
            task_id=tid,
            query=query,
            user_id=uid,
            subject=subject,
            options=options,
            status=str(db_task.get("status") or "") or "unknown",
            error=str(err_obj.get("message") or err_obj.get("error") or "").strip() or None,
            created_at_s=_iso_to_epoch(db_task.get("created_at")),
            updated_at_s=_iso_to_epoch(db_task.get("updated_at")),
            parent_task_id=str(db_task.get("parent_task_id") or "").strip() or None,
            resume_working_memory=resume_wm,
            last_success_step=meta.get("last_success_step") if isinstance(meta.get("last_success_step"), dict) else None,
            last_failed_step=meta.get("last_failed_step") if isinstance(meta.get("last_failed_step"), dict) else None,
            last_success_stage=str(meta.get("last_success_stage") or "").strip(),
            last_failed_stage=str(meta.get("last_failed_stage") or "").strip(),
            per_kp_state=meta.get("per_kp_state") if isinstance(meta.get("per_kp_state"), dict) else {},
            search_summary_by_kp=meta.get("search_summary_by_kp") if isinstance(meta.get("search_summary_by_kp"), dict) else {},
            first_seq=1,
            last_seq=last_seq,
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

        last_sent = max(0, int(after_seq or 0))
        last_ping_at = 0.0
        compact_threshold = _stream_compact_threshold()
        compact_pending = compact_threshold > 0
        while True:
            task = await db_get_task(user_id=uid, task_id=tid, include_events=False)
            if not task:
                runtime_task = await task_runtime.get_task(tid)
                if runtime_task and str(runtime_task.user_id or "") == uid:
                    async for event in task_runtime.stream(tid, after_seq=last_sent, heartbeat_s=heartbeat_s):
                        yield event
                    return
                yield {"taskId": tid, "seq": last_sent, "type": "error", "data": {"error": "task_not_found"}}
                return

            # 追赶压缩：落后过多时一次性拉取并折叠瞬态/快照事件，避免全量回放数千条导致重连极慢。
            if compact_pending:
                compact_pending = False
                task_last_seq = int(task.get("last_seq") or 0)
                if task_last_seq - last_sent > compact_threshold:
                    buffered: list = []
                    cursor = last_sent
                    while True:
                        page = await db_list_task_events(user_id=uid, task_id=tid, after_seq=cursor, limit=500)
                        if not page:
                            break
                        buffered.extend(page)
                        cursor = int(page[-1].get("seq") or cursor)
                        if len(page) < 500:
                            break
                    kept, skipped = _compact_catchup_events(buffered)
                    if skipped > 0:
                        yield {"taskId": tid, "seq": last_sent, "type": "catch_up", "data": {"skipped": skipped}}
                    for evt in kept:
                        seq = int(evt.get("seq") or 0)
                        if seq <= last_sent:
                            continue
                        last_sent = seq
                        yield evt
                    if str(task.get("status") or "") != "running":
                        return

            events = await db_list_task_events(user_id=uid, task_id=tid, after_seq=last_sent, limit=500)
            for evt in events:
                seq = int(evt.get("seq") or 0)
                if seq <= last_sent:
                    continue
                last_sent = seq
                yield evt

            if len(events) >= 500:
                continue

            if str(task.get("status") or "") != "running":
                return

            now = _now_s()
            if now - last_ping_at >= max(1.0, float(heartbeat_s or 4.0)):
                last_ping_at = now
                yield {"taskId": tid, "seq": last_sent, "type": "ping", "data": {"status": "running", "last_seq": last_sent}}

            await asyncio.sleep(0.5)

    async def get_events_after(
        self,
        task_id: str,
        *,
        user_id: str,
        after_seq: int = 0,
        limit: int = 500,
    ) -> Optional[Dict[str, Any]]:
        """全量 trace 分页读取：按 seq 过滤，不做任何压缩（压缩只发生在实时 SSE 追赶通道）。

        返回 ``{"events": [...], "next_after_seq": int, "has_more": bool}``；
        任务不存在或不属于该用户时返回 None（API 层映射 404）。
        """

        tid = str(task_id or "").strip()
        uid = str(user_id or "").strip()
        if not tid or not uid:
            return None

        try:
            db_task = await db_get_task(user_id=uid, task_id=tid, include_events=False)
        except Exception:
            logger.warning(
                "study_materials_task_db_lookup_failed",
                extra={"task_id": tid, "user_id": uid},
                exc_info=True,
            )
            return None
        if not isinstance(db_task, dict):
            # 与 stream 一致：尚未落库的运行时任务允许读（事件表暂空），其余一律视为不存在。
            runtime_task = await task_runtime.get_task(tid)
            if not runtime_task or str(runtime_task.user_id or "") != uid:
                return None

        try:
            limit_safe = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit_safe = 500
        cursor = max(0, int(after_seq or 0))
        # 多取 1 条判断 has_more，避免「恰好整页」时多一次空翻页。
        page = await db_list_task_events(user_id=uid, task_id=tid, after_seq=cursor, limit=limit_safe + 1)
        has_more = len(page) > limit_safe
        events = page[:limit_safe]
        next_after_seq = int(events[-1].get("seq") or cursor) if events else cursor
        return {"events": events, "next_after_seq": next_after_seq, "has_more": has_more}

    async def _upsert_archive_from_resume_state(
        self,
        task: RuntimeTask,
        *,
        meta: Dict[str, Any],
        query: str,
        subject: str,
        options: Dict[str, Any],
    ) -> None:
        try:
            wm = _dict(meta.get("resume_working_memory"))
            markdown = str(wm.get("assemble_study_archive") or wm.get("markdown") or "").strip()
            material = _dict(wm.get("generate_study_material"))
            sections = material.get("sections") if isinstance(material.get("sections"), list) else []
            preset = str(options.get("preset") or "").strip() or str(material.get("preset") or "")
            requirements = str(options.get("requirements") or "").strip() or str(material.get("requirements") or "")
            topic = str(material.get("topic") or query or "").strip()
            subj = str(material.get("subject") or subject or "").strip()
            if markdown and topic and subj:
                workflow_state = _dict(wm.get("study_materials_workflow")) or _dict(meta.get("study_materials_workflow"))
                acceptance = _dict(workflow_state.get("acceptance"))
                await upsert_study_archive(
                    user_id=task.user_id,
                    subject=subj,
                    topic=topic,
                    preset=preset,
                    requirements=requirements,
                    markdown=markdown,
                    sections=[x for x in sections if isinstance(x, dict)],
                    acceptance=acceptance,
                )
        except Exception as exc:
            logger.warning(
                "study_materials_archive_upsert_failed",
                extra={"task_id": getattr(task, "task_id", "")},
                exc_info=True,
            )
            self._record_persistence_warning(task, target="archive_upsert", error=exc, meta=meta)

    def _workflow_state_from_archive(
        self,
        archive: Dict[str, Any],
        *,
        preset: str,
        query: str,
        subject: str,
        archive_current: bool,
    ) -> Dict[str, Any]:
        """从历史归档合成 staged workflow 状态（归档复用/冷续作共用）。

        B18: coverage_map 必须来自真实小节拆分（coverage.split_sections_by_kp），
        只为能匹配到小节的知识点记 True——质量门会把 coverage_map 与小节拆分交叉
        校验（coverage_map_mismatch），伪造的全 True map 会在复验时直接失败。
        """

        markdown = str(archive.get("markdown") or "").strip()
        sections = archive.get("sections") if isinstance(archive.get("sections"), list) else []
        point_titles = [
            str(item.get("knowledge_point") or item.get("title") or "").strip()
            for item in sections
            if isinstance(item, dict) and str(item.get("knowledge_point") or item.get("title") or "").strip()
        ]
        if not point_titles:
            point_titles = [str(query or archive.get("topic") or "").strip()] if str(query or archive.get("topic") or "").strip() else []
        plan_points = [
            {"id": f"kp-{index + 1}", "title": title, "queries": [f"{title} {subject}".strip()]}
            for index, title in enumerate(point_titles[:15])
        ]
        acceptance = _dict(archive.get("acceptance"))
        workflow_state: Dict[str, Any] = {
            "version": WORKFLOW_VERSION,
            "stage": "completed" if archive_current else "research",
            "last_successful_stage": "accept" if acceptance else "",
            "preset": preset,
            "plan": {"knowledge_points": plan_points},
            "research": {},
            "markdown": markdown,
            "review": {},
            "quality_report": {},
            "acceptance": acceptance,
            "revision_attempts": 0,
            "last_failure": {},
        }
        sections_by_kp = split_sections_by_kp(markdown, point_titles) if point_titles else {}
        coverage_map = {
            point["id"]: bool(str(sections_by_kp.get(point["title"]) or "").strip())
            for point in plan_points
        }
        if coverage_map and any(coverage_map.values()):
            workflow_state["coverage_map"] = coverage_map
        # 整篇都匹配不到小节时（如旧归档没有编号二级标题）索性不写 coverage_map：
        # 缺失/空 map 在质量门里同样按未覆盖处理，避免“全 True”的假阳性。
        if workflow_state["stage"] != "completed":
            workflow_state["resume_after_research"] = "review"
        return workflow_state

    def _task_run_context(self, task: RuntimeTask) -> _TaskRunContext:
        """B2: 收集 _run_task 单次执行所需的共享上下文。"""

        meta = task.meta if isinstance(task.meta, dict) else {}
        req = task.request if isinstance(task.request, dict) else {}
        return _TaskRunContext(
            task=task,
            meta=meta,
            query=str(req.get("query") or "").strip(),
            subject=str(req.get("subject") or "").strip(),
            options=req.get("options") if isinstance(req.get("options"), dict) else {},
            parent_task_id=str(task.parent_task_id or "").strip() or None,
            resume_wm=meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {},
            iteration_offset=int(meta.get("iteration_offset") or 0),
            max_iterations=meta.get("max_iterations"),
        )

    def _capture_resume_snapshot(self, ctx: _TaskRunContext, *, force: bool) -> None:
        task = ctx.task
        meta = ctx.meta
        agent = ctx.agent
        if agent is None:
            if force:
                self._persist_snapshot(task, force=True)
            return
        try:
            agent_ctx = getattr(agent, "last_context", None)
            wm = getattr(agent_ctx, "working_memory", None) if agent_ctx is not None else None
            if isinstance(wm, dict) and wm:
                meta["resume_working_memory"] = dict(wm)
                _refresh_resume_meta(meta=meta)
                self._persist_snapshot(task, force=force)
        except Exception:
            logger.warning("study_materials_resume_snapshot_failed", extra={"task_id": task.task_id}, exc_info=True)

    async def _export_markdown_with_retry(
        self,
        task: RuntimeTask,
        *,
        markdown: str,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """B5: 导出失败不得拖垮内容上已完成的任务。

        最多尝试 2 次；最终失败时把错误写入 ``meta["export_error"]`` 并广播
        ``export_failed`` 事件，返回空 dict——调用方继续用 markdown 结果完成任务，
        而不是让异常扩散到 _run_task 的通用失败分支把任务判死。
        """

        last_error: Optional[BaseException] = None
        for attempt in range(2):
            try:
                return await _export_markdown_to_media(markdown=markdown, user_id=task.user_id)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "study_materials_export_attempt_failed",
                    extra={"task_id": task.task_id, "attempt": attempt + 1, "error": str(exc)},
                    exc_info=True,
                )
        message = str(last_error or "").strip() or (type(last_error).__name__ if last_error else "export_failed")
        meta["export_error"] = message
        logger.warning("study_materials_export_failed", extra={"task_id": task.task_id, "error": message})
        try:
            await task_runtime.append_event(
                task,
                agent_event("export_failed", {"target": "markdown_export", "error": message}),
            )
        except Exception:
            logger.warning(
                "study_materials_export_failed_event_failed",
                extra={"task_id": task.task_id},
                exc_info=True,
            )
        return {}

    async def _preflight_export_continuation(self, ctx: _TaskRunContext) -> bool:
        """fix_export / skip_export 续作：有成稿且验收仍有效时直接（重新）导出并完成。"""

        task = ctx.task
        meta = ctx.meta
        options = ctx.options
        resume_wm = ctx.resume_wm
        continue_mode = str(options.get("continue_mode") or "").strip().lower()
        if continue_mode not in {"fix_export", "skip_export"}:
            return False

        workflow_state = _dict(resume_wm.get("study_materials_workflow"))
        if not workflow_state:
            # legacy AgentCore 产物没有 staged workflow 状态与验收记录；
            # 导出续作交回 AgentCore 的 export_only / skip_export 原生路径。
            return False
        markdown = str(
            workflow_state.get("markdown")
            or resume_wm.get("assemble_study_archive")
            or resume_wm.get("markdown")
            or ""
        ).strip()
        # B8: deepen 续作的验收记录按原始 preset（acceptance_preset）签发，校验时也要用它。
        preset = str(
            options.get("acceptance_preset") or options.get("preset") or workflow_state.get("preset") or "standard"
        ).strip().lower()
        acceptance = _dict(workflow_state.get("acceptance"))
        if not markdown or not acceptance_record_is_current(
            archive={"acceptance": acceptance},
            preset=preset,
            markdown=markdown,
            options=options,
        ):
            await task_runtime.fail_task(
                task,
                "accepted_content_required",
                error={
                    "message": "accepted_content_required",
                    "code": "accepted_content_required",
                    "stage": "export",
                    "recoverable": True,
                },
            )
            return True

        exported: Dict[str, Any] = {}
        if continue_mode == "fix_export":
            exported = await self._export_markdown_with_retry(task, markdown=markdown, meta=meta)

        next_resume = dict(resume_wm)
        next_resume.update(exported)
        next_resume["markdown"] = markdown
        next_resume["assemble_study_archive"] = markdown
        next_resume["study_materials_workflow"] = workflow_state
        meta["resume_working_memory"] = next_resume
        meta["study_materials_workflow"] = workflow_state
        _refresh_resume_meta(meta=meta)
        self._persist_snapshot(task, force=True)

        file_fields = {
            key: value
            for key, value in next_resume.items()
            if key in {"md_url", "md_filename", "sha256", "bytes", "expires_at"}
        }
        result = {
            "success": True,
            "material": {
                "topic": ctx.query,
                "subject": ctx.subject,
                "markdown": markdown,
                "iteration": int(meta.get("iterations_done") or ctx.iteration_offset or 1),
                "passed": True,
                "issues": [],
                "error": None,
                **file_fields,
            },
            "acceptance": acceptance,
            "workflow": workflow_state,
            "resume_working_memory": next_resume,
            **file_fields,
        }
        await task_runtime.append_event(task, agent_event("done", result))
        await task_runtime.complete_task(task, result=result)
        return True

    async def _preflight_archive_reuse(self, ctx: _TaskRunContext) -> bool:
        """本地归档复用预审：命中同指纹归档时作为快速通道或候选草稿。"""

        task = ctx.task
        meta = ctx.meta
        options = ctx.options
        query = ctx.query
        subject = ctx.subject
        if ctx.parent_task_id or ctx.resume_wm:
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
            logger.warning(
                "study_materials_local_archive_lookup_failed",
                extra={"task_id": task.task_id, "user_id": task.user_id},
                exc_info=True,
            )
            archive = None
        if not isinstance(archive, dict):
            return False

        markdown = str(archive.get("markdown") or "").strip()
        if not markdown:
            return False

        sections = archive.get("sections") if isinstance(archive.get("sections"), list) else []
        acceptance = _dict(archive.get("acceptance"))
        # B10: 归档复用决策统一带 options 指纹与新鲜度预算（0 = 不做时间过期）。
        archive_current = acceptance_record_is_current(
            archive=archive,
            preset=preset,
            markdown=markdown,
            options=options,
            max_age_s=_archive_max_age_s(),
        )
        # B18: coverage_map 由真实小节拆分计算；整篇匹配不到小节时省略该键
        # （缺失/空 map 在质量门按未覆盖处理，绝不伪造全 True）。
        workflow_state = self._workflow_state_from_archive(
            archive,
            preset=preset,
            query=query,
            subject=subject,
            archive_current=archive_current,
        )

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
            "study_materials_workflow": workflow_state,
        }
        meta["study_materials_workflow"] = workflow_state
        _refresh_resume_meta(meta=meta)
        self._persist_snapshot(task, force=True)

        if workflow_state["stage"] != "completed":
            await task_runtime.append_event(
                task,
                agent_event(
                    "status",
                    {"content": "本地知识库命中：历史归档将作为候选草稿重新检索并通过当前质量门。"},
                ),
            )
            return False

        exported = await self._export_markdown_with_retry(task, markdown=markdown, meta=meta)
        meta["resume_working_memory"]["md_url"] = exported.get("md_url")
        meta["resume_working_memory"]["md_filename"] = exported.get("md_filename")
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
                    "acceptance": acceptance,
                    "per_kp_report": [],
                    "timing_report": {"reused_local_archive": True},
                },
            ),
        )
        await task_runtime.complete_task(task, result={"reused_local_archive": True, **exported})
        return True

    async def _run_codex_staged(self, ctx: _TaskRunContext) -> None:
        """Codex staged workflow 路径（plan→research→draft→review→revise→accept）。

        WorkflowFailure 在此终结任务；StageResultError 继续抛出，由 _run_task
        决定判失败还是显式回退 legacy AgentCore。
        """

        task = ctx.task
        meta = ctx.meta

        async def _workflow_event_sink(evt: Dict[str, Any]) -> None:
            if task.status != "running":
                raise asyncio.CancelledError
            await task_runtime.append_event(task, evt)

        async def _workflow_checkpoint_sink(state: Dict[str, Any], wm: Dict[str, Any]) -> None:
            existing = meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {}
            meta["resume_working_memory"] = _merge_resume_working_memory(existing, wm)
            meta["study_materials_workflow"] = dict(state)
            _refresh_resume_meta(meta=meta)
            self._persist_snapshot(task, force=False)

        try:
            result = await run_study_materials_workflow(
                task_id=task.task_id,
                user_id=task.user_id,
                topic=ctx.query,
                subject=ctx.subject,
                preset=str(ctx.options.get("preset") or "standard"),
                requirements=str(ctx.options.get("requirements") or ""),
                options=ctx.options,
                resume_working_memory=_dict(meta.get("resume_working_memory")),
                event_sink=_workflow_event_sink,
                checkpoint_sink=_workflow_checkpoint_sink,
            )
        except WorkflowFailure as failure:
            error = {"message": failure.code, **failure.to_dict()}
            await task_runtime.fail_task(task, failure.code, error=error)
            return
        result_wm = _dict(result.get("resume_working_memory"))
        if result_wm:
            existing = meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {}
            meta["resume_working_memory"] = _merge_resume_working_memory(existing, result_wm)
        workflow_state = _dict(result.get("workflow"))
        if workflow_state:
            meta["study_materials_workflow"] = workflow_state
        material = _dict(result.get("material"))
        try:
            iterations_done = int(material.get("iteration") or 0)
        except (TypeError, ValueError):
            iterations_done = 0
        meta["iterations_done"] = iterations_done or (ctx.iteration_offset + 1)
        _refresh_resume_meta(meta=meta)
        await self._upsert_archive_from_resume_state(
            task,
            meta=meta,
            query=ctx.query,
            subject=ctx.subject,
            options=ctx.options,
        )
        self._persist_snapshot(task, force=True)
        # B6: workflow 结果原样透传——degraded / material.passed / material.issues
        # 必须同时出现在 done 事件载荷与 complete_task 结果里（前端直接读取）。
        await task_runtime.append_event(task, agent_event("done", result))
        await task_runtime.complete_task(task, result=result)

    async def _run_author_staged(self, ctx: _TaskRunContext) -> None:
        """作者流水线 路径（research→blueprint→backbone→fill∥fig→assemble→audit→accept）。

        形状仿 _run_codex_staged：事件经同一总线发射、快照落盘、完成后走现有归档
        upsert 路径；任务快照目录下建 notes/ 与 todos.json。pipeline 返回
        status=failed 时置任务 failed 终态（recoverable），不抛未捕获异常。
        """

        task = ctx.task
        meta = ctx.meta

        async def _author_event_forward(evt: Dict[str, Any]) -> None:
            try:
                await task_runtime.append_event(task, evt)
            except Exception:
                logger.warning(
                    "study_materials_author_event_append_failed",
                    extra={"task_id": task.task_id},
                    exc_info=True,
                )

        # I-5: 单 drainer 从队列串行转发（保证与 emit 同序）；终端迁移（fail_task/done）
        # 前 join 清空队列，取消/异常路径在 finally 取消 drainer，不留泄露 task。
        forward_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

        async def _author_event_drainer() -> None:
            while True:
                evt = await forward_queue.get()
                try:
                    await _author_event_forward(evt)
                finally:
                    forward_queue.task_done()

        drainer = asyncio.get_running_loop().create_task(_author_event_drainer())

        def _author_emit(evt: Dict[str, Any]) -> None:
            # pipeline 的 emit 是同步回调；任务不再 running 时同步抛 CancelledError 终止流水线。
            if task.status != "running":
                raise asyncio.CancelledError
            forward_queue.put_nowait(evt)

        async def _author_llm(system_prompt: str, user_prompt: str) -> str:
            # 延迟导入：注入假 llm_func 的测试不触碰 LLM 栈。
            from backend.core.settings import LESSON_PLAN_MODEL
            from backend.llm.client import chat_completion_text

            return await chat_completion_text(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
                temperature=0.2,
                max_tokens=0,
                req_id_prefix="study_author",
            )

        try:
            preset = str(ctx.options.get("preset") or "standard").strip() or "standard"
            requirements = str(ctx.options.get("requirements") or "")
            pipeline_ctx = AuthorPipelineContext(
                task_id=task.task_id,
                topic=ctx.query,
                subject=ctx.subject,
                work_dir=_TASK_SNAPSHOTS_DIR / task.task_id,
                user_id=task.user_id,
                preset=preset,
                requirements=requirements,
                options=ctx.options,
                knowledge_points=[ctx.query] if ctx.query else [],
            )
            result = await run_author_pipeline(
                pipeline_ctx,
                llm_func=_author_llm,
                toolbox=ResearchToolbox(),
                emit=_author_emit,
                forge=FigureForge(on_trace=_author_emit),
            )
            # I-5: 终端迁移前 drain——清空转发队列，迟到事件不得落在 fail_task/done 之后。
            await forward_queue.join()
            if not result.get("success"):
                error = _dict(result.get("error"))
                code = str(error.get("code") or "author_pipeline_failed")
                await task_runtime.fail_task(
                    task,
                    code,
                    error={
                        "message": code,
                        "code": code,
                        "stage": str(error.get("stage") or ""),
                        "issues": list(error.get("issues") or []),
                        "detail": str(error.get("detail") or ""),
                        "recoverable": True,
                    },
                )
                return

            markdown = str(result.get("markdown") or "")
            material = _dict(result.get("material"))
            acceptance = _dict(result.get("acceptance"))
            quality_report = _dict(result.get("quality_report"))
            workflow_state = {
                "version": WORKFLOW_VERSION,
                "stage": "completed",
                "last_successful_stage": "accept",
                "preset": preset,
                "plan": _dict(result.get("plan")),
                "research": _dict(result.get("research")),
                "markdown": markdown,
                "review": _dict(result.get("review")),
                "quality_report": quality_report,
                "acceptance": acceptance,
                "revision_attempts": int(result.get("revision_attempts") or 0),
                "last_failure": {},
                "coverage_map": _dict(result.get("coverage_map")),
                "runtime": "author",
            }
            sections = [
                {"knowledge_point": str(item.get("title") or "").strip(), "title": str(item.get("title") or "").strip()}
                for item in (result.get("sections") or [])
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            ]
            existing = meta.get("resume_working_memory") if isinstance(meta.get("resume_working_memory"), dict) else {}
            meta["resume_working_memory"] = _merge_resume_working_memory(
                existing,
                {
                    "study_options": {"preset": preset, "requirements": requirements},
                    "assemble_study_archive": markdown,
                    "markdown": markdown,
                    "generate_study_material": {
                        "topic": ctx.query,
                        "subject": ctx.subject,
                        "preset": preset,
                        "requirements": requirements,
                        "sections": sections,
                    },
                    "study_materials_workflow": workflow_state,
                },
            )
            meta["study_materials_workflow"] = workflow_state
            meta["iterations_done"] = int(material.get("iteration") or 0) or (ctx.iteration_offset + 1)
            _refresh_resume_meta(meta=meta)
            await self._upsert_archive_from_resume_state(
                task, meta=meta, query=ctx.query, subject=ctx.subject, options=ctx.options
            )
            self._persist_snapshot(task, force=True)

            # done 载荷瘦身（DB JSON 上限 TASK_JSON_MAX_CHARS=200k，超限会被整包截断）：
            # 正文只在 material.markdown 携带一份，workflow 不再重复 markdown / research
            # 证据全文（完整状态在 meta 工作流状态与任务快照里；B3 冷续作由
            # _resume_wm_from_result_payload 从 material 回填 markdown）。
            research = _dict(result.get("research"))
            done_workflow = {
                "version": WORKFLOW_VERSION,
                "stage": workflow_state["stage"],
                "last_successful_stage": workflow_state["last_successful_stage"],
                "preset": preset,
                "plan": _dict(result.get("plan")),
                "research": {},
                "research_evidence_count": sum(
                    len(items) for items in research.values() if isinstance(items, list)
                ),
                "review": _dict(result.get("review")),
                "quality_report": quality_report,
                "acceptance": acceptance,
                "revision_attempts": int(result.get("revision_attempts") or 0),
                "last_failure": {},
                "coverage_map": _dict(result.get("coverage_map")),
                "runtime": "author",
            }
            done_payload: Dict[str, Any] = {
                "success": True,
                "material": material,
                "quality_report": quality_report,
                "review": _dict(result.get("review")),
                "acceptance": acceptance,
                "workflow": done_workflow,
                "author": {
                    "todos": result.get("todos") or [],
                    "references": result.get("references") or [],
                    "audit": _dict(result.get("audit")),
                    "quality_notes": result.get("quality_notes") or [],
                    "blueprint": _author_blueprint_summary(_dict(result.get("blueprint"))),
                },
            }
            if result.get("degraded"):
                # 与 codex workflow 相同的降级交付：done 前先广播 quality_degraded，
                # degraded / material.passed 同时出现在 done 载荷与 complete_task 结果里。
                done_payload["degraded"] = True
                await task_runtime.append_event(
                    task,
                    {
                        "type": "quality_degraded",
                        "event": "quality_degraded",
                        "data": {
                            "issues": list(material.get("issues") or []),
                            "revision_attempts": int(result.get("revision_attempts") or 0),
                        },
                    },
                )
            await task_runtime.append_event(task, agent_event("done", done_payload))
            await task_runtime.complete_task(task, result=done_payload)
        finally:
            # I-5: 取消/异常路径撤销 drainer——转发 task 不得泄露到本作用域之外。
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)

    async def _run_legacy_agent(self, ctx: _TaskRunContext) -> None:
        """legacy AgentCore 路径（默认；也是 codex staged 显式回退的目标）。"""

        task = ctx.task
        meta = ctx.meta
        agent = AgentCore()
        ctx.agent = agent
        preferences: Dict[str, Any] = {}
        if ctx.subject:
            preferences["subject"] = ctx.subject

        async for evt in agent.run(
            ctx.query,
            user_id=task.user_id,
            preferences=preferences,
            options=ctx.options,
            resume_working_memory=ctx.resume_wm if ctx.resume_wm else None,
            iteration_offset=ctx.iteration_offset,
            max_iterations=ctx.max_iterations,
        ):
            if task.status != "running":
                break

            await task_runtime.append_event(task, evt)

            kind = str(evt.get("event") or evt.get("type") or "")
            if kind in {"done", "error"}:
                self._capture_resume_snapshot(ctx, force=True)

            if kind == "done":
                data = evt.get("data")
                if isinstance(data, dict):
                    material = data.get("material")
                    if isinstance(material, dict):
                        try:
                            meta["iterations_done"] = int(material.get("iteration") or meta.get("iterations_done") or 0)
                        except (TypeError, ValueError):
                            pass

                # 空成果诚实失败：legacy 路径工具失败会被 ReAct 吞掉继续，全部写作失败时
                # done 里可能是空 markdown——不能标 completed 冒充成功（线上已出现两次）。
                # 仅对 generation 形态的 done（含 material 字典）检查；export 形态不受影响。
                material_obj = data.get("material") if isinstance(data, dict) else None
                if isinstance(material_obj, dict) and not str(material_obj.get("markdown") or "").strip():
                    issues = ["生成结束但正文为空：写作步骤可能全部失败（可检查 LLM 配置后重试）"]
                    await task_runtime.append_event(
                        task,
                        agent_event(
                            "recovery_available",
                            {"code": "empty_material", "stage": "write", "issues": issues, "recoverable": True},
                        ),
                    )
                    await task_runtime.fail_task(
                        task,
                        "empty_material",
                        error={"message": "empty_material", "code": "empty_material", "recoverable": True, "issues": issues},
                        emit_event=False,
                    )
                    return

                await self._upsert_archive_from_resume_state(
                    task, meta=meta, query=ctx.query, subject=ctx.subject, options=ctx.options
                )

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

            self._capture_resume_snapshot(ctx, force=False)

    async def _run_task(self, task: RuntimeTask) -> None:
        ctx = self._task_run_context(task)
        try:
            if await self._preflight_export_continuation(ctx):
                return
            if await self._preflight_archive_reuse(ctx):
                return

            if _study_materials_author_enabled():
                await self._run_author_staged(ctx)
                return

            if _study_materials_codex_enabled():
                try:
                    await self._run_codex_staged(ctx)
                    return
                except StageResultError as failure:
                    allow_fallback = (
                        failure.code == "invalid_stage_result"
                        and failure.detail == "stage_result_missing"
                        and legacy_agent_fallback_enabled()
                    )
                    if not allow_fallback:
                        await task_runtime.fail_task(
                            task,
                            failure.code,
                            error={
                                "message": failure.code,
                                "code": failure.code,
                                "stage": failure.stage,
                                "detail": failure.detail,
                                "recoverable": True,
                            },
                        )
                        return
                    # B2: codex→legacy 显式回退——留日志与任务事件，绝不靠位置静默落入 legacy。
                    logger.warning(
                        "study_materials_codex_fallback_to_legacy",
                        extra={
                            "task_id": task.task_id,
                            "stage": failure.stage,
                            "detail": failure.detail,
                        },
                    )
                    await task_runtime.append_event(
                        task,
                        agent_event(
                            "codex_fallback_to_legacy",
                            {
                                "stage": failure.stage,
                                "detail": failure.detail,
                                "content": "Codex 阶段结果缺失，已切换到内置生成流程继续。",
                            },
                        ),
                    )
                    return await self._run_legacy_agent(ctx)

            await self._run_legacy_agent(ctx)
        except asyncio.CancelledError:
            if task.status in {"paused", "canceled", "cancelled"}:
                return
            await task_runtime.fail_task(task, "Task cancelled", error={"message": "Task cancelled"})
            raise
        except Exception as exc:  # pragma: no cover
            logger.exception("study_materials_task_run_failed", extra={"task_id": task.task_id})
            await task_runtime.fail_task(task, str(exc), error={"message": str(exc)})
        finally:
            self._capture_resume_snapshot(ctx, force=True)
            if task.status == "running":
                await task_runtime.fail_task(
                    task,
                    "Task ended unexpectedly",
                    error={"message": "Task ended unexpectedly"},
                )
