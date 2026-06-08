from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.websockets import WebSocketDisconnect, WebSocketState

from backend.core import logging_utils
from backend.core.audit import AuditAction, AuditLogger

ROOT = Path(__file__).resolve().parents[2]


class BugrepNetworkScriptsLogsWsTests(unittest.IsolatedAsyncioTestCase):
    async def test_wikipedia_sync_package_path_is_bounded_by_timeout(self) -> None:
        fake_wikipedia = types.ModuleType("wikipedia")
        fake_wikipedia.set_lang = lambda _lang: None
        fake_wikipedia.search = lambda *_args, **_kwargs: ["Python"]

        fake_exceptions = types.ModuleType("wikipedia.exceptions")

        class FakeDisambiguationError(Exception):
            options: list[str] = []

        class FakePageError(Exception):
            pass

        fake_exceptions.DisambiguationError = FakeDisambiguationError
        fake_exceptions.PageError = FakePageError

        from backend.integrations.mcp.search import wikipedia as wiki_mod

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(60)

        with patch.dict(sys.modules, {"wikipedia": fake_wikipedia, "wikipedia.exceptions": fake_exceptions}), patch.object(
            wiki_mod,
            "API_TIMEOUT",
            0.05,
        ), patch.object(wiki_mod, "_to_thread", new=AsyncMock(side_effect=never_returns)):
            result = await asyncio.wait_for(wiki_mod.wikipedia_search("Python"), timeout=0.5)

        self.assertFalse(result["success"])
        self.assertEqual(result["provider"], "wikipedia")
        self.assertIn("timeout", result["error"].lower())

    async def test_ws_task_stream_stops_after_total_duration_cap(self) -> None:
        from backend.api import ws

        class FakeWebSocket:
            client_state = WebSocketState.CONNECTED

            def __init__(self) -> None:
                self.sent: list[dict] = []

            async def send_json(self, event: dict) -> None:
                self.sent.append(event)

        async def fake_get_task(*_args, **_kwargs):
            return {"status": "running"}

        fake_socket = FakeWebSocket()

        with patch.object(ws, "_TASK_STREAM_HEARTBEAT_SECONDS", 0.01), patch.object(
            ws,
            "_TASK_STREAM_POLL_SECONDS",
            0.01,
        ), patch.object(ws, "_TASK_STREAM_MAX_SECONDS", 0.03), patch.object(
            ws,
            "db_get_task",
            new=AsyncMock(side_effect=fake_get_task),
        ), patch.object(
            ws,
            "db_list_task_events",
            new=AsyncMock(return_value=[]),
        ):
            await asyncio.wait_for(
                ws._stream_task_events(fake_socket, task_id="task-1", user_id="user-1", after_seq=0),
                timeout=0.5,
            )

        self.assertTrue(any(event.get("type") == "ping" for event in fake_socket.sent))
        self.assertTrue(any(event.get("type") == "error" and event.get("data", {}).get("error") == "stream_timeout" for event in fake_socket.sent))

    async def test_ws_task_stream_exits_when_reader_detects_disconnect(self) -> None:
        from backend.api import ws

        class FakeWebSocket:
            def __init__(self) -> None:
                self.accepted = False
                self.closed = False

            async def accept(self) -> None:
                self.accepted = True

            async def receive_text(self) -> str:
                raise WebSocketDisconnect()

            async def close(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                self.closed = True

        stream_cancelled = asyncio.Event()

        async def slow_stream(*_args, **_kwargs):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                stream_cancelled.set()
                raise

        fake_socket = FakeWebSocket()
        with patch.object(ws, "validate_ws_token", return_value={"user_id": "user-1"}), patch.object(
            ws,
            "_stream_task_events",
            new=AsyncMock(side_effect=slow_stream),
        ):
            await asyncio.wait_for(ws.ws_task_stream(fake_socket, "task-1", token="ok"), timeout=0.5)

        self.assertTrue(fake_socket.accepted)
        self.assertTrue(fake_socket.closed)
        self.assertTrue(stream_cancelled.is_set())

    async def test_metrics_uses_constant_404_label_for_unmatched_paths(self) -> None:
        from fastapi import FastAPI
        from starlette.requests import Request

        from backend.core.metrics import _metric_path_label

        app = FastAPI()
        labels: list[str] = []
        for path in ("/scanner/one", "/scanner/two"):
            scope = {
                "type": "http",
                "method": "GET",
                "path": path,
                "root_path": "",
                "scheme": "http",
                "query_string": b"",
                "headers": [],
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
                "app": app,
                "router": app.router,
                "path_params": {},
            }
            labels.append(_metric_path_label(Request(scope), status_code=404))

        self.assertEqual(labels, ["<not_found>", "<not_found>"])

    async def test_logging_scrubs_cookie_and_url_secrets_from_text(self) -> None:
        raw = (
            "Cookie: sessionid=plain-session; csrftoken=plain-csrf "
            "https://api.test/?access_token=plain-access&api_key=plain-key"
        )

        scrubbed = logging_utils._scrub_text(raw)

        self.assertNotIn("plain-session", scrubbed)
        self.assertNotIn("plain-csrf", scrubbed)
        self.assertNotIn("plain-access", scrubbed)
        self.assertNotIn("plain-key", scrubbed)

    async def test_audit_logger_sanitizes_nested_details_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            audit = AuditLogger(path=str(path))

            audit.log(
                user_id="u1",
                action=AuditAction.API_KEY_USE,
                resource="/api/test",
                details={
                    "nested": {"Authorization": "Bearer plain-token"},
                    "message": "password=plain-password",
                },
            )

            payload = json.loads(path.read_text(encoding="utf-8").strip())

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("plain-token", encoded)
        self.assertNotIn("plain-password", encoded)


class BugrepScriptImportTests(unittest.TestCase):
    def _assert_import_is_side_effect_free(self, module_name: str) -> None:
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module_name}; print('import-ok')"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("import-ok", proc.stdout)
        self.assertNotIn("启动浏览器", proc.stdout)
        self.assertNotIn("请在浏览器", proc.stdout)

    def test_save_login_import_does_not_start_browser_or_parse_cli(self) -> None:
        self._assert_import_is_side_effect_free("scripts.ops.crawler.save_login")

    def test_test_login_import_does_not_start_browser_or_prompt(self) -> None:
        self._assert_import_is_side_effect_free("scripts.ops.crawler.test_login")

    def test_start_spawn_uses_windows_process_group_for_dev_children(self) -> None:
        start = importlib.import_module("scripts.start")
        popen = MagicMock(return_value=MagicMock())

        with patch.object(start, "_is_windows", return_value=True), patch.object(start.subprocess, "Popen", popen):
            start._spawn(["python", "-m", "backend.app"], cwd=ROOT)

        kwargs = popen.call_args.kwargs
        self.assertTrue(kwargs.get("creationflags", 0) & start.subprocess.CREATE_NEW_PROCESS_GROUP)


if __name__ == "__main__":
    unittest.main()
