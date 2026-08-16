from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterable, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import model_name, model_param
from backend.generation.agentic.types import AgentRunSpec

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TASK_ROOT = (_REPO_ROOT / ".local" / "codex-runtime-agent").resolve()

DEFAULT_ALLOWED_TOOLS = "Read,Grep,Glob,Write,Edit,MultiEdit,Bash"
SAFE_APPROVAL_POLICIES = {"untrusted", "on-failure", "on-request", "never"}
SAFE_SANDBOX_MODES = {"read-only", "workspace-write"}
SAFE_PERMISSION_MODES = {"acceptEdits", "auto", "default", "dontAsk", "plan"}
DANGEROUS_PERMISSION_MODES = {"bypassPermissions"}

CODEX_RUNTIME_RESULT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "required": ["status", "summary", "result"],
    "properties": {
        "status": {"type": "string", "enum": ["completed", "failed", "cancelled", "canceled"]},
        "summary": {"type": "string"},
        "result": {"type": "object", "additionalProperties": True},
        "events": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "artifacts": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "error": {"type": "string"},
        "metadata": {"type": "object", "additionalProperties": True},
    },
}
CLAUDE_CODE_RESULT_SCHEMA = CODEX_RUNTIME_RESULT_SCHEMA


ProcessFactory = Callable[..., Awaitable[Any]]


class _ThreadedPipeReader:
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def readline(self) -> bytes:
        chunk = await asyncio.to_thread(self._stream.readline)
        if not chunk:
            await asyncio.to_thread(self._stream.close)
        return chunk

    async def read(self) -> bytes:
        try:
            return await asyncio.to_thread(self._stream.read)
        finally:
            await asyncio.to_thread(self._stream.close)


class _ThreadedPipeWriter:
    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._pending = bytearray()

    def write(self, chunk: bytes) -> None:
        self._pending.extend(chunk)

    async def drain(self) -> None:
        chunk = bytes(self._pending)
        self._pending.clear()
        if chunk:
            await asyncio.to_thread(self._write_and_flush, chunk)

    def _write_and_flush(self, chunk: bytes) -> None:
        self._stream.write(chunk)
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


class _ThreadedPopenProcess:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self.stdin = _ThreadedPipeWriter(process.stdin) if process.stdin is not None else None
        self.stdout = _ThreadedPipeReader(process.stdout) if process.stdout is not None else None
        self.stderr = _ThreadedPipeReader(process.stderr) if process.stderr is not None else None
        self.pid = process.pid

    @property
    def returncode(self) -> Optional[int]:
        return self._process.returncode

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()


async def _start_runtime_process(
    *cmd: str,
    process_factory: Optional[ProcessFactory] = None,
    **kwargs: Any,
) -> Any:
    factory = process_factory or asyncio.create_subprocess_exec
    try:
        return await factory(*cmd, **kwargs)
    except NotImplementedError:
        if os.name != "nt" or process_factory is not None:
            raise
        process = await asyncio.to_thread(subprocess.Popen, list(cmd), **kwargs)
        return _ThreadedPopenProcess(process)


def _resolve_runtime_executable(command: str) -> str:
    raw = str(command or "").strip()
    if os.name != "nt" or not raw:
        return raw
    return str(shutil.which(raw) or raw)


