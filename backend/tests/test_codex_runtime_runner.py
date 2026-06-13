from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.generation.agentic.types import AgentRunSpec, AgentToolPolicy


class _FakeStream:
    def __init__(self, chunks: list[bytes], *, delay_s: float = 0.0) -> None:
        self._chunks = list(chunks)
        self._delay_s = float(delay_s)

    async def readline(self) -> bytes:
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def read(self) -> bytes:
        chunks = list(self._chunks)
        self._chunks.clear()
        return b"".join(chunks)


class _FakeProcess:
    def __init__(self, *, stdout: list[dict[str, Any]] | None = None, stderr: str = "", returncode: int = 0) -> None:
        lines = [(json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8") for item in (stdout or [])]
        self.stdout = _FakeStream(lines)
        self.stderr = _FakeStream([stderr.encode("utf-8")])
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _spec() -> AgentRunSpec:
    return AgentRunSpec(
        domain="deepthink",
        goal="求解题目",
        subject="高中数学",
        input_payload={"question": "已知 f(x)=x^2，求单调区间"},
        tool_policy=AgentToolPolicy(allowed_tools=["Read", "Grep"]),
    )


class CodexRuntimeRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_build_command_uses_supported_codex_exec_flags(self) -> None:
        from backend.generation.agentic.codex_runtime import (
            CODEX_RUNTIME_RESULT_SCHEMA,
            CodexRuntimeConfig,
            build_codex_runtime_command,
        )

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            config = CodexRuntimeConfig(command="codex", task_root=task_dir)
            cmd = build_codex_runtime_command(
                prompt="完成任务",
                schema=CODEX_RUNTIME_RESULT_SCHEMA,
                task_dir=task_dir,
                add_dirs=[task_dir],
                config=config,
            )

        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertIn("--json", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--cd", cmd)
        self.assertIn("--output-schema", cmd)
        self.assertIn("--output-last-message", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--ask-for-approval", cmd)
        self.assertEqual(cmd[cmd.index("--ask-for-approval") + 1], "never")
        joined = " ".join(cmd)
        self.assertNotIn("Claude Code", joined)
        self.assertNotIn("--bare", cmd)
        self.assertNotIn("--permission-mode", cmd)
        self.assertNotIn("--allowedTools", cmd)
        self.assertNotIn("bypassPermissions", joined)

    async def test_stream_json_maps_tools_reasoning_and_final_result(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        captured: dict[str, Any] = {}

        async def fake_process_factory(*cmd: str, **kwargs: Any) -> _FakeProcess:
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeProcess(
                stdout=[
                    {"type": "system", "subtype": "init", "session_id": "s1"},
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"file_path": "agent-input.json"}}
                            ]
                        },
                    },
                    {
                        "type": "user",
                        "message": {"content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}]},
                    },
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "正在整理答案"}]}},
                    {
                        "type": "result",
                        "result": json.dumps(
                            {"status": "completed", "summary": "完成", "result": {"ok": True}},
                            ensure_ascii=False,
                        ),
                    },
                ]
            )

        with tempfile.TemporaryDirectory() as tmp:
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "x^2"},
                    user_id="u-1",
                    task_id="task-1",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        self.assertEqual(captured["cmd"][:2], ("codex", "exec"))
        self.assertEqual(events[0]["data"]["runtime"], "codex_runtime")
        self.assertNotIn("Claude Code", events[0]["data"]["content"])
        self.assertIn("tool_call", [event.get("type") for event in events])
        self.assertIn("tool_result", [event.get("type") for event in events])
        self.assertIn("reasoning_delta", [event.get("type") for event in events])
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["ok"], True)
        self.assertEqual(events[-1]["data"]["runtime"], "codex_runtime")
        self.assertEqual(events[-1]["data"]["metadata"]["runtime"], "codex_runtime")

    async def test_request_paths_do_not_grant_arbitrary_add_dir_access(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        captured: dict[str, Any] = {}

        async def fake_process_factory(*cmd: str, **kwargs: Any) -> _FakeProcess:
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeProcess(
                stdout=[
                    {
                        "type": "result",
                        "result": json.dumps(
                            {"status": "completed", "summary": "完成", "result": {"ok": True}},
                            ensure_ascii=False,
                        ),
                    }
                ]
            )

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            outside_dir = Path(outside).resolve()
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "x^2", "options": {"archive_path": str(outside_dir)}},
                    user_id="u-1",
                    task_id="task-path",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        cmd = list(captured["cmd"])
        add_dirs = [Path(cmd[i + 1]).resolve() for i, item in enumerate(cmd[:-1]) if item == "--add-dir"]
        self.assertNotIn(outside_dir, add_dirs)
        self.assertEqual(events[-1]["type"], "result")

    async def test_nonzero_exit_reports_stderr(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        async def fake_process_factory(*_cmd: str, **_kwargs: Any) -> _FakeProcess:
            return _FakeProcess(stdout=[], stderr="codex failed", returncode=2)

        with tempfile.TemporaryDirectory() as tmp:
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={},
                    user_id="u-1",
                    task_id="task-2",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                )
            ]

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["data"]["code"], "codex_runtime_failed")
        self.assertIn("codex failed", events[-1]["data"]["stderr"])

    async def test_timeout_terminates_process(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        created: dict[str, _FakeProcess] = {}

        async def fake_process_factory(*_cmd: str, **_kwargs: Any) -> _FakeProcess:
            proc = _FakeProcess(stdout=[], returncode=0)
            proc.stdout = _FakeStream([], delay_s=0.1)
            created["proc"] = proc
            return proc

        with tempfile.TemporaryDirectory() as tmp:
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={},
                    user_id="u-1",
                    task_id="task-3",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=0.01),
                    process_factory=fake_process_factory,
                )
            ]

        self.assertTrue(created["proc"].terminated)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["data"]["code"], "codex_runtime_timeout")

    async def test_cancellation_terminates_process(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        created: dict[str, _FakeProcess] = {}

        async def fake_process_factory(*_cmd: str, **_kwargs: Any) -> _FakeProcess:
            proc = _FakeProcess(stdout=[], returncode=0)
            proc.stdout = _FakeStream([], delay_s=1.0)
            created["proc"] = proc
            return proc

        async def collect() -> list[dict[str, Any]]:
            with tempfile.TemporaryDirectory() as tmp:
                return [
                    event
                    async for event in run_codex_runtime_agent_events(
                        task_type="deepthink",
                        request={},
                        user_id="u-1",
                        task_id="task-4",
                        spec=_spec(),
                        config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=10),
                        process_factory=fake_process_factory,
                    )
                ]

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.03)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(created["proc"].terminated)

    def test_legacy_claude_runtime_name_still_activates_codex_metadata(self) -> None:
        from unittest.mock import patch

        from backend.generation.agentic.codex_runtime import (
            agent_runtime_name,
            codex_runtime_metadata_defaults,
            is_codex_runtime_agent_runtime,
        )

        with patch.dict("os.environ", {"AGENT_RUNTIME": "claude_code"}, clear=False):
            self.assertEqual(agent_runtime_name(), "claude_code")
            self.assertTrue(is_codex_runtime_agent_runtime())
            metadata = codex_runtime_metadata_defaults()

        self.assertEqual(metadata["runtime"], "codex_runtime")
        self.assertIn("codex_runtime_version", metadata)

    def test_legacy_claude_command_env_does_not_override_codex_cli(self) -> None:
        from unittest.mock import patch

        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig

        with patch.dict(
            "os.environ",
            {"AGENT_RUNTIME": "claude_code", "CLAUDE_CODE_COMMAND": "claude", "CLAUDE_CODE_MODEL": "sonnet"},
            clear=False,
        ):
            config = CodexRuntimeConfig.from_env()

        self.assertEqual(config.command, "codex")
        self.assertEqual(config.model, "")


if __name__ == "__main__":
    unittest.main()
