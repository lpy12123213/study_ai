from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence


class SandboxUnavailableError(RuntimeError):
    """Raised when Docker or the configured compose sandbox image is unavailable."""


class SandboxSecurityError(ValueError):
    """Raised when a sandbox operation violates path, size, or command policy."""


class SandboxExpiredError(SandboxSecurityError):
    """Raised when a sandbox session exceeds its configured TTL."""


@dataclass
class DockerCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class ComposeSandboxConfig:
    image: str = "study-ai/compose-sandbox:latest"
    root_dir: Path | str = Path(".local/compose-sandbox")
    timeout_s: int = 60
    ttl_s: int = 900
    max_workspace_bytes: int = 50 * 1024 * 1024
    memory: str = "1g"
    cpus: str = "2"
    pids_limit: int = 128
    user: str = "1000:1000"
    docker_bin: str = "docker"
    delete_workspace_on_close: bool = True


@dataclass
class ComposeSandboxSession:
    session_id: str
    container_name: str
    container_id: str
    workspace: Path
    created_at: float
    expires_at: float
    closed: bool = False


def _int_env(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or "").strip() or default)
    except (TypeError, ValueError):
        return int(default)


def default_compose_sandbox_config() -> ComposeSandboxConfig:
    return ComposeSandboxConfig(
        image=(os.getenv("COMPOSE_SANDBOX_DOCKER_IMAGE") or "study-ai/compose-sandbox:latest").strip(),
        root_dir=Path(os.getenv("COMPOSE_SANDBOX_ROOT") or ".local/compose-sandbox"),
        timeout_s=_int_env("COMPOSE_SANDBOX_TIMEOUT_S", 60),
        ttl_s=_int_env("COMPOSE_SANDBOX_TTL_S", 900),
        max_workspace_bytes=_int_env("COMPOSE_SANDBOX_MAX_WORKSPACE_BYTES", 50 * 1024 * 1024),
        memory=(os.getenv("COMPOSE_SANDBOX_MEMORY") or "1g").strip() or "1g",
        cpus=(os.getenv("COMPOSE_SANDBOX_CPUS") or "2").strip() or "2",
        pids_limit=_int_env("COMPOSE_SANDBOX_PIDS_LIMIT", 128),
        user=(os.getenv("COMPOSE_SANDBOX_USER") or "1000:1000").strip() or "1000:1000",
        docker_bin=(os.getenv("DOCKER_BIN") or "docker").strip() or "docker",
    )


