from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class ComposeSandboxManagerTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, root: Path, **overrides):
        from backend.generation.paper_compose.compose_sandbox import ComposeSandboxConfig, ComposeSandboxManager

        values = {
            "image": "study-ai/compose-sandbox:test",
            "root_dir": root,
            "timeout_s": 5,
            "ttl_s": 60,
            "max_workspace_bytes": 1024 * 1024,
        }
        values.update(overrides)
        config = ComposeSandboxConfig(**values)
        manager = ComposeSandboxManager(config=config)
        return manager

    async def test_open_reports_unavailable_when_docker_is_missing(self) -> None:
        from backend.generation.paper_compose.compose_sandbox import SandboxUnavailableError

        with tempfile.TemporaryDirectory() as tmp:
            manager = self._manager(Path(tmp))
            with patch("backend.generation.paper_compose.compose_sandbox.shutil.which", return_value=None):
                with self.assertRaises(SandboxUnavailableError):
                    await manager.open(session_id="task-1")

    async def test_session_lifecycle_writes_reads_runs_exports_and_closes(self) -> None:
        from backend.generation.paper_compose.compose_sandbox import DockerCommandResult

        calls: list[list[str]] = []

        async def fake_run(args, *, timeout_s=None):
            calls.append(list(args))
            if args[:2] == ["image", "inspect"]:
                return DockerCommandResult(returncode=0, stdout="", stderr="")
            if args and args[0] == "create":
                return DockerCommandResult(returncode=0, stdout="container-123\n", stderr="")
            if args and args[0] == "exec":
                return DockerCommandResult(returncode=0, stdout="paper.tex\n", stderr="")
            return DockerCommandResult(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            manager = self._manager(Path(tmp))
            manager._run_docker = fake_run  # type: ignore[method-assign]
            with patch("backend.generation.paper_compose.compose_sandbox.shutil.which", return_value="docker"):
                session = await manager.open(
                    session_id="task-1",
                    paper={"questions": [{"question_id": "q1", "stem": "old"}]},
                )
                write_result = await manager.write(session.session_id, "export/paper.tex", "hello")
                self.assertEqual(write_result["path"], "export/paper.tex")
                self.assertEqual(await manager.read(session.session_id, "export/paper.tex"), "hello")

                run_result = await manager.run(session.session_id, "ls", ["export"])
                self.assertEqual(run_result.returncode, 0)
                self.assertEqual(run_result.stdout.strip(), "paper.tex")

                exported = await manager.export(session.session_id)
                self.assertIn("paper.json", [item["path"] for item in exported["files"]])
                self.assertIn("export/paper.tex", [item["path"] for item in exported["files"]])

                await manager.close(session.session_id)
                create_call = next(call for call in calls if call and call[0] == "create")
                self.assertEqual(create_call[create_call.index("--network") + 1], "none")
                self.assertIn("--read-only", create_call)
                self.assertIn("--cap-drop", create_call)
                self.assertTrue(any(call[:2] == ["exec", "--workdir"] for call in calls))
                self.assertFalse(session.workspace.exists())

    async def test_path_traversal_workspace_size_and_command_whitelist_are_rejected(self) -> None:
        from backend.generation.paper_compose.compose_sandbox import (
            DockerCommandResult,
            SandboxSecurityError,
        )

        async def fake_run(args, *, timeout_s=None):
            if args and args[0] == "create":
                return DockerCommandResult(returncode=0, stdout="container-123", stderr="")
            return DockerCommandResult(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            manager = self._manager(Path(tmp), max_workspace_bytes=512)
            manager._run_docker = fake_run  # type: ignore[method-assign]
            with patch("backend.generation.paper_compose.compose_sandbox.shutil.which", return_value="docker"):
                session = await manager.open(session_id="task-1", paper={"questions": []})

            with self.assertRaises(SandboxSecurityError):
                await manager.write(session.session_id, "../escape.txt", "x")
            with self.assertRaises(SandboxSecurityError):
                await manager.run(session.session_id, "bash", [])
            with self.assertRaises(SandboxSecurityError):
                await manager.run(session.session_id, "cat", ["../paper.json"])
            with self.assertRaises(SandboxSecurityError):
                await manager.write(session.session_id, "big.txt", "x" * 2000)

    async def test_patch_question_updates_only_matching_question(self) -> None:
        from backend.generation.paper_compose.compose_sandbox import DockerCommandResult

        async def fake_run(args, *, timeout_s=None):
            if args and args[0] == "create":
                return DockerCommandResult(returncode=0, stdout="container-123", stderr="")
            return DockerCommandResult(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            manager = self._manager(Path(tmp))
            manager._run_docker = fake_run  # type: ignore[method-assign]
            with patch("backend.generation.paper_compose.compose_sandbox.shutil.which", return_value="docker"):
                session = await manager.open(
                    session_id="task-1",
                    paper={
                        "questions": [
                            {"question_id": "q1", "stem": "old", "answer": ""},
                            {"question_id": "q2", "stem": "keep", "answer": ""},
                        ]
                    },
                )

            updated = await manager.patch_question(session.session_id, "q1", {"stem": "new", "answer": "A"})
            self.assertEqual(updated["question"]["stem"], "new")

            paper = json.loads((session.workspace / "paper.json").read_text(encoding="utf-8"))
            self.assertEqual(paper["questions"][0]["answer"], "A")
            self.assertEqual(paper["questions"][1]["stem"], "keep")

    async def test_expired_session_is_rejected(self) -> None:
        from backend.generation.paper_compose.compose_sandbox import DockerCommandResult, SandboxExpiredError

        async def fake_run(args, *, timeout_s=None):
            if args and args[0] == "create":
                return DockerCommandResult(returncode=0, stdout="container-123", stderr="")
            return DockerCommandResult(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            manager = self._manager(Path(tmp))
            manager._run_docker = fake_run  # type: ignore[method-assign]
            with patch("backend.generation.paper_compose.compose_sandbox.shutil.which", return_value="docker"):
                session = await manager.open(session_id="task-1", paper={"questions": []})
            session.expires_at = time.monotonic() - 1

            with self.assertRaises(SandboxExpiredError):
                await manager.read(session.session_id, "paper.json")


class ComposeSandboxAgentToolTests(unittest.TestCase):
    def test_executor_registers_compose_sandbox_tools(self) -> None:
        from backend.agent.executor import Executor

        expected_tools = {
            "compose_sandbox_open",
            "compose_sandbox_write_file",
            "compose_sandbox_read_file",
            "compose_sandbox_run",
            "compose_sandbox_patch_question",
            "compose_sandbox_export",
            "compose_sandbox_close",
        }

        registered = {tool["name"] for tool in Executor().tool_registry.list_tools()}
        self.assertTrue(expected_tools.issubset(registered))


if __name__ == "__main__":
    unittest.main()
