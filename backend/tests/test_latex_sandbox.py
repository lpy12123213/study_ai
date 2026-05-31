from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class LatexSandboxCommandTests(unittest.TestCase):
    def test_docker_command_has_strict_sandbox_flags(self) -> None:
        try:
            from backend.generation.paper_compose.latex_sandbox import (
                LatexSandboxConfig,
                build_docker_run_command,
            )
        except ImportError as exc:
            self.fail(f"latex_sandbox module is missing: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            build_dir = Path(tmp)
            cmd = build_docker_run_command(
                build_dir=build_dir,
                config=LatexSandboxConfig(
                    image="study-ai/latex-sandbox:test",
                    timeout_s=123,
                    memory="512m",
                    cpus="1.5",
                    pids_limit=64,
                    user="1001:1001",
                    docker_bin="docker",
                ),
            )

        joined = " ".join(cmd)
        self.assertIn("--network none", joined)
        self.assertIn("--ipc none", joined)
        self.assertIn("--read-only", cmd)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("--security-opt no-new-privileges", joined)
        self.assertIn("--user 1001:1001", joined)
        self.assertIn("--cpus 1.5", joined)
        self.assertIn("--memory 512m", joined)
        self.assertIn("--pids-limit 64", joined)
        self.assertIn("--tmpfs /tmp:rw,nosuid,nodev", joined)
        self.assertIn("--tmpfs /home:rw,nosuid,nodev", joined)
        self.assertIn("--workdir /workspace", joined)
        self.assertEqual(cmd[-4:], ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"])


if __name__ == "__main__":
    unittest.main()
