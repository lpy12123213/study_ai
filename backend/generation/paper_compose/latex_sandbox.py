from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


class SandboxUnavailableError(RuntimeError):
    """Raised when Docker or the configured LaTeX image is unavailable."""


@dataclass
class LatexSandboxConfig:
    image: str = ""
    timeout_s: int = 600
    memory: str = "1g"
    cpus: str = "2"
    pids_limit: int = 128
    user: str = "1000:1000"
    docker_bin: str = "docker"


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or "").strip() or default)
    except (TypeError, ValueError):
        return int(default)


def default_latex_sandbox_config() -> LatexSandboxConfig:
    return LatexSandboxConfig(
        image=(os.getenv("LATEX_SANDBOX_DOCKER_IMAGE") or "study-ai/latex-sandbox:latest").strip(),
        timeout_s=_int_env("LATEX_SANDBOX_TIMEOUT_S", _int_env("PAPER_EXPORT_LATEX_TIMEOUT_S", 600)),
        memory=(os.getenv("LATEX_SANDBOX_MEMORY") or "1g").strip() or "1g",
        cpus=(os.getenv("LATEX_SANDBOX_CPUS") or "2").strip() or "2",
        pids_limit=_int_env("LATEX_SANDBOX_PIDS_LIMIT", 128),
        user=(os.getenv("LATEX_SANDBOX_USER") or "1000:1000").strip() or "1000:1000",
        docker_bin=(os.getenv("DOCKER_BIN") or "docker").strip() or "docker",
    )


def _mount_arg(build_dir: Path) -> str:
    return f"{str(build_dir.resolve())}:/workspace"


def _container_name(build_dir: Path) -> str:
    suffix = re.sub(r"[^a-zA-Z0-9_.-]+", "-", build_dir.name).strip("-._") or "build"
    return f"study-ai-latex-{suffix[:48]}"


def build_docker_run_command(
    *,
    build_dir: Path,
    config: Optional[LatexSandboxConfig] = None,
    container_name: Optional[str] = None,
) -> List[str]:
    cfg = config or default_latex_sandbox_config()
    image = str(cfg.image or "").strip()
    if not image:
        raise SandboxUnavailableError("missing_latex_docker_image")

    pids = int(cfg.pids_limit or 128)
    return [
        cfg.docker_bin,
        "run",
        "--rm",
        "--name",
        str(container_name or _container_name(build_dir)),
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
        str(pids),
        "--ulimit",
        "nofile=256:256",
        "--ulimit",
        f"nproc={pids}:{pids}",
        "--stop-timeout",
        "5",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m",
        "--tmpfs",
        "/home:rw,nosuid,nodev,size=256m",
        "-e",
        "HOME=/tmp",
        "-v",
        _mount_arg(build_dir),
        "--workdir",
        "/workspace",
        image,
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "main.tex",
    ]


async def ensure_sandbox_available(config: Optional[LatexSandboxConfig] = None) -> None:
    cfg = config or default_latex_sandbox_config()
    if not shutil.which(cfg.docker_bin):
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
        raise SandboxUnavailableError(msg or "latex_docker_image_unavailable")


async def _cleanup_container(cfg: LatexSandboxConfig, container_name: str) -> None:
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


async def compile_latex_in_docker(
    *,
    build_dir: Path,
    config: Optional[LatexSandboxConfig] = None,
) -> Tuple[Optional[bytes], str]:
    cfg = config or default_latex_sandbox_config()
    root = build_dir.resolve()
    tex_path = root / "main.tex"
    if not tex_path.exists() or not tex_path.is_file():
        return None, "latex_main_tex_missing"

    container_name = _container_name(root)
    cmd = build_docker_run_command(build_dir=root, config=cfg, container_name=container_name)
    logs: list[str] = []

    for _ in range(2):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxUnavailableError("docker_not_found") from exc

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=max(1, int(cfg.timeout_s or 600)))
        except asyncio.TimeoutError:
            await _cleanup_container(cfg, container_name)
            if proc.returncode is None:
                proc.kill()
                await proc.communicate()
            return None, "latex_docker_compile_timeout"
        except asyncio.CancelledError:
            await _cleanup_container(cfg, container_name)
            if proc.returncode is None:
                proc.kill()
                await proc.communicate()
            raise

        stdout = stdout_b.decode("utf-8", errors="ignore")
        stderr = stderr_b.decode("utf-8", errors="ignore")
        logs.append((stdout + "\n" + stderr).strip())
        if proc.returncode != 0:
            return None, "\n".join(logs)[-8000:]

    pdf_path = root / "main.pdf"
    if not pdf_path.exists() or not pdf_path.is_file():
        return None, "\n".join(logs)[-8000:] or "pdf_missing"
    return pdf_path.read_bytes(), "\n".join(logs)[-8000:]