class ComposeSandboxManager:
    """Manage short-lived Docker workspaces for paper compose repair and verification."""

    ALLOWED_COMMANDS = {"xelatex", "python3", "ls", "cat"}
    _SAFE_XELATEX_PREFIXES = (
        "-interaction=",
        "-halt-on-error",
        "-file-line-error",
        "-synctex=0",
        "-no-pdf",
    )

    def __init__(self, config: Optional[ComposeSandboxConfig] = None) -> None:
        self.config = config or default_compose_sandbox_config()
        self._sessions: dict[str, ComposeSandboxSession] = {}

    async def open(
        self,
        session_id: Optional[str] = None,
        *,
        paper: Optional[Mapping[str, Any]] = None,
        files: Optional[Mapping[str, str | bytes]] = None,
    ) -> ComposeSandboxSession:
        await self.ensure_available()
        sid = self._safe_session_id(session_id)
        if sid in self._sessions and not self._sessions[sid].closed:
            raise SandboxSecurityError("compose_sandbox_session_exists")

        root = Path(self.config.root_dir).resolve()
        workspace = root / sid
        container_name = f"study-ai-compose-{sid[:48]}"
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        session = ComposeSandboxSession(
            session_id=sid,
            container_name=container_name,
            container_id="",
            workspace=workspace,
            created_at=time.monotonic(),
            expires_at=time.monotonic() + max(1, int(self.config.ttl_s or 900)),
        )

        try:
            self._bootstrap_workspace(session, paper=paper, files=files)
            created = await self._run_docker(self._docker_create_args(session), timeout_s=15)
            if created.returncode != 0:
                raise SandboxUnavailableError(created.stderr.strip() or "compose_sandbox_create_failed")
            session.container_id = (created.stdout or "").strip() or container_name

            started = await self._run_docker(["start", container_name], timeout_s=15)
            if started.returncode != 0:
                raise SandboxUnavailableError(started.stderr.strip() or "compose_sandbox_start_failed")
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        self._sessions[sid] = session
        return session

    async def write(self, session_id: str, path: str, content: str | bytes) -> dict[str, Any]:
        session = await self._require_session(session_id)
        data = content if isinstance(content, bytes) else str(content or "").encode("utf-8")
        target = self._resolve_workspace_path(session, path)
        self._write_bytes_checked(session, target, data)
        return {"session_id": session.session_id, "path": self._relative_path(session, target), "bytes": len(data)}

    async def read(self, session_id: str, path: str) -> str:
        session = await self._require_session(session_id)
        target = self._resolve_workspace_path(session, path)
        data = target.read_bytes()
        return data.decode("utf-8", errors="replace")

    async def run(
        self,
        session_id: str,
        command: str,
        args: Optional[Sequence[Any]] = None,
        *,
        timeout_s: Optional[int] = None,
    ) -> DockerCommandResult:
        session = await self._require_session(session_id)
        cmd, safe_args = self._validate_run_request(command, args or [])
        return await self._run_docker(
            ["exec", "--workdir", "/workspace", session.container_name, cmd, *safe_args],
            timeout_s=timeout_s or self.config.timeout_s,
        )

    async def patch_question(self, session_id: str, question_id: str, patch: Mapping[str, Any]) -> dict[str, Any]:
        session = await self._require_session(session_id)
        if not isinstance(patch, Mapping):
            raise SandboxSecurityError("compose_sandbox_patch_must_be_object")
        paper_path = self._resolve_workspace_path(session, "paper.json")
        paper = json.loads(paper_path.read_text(encoding="utf-8"))
        questions = paper.get("questions") if isinstance(paper, dict) else None
        if not isinstance(questions, list):
            raise SandboxSecurityError("compose_sandbox_paper_questions_missing")

        target_id = str(question_id or "").strip()
        if not target_id:
            raise SandboxSecurityError("compose_sandbox_question_id_missing")

        updated_question: Optional[dict[str, Any]] = None
        for item in questions:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("question_id") or item.get("id") or "").strip()
            if item_id == target_id:
                item.update(dict(patch))
                updated_question = item
                break
        if updated_question is None:
            raise KeyError(f"compose_sandbox_question_not_found: {target_id}")

        data = json.dumps(paper, ensure_ascii=False, indent=2).encode("utf-8")
        self._write_bytes_checked(session, paper_path, data)
        return {"session_id": session.session_id, "question": dict(updated_question)}

    async def export(self, session_id: str) -> dict[str, Any]:
        session = await self._require_session(session_id)
        files: list[dict[str, Any]] = []
        paper_path = session.workspace / "paper.json"
        if paper_path.exists() and paper_path.is_file():
            files.append({"path": "paper.json", "bytes": paper_path.stat().st_size})

        export_root = session.workspace / "export"
        if export_root.exists():
            for item in sorted(export_root.rglob("*")):
                if item.is_file():
                    files.append({"path": self._relative_path(session, item), "bytes": item.stat().st_size})

        return {"session_id": session.session_id, "workspace": str(session.workspace), "files": files}

    export_artifacts = export

    async def close(self, session_id: str, *, delete_workspace: Optional[bool] = None) -> dict[str, Any]:
        sid, session = self._lookup_session(session_id)
        if session is None:
            return {"session_id": sid, "closed": True, "missing": True}
        await self._cleanup_session(session, delete_workspace=delete_workspace)
        self._sessions.pop(session.session_id, None)
        return {"session_id": session.session_id, "closed": True}

    async def ensure_available(self) -> None:
        cfg = self.config
        if not str(cfg.image or "").strip():
            raise SandboxUnavailableError("compose_sandbox_image_missing")
        if not shutil.which(str(cfg.docker_bin or "docker")):
            raise SandboxUnavailableError("docker_not_found")

        inspected = await self._run_docker(["image", "inspect", str(cfg.image)], timeout_s=15)
        if inspected.returncode != 0:
            raise SandboxUnavailableError(inspected.stderr.strip() or "compose_sandbox_image_unavailable")

    async def cleanup_expired(self) -> int:
        now = time.monotonic()
        expired = [sid for sid, session in self._sessions.items() if not session.closed and now > session.expires_at]
        for sid in expired:
            await self.close(sid)
        return len(expired)

    def _docker_create_args(self, session: ComposeSandboxSession) -> list[str]:
        cfg = self.config
        pids = int(cfg.pids_limit or 128)
        return [
            "create",
            "--name",
            session.container_name,
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
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            "--tmpfs",
            "/home:rw,nosuid,nodev,size=64m",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{session.workspace.resolve()}:/workspace:rw",
            "--workdir",
            "/workspace",
            str(cfg.image),
            "tail",
            "-f",
            "/dev/null",
        ]

    async def _run_docker(self, args: Sequence[str], *, timeout_s: Optional[int] = None) -> DockerCommandResult:
        cfg = self.config
        try:
            proc = await asyncio.create_subprocess_exec(
                str(cfg.docker_bin),
                *[str(arg) for arg in args],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxUnavailableError("docker_not_found") from exc

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=max(1, int(timeout_s or cfg.timeout_s or 60)),
            )
        except asyncio.TimeoutError:
            if proc.returncode is None:
                proc.kill()
                await proc.communicate()
            return DockerCommandResult(returncode=124, stdout="", stderr="compose_sandbox_command_timeout")

        return DockerCommandResult(
            returncode=int(proc.returncode or 0),
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )

    async def _require_session(self, session_id: str) -> ComposeSandboxSession:
        _sid, session = self._lookup_session(session_id)
        if session is None or session.closed:
            raise SandboxUnavailableError("compose_sandbox_session_missing")
        if time.monotonic() > session.expires_at:
            await self._cleanup_session(session, delete_workspace=True)
            self._sessions.pop(session.session_id, None)
            raise SandboxExpiredError("compose_sandbox_session_expired")
        return session

    def _lookup_session(self, session_id: str) -> tuple[str, Optional[ComposeSandboxSession]]:
        raw = str(session_id or "").strip()
        if not raw:
            return "", None
        session = self._sessions.get(raw)
        if session is not None:
            return raw, session
        sid = self._safe_session_id(raw)
        return sid, self._sessions.get(sid)

    async def _cleanup_session(
        self,
        session: ComposeSandboxSession,
        *,
        delete_workspace: Optional[bool] = None,
    ) -> None:
        session.closed = True
        for args in (["kill", session.container_name], ["rm", "-f", session.container_name]):
            try:
                await self._run_docker(args, timeout_s=10)
            except SandboxUnavailableError:
                continue
        should_delete = self.config.delete_workspace_on_close if delete_workspace is None else bool(delete_workspace)
        if should_delete:
            self._delete_workspace(session.workspace)

    def _bootstrap_workspace(
        self,
        session: ComposeSandboxSession,
        *,
        paper: Optional[Mapping[str, Any]],
        files: Optional[Mapping[str, str | bytes]],
    ) -> None:
        for child in ("export", "export/assets", "scripts", "build"):
            (session.workspace / child).mkdir(parents=True, exist_ok=True)
        paper_data = json.dumps(dict(paper or {"questions": []}), ensure_ascii=False, indent=2).encode("utf-8")
        self._write_bytes_checked(session, session.workspace / "paper.json", paper_data)
        for rel_path, content in dict(files or {}).items():
            data = content if isinstance(content, bytes) else str(content or "").encode("utf-8")
            self._write_bytes_checked(session, self._resolve_workspace_path(session, str(rel_path)), data)

    def _write_bytes_checked(self, session: ComposeSandboxSession, target: Path, data: bytes) -> None:
        if len(data) > int(self.config.max_workspace_bytes or 0):
            raise SandboxSecurityError("compose_sandbox_workspace_size_exceeded")
        current = self._workspace_size(session.workspace, exclude=target)
        if current + len(data) > int(self.config.max_workspace_bytes or 0):
            raise SandboxSecurityError("compose_sandbox_workspace_size_exceeded")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _resolve_workspace_path(self, session: ComposeSandboxSession, relative_path: str) -> Path:
        raw = str(relative_path or "").replace("\\", "/").strip()
        if not raw or raw in {".", "/"} or "\x00" in raw:
            raise SandboxSecurityError("compose_sandbox_invalid_path")
        if raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
            raise SandboxSecurityError("compose_sandbox_absolute_path_rejected")
        parts = PurePosixPath(raw).parts
        if any(part in {"..", ""} for part in parts):
            raise SandboxSecurityError("compose_sandbox_path_traversal_rejected")
        candidate = (session.workspace / Path(*parts)).resolve()
        root = session.workspace.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise SandboxSecurityError("compose_sandbox_path_escape_rejected") from exc
        return candidate

    def _relative_path(self, session: ComposeSandboxSession, path: Path) -> str:
        return path.resolve().relative_to(session.workspace.resolve()).as_posix()

    def _workspace_size(self, root: Path, *, exclude: Optional[Path] = None) -> int:
        total = 0
        exclude_resolved = exclude.resolve() if exclude is not None and exclude.exists() else None
        for item in root.rglob("*"):
            try:
                if not item.is_file():
                    continue
                if exclude_resolved is not None and item.resolve() == exclude_resolved:
                    continue
                total += item.stat().st_size
            except OSError:
                continue
        return total

    def _validate_run_request(self, command: str, args: Sequence[Any]) -> tuple[str, list[str]]:
        cmd = str(command or "").strip()
        if cmd not in self.ALLOWED_COMMANDS:
            raise SandboxSecurityError("compose_sandbox_command_not_allowed")
        safe_args = [str(arg) for arg in list(args or [])]
        if any("\x00" in arg for arg in safe_args):
            raise SandboxSecurityError("compose_sandbox_invalid_argument")

        if cmd == "python3":
            if not safe_args:
                raise SandboxSecurityError("compose_sandbox_python_script_required")
            if safe_args[0].startswith("-"):
                raise SandboxSecurityError("compose_sandbox_python_inline_rejected")
            self._validate_relative_arg_path(safe_args[0])
            for arg in safe_args[1:]:
                self._reject_path_escape_tokens(arg)
            return cmd, safe_args

        if cmd == "xelatex":
            for arg in safe_args:
                lower = arg.lower()
                if "shell-escape" in lower or "write18" in lower:
                    raise SandboxSecurityError("compose_sandbox_xelatex_shell_escape_rejected")
                if arg.startswith("-"):
                    if not any(lower.startswith(prefix) for prefix in self._SAFE_XELATEX_PREFIXES):
                        raise SandboxSecurityError("compose_sandbox_xelatex_flag_rejected")
                    continue
                self._validate_relative_arg_path(arg)
            return cmd, safe_args

        if cmd == "ls":
            for arg in safe_args:
                if arg.startswith("-"):
                    if arg not in {"-l", "-a", "-la", "-al"}:
                        raise SandboxSecurityError("compose_sandbox_ls_flag_rejected")
                    continue
                self._validate_relative_arg_path(arg)
            return cmd, safe_args

        if cmd == "cat":
            for arg in safe_args:
                if arg.startswith("-"):
                    raise SandboxSecurityError("compose_sandbox_cat_flag_rejected")
                self._validate_relative_arg_path(arg)
            return cmd, safe_args

        return cmd, safe_args

    def _validate_relative_arg_path(self, value: str) -> None:
        raw = str(value or "").replace("\\", "/").strip()
        if not raw or raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
            raise SandboxSecurityError("compose_sandbox_argument_path_rejected")
        self._reject_path_escape_tokens(raw)

    def _reject_path_escape_tokens(self, value: str) -> None:
        raw = str(value or "").replace("\\", "/").strip()
        if ".." in PurePosixPath(raw).parts:
            raise SandboxSecurityError("compose_sandbox_argument_path_traversal_rejected")

    def _safe_session_id(self, session_id: Optional[str]) -> str:
        raw = str(session_id or "").strip() or f"session-{uuid.uuid4().hex[:12]}"
        sid = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-._")
        return (sid or f"session-{uuid.uuid4().hex[:12]}")[:64]

    def _delete_workspace(self, workspace: Path) -> None:
        root = Path(self.config.root_dir).resolve()
        target = workspace.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise SandboxSecurityError("compose_sandbox_workspace_delete_escape_rejected") from exc
        shutil.rmtree(target, ignore_errors=True)
