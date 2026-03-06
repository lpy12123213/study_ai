from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.agent.core import AgentCore
from backend.agent.types import agent_event
from backend.database.models import get_study_archive_by_fingerprint, upsert_study_archive


def _now_s() -> float:
    return time.time()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASK_SNAPSHOTS_DIR = (_REPO_ROOT / ".local" / "study_materials" / "tasks").resolve()


def _truthy(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


def _export_markdown_to_media(*, markdown: str) -> Dict[str, Any]:
    data = (markdown + ("\n" if not markdown.endswith("\n") else "")).encode("utf-8", errors="ignore")
    sha = hashlib.sha256(data).hexdigest()
    filename = f"{sha}.md"
    url = f"/api/media/generated/{filename}"

    out_dir = (_REPO_ROOT / ".local" / "media" / "generated").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    if not out_path.exists():
        out_path.write_bytes(data)

    return {"md_url": url, "md_filename": filename, "sha256": sha, "bytes": len(data)}


@dataclass
class StudyMaterialsTask:
    task_id: str
    query: str
    user_id: str
    subject: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    created_at_s: float = field(default_factory=_now_s)
    updated_at_s: float = field(default_factory=_now_s)
    status: str = "running"  # running|completed|failed
    error: Optional[str] = None

    # Continuation support (for "completed -> continue iteration" flows).
    parent_task_id: Optional[str] = None
    resume_working_memory: Dict[str, Any] = field(default_factory=dict)
    iteration_offset: int = 0
    max_iterations: Optional[int] = None
    iterations_done: int = 0

    # seq starts at 1; `events[i-1]["seq"] == i`.
    events: List[Dict[str, Any]] = field(default_factory=list)
    last_seq: int = 0
    seq_offset: int = 0  # number of dropped events; first stored seq is seq_offset + 1

    # Notified when events/status change.
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)

    # Runner task (created by manager).
    runner: Optional[asyncio.Task] = None
    persisted_at_s: float = 0.0


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

            # A "running" task cannot continue after restart; mark as failed with a clear reason.
            if task.status == "running":
                task.status = "failed"
                task.error = task.error or "server_restarted"
                task.updated_at_s = _now_s()
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
                        pass
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
        if mode_norm not in {"improve", "deepen_research", "fix_export", "skip_export"}:
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

        return await self.create_task(
            query=parent.query,
            user_id=uid,
            subject=parent.subject,
            options=options,
            parent_task_id=parent.task_id,
            resume_working_memory=parent.resume_working_memory,
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

        async with task.cond:
            task.last_seq += 1
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
            force = str(payload.get("type") or "") in {"task_started", "done", "result", "error"}
            self._persist_snapshot(task, force=force or task.status != "running")
        except Exception:
            pass

    async def _fail_task(self, task: StudyMaterialsTask, message: str) -> None:
        task.status = "failed"
        task.error = message
        await self._append_event(task, {"type": "error", "data": {"error": message}})
        async with task.cond:
            task.cond.notify_all()

    async def _complete_task(self, task: StudyMaterialsTask) -> None:
        task.status = "completed"
        task.updated_at_s = _now_s()
        self._persist_snapshot(task, force=True)
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
                else opts.get("prefer_local_archive") if "prefer_local_archive" in opts else None
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

            exported = _export_markdown_to_media(markdown=markdown)

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
            except Exception:
                pass

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
                                pass
                    _capture_resume_snapshot()
                    try:
                        wm = dict(task.resume_working_memory or {})
                        markdown = str(wm.get("assemble_study_archive") or wm.get("markdown") or "").strip()
                        material = wm.get("generate_study_material") if isinstance(wm.get("generate_study_material"), dict) else {}
                        sections = material.get("sections") if isinstance(material.get("sections"), list) else []
                        preset = str((task.options or {}).get("preset") or "").strip() or str(material.get("preset") or "")
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
                        pass
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
