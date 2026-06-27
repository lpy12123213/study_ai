from __future__ import annotations

import asyncio
import json
import sys
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


class _FakeStdin:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, chunk: bytes) -> None:
        self.data.extend(chunk)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: list[dict[str, Any]] | None = None,
        stderr: str = "",
        returncode: int = 0,
        pid: int | None = None,
    ) -> None:
        lines = [(json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8") for item in (stdout or [])]
        self.stdout = _FakeStream(lines)
        self.stderr = _FakeStream([stderr.encode("utf-8")])
        self.stdin = _FakeStdin()
        self.returncode = returncode
        self.pid = pid
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
    @unittest.skipUnless(sys.platform == "win32", "Windows selector-loop regression")
    def test_windows_selector_loop_falls_back_to_threaded_subprocess(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        async def collect_events(task_root: Path) -> list[dict[str, Any]]:
            return [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "x^2"},
                    user_id="u-1",
                    task_id="selector-loop",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command=sys.executable, task_root=task_root, timeout_s=5),
                )
            ]

        with tempfile.TemporaryDirectory() as tmp:
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                events = runner.run(collect_events(Path(tmp)))

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["data"]["code"], "codex_runtime_failed")
        self.assertNotEqual(events[-1]["data"]["code"], "codex_runtime_exception")

    async def test_empty_runtime_exception_uses_exception_class_name(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        async def failing_factory(*cmd: str, **kwargs: Any) -> _FakeProcess:
            raise RuntimeError()

        with tempfile.TemporaryDirectory() as tmp, self.assertLogs(
            "backend.generation.agentic.claude_code", level="ERROR"
        ):
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "x^2"},
                    user_id="u-1",
                    task_id="empty-error",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=failing_factory,
                )
            ]

        self.assertEqual(events[-1]["data"]["code"], "codex_runtime_exception")
        self.assertEqual(events[-1]["data"]["message"], "RuntimeError")

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
                disable_shell_tool=True,
            )

        self.assertEqual(cmd[0], "codex")
        self.assertIn("exec", cmd)
        self.assertIn("--json", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--cd", cmd)
        self.assertNotIn("--output-schema", cmd)
        self.assertIn("--output-last-message", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--ask-for-approval", cmd)
        self.assertEqual(cmd[cmd.index("--ask-for-approval") + 1], "never")
        self.assertLess(cmd.index("--ask-for-approval"), cmd.index("exec"))
        self.assertIn("--disable", cmd)
        disabled_features = [cmd[index + 1] for index, item in enumerate(cmd[:-1]) if item == "--disable"]
        self.assertIn("plugins", disabled_features)
        self.assertIn("memories", disabled_features)
        self.assertIn("shell_tool", disabled_features)
        self.assertLess(cmd.index("--disable"), cmd.index("exec"))
        joined = " ".join(cmd)
        self.assertNotIn("Claude Code", joined)
        self.assertNotIn("--bare", cmd)
        self.assertNotIn("--permission-mode", cmd)
        self.assertNotIn("--allowedTools", cmd)
        self.assertNotIn("bypassPermissions", joined)
        self.assertEqual(cmd[-1], "-")
        self.assertNotIn("完成任务", cmd)

    def test_paper_compose_prompt_describes_pending_review_result_contract(self) -> None:
        from backend.generation.agentic.codex_runtime import build_codex_runtime_prompt
        from backend.generation.agentic.task_specs import build_agent_run_spec_for_task

        spec = build_agent_run_spec_for_task(
            task_type="paper_compose",
            request={"subject": "高中数学", "paperName": "待审卷"},
        )

        prompt = build_codex_runtime_prompt(
            task_type="paper_compose",
            request={"subject": "高中数学", "paperName": "待审卷"},
            user_id="u-1",
            task_id="task-review",
            spec=spec,
        )

        self.assertIn("pending_review", prompt)
        self.assertIn("composeDraft", prompt)
        self.assertIn("agent-input.json", prompt)
        self.assertNotIn('"agent_run_spec"', prompt)
        self.assertLess(len(prompt), 1200)

    def test_study_materials_prompt_inlines_input_and_defers_file_exports(self) -> None:
        from backend.generation.agentic.codex_runtime import build_codex_runtime_prompt
        from backend.generation.agentic.study_materials import build_study_materials_agent_spec

        request = {"query": "函数单调性", "subject": "高中数学", "options": {"preset": "quick"}}
        spec = build_study_materials_agent_spec(
            query=request["query"],
            subject=request["subject"],
            options=request["options"],
        )

        prompt = build_codex_runtime_prompt(
            task_type="study_materials",
            request=request,
            user_id="u-1",
            task_id="study-1",
            spec=spec,
        )

        self.assertIn('"query":"函数单调性"', prompt)
        self.assertIn("result.material.markdown", prompt)
        self.assertIn("不要生成或写入 Markdown、LaTeX、PDF 文件", prompt)

    def test_final_study_material_markdown_is_emitted_as_text_delta(self) -> None:
        from backend.generation.agentic.claude_code import _events_from_final_result

        events = _events_from_final_result(
            {
                "events": [],
                "result": {"material": {"markdown": "# 函数单调性\n\n正文"}},
            }
        )

        self.assertEqual(events, [{"type": "text_delta", "event": "text_delta", "data": {"content": "# 函数单调性\n\n正文"}}])

    async def test_stream_json_maps_tools_reasoning_and_final_result(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        captured: dict[str, Any] = {}

        async def fake_process_factory(*cmd: str, **kwargs: Any) -> _FakeProcess:
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            proc = _FakeProcess(
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
            captured["proc"] = proc
            return proc

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

        self.assertIn(Path(captured["cmd"][0]).name.lower(), {"codex", "codex.cmd", "codex.exe"})
        self.assertIn("exec", captured["cmd"])
        self.assertIn("Study AI", bytes(captured["proc"].stdin.data).decode("utf-8"))
        self.assertTrue(captured["proc"].stdin.closed)
        self.assertEqual(events[0]["data"]["runtime"], "codex_runtime")
        self.assertNotIn("Claude Code", events[0]["data"]["content"])
        self.assertIn("tool_call", [event.get("type") for event in events])
        self.assertIn("tool_result", [event.get("type") for event in events])
        self.assertIn("reasoning_delta", [event.get("type") for event in events])
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["ok"], True)
        self.assertEqual(events[-1]["data"]["runtime"], "codex_runtime")
        self.assertEqual(events[-1]["data"]["metadata"]["runtime"], "codex_runtime")

    async def test_windows_runtime_resolves_bare_codex_to_cmd_shim_before_launch(self) -> None:
        from unittest.mock import patch

        from backend.generation.agentic import claude_code

        captured: dict[str, Any] = {}

        async def fake_process_factory(*cmd: str, **_kwargs: Any) -> _FakeProcess:
            captured["cmd"] = cmd
            return _FakeProcess(
                stdout=[
                    {
                        "type": "result",
                        "result": json.dumps({"status": "completed", "summary": "完成", "result": {"ok": True}}),
                    }
                ]
            )

        resolved = r"C:\Users\tester\AppData\Roaming\npm\codex.cmd"
        with tempfile.TemporaryDirectory() as tmp, patch.object(claude_code.os, "name", "nt"), patch(
            "shutil.which",
            return_value=resolved,
        ):
            events = [
                event
                async for event in claude_code.run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "1+1"},
                    user_id="u-1",
                    task_id="task-windows-command",
                    spec=_spec(),
                    config=claude_code.CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        self.assertEqual(captured["cmd"][0], resolved)
        self.assertEqual(events[-1]["type"], "result")

    async def test_runtime_inherits_windows_user_proxy_when_proxy_env_is_missing(self) -> None:
        import os
        from unittest.mock import patch

        from backend.generation.agentic import claude_code

        captured: dict[str, Any] = {}

        async def fake_process_factory(*_cmd: str, **kwargs: Any) -> _FakeProcess:
            captured["kwargs"] = kwargs
            return _FakeProcess(
                stdout=[
                    {
                        "type": "result",
                        "result": json.dumps({"status": "completed", "summary": "完成", "result": {"ok": True}}),
                    }
                ]
            )

        empty_proxy_env = {
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "CODEX_RUNTIME_PROXY": "",
        }
        detected_proxy = {
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "HTTPS_PROXY": "http://127.0.0.1:7897",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, empty_proxy_env, clear=False), patch.object(
            claude_code,
            "_windows_user_proxy_urls",
            return_value=detected_proxy,
            create=True,
        ):
            events = [
                event
                async for event in claude_code.run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "1+1"},
                    user_id="u-1",
                    task_id="task-windows-proxy",
                    spec=_spec(),
                    config=claude_code.CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        child_env = captured["kwargs"].get("env")
        self.assertIsInstance(child_env, dict)
        self.assertEqual(child_env["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(child_env["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(events[-1]["type"], "result")

    async def test_codex_runtime_proxy_overrides_existing_proxy_env(self) -> None:
        import os
        from unittest.mock import patch

        from backend.generation.agentic import claude_code

        captured: dict[str, Any] = {}

        async def fake_process_factory(*_cmd: str, **kwargs: Any) -> _FakeProcess:
            captured["kwargs"] = kwargs
            return _FakeProcess(
                stdout=[
                    {
                        "type": "result",
                        "result": json.dumps({"status": "completed", "summary": "完成", "result": {"ok": True}}),
                    }
                ]
            )

        proxy_env = {
            "HTTP_PROXY": "http://127.0.0.1:1111",
            "HTTPS_PROXY": "http://127.0.0.1:1111",
            "ALL_PROXY": "",
            "CODEX_RUNTIME_PROXY": "127.0.0.1:7897",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, proxy_env, clear=False):
            events = [
                event
                async for event in claude_code.run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "1+1"},
                    user_id="u-1",
                    task_id="task-explicit-proxy",
                    spec=_spec(),
                    config=claude_code.CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        child_env = captured["kwargs"].get("env")
        self.assertIsInstance(child_env, dict)
        self.assertEqual(child_env["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(child_env["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(child_env["ALL_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(events[-1]["type"], "result")

    async def test_output_last_message_file_is_read_for_current_codex_jsonl(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        async def fake_process_factory(*cmd: str, **_kwargs: Any) -> _FakeProcess:
            output_path = Path(cmd[cmd.index("--output-last-message") + 1])
            output_path.write_text(
                json.dumps({"status": "completed", "summary": "完成", "result": {"ok": True}}),
                encoding="utf-8",
            )
            return _FakeProcess(
                stdout=[
                    {"type": "thread.started", "thread_id": "thread-1"},
                    {"type": "turn.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item-1",
                            "type": "agent_message",
                            "text": '{"status":"completed","summary":"完成","result":{"ok":true}}',
                        },
                    },
                    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
                ]
            )

        with tempfile.TemporaryDirectory() as tmp:
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "1+1"},
                    user_id="u-1",
                    task_id="task-output-file",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        self.assertEqual(events[-1]["type"], "result")
        self.assertTrue(events[-1]["result"]["ok"])

    async def test_stale_output_last_message_is_removed_before_launch(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        async def fake_process_factory(*_cmd: str, **_kwargs: Any) -> _FakeProcess:
            return _FakeProcess(stdout=[])

        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task-stale-output"
            task_dir.mkdir(parents=True)
            output_path = task_dir / "agent-output.json"
            output_path.write_text(
                json.dumps({"status": "completed", "summary": "旧结果", "result": {"stale": True}}),
                encoding="utf-8",
            )
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={"question": "1+1"},
                    user_id="u-1",
                    task_id="task-stale-output",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["data"]["code"], "codex_runtime_invalid_result")

    async def test_final_result_pending_review_maps_to_pending_review_event(self) -> None:
        from backend.generation.agentic.codex_runtime import CodexRuntimeConfig, run_codex_runtime_agent_events

        draft = {
            "paperName": "待审卷",
            "subject": "高中数学",
            "questions": [{"question_id": "q-codex", "stem": "待审题"}],
        }

        async def fake_process_factory(*_cmd: str, **_kwargs: Any) -> _FakeProcess:
            return _FakeProcess(
                stdout=[
                    {
                        "type": "result",
                        "result": json.dumps(
                            {
                                "status": "completed",
                                "summary": "等待人工审核",
                                "result": {"status": "pending_review", "composeDraft": draft},
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )

        with tempfile.TemporaryDirectory() as tmp:
            events = [
                event
                async for event in run_codex_runtime_agent_events(
                    task_type="paper_compose",
                    request={"subject": "高中数学", "paperName": "待审卷"},
                    user_id="u-1",
                    task_id="task-review",
                    spec=_spec(),
                    config=CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=5),
                    process_factory=fake_process_factory,
                    final_event_type="result",
                )
            ]

        self.assertEqual(events[-1]["type"], "pending_review")
        self.assertEqual(events[-1]["event"], "pending_review")
        self.assertEqual(events[-1]["taskId"], "task-review")
        self.assertEqual(events[-1]["composeDraft"], draft)
        self.assertEqual(events[-1]["data"]["runtime"], "codex_runtime")

    def test_compose_draft_is_pending_review_even_without_nested_status(self) -> None:
        from backend.generation.agentic.claude_code import _final_event

        draft = {"paperName": "待审卷", "questions": [{"question_id": "q-codex"}]}

        event = _final_event(
            {"status": "completed", "summary": "等待人工审核", "result": {"composeDraft": draft}},
            final_event_type="result",
            task_id="task-review",
        )

        self.assertEqual(event["type"], "pending_review")
        self.assertEqual(event["composeDraft"], draft)

    def test_pending_review_without_valid_compose_draft_is_an_error(self) -> None:
        from backend.generation.agentic.claude_code import _final_event

        event = _final_event(
            {"status": "completed", "summary": "等待人工审核", "result": {"status": "pending_review"}},
            final_event_type="result",
            task_id="task-review",
        )

        self.assertEqual(event["type"], "error")
        self.assertEqual(event["data"]["code"], "codex_runtime_invalid_pending_review")

    def test_cli_reconnect_diagnostic_is_not_a_terminal_error(self) -> None:
        from backend.generation.agentic.claude_code import _events_from_stream_obj

        events = _events_from_stream_obj(
            {"type": "error", "message": "Reconnecting... 2/5 (request timed out)"}
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "status")
        self.assertEqual(events[0]["data"]["level"], "warning")
        self.assertEqual(events[0]["data"]["code"], "codex_runtime_stream_error")

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

    async def test_windows_timeout_terminates_process_tree(self) -> None:
        from unittest.mock import patch

        from backend.generation.agentic import claude_code

        taskkill_calls: list[tuple[str, ...]] = []

        async def fake_process_factory(*_cmd: str, **_kwargs: Any) -> _FakeProcess:
            proc = _FakeProcess(stdout=[], returncode=0, pid=4242)
            proc.stdout = _FakeStream([], delay_s=0.1)
            return proc

        async def fake_taskkill_factory(*cmd: str, **_kwargs: Any) -> _FakeProcess:
            taskkill_calls.append(tuple(cmd))
            return _FakeProcess()

        with tempfile.TemporaryDirectory() as tmp, patch.object(claude_code.os, "name", "nt"), patch.object(
            claude_code.shutil,
            "which",
            return_value="codex.cmd",
        ), patch.object(claude_code.asyncio, "create_subprocess_exec", new=fake_taskkill_factory):
            events = [
                event
                async for event in claude_code.run_codex_runtime_agent_events(
                    task_type="deepthink",
                    request={},
                    user_id="u-1",
                    task_id="task-windows-timeout",
                    spec=_spec(),
                    config=claude_code.CodexRuntimeConfig(command="codex", task_root=Path(tmp), timeout_s=0.01),
                    process_factory=fake_process_factory,
                )
            ]

        self.assertEqual(taskkill_calls, [("taskkill.exe", "/PID", "4242", "/T", "/F")])
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
