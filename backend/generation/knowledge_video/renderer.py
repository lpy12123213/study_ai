from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from backend.generation.knowledge_video.models import RenderResult


class SandboxUnavailableError(RuntimeError):
    """Raised when Docker or the configured Manim image is unavailable."""


@dataclass
class DockerRenderConfig:
    image: str = ""
    quality: str = "low"
    timeout_s: int = 180
    memory: str = "1g"
    cpus: str = "2"
    pids_limit: int = 128
    user: str = "1000:1000"
    docker_bin: str = "docker"


def default_docker_render_config(*, quality: str = "") -> DockerRenderConfig:
    return DockerRenderConfig(
        image=(os.getenv("KNOWLEDGE_VIDEO_DOCKER_IMAGE") or "study-ai/manim-sandbox:latest").strip(),
        quality=str(quality or os.getenv("KNOWLEDGE_VIDEO_QUALITY") or "low").strip() or "low",
        timeout_s=int(os.getenv("KNOWLEDGE_VIDEO_RENDER_TIMEOUT_S") or "180"),
        memory=(os.getenv("KNOWLEDGE_VIDEO_DOCKER_MEMORY") or "1g").strip() or "1g",
        cpus=(os.getenv("KNOWLEDGE_VIDEO_DOCKER_CPUS") or "2").strip() or "2",
        pids_limit=int(os.getenv("KNOWLEDGE_VIDEO_DOCKER_PIDS_LIMIT") or "128"),
        user=(os.getenv("KNOWLEDGE_VIDEO_DOCKER_USER") or "1000:1000").strip() or "1000:1000",
        docker_bin=(os.getenv("DOCKER_BIN") or "docker").strip() or "docker",
    )


def _quality_flag(value: str) -> str:
    q = str(value or "").strip().lower()
    if q in {"low", "l", "480p", "preview"}:
        return "-ql"
    if q in {"medium", "m", "720p"}:
        return "-qm"
    if q in {"high", "h", "1080p"}:
        return "-qh"
    return "-ql"


def _mount_arg(task_dir: Path) -> str:
    return f"{str(task_dir.resolve())}:/workspace"


def _container_name(task_dir: Path) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", task_dir.name).strip("-._") or "task"
    return f"study-ai-manim-{suffix[:48]}"


def build_docker_run_command(
    *,
    task_dir: Path,
    script_name: str,
    scene_name: str,
    config: Optional[DockerRenderConfig] = None,
    container_name: Optional[str] = None,
) -> List[str]:
    cfg = config or default_docker_render_config()
    image = str(cfg.image or "").strip()
    if not image:
        raise SandboxUnavailableError("missing_docker_image")

    return [
        cfg.docker_bin,
        "run",
        "--rm",
        "--name",
        str(container_name or _container_name(task_dir)),
        "--network",
        "none",
        "--ipc",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        str(cfg.user),
        "--cpus",
        str(cfg.cpus),
        "--memory",
        str(cfg.memory),
        "--pids-limit",
        str(int(cfg.pids_limit or 128)),
        "--ulimit",
        "nofile=256:256",
        "--ulimit",
        f"nproc={int(cfg.pids_limit or 128)}:{int(cfg.pids_limit or 128)}",
        "--stop-timeout",
        "5",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m",
        "--tmpfs",
        "/home/manimuser:rw,nosuid,nodev,size=256m",
        "-e",
        "HOME=/tmp",
        "-v",
        _mount_arg(task_dir),
        "--workdir",
        "/workspace",
        image,
        "manim",
        _quality_flag(cfg.quality),
        "--media_dir",
        "/workspace/media",
        "--disable_caching",
        str(script_name),
        str(scene_name),
    ]


async def ensure_sandbox_available(config: Optional[DockerRenderConfig] = None) -> None:
    cfg = config or default_docker_render_config()
    docker_path = shutil.which(cfg.docker_bin)
    if not docker_path:
        raise SandboxUnavailableError("docker_not_found")

    proc = await asyncio.create_subprocess_exec(
        cfg.docker_bin,
        "image",
        "inspect",
        cfg.image,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = (stderr or b"").decode("utf-8", errors="ignore").strip()
        raise SandboxUnavailableError(msg or "docker_image_unavailable")


def find_rendered_video(task_dir: Path, *, scene_name: str) -> Optional[Path]:
    root = (task_dir / "media").resolve()
    if not root.exists():
        return None
    candidates = [p for p in root.rglob("*.mp4") if p.is_file()]
    if not candidates:
        return None
    preferred = [p for p in candidates if p.stem == scene_name]
    picked = preferred[0] if preferred else candidates[0]
    return picked.resolve()


async def _cleanup_container(cfg: DockerRenderConfig, container_name: str) -> None:
    for args in (("kill", container_name), ("rm", "-f", container_name)):
        try:
            proc = await asyncio.create_subprocess_exec(
                cfg.docker_bin,
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
        except (OSError, asyncio.TimeoutError):
            continue


async def render_with_docker(
    *,
    task_dir: Path,
    script_name: str,
    scene_name: str,
    config: Optional[DockerRenderConfig] = None,
) -> RenderResult:
    cfg = config or default_docker_render_config()
    container_name = _container_name(task_dir)
    cmd = build_docker_run_command(
        task_dir=task_dir,
        script_name=script_name,
        scene_name=scene_name,
        config=cfg,
        container_name=container_name,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise SandboxUnavailableError("docker_not_found") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=max(1, int(cfg.timeout_s or 180)))
    except asyncio.TimeoutError:
        await _cleanup_container(cfg, container_name)
        if proc.returncode is None:
            proc.kill()
            await proc.communicate()
        return RenderResult(success=False, video_path=None, stdout="", stderr="render_timeout", returncode=-1)
    except asyncio.CancelledError:
        await _cleanup_container(cfg, container_name)
        if proc.returncode is None:
            proc.kill()
            await proc.communicate()
        raise

    stdout = stdout_b.decode("utf-8", errors="ignore")
    stderr = stderr_b.decode("utf-8", errors="ignore")
    video = find_rendered_video(task_dir, scene_name=scene_name)
    ok = proc.returncode == 0 and video is not None
    return RenderResult(success=ok, video_path=video, stdout=stdout, stderr=stderr, returncode=int(proc.returncode or 0))