def _exception_message(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def _proxy_url(value: Any, *, scheme: str = "http") -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return raw
    return f"{scheme}://{raw}"


def _parse_windows_proxy_server(value: Any) -> Dict[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return {}
    if "=" not in raw:
        proxy = _proxy_url(raw)
        return {"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy} if proxy else {}

    parsed: Dict[str, str] = {}
    for item in raw.split(";"):
        name, separator, address = item.partition("=")
        if not separator:
            continue
        protocol = name.strip().lower()
        if protocol == "http":
            parsed["HTTP_PROXY"] = _proxy_url(address)
        elif protocol == "https":
            parsed["HTTPS_PROXY"] = _proxy_url(address)
        elif protocol.startswith("socks"):
            parsed["ALL_PROXY"] = _proxy_url(address, scheme="socks5")
    if parsed.get("HTTP_PROXY") and not parsed.get("HTTPS_PROXY"):
        parsed["HTTPS_PROXY"] = parsed["HTTP_PROXY"]
    return {key: value for key, value in parsed.items() if value}


def _windows_user_proxy_urls() -> Dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            proxy_server = winreg.QueryValueEx(key, "ProxyServer")[0] if enabled else ""
    except (OSError, TypeError, ValueError):
        return {}
    return _parse_windows_proxy_server(proxy_server)


def _codex_subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    explicit_proxy = _env_first("CODEX_RUNTIME_PROXY")
    if explicit_proxy:
        proxy = _proxy_url(explicit_proxy)
        for key in proxy_keys:
            env.pop(key.lower(), None)
            env[key] = proxy
        return env

    if any(str(env.get(key) or env.get(key.lower()) or "").strip() for key in proxy_keys):
        return env

    proxy_values = _windows_user_proxy_urls()
    for key, value in proxy_values.items():
        if value and not str(env.get(key) or env.get(key.lower()) or "").strip():
            env[key] = value
    return env


@dataclass
class CodexRuntimeConfig:
    command: str = "codex"
    model: str = ""
    effort: str = "high"
    approval_policy: str = "never"
    sandbox_mode: str = "workspace-write"
    permission_mode: str = "auto"
    allowed_tools: str = DEFAULT_ALLOWED_TOOLS
    timeout_s: float = 900.0
    max_budget_usd: str = ""
    task_root: Path = _TASK_ROOT

    @classmethod
    def from_env(cls) -> "CodexRuntimeConfig":
        return cls(
            command=_env_first("CODEX_RUNTIME_COMMAND", default="codex") or "codex",
            model=model_name("codex_runtime"),
            effort=str(model_param("codex_runtime_effort", "high") or "high").strip(),
            approval_policy=_normalize_approval_policy(
                _env_first("CODEX_RUNTIME_APPROVAL_POLICY", "CODEX_RUNTIME_PERMISSION_MODE", default="never")
            ),
            sandbox_mode=_normalize_sandbox_mode(
                _env_first("CODEX_RUNTIME_SANDBOX", "CODEX_RUNTIME_SANDBOX_MODE", default="workspace-write")
            ),
            permission_mode="auto",
            allowed_tools=_env_first("CODEX_RUNTIME_ALLOWED_TOOLS", default=DEFAULT_ALLOWED_TOOLS) or DEFAULT_ALLOWED_TOOLS,
            timeout_s=_float_env(
                "CODEX_RUNTIME_TIMEOUT_S",
                default=900.0,
                min_v=1.0,
                max_v=24 * 3600.0,
            ),
            max_budget_usd=_env_first("CODEX_RUNTIME_MAX_BUDGET_USD", default=""),
            task_root=Path(_env_first("CODEX_RUNTIME_TASK_ROOT", default=str(_TASK_ROOT))).resolve(),
        )

    def normalized(self) -> "CodexRuntimeConfig":
        return CodexRuntimeConfig(
            command=str(self.command or "codex").strip() or "codex",
            model=str(self.model or "").strip(),
            effort=str(self.effort or "").strip() or "high",
            approval_policy=_normalize_approval_policy(self.approval_policy or self.permission_mode or "never"),
            sandbox_mode=_normalize_sandbox_mode(self.sandbox_mode or "workspace-write"),
            permission_mode=_normalize_permission_mode(self.permission_mode or "auto"),
            allowed_tools=str(self.allowed_tools or "").strip() or DEFAULT_ALLOWED_TOOLS,
            timeout_s=max(0.001, float(self.timeout_s or 900.0)),
            max_budget_usd=str(self.max_budget_usd or "").strip(),
            task_root=Path(self.task_root or _TASK_ROOT).resolve(),
        )


ClaudeCodeConfig = CodexRuntimeConfig


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return str(default or "").strip()


def _float_env(*names: str, default: float, min_v: float, max_v: float) -> float:
    try:
        raw = _env_first(*names, default=str(default))
        value = float(raw or default)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(min_v), min(float(max_v), value))


def _truthy(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _normalize_permission_mode(value: str) -> str:
    raw = str(value or "").strip()
    if raw in SAFE_PERMISSION_MODES:
        return raw
    return "auto"


def _normalize_approval_policy(value: str) -> str:
    raw = str(value or "").strip()
    if raw in SAFE_APPROVAL_POLICIES:
        return raw
    legacy_map = {
        "auto": "never",
        "dontAsk": "never",
        "default": "on-request",
        "acceptEdits": "on-request",
        "plan": "on-request",
    }
    return legacy_map.get(raw, "never")


def _normalize_sandbox_mode(value: str) -> str:
    raw = str(value or "").strip()
    if raw in SAFE_SANDBOX_MODES:
        return raw
    if raw == "danger-full-access" and _truthy(os.getenv("CODEX_RUNTIME_ALLOW_DANGER_FULL_ACCESS")):
        return raw
    return "workspace-write"


def agent_runtime_name() -> str:
    return str(os.getenv("AGENT_RUNTIME") or "codex_runtime").strip().lower().replace("-", "_") or "codex_runtime"


def is_codex_runtime_agent_runtime() -> bool:
    return agent_runtime_name() in {"codex", "codex_runtime", "codexruntime", "claude", "claude_code", "claudecode"}


def is_claude_code_agent_runtime() -> bool:
    return is_codex_runtime_agent_runtime()


def legacy_agent_fallback_enabled() -> bool:
    return _truthy(_env_first("CODEX_RUNTIME_FALLBACK_LEGACY"), default=False)


def codex_runtime_metadata_defaults() -> Dict[str, Any]:
    config = CodexRuntimeConfig.from_env()
    return {
        "runtime": "codex_runtime",
        "codex_runtime_version": _env_first(
            "CODEX_RUNTIME_VERSION",
            "CODEX_CLI_VERSION",
            default="unknown",
        ),
        "approval_policy": config.approval_policy,
        "sandbox_mode": config.sandbox_mode,
    }


def claude_code_metadata_defaults() -> Dict[str, Any]:
    return codex_runtime_metadata_defaults()


def build_codex_runtime_command(
    *,
    prompt: str,
    schema: Dict[str, Any],
    task_dir: Path,
    add_dirs: Optional[Iterable[Path]] = None,
    config: Optional[CodexRuntimeConfig] = None,
    disable_shell_tool: bool = False,
) -> list[str]:
    cfg = (config or CodexRuntimeConfig.from_env()).normalized()
    output_path = Path(task_dir).resolve() / "agent-output.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        cfg.command,
        "--ask-for-approval",
        cfg.approval_policy,
        "--disable",
        "plugins",
        "--disable",
        "memories",
    ]
    if disable_shell_tool:
        cmd.extend(["--disable", "shell_tool"])
    cmd.extend(
        [
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--cd",
            str(Path(task_dir).resolve()),
            "--sandbox",
            cfg.sandbox_mode,
            "--output-last-message",
            str(output_path),
        ]
    )
    if cfg.model:
        cmd.extend(["--model", cfg.model])

    for directory in _dedupe_dirs([Path(task_dir), *(list(add_dirs or []))]):
        cmd.extend(["--add-dir", str(directory)])
    cmd.append("-")
    return cmd


def build_claude_code_command(
    *,
    prompt: str,
    schema: Dict[str, Any],
    task_dir: Path,
    add_dirs: Optional[Iterable[Path]] = None,
    config: Optional[CodexRuntimeConfig] = None,
) -> list[str]:
    return build_codex_runtime_command(
        prompt=prompt,
        schema=schema,
        task_dir=task_dir,
        add_dirs=add_dirs,
        config=config,
    )


def build_codex_runtime_prompt(
    *,
    task_type: str,
    request: Dict[str, Any],
    user_id: str,
    task_id: str,
    spec: AgentRunSpec,
) -> str:
    confirmation_hint = ""
    output_contract = spec.output_contract if isinstance(spec.output_contract, dict) else {}
    if output_contract.get("requires_confirmation"):
        confirmation_hint = (
            "待审输出：当任务需要人工确认且已生成待审核草稿时，最终 JSON 顶层 status 仍填 completed，"
            "并在 result 中填 status=pending_review、composeDraft={...}；不要改为失败，也不要保存为最终完成结果。\n"
        )
    input_instruction = "先读取当前工作目录中的 agent-input.json，并严格按其中的任务规格和请求完成任务。"
    task_hint = ""
    if str(task_type or "").strip() == "study_materials":
        inline_input = json.dumps(
            {"request": dict(request or {}), "agent_run_spec": spec.to_dict()},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        input_instruction = f"直接使用下列内联输入完成任务，无需读取其他文件：{inline_input}"
        task_hint = (
            "自学资料初次生成只返回 Markdown 正文，放在 result.material.markdown；"
            "不要生成或写入 Markdown、LaTeX、PDF 文件，LaTeX/PDF 由后续独立导出流程处理。\n"
        )
    return (
        "你是 Study AI 的本机 Codex runtime。\n"
        f"输入：{input_instruction}\n"
        "限制：不要读取或输出密钥、cookie、本地数据库或无关文件；不要请求交互式确认；不要绕过权限模式。\n"
        "最终响应必须只包含一个 JSON 对象，不要附加 Markdown 或说明。\n"
        "JSON 顶层至少包含 status、summary、result；成功时 status=completed，失败时 status=failed 并填写 error。\n"
        f"{task_hint}"
        f"{confirmation_hint}"
        f"任务类型：{str(task_type or spec.metadata.get('task_type') or spec.domain)}；任务 ID：{str(task_id or '')}。"
    )


def build_claude_code_prompt(
    *,
    task_type: str,
    request: Dict[str, Any],
    user_id: str,
    task_id: str,
    spec: AgentRunSpec,
) -> str:
    return build_codex_runtime_prompt(task_type=task_type, request=request, user_id=user_id, task_id=task_id, spec=spec)


async def run_codex_runtime_agent_events(
    *,
    task_type: str,
    request: Dict[str, Any],
    user_id: str,
    task_id: str,
    spec: Optional[AgentRunSpec] = None,
    config: Optional[CodexRuntimeConfig] = None,
    process_factory: Optional[ProcessFactory] = None,
    final_event_type: str = "done",
    prompt_override: str = "",
    result_schema: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    req = dict(request or {})
    spec_obj = spec or _build_spec_for_task(task_type=task_type, request=req)
    if spec_obj is None:
        yield _error_event("codex_runtime_agent_spec_missing", message="agent_run_spec_missing")
        return

    cfg = (config or CodexRuntimeConfig.from_env()).normalized()
    safe_task_id = _safe_task_id(task_id or req.get("taskId") or req.get("task_id") or f"{task_type}-{int(time.time())}")
    task_dir = (cfg.task_root / safe_task_id).resolve()
    task_dir.mkdir(parents=True, exist_ok=True)
    output_path = task_dir / "agent-output.json"
    with contextlib.suppress(FileNotFoundError):
        output_path.unlink()

    input_payload = {
        "task_type": str(task_type or spec_obj.metadata.get("task_type") or spec_obj.domain),
        "task_id": safe_task_id,
        "user_id": str(user_id or ""),
        "request": req,
        "agent_run_spec": spec_obj.to_dict(),
    }
    (task_dir / "agent-input.json").write_text(json.dumps(input_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    add_dirs = [task_dir, *_collect_input_dirs(req, allowed_roots=_allowed_input_roots(task_dir=task_dir, config=cfg))]
    prompt = str(prompt_override or "").strip() or build_codex_runtime_prompt(
        task_type=task_type,
        request=req,
        user_id=user_id,
        task_id=safe_task_id,
        spec=spec_obj,
    )
    cmd = build_codex_runtime_command(
        prompt=prompt,
        schema=result_schema if isinstance(result_schema, dict) and result_schema else CODEX_RUNTIME_RESULT_SCHEMA,
        task_dir=task_dir,
        add_dirs=add_dirs,
        config=cfg,
        disable_shell_tool=str(task_type or "").strip() == "study_materials",
    )
    cmd[0] = _resolve_runtime_executable(cmd[0])
    proc: Any = None
    stderr_task: Optional[asyncio.Task[str]] = None
    final_result: Optional[Dict[str, Any]] = None
    text_parts: list[str] = []

    try:
        proc = await _start_runtime_process(
            *cmd,
            process_factory=process_factory,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(task_dir),
            env=_codex_subprocess_env(),
        )
        proc_stdin = getattr(proc, "stdin", None)
        if proc_stdin is not None:
            proc_stdin.write(str(prompt or "").encode("utf-8"))
            await proc_stdin.drain()
            proc_stdin.close()
        stderr_task = asyncio.create_task(_read_stderr(proc))
        yield {
            "type": "status",
            "event": "status",
            "data": {"content": "Codex runtime started", "runtime": "codex_runtime", "task_dir": str(task_dir)},
        }

        try:
            async with asyncio.timeout(float(cfg.timeout_s)):
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    obj = _parse_json_line(line)
                    if obj is None:
                        text_parts.append(line)
                        yield {"type": "reasoning_delta", "event": "reasoning_delta", "data": {"content": line}}
                        continue

                    parsed_final = _final_result_from_stream_obj(obj)
                    if parsed_final is not None:
                        final_result = parsed_final
                        continue

                    for event in _events_from_stream_obj(obj):
                        yield event
                    text_parts.extend(_text_parts_from_stream_obj(obj))

                returncode = await proc.wait()
        except asyncio.TimeoutError:
            await _terminate_process(proc)
            if stderr_task is not None:
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task
            yield _error_event(
                "codex_runtime_timeout",
                message=f"Codex runtime exceeded {float(cfg.timeout_s):.3g}s timeout.",
            )
            return

        stderr = await stderr_task if stderr_task is not None else ""
        if returncode:
            yield _error_event(
                "codex_runtime_failed",
                message=f"Codex runtime exited with code {returncode}.",
                stderr=stderr,
                returncode=returncode,
            )
            return

        if final_result is None:
            final_result = _parse_agent_result_file(output_path) or _parse_agent_result("\n".join(text_parts))
        if final_result is None:
            yield _error_event(
                "codex_runtime_invalid_result",
                message="Codex runtime completed without a valid final JSON result.",
                stderr=stderr,
            )
            return

        if str(final_result.get("status") or "").strip().lower() not in {"completed", "success", "succeeded"}:
            yield _error_event(
                "codex_runtime_agent_failed",
                message=str(final_result.get("error") or final_result.get("summary") or "codex_runtime_agent_failed"),
                result=final_result.get("result") if isinstance(final_result.get("result"), dict) else {},
            )
            return

        for event in _events_from_final_result(final_result):
            yield event
        yield _final_event(final_result, final_event_type=final_event_type, task_id=safe_task_id)
    except asyncio.CancelledError:
        if proc is not None:
            await _terminate_process(proc)
        if stderr_task is not None:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
        raise
    except FileNotFoundError as exc:
        yield _error_event("codex_runtime_command_not_found", message=str(exc))
    except Exception as exc:  # pragma: no cover - defensive diagnostics for real subprocess edge cases.
        logger.exception("codex_runtime_agent_failed", extra={"task_id": task_id, "task_type": task_type})
        if proc is not None:
            await _terminate_process(proc)
        if stderr_task is not None:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
        yield _error_event("codex_runtime_exception", message=_exception_message(exc))


async def run_claude_code_agent_events(
    *,
    task_type: str,
    request: Dict[str, Any],
    user_id: str,
    task_id: str,
    spec: Optional[AgentRunSpec] = None,
    config: Optional[CodexRuntimeConfig] = None,
    process_factory: Optional[ProcessFactory] = None,
    final_event_type: str = "done",
) -> AsyncIterator[Dict[str, Any]]:
    async for event in run_codex_runtime_agent_events(
        task_type=task_type,
        request=request,
        user_id=user_id,
        task_id=task_id,
        spec=spec,
        config=config,
        process_factory=process_factory,
        final_event_type=final_event_type,
    ):
        yield event


async def run_codex_runtime_task(
    task: Any,
    *,
    user_id: str,
    task_type: Optional[str] = None,
    final_event_type: str = "done",
) -> bool:
    """Run a RuntimeTask through Codex runtime and complete/fail it via the existing task runtime."""

    if not is_codex_runtime_agent_runtime():
        return False

    from backend.shared.tasks import task_runtime

    ttype = str(task_type or getattr(task, "task_type", "") or "").strip()
    req = getattr(task, "request", None) if isinstance(getattr(task, "request", None), dict) else {}
    meta = getattr(task, "meta", None) if isinstance(getattr(task, "meta", None), dict) else {}
    spec = _spec_from_meta(meta) or _build_spec_for_task(task_type=ttype, request=req)
    if spec is None:
        if legacy_agent_fallback_enabled():
            return False
        msg = "agent_run_spec_missing"
        await task_runtime.fail_task(task, msg, error={"message": msg, "runtime": "codex_runtime"})
        return True

    completed = False
    async for event in run_codex_runtime_agent_events(
        task_type=ttype,
        request=req,
        user_id=user_id,
        task_id=str(getattr(task, "task_id", "") or ""),
        spec=spec,
        final_event_type=final_event_type,
    ):
        if str(getattr(task, "status", "running") or "") != "running":
            return True

        await task_runtime.append_event(task, event)
        kind = str(event.get("type") or event.get("event") or "").strip()
        if kind == "result":
            result = event.get("result") if isinstance(event.get("result"), dict) else {"result": event.get("result")}
            await task_runtime.complete_task(task, result=result)
            completed = True
            return True
        if kind == "done":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            result = data.get("result") if isinstance(data.get("result"), dict) else data
            await task_runtime.complete_task(task, result=result if isinstance(result, dict) else {"result": result})
            completed = True
            return True
        if kind == "error":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            msg = str(data.get("message") or data.get("error") or data.get("code") or "codex_runtime_failed").strip()
            await task_runtime.fail_task(task, msg, error={"message": msg, **data}, emit_event=False)
            return True

    if not completed and str(getattr(task, "status", "running") or "") == "running":
        await task_runtime.fail_task(task, "codex_runtime_ended_unexpectedly", error={"message": "codex_runtime_ended_unexpectedly"})
    return True


async def run_claude_code_task(
    task: Any,
    *,
    user_id: str,
    task_type: Optional[str] = None,
    final_event_type: str = "done",
) -> bool:
    return await run_codex_runtime_task(task, user_id=user_id, task_type=task_type, final_event_type=final_event_type)


def _build_spec_for_task(*, task_type: str, request: Dict[str, Any]) -> Optional[AgentRunSpec]:
    from backend.generation.agentic.task_specs import build_agent_run_spec_for_task

    return build_agent_run_spec_for_task(task_type=task_type, request=request)


def _spec_from_meta(meta: Dict[str, Any]) -> Optional[AgentRunSpec]:
    raw = meta.get("agent_run_spec") if isinstance(meta, dict) else None
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        return AgentRunSpec.from_dict(raw)
    except (TypeError, ValueError):
        return None


def _safe_task_id(value: Any) -> str:
    raw = str(value or "").strip() or "task"
    out = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")
    return out[:120] or "task"


def _dedupe_dirs(values: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for value in values:
        try:
            path = Path(value).resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _allowed_input_roots(*, task_dir: Path, config: CodexRuntimeConfig) -> list[Path]:
    roots = [
        task_dir,
        config.task_root,
        _REPO_ROOT / ".local" / "question_library" / "media_imports",
        _REPO_ROOT / ".local" / "media" / "generated",
    ]
    return _dedupe_dirs(root for root in roots if root.exists())


def _collect_input_dirs(value: Any, *, allowed_roots: Optional[Iterable[Path]] = None) -> list[Path]:
    roots = _dedupe_dirs(allowed_roots or [])
    dirs: list[Path] = []

    def visit(item: Any, key_hint: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, str(key or ""))
            return
        if isinstance(item, list):
            for child in item:
                visit(child, key_hint)
            return
        if not isinstance(item, str):
            return
        key = key_hint.lower()
        if not (key in {"path", "file_path", "filepath"} or key.endswith("_path") or key.endswith("path")):
            return
        raw = item.strip()
        if not raw or raw.startswith(("http://", "https://", "data:")):
            return
        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return
        if not path.exists():
            return
        directory = path if path.is_dir() else path.parent
        if roots and not any(_is_relative_to(directory, root) for root in roots):
            return
        dirs.append(directory)

    visit(value)
    return _dedupe_dirs(dirs)


def _parse_json_line(line: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _content_items(obj: Dict[str, Any]) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    content = message.get("content") if isinstance(message, dict) else obj.get("content")
    if isinstance(content, list):
        items.extend([dict(item) for item in content if isinstance(item, dict)])
    elif isinstance(content, dict):
        items.append(dict(content))
    return items


def _events_from_stream_obj(obj: Dict[str, Any]) -> list[Dict[str, Any]]:
    events: list[Dict[str, Any]] = []
    typ = str(obj.get("type") or "").strip()
    if typ == "system":
        events.append(
            {
                "type": "status",
                "event": "status",
                "data": {
                    "content": str(obj.get("subtype") or "codex_runtime_system"),
                    "runtime": "codex_runtime",
                    "session_id": obj.get("session_id"),
                },
            }
        )
    for item in _content_items(obj):
        item_type = str(item.get("type") or "").strip()
        if item_type == "tool_use":
            events.append(
                {
                    "type": "tool_call",
                    "event": "tool_call",
                    "data": {
                        "id": str(item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "arguments": item.get("input") if isinstance(item.get("input"), dict) else {},
                        "runtime": "codex_runtime",
                    },
                }
            )
        elif item_type == "tool_result":
            events.append(
                {
                    "type": "tool_result",
                    "event": "tool_result",
                    "data": {
                        "id": str(item.get("tool_use_id") or item.get("id") or ""),
                        "content": item.get("content"),
                        "is_error": bool(item.get("is_error")),
                        "runtime": "codex_runtime",
                    },
                }
            )
        elif item_type == "text":
            text = str(item.get("text") or "")
            if text:
                events.append({"type": "reasoning_delta", "event": "reasoning_delta", "data": {"content": text}})
    if typ == "error":
        message = str(obj.get("error") or obj.get("message") or "")
        events.append(
            {
                "type": "status",
                "event": "status",
                "data": {
                    "content": message or "Codex runtime stream warning",
                    "message": message,
                    "code": "codex_runtime_stream_error",
                    "level": "warning",
                    "runtime": "codex_runtime",
                },
            }
        )
    return events


def _text_parts_from_stream_obj(obj: Dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for item in _content_items(obj):
        if str(item.get("type") or "") == "text" and str(item.get("text") or ""):
            parts.append(str(item.get("text") or ""))
    delta = obj.get("delta") if isinstance(obj.get("delta"), dict) else {}
    if str(delta.get("text") or ""):
        parts.append(str(delta.get("text") or ""))
    if isinstance(obj.get("content"), str) and obj.get("content"):
        parts.append(str(obj.get("content")))
    return parts


def _final_result_from_stream_obj(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    typ = str(obj.get("type") or "").strip()
    if typ == "result":
        if isinstance(obj.get("result"), dict):
            return _normalize_agent_result(obj.get("result"))
        parsed = _parse_agent_result(str(obj.get("result") or ""))
        if parsed is not None:
            return parsed
    return None


def _parse_agent_result(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return _normalize_agent_result(value)
    text = str(value or "").strip()
    if not text:
        return None
    parsed = _parse_json_object_text(text)
    return _normalize_agent_result(parsed) if isinstance(parsed, dict) else None


def _parse_agent_result_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        return _parse_agent_result(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _parse_json_object_text(text: str) -> Optional[Dict[str, Any]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(cleaned):
        if ch != "{":
            continue
        with contextlib.suppress(json.JSONDecodeError):
            obj, _end = decoder.raw_decode(cleaned[idx:])
            if isinstance(obj, dict):
                return obj
    return None


def _normalize_agent_result(obj: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(obj or {})
    looks_like_result = any(key in data for key in {"status", "summary", "result", "events", "artifacts", "error"})
    if not looks_like_result:
        data = {"status": "completed", "summary": "", "result": data}

    status = str(data.get("status") or ("failed" if data.get("error") else "completed")).strip().lower()
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    if not result and "result" in data and data.get("result") is not None and not isinstance(data.get("result"), dict):
        result = {"value": data.get("result")}

    return {
        "status": status,
        "summary": str(data.get("summary") or ""),
        "result": result,
        "events": [dict(item) for item in data.get("events", []) if isinstance(item, dict)]
        if isinstance(data.get("events"), list)
        else [],
        "artifacts": [dict(item) for item in data.get("artifacts", []) if isinstance(item, dict)]
        if isinstance(data.get("artifacts"), list)
        else [],
        "error": str(data.get("error") or ""),
        "metadata": dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {},
    }


def _events_from_final_result(result: Dict[str, Any]) -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    for item in result.get("events") or []:
        if not isinstance(item, dict):
            continue
        event = dict(item)
        event_type = str(event.get("type") or event.get("event") or "status").strip() or "status"
        event["type"] = event_type
        event.setdefault("event", event_type)
        event.setdefault("data", {})
        out.append(event)
    if not any(str(event.get("type") or "").strip() == "text_delta" for event in out):
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        material = payload.get("material") if isinstance(payload.get("material"), dict) else {}
        markdown = str(material.get("markdown") or "").strip()
        if markdown:
            out.append({"type": "text_delta", "event": "text_delta", "data": {"content": markdown}})
    return out


def _pending_review_event_from_payload(
    payload: Dict[str, Any],
    *,
    result: Dict[str, Any],
    task_id: str,
) -> Optional[Dict[str, Any]]:
    draft = payload.get("composeDraft") if isinstance(payload.get("composeDraft"), dict) else payload.get("compose_draft")
    if not isinstance(draft, dict) or not draft:
        return None

    metadata = {"runtime": "codex_runtime", **(result.get("metadata") if isinstance(result.get("metadata"), dict) else {})}
    data = {
        "success": True,
        "summary": result.get("summary") or "",
        "status": "pending_review",
        "runtime": "codex_runtime",
        "composeDraft": draft,
        "result": payload,
        "metadata": metadata,
    }
    return {
        "type": "pending_review",
        "event": "pending_review",
        "taskId": str(payload.get("taskId") or payload.get("task_id") or task_id or ""),
        "composeDraft": draft,
        "data": data,
    }


def _final_event(result: Dict[str, Any], *, final_event_type: str, task_id: str = "") -> Dict[str, Any]:
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    payload = dict(payload)
    payload.setdefault("native_agentic", True)
    payload.setdefault("runtime", "codex_runtime")
    if result.get("artifacts"):
        payload.setdefault("artifacts", result.get("artifacts"))

    pending_review = _pending_review_event_from_payload(payload, result=result, task_id=task_id)
    if pending_review is not None:
        return pending_review

    pending_status = str(payload.get("status") or payload.get("task_status") or "").strip().lower()
    has_compose_draft = "composeDraft" in payload or "compose_draft" in payload
    if pending_status == "pending_review" or has_compose_draft:
        return _error_event(
            "codex_runtime_invalid_pending_review",
            message="Codex runtime returned pending review without a valid composeDraft.",
            result=payload,
        )

    data = {
        "success": True,
        "summary": result.get("summary") or "",
        "runtime": "codex_runtime",
        "result": payload,
        "metadata": {"runtime": "codex_runtime", **(result.get("metadata") if isinstance(result.get("metadata"), dict) else {})},
    }
    for key, value in payload.items():
        data.setdefault(key, value)

    if str(final_event_type or "").strip() == "result":
        return {"type": "result", "result": payload, "data": data}
    return {"type": "done", "event": "done", "data": data}


def _error_event(code: str, *, message: str = "", **extra: Any) -> Dict[str, Any]:
    data = {"code": str(code or "codex_runtime_error"), "message": str(message or code or "codex_runtime_error"), **extra}
    return {"type": "error", "event": "error", "data": data, "error": data["code"]}


async def _read_stderr(proc: Any) -> str:
    stream = getattr(proc, "stderr", None)
    if stream is None:
        return ""
    with contextlib.suppress(Exception):
        raw = await stream.read()
        return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
    return ""


async def _terminate_process(proc: Any) -> None:
    pid = getattr(proc, "pid", None)
    if os.name == "nt" and isinstance(pid, int) and pid > 0:
        with contextlib.suppress(Exception):
            taskkill = await asyncio.create_subprocess_exec(
                "taskkill.exe",
                "/PID",
                str(pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            taskkill_returncode = await asyncio.wait_for(taskkill.wait(), timeout=5.0)
            if taskkill_returncode == 0:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                return
    with contextlib.suppress(Exception):
        proc.terminate()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=2.0)
        return
    with contextlib.suppress(Exception):
        proc.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), timeout=2.0)
