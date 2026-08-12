"""API-surface regression tests for the study-materials campaign.

Covers:
- B7: invalid continue modes map to HTTP 400 with the valid mode list
- B11: both generate surfaces share one options builder (identical options)
- B12: convert-markdown-to-latex/stream uses the standard task-stream envelope
- B13: local-auth fallback means no dead 401 branches in study_materials.py
- B14: POST-as-stream generate/continue expose X-Task-Id
- B15: GET /api/study-archives supports the base_fingerprint filter
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.agent.types import StepResult
from backend.api.auth import require_auth
from backend.app import create_app

_SINGLETON = "backend.generation.study_materials.orchestrator_singleton.study_material_tasks"

_VALID_MODES = (
    "improve",
    "deepen_research",
    "fix_export",
    "skip_export",
    "resume_failed_stage",
    "retry_search",
    "replan_from_failure",
)


def _override_auth(app) -> None:
    app.dependency_overrides[require_auth] = lambda: {"user_id": "u-1", "username": "alice", "role": "user"}


def _fake_stream_events(task_id: str):
    async def fake_stream(tid: str, *, user_id: str, after_seq: int = 0, heartbeat_s: float = 4.0):
        yield {"taskId": tid, "seq": 1, "type": "done", "data": {"task_id": tid}}

    return fake_stream


def _sse_data_lines(body: str) -> list[str]:
    return [line[len("data: "):] for line in body.splitlines() if line.startswith("data: ")]


class TestInvalidContinueModeMapping(unittest.TestCase):
    """B7: continue_task raises ValueError('invalid_continue_mode') for unknown
    modes; both HTTP surfaces must map it to a 400 listing the valid modes."""

    def _assert_invalid_mode_400(self, resp) -> None:
        self.assertEqual(resp.status_code, 400)
        detail = str(resp.json().get("detail") or "")
        self.assertTrue(detail.startswith("invalid_continue_mode"), detail)
        for mode in _VALID_MODES:
            self.assertIn(mode, detail)

    def test_stream_surface_maps_invalid_mode_to_400(self) -> None:
        app = create_app()
        _override_auth(app)
        client = TestClient(app)
        # The real continue_task validates the mode before any snapshot/DB I/O.
        resp = client.post("/api/study-materials/tasks/sm-x/continue", json={"mode": "bogus_mode"})
        self._assert_invalid_mode_400(resp)

    def test_submit_surface_maps_invalid_mode_to_400(self) -> None:
        app = create_app()
        _override_auth(app)
        client = TestClient(app)
        resp = client.post("/api/tasks/study-materials/sm-x/continue", json={"mode": "bogus_mode"})
        self._assert_invalid_mode_400(resp)


class TestSharedOptionsBuilder(unittest.TestCase):
    """B11: /api/study-materials/generate and /api/tasks/study-materials/generate
    must build identical orchestrator options for identical inputs."""

    _PAYLOAD = {
        "query": "导数",
        "subject": "高中数学",
        "preset": "deep",
        "requirements": "更通俗一些" + "x" * 1000,
        "with_questions": True,
        "with_diagrams": False,
        "enable_extra_tools": True,
        "max_points": 99,
        "prefer_local_archive": True,
        "research_budget": "lean",
    }

    def _capture_options(self, path: str) -> dict:
        app = create_app()
        _override_auth(app)
        create_task = AsyncMock(return_value=SimpleNamespace(task_id="sm-new"))
        with (
            patch(f"{_SINGLETON}.create_task", new=create_task),
            patch(f"{_SINGLETON}.stream", new=_fake_stream_events("sm-new")),
        ):
            client = TestClient(app)
            resp = client.post(path, json=dict(self._PAYLOAD))
        self.assertEqual(resp.status_code, 200)
        create_task.assert_awaited_once()
        return create_task.await_args.kwargs["options"]

    def test_both_generate_surfaces_build_identical_options(self) -> None:
        opts_stream = self._capture_options("/api/study-materials/generate")
        opts_submit = self._capture_options("/api/tasks/study-materials/generate")

        self.assertEqual(opts_stream, opts_submit)
        self.assertEqual(opts_stream["preset"], "deep")
        # requirements clipped at 600 chars (including ellipsis)
        self.assertLessEqual(len(opts_stream["requirements"]), 600)
        self.assertNotEqual(opts_stream["requirements"], self._PAYLOAD["requirements"])
        # max_points clamped into 1-15
        self.assertEqual(opts_stream["max_points"], 15)
        self.assertTrue(opts_stream["with_questions"])
        self.assertFalse(opts_stream["with_diagrams"])
        self.assertTrue(opts_stream["enable_extra_tools"])
        self.assertTrue(opts_stream["preferLocalArchive"])
        self.assertEqual(opts_stream["research_budget"], "lean")

    def test_builder_drops_non_positive_max_points(self) -> None:
        from backend.api.study_materials_schemas import (
            StudyMaterialsGenerateRequest,
            build_study_materials_options,
        )

        options = build_study_materials_options(StudyMaterialsGenerateRequest(query="q", max_points=0))
        self.assertNotIn("max_points", options)

        options = build_study_materials_options(StudyMaterialsGenerateRequest(query="q", max_points=1))
        self.assertEqual(options["max_points"], 1)


class TestLatexStreamEnvelope(unittest.TestCase):
    """B12: convert-markdown-to-latex/stream must emit the standard task-stream
    envelope: {taskId, seq, type, data} frames + ping heartbeat + terminal [DONE]."""

    def _post_stream(self, executor: MagicMock, env: dict | None = None):
        app = create_app()
        _override_auth(app)
        with (
            patch("backend.api.study_materials.Executor", return_value=executor),
            patch.dict(os.environ, env or {}),
        ):
            client = TestClient(app)
            return client.post(
                "/api/study-materials/convert-markdown-to-latex/stream",
                json={"markdown": "# 标题\n\n内容", "topic": "函数"},
            )

    @staticmethod
    def _executor_with_result(result: StepResult) -> MagicMock:
        executor = MagicMock()
        executor.execute_step = AsyncMock(return_value=result)
        return executor

    def test_success_stream_uses_standard_envelope(self) -> None:
        executor = self._executor_with_result(
            StepResult(
                step_id="s",
                tool="convert_markdown_to_latex",
                success=True,
                output={"tex_url": "/media/x.tex", "filename": "x.tex"},
            )
        )
        resp = self._post_stream(executor)
        self.assertEqual(resp.status_code, 200)

        lines = _sse_data_lines(resp.text)
        self.assertGreaterEqual(len(lines), 6)
        *json_lines, terminal = lines
        frames = [json.loads(line) for line in json_lines]

        for frame in frames:
            self.assertIn("taskId", frame)
            self.assertIn("seq", frame)
            self.assertIn("type", frame)
            self.assertIn("data", frame)
            # Old raw agent-event framing must be gone.
            self.assertNotIn("event", frame)

        non_ping = [f for f in frames if f["type"] != "ping"]
        self.assertEqual([f["seq"] for f in non_ping], list(range(1, len(non_ping) + 1)))
        self.assertTrue(all(f["taskId"] for f in frames))

        types = [f["type"] for f in non_ping]
        self.assertEqual(types[0], "status")
        self.assertIn("progress", types)
        self.assertIn("tool_call", types)
        self.assertIn("tool_result", types)
        self.assertEqual(types[-1], "done")
        self.assertEqual(terminal, "[DONE]")

    def test_failure_stream_emits_error_then_done_marker(self) -> None:
        executor = self._executor_with_result(
            StepResult(step_id="s", tool="convert_markdown_to_latex", success=False, output=None, error="boom")
        )
        resp = self._post_stream(executor)
        self.assertEqual(resp.status_code, 200)

        lines = _sse_data_lines(resp.text)
        *json_lines, terminal = lines
        frames = [json.loads(line) for line in json_lines]
        non_ping = [f for f in frames if f["type"] != "ping"]
        self.assertEqual(non_ping[-1]["type"], "error")
        self.assertIn("boom", str(non_ping[-1]["data"].get("message") or ""))
        self.assertEqual(terminal, "[DONE]")

    def test_stream_emits_ping_heartbeat_while_tool_runs(self) -> None:
        async def slow_step(*_args, **_kwargs):
            await asyncio.sleep(1.4)
            return StepResult(step_id="s", tool="convert_markdown_to_latex", success=True, output={"tex_url": "/t"})

        executor = MagicMock()
        executor.execute_step = AsyncMock(side_effect=slow_step)
        resp = self._post_stream(executor, env={"STUDY_MATERIALS_SSE_HEARTBEAT_S": "0.5"})
        self.assertEqual(resp.status_code, 200)

        lines = _sse_data_lines(resp.text)
        *json_lines, terminal = lines
        frames = [json.loads(line) for line in json_lines]
        pings = [f for f in frames if f["type"] == "ping"]
        self.assertGreaterEqual(len(pings), 1)
        for ping in pings:
            self.assertEqual(ping["data"]["status"], "running")
            self.assertIn("last_seq", ping["data"])
        # Pings must not consume sequence numbers.
        non_ping = [f for f in frames if f["type"] != "ping"]
        self.assertEqual([f["seq"] for f in non_ping], list(range(1, len(non_ping) + 1)))
        self.assertEqual(terminal, "[DONE]")


class TestTaskIdResponseHeader(unittest.TestCase):
    """B14: POST-as-stream endpoints create the task id server-side; it must be
    discoverable via the X-Task-Id response header."""

    def test_generate_returns_x_task_id_header(self) -> None:
        app = create_app()
        _override_auth(app)
        with (
            patch(f"{_SINGLETON}.create_task", new=AsyncMock(return_value=SimpleNamespace(task_id="sm-gen-1"))),
            patch(f"{_SINGLETON}.stream", new=_fake_stream_events("sm-gen-1")),
        ):
            client = TestClient(app)
            resp = client.post("/api/study-materials/generate", json={"query": "导数"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-task-id"), "sm-gen-1")

    def test_continue_returns_x_task_id_header(self) -> None:
        app = create_app()
        _override_auth(app)
        with (
            patch(f"{_SINGLETON}.continue_task", new=AsyncMock(return_value=SimpleNamespace(task_id="sm-cont-1"))),
            patch(f"{_SINGLETON}.stream", new=_fake_stream_events("sm-cont-1")),
        ):
            client = TestClient(app)
            resp = client.post("/api/study-materials/tasks/sm-old/continue", json={"mode": "improve"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-task-id"), "sm-cont-1")


class TestLocalAuthFallback(unittest.TestCase):
    """B13: require_auth falls back to the built-in local user, so the router
    carries no unreachable invalid_or_expired_token branches."""

    def test_router_has_no_dead_401_branches(self) -> None:
        import backend.api.study_materials as study_materials_module

        src = inspect.getsource(study_materials_module)
        self.assertNotIn("invalid_or_expired_token", src)

    def test_endpoint_works_without_any_credentials(self) -> None:
        app = create_app()  # no auth override, no headers: real local-auth fallback
        dummy = SimpleNamespace(
            task_id="sm-1",
            query="q",
            user_id="local-user",
            status="done",
            error=None,
            created_at_s=1.0,
            updated_at_s=2.0,
            first_seq=1,
            last_seq=3,
            last_success_step=None,
            last_failed_step=None,
            last_success_stage="",
            last_failed_stage="",
            per_kp_state={},
            search_summary_by_kp={},
        )
        with patch(f"{_SINGLETON}.get_task", new=AsyncMock(return_value=dummy)):
            client = TestClient(app)
            resp = client.get("/api/study-materials/tasks/sm-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["task_id"], "sm-1")


class TestArchiveBaseFingerprintFilter(unittest.TestCase):
    """B15: GET /api/study-archives threads base_fingerprint into the repository;
    absent or blank values behave as no filter."""

    _ROWS = [
        {"id": 1, "topic": "函数单调性", "base_fingerprint": "fp-a"},
        {"id": 2, "topic": "导数定义", "base_fingerprint": "fp-b"},
        {"id": 3, "topic": "函数单调性（进阶）", "base_fingerprint": "fp-a"},
    ]

    def _request(self, params: dict | None = None):
        app = create_app()
        _override_auth(app)
        calls: list[dict] = []

        async def fake_list(**kwargs):
            calls.append(kwargs)
            fp = str(kwargs.get("base_fingerprint") or "").strip()
            rows = [r for r in self._ROWS if not fp or r.get("base_fingerprint") == fp]
            return rows

        with patch("backend.api.study_archives.list_study_archives", new=fake_list):
            client = TestClient(app)
            resp = client.get("/api/study-archives", params=params or {})
        return resp, calls

    def test_filter_returns_only_matching_rows(self) -> None:
        resp, calls = self._request({"base_fingerprint": "fp-a"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual({row["id"] for row in data["items"]}, {1, 3})
        self.assertEqual(calls[0]["base_fingerprint"], "fp-a")

    def test_absent_param_is_unfiltered(self) -> None:
        resp, calls = self._request()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertIsNone(calls[0]["base_fingerprint"])

    def test_blank_param_behaves_as_absent(self) -> None:
        resp, calls = self._request({"base_fingerprint": "   "})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 3)
        self.assertIsNone(calls[0]["base_fingerprint"])


if __name__ == "__main__":
    unittest.main()
