from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch


class LatexBackendSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_backend_uses_host_compiler(self) -> None:
        from backend.generation.paper_compose.exporters import latex

        if not hasattr(latex, "resolve_latex_backend"):
            self.fail("resolve_latex_backend is missing")

        with patch.dict(os.environ, {"PAPER_EXPORT_LATEX_BACKEND": "host"}, clear=False), patch.object(
            latex,
            "_compile_latex_to_pdf_host",
            return_value=(b"%PDF-host", "host-log"),
        ) as host_compile:
            pdf, log = await latex.compile_latex_to_pdf_async(tex="\\documentclass{article}\\begin{document}x\\end{document}")

        self.assertEqual(pdf, b"%PDF-host")
        self.assertEqual(log, "host-log")
        host_compile.assert_called_once()

    async def test_auto_backend_uses_docker_when_available(self) -> None:
        from backend.generation.paper_compose.exporters import latex

        if not hasattr(latex, "resolve_latex_backend"):
            self.fail("resolve_latex_backend is missing")

        with patch.dict(os.environ, {"PAPER_EXPORT_LATEX_BACKEND": "auto"}, clear=False), patch.object(
            latex,
            "ensure_sandbox_available",
            new=AsyncMock(return_value=None),
        ), patch.object(
            latex,
            "compile_latex_in_docker",
            new=AsyncMock(return_value=(b"%PDF-docker", "docker-log")),
        ), patch.object(
            latex,
            "_compile_latex_to_pdf_host",
            return_value=(b"%PDF-host", "host-log"),
        ) as host_compile:
            pdf, log = await latex.compile_latex_to_pdf_async(tex="\\documentclass{article}\\begin{document}x\\end{document}")

        self.assertEqual(pdf, b"%PDF-docker")
        self.assertEqual(log, "docker-log")
        host_compile.assert_not_called()

    async def test_auto_backend_falls_back_to_host_when_docker_unavailable(self) -> None:
        from backend.generation.paper_compose.exporters import latex

        if not hasattr(latex, "resolve_latex_backend"):
            self.fail("resolve_latex_backend is missing")

        from backend.generation.paper_compose.latex_sandbox import SandboxUnavailableError

        with patch.dict(os.environ, {"PAPER_EXPORT_LATEX_BACKEND": "auto"}, clear=False), patch.object(
            latex,
            "ensure_sandbox_available",
            new=AsyncMock(side_effect=SandboxUnavailableError("docker_not_found")),
        ), patch.object(
            latex,
            "compile_latex_in_docker",
            new=AsyncMock(return_value=(b"%PDF-docker", "docker-log")),
        ) as docker_compile, patch.object(
            latex,
            "_compile_latex_to_pdf_host",
            return_value=(b"%PDF-host", "host-log"),
        ) as host_compile:
            pdf, log = await latex.compile_latex_to_pdf_async(tex="\\documentclass{article}\\begin{document}x\\end{document}")

        self.assertEqual(pdf, b"%PDF-host")
        self.assertIn("host-log", log)
        self.assertIn("docker_unavailable", log)
        docker_compile.assert_not_called()
        host_compile.assert_called_once()


if __name__ == "__main__":
    unittest.main()
