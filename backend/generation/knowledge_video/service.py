from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.text_utils import clip_text as _clip_text
from backend.database.repositories.content.study_archives import get_study_archive
from backend.generation.knowledge_video.llm import generate_manim_package
from backend.generation.knowledge_video.models import GeneratedVideoPackage, KnowledgeVideoRequest, RenderResult
from backend.generation.knowledge_video.renderer import (
    SandboxUnavailableError,
    default_docker_render_config,
    ensure_sandbox_available,
    render_with_docker,
)
from backend.generation.knowledge_video.safety import UnsafeManimCodeError, validate_manim_code
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes, publish_generated_text
from backend.shared.tasks import RuntimeTask, task_runtime

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TASK_ROOT = (_REPO_ROOT / ".local" / "knowledge_videos").resolve()


def _normalize_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = int(default)
    return max(min_value, min(n, max_value))


def normalize_request(raw: Dict[str, Any]) -> KnowledgeVideoRequest:
    req = raw if isinstance(raw, dict) else {}
    topic = _clip_text(str(req.get("topic") or req.get("query") or "").strip(), max_chars=300)
    if not topic:
        raise ValueError("missing_topic")
    source_archive_id = _normalize_int(req.get("source_archive_id") or req.get("sourceArchiveId"), default=0, min_value=0, max_value=2_147_483_647)
    duration = _normalize_int(req.get("duration_seconds") or req.get("durationSeconds"), default=30, min_value=10, max_value=180)
    return KnowledgeVideoRequest(
        topic=topic,
        subject=_clip_text(str(req.get("subject") or "").strip(), max_chars=100),
        source_markdown=_clip_text(str(req.get("source_markdown") or req.get("sourceMarkdown") or "").strip(), max_chars=80_000),
        source_archive_id=source_archive_id,
        duration_seconds=duration,
        style=_clip_text(str(req.get("style") or "clean").strip(), max_chars=80) or "clean",
        requirements=_clip_text(str(req.get("requirements") or "").strip(), max_chars=4000),
        quality=_clip_text(str(req.get("quality") or "low").strip(), max_chars=30) or "low",
    )


async def _hydrate_source_markdown(request: KnowledgeVideoRequest, *, user_id: str) -> KnowledgeVideoRequest:
    if request.source_markdown or request.source_archive_id <= 0:
        return request
    try:
        archive = await get_study_archive(user_id=user_id, archive_id=request.source_archive_id)
    except Exception:
        logger.warning(
            "knowledge_video_source_archive_lookup_failed",
            extra={"user_id": user_id, "archive_id": request.source_archive_id},
            exc_info=True,
        )
        archive = None
    if not isinstance(archive, dict):
        return request
    markdown = str(archive.get("markdown") or "").strip()
    if markdown:
        request.source_markdown = _clip_text(markdown, max_chars=80_000)
    if not request.subject:
        request.subject = _clip_text(str(archive.get("subject") or "").strip(), max_chars=100)
    return request


def subtitles_to_srt(items: List[Dict[str, Any]]) -> str:
    def fmt(seconds: Any) -> str:
        try:
            total_ms = max(0, int(float(seconds) * 1000))
        except (TypeError, ValueError):
            total_ms = 0
        ms = total_ms % 1000
        total_s = total_ms // 1000
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines: List[str] = []
    for i, item in enumerate([x for x in items if isinstance(x, dict)], start=1):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = fmt(item.get("start") or 0)
        end = fmt(item.get("end") or item.get("start") or 0)
        lines.extend([str(i), f"{start} --> {end}", text, ""])
    return "\n".join(lines).strip() + "\n"


async def _publish_outputs(
    *,
    package: GeneratedVideoPackage,
    render_result: RenderResult,
    user_id: str,
    attempts: int,
) -> Dict[str, Any]:
    if not render_result.video_path or not render_result.video_path.exists():
        raise ValueError("missing_rendered_video")

    ttl_s = default_generated_media_ttl_s()
    video_out = await publish_generated_bytes(
        render_result.video_path.read_bytes(),
        user_id=user_id,
        ext=".mp4",
        file_type="video",
        mime_type="video/mp4",
        ttl_s=ttl_s,
    )
    subtitle_text = subtitles_to_srt(package.subtitles)
    subtitle_out = await publish_generated_text(
        subtitle_text,
        user_id=user_id,
        ext=".srt",
        file_type="subtitle",
        mime_type="application/x-subrip; charset=utf-8",
        ttl_s=ttl_s,
    )
    script_out = await publish_generated_text(
        package.code,
        user_id=user_id,
        ext=".py",
        file_type="script",
        mime_type="text/x-python; charset=utf-8",
        ttl_s=ttl_s,
    )
    metadata = dict(package.metadata or {})
    metadata.update(
        {
            "scene_name": package.scene_name,
            "attempts": int(attempts),
            "subtitles": package.subtitles,
            "render_returncode": render_result.returncode,
        }
    )
    meta_out = await publish_generated_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        user_id=user_id,
        ext=".json",
        file_type="metadata",
        mime_type="application/json; charset=utf-8",
        ttl_s=ttl_s,
    )

    return {
        "video_url": video_out.get("url") or "",
        "video_filename": video_out.get("filename") or "",
        "subtitle_url": subtitle_out.get("url") or "",
        "subtitle_filename": subtitle_out.get("filename") or "",
        "script_url": script_out.get("url") or "",
        "script_filename": script_out.get("filename") or "",
        "metadata_url": meta_out.get("url") or "",
        "metadata_filename": meta_out.get("filename") or "",
        "metadata": metadata,
    }


async def _emit_progress(task: RuntimeTask, *, stage: str, label: str, progress: float) -> None:
    await task_runtime.append_event(
        task,
        {"type": "progress", "stage_id": stage, "stage_label": label, "progress": float(progress)},
    )


async def _emit_step(task: RuntimeTask, *, step_id: str, title: str, status: str = "completed", output: Optional[dict] = None) -> None:
    step: Dict[str, Any] = {"id": step_id, "title": title, "status": status, "toolName": "knowledge_video"}
    if output is not None:
        step["output"] = output
    await task_runtime.append_event(task, {"type": "step", "step": step})


async def run_knowledge_video_task(task: RuntimeTask, *, user_id: str, max_attempts: int = 3) -> None:
    uid = str(user_id or "").strip()
    if not uid:
        return

    task_dir: Optional[Path] = None
    previous_code = ""
    last_render_error = ""

    try:
        request = await _hydrate_source_markdown(normalize_request(task.request), user_id=uid)
        config = default_docker_render_config(quality=request.quality)

        await _emit_progress(task, stage="plan", label="整理视频需求", progress=5.0)
        try:
            await ensure_sandbox_available(config)
        except SandboxUnavailableError as exc:
            await task_runtime.append_event(task, {"type": "error", "error": {"code": "sandbox_unavailable", "message": str(exc)}})
            await task_runtime.fail_task(task, "sandbox_unavailable", error={"message": str(exc)}, emit_event=False)
            return

        _TASK_ROOT.mkdir(parents=True, exist_ok=True)
        task_dir = Path(tempfile.mkdtemp(prefix=f"{task.task_id}-", dir=str(_TASK_ROOT))).resolve()

        attempts = max(1, int(max_attempts or 3))
        for attempt in range(1, attempts + 1):
            if task.status != "running":
                return

            await _emit_progress(task, stage="code", label="AI 生成 Manim 代码", progress=15.0 + (attempt - 1) * 15.0)
            package = await generate_manim_package(
                request=request,
                previous_code=previous_code,
                render_error=last_render_error,
            )

            await _emit_progress(task, stage="safety_check", label="静态安全检查", progress=35.0 + (attempt - 1) * 10.0)
            try:
                validate_manim_code(package.code, scene_name=package.scene_name)
            except UnsafeManimCodeError as exc:
                previous_code = package.code
                last_render_error = f"safety_check_failed: {exc}"
                await _emit_step(
                    task,
                    step_id=f"safety:{attempt}",
                    title="安全检查未通过，准备修复",
                    status="failed" if attempt >= attempts else "completed",
                    output={"error": str(exc)},
                )
                if attempt >= attempts:
                    await task_runtime.fail_task(task, "unsafe_generated_code", error={"message": str(exc)}, emit_event=True)
                    return
                await _emit_progress(task, stage="repair", label="修复 Manim 代码", progress=45.0)
                continue

            script_path = task_dir / "scene.py"
            script_path.write_text(package.code, encoding="utf-8")
            (task_dir / "subtitles.srt").write_text(subtitles_to_srt(package.subtitles), encoding="utf-8")
            (task_dir / "metadata.json").write_text(json.dumps(package.metadata, ensure_ascii=False, indent=2), encoding="utf-8")

            await _emit_progress(task, stage="render", label="Docker 沙盒渲染", progress=55.0 + (attempt - 1) * 10.0)
            render_result = await render_with_docker(
                task_dir=task_dir,
                script_name="scene.py",
                scene_name=package.scene_name,
                config=config,
            )
            if render_result.success:
                await _emit_step(
                    task,
                    step_id=f"render:{attempt}",
                    title="Manim 渲染完成",
                    output={"returncode": render_result.returncode, "scene_name": package.scene_name},
                )
                await _emit_progress(task, stage="publish", label="发布视频文件", progress=92.0)
                result = await _publish_outputs(
                    package=package,
                    render_result=render_result,
                    user_id=uid,
                    attempts=attempt,
                )
                await task_runtime.complete_task(task, result=result)
                return

            previous_code = package.code
            last_render_error = _clip_text("\n".join([render_result.stderr, render_result.stdout]).strip(), max_chars=5000)
            await _emit_step(
                task,
                step_id=f"render:{attempt}",
                title="Manim 渲染失败，准备修复" if attempt < attempts else "Manim 渲染失败",
                status="failed" if attempt >= attempts else "completed",
                output={"returncode": render_result.returncode, "error": last_render_error},
            )
            if attempt < attempts:
                await _emit_progress(task, stage="repair", label="修复 Manim 代码", progress=70.0)

        await task_runtime.fail_task(
            task,
            "render_failed",
            error={"message": "render_failed", "detail": last_render_error},
            emit_event=True,
        )
    except ValueError as exc:
        await task_runtime.fail_task(task, str(exc), error={"message": str(exc)}, emit_event=True)
    except Exception as exc:  # pragma: no cover
        logger.exception("knowledge_video_task_failed", extra={"task_id": task.task_id, "user_id": uid})
        await task_runtime.fail_task(task, str(exc), error={"message": str(exc)}, emit_event=True)
    finally:
        if task_dir is not None:
            try:
                shutil.rmtree(task_dir, ignore_errors=True)
            except OSError:
                logger.warning("knowledge_video_task_cleanup_failed", extra={"task_id": task.task_id}, exc_info=True)
