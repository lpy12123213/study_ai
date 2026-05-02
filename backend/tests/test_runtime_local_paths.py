from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.agent.tools.generation import diagrams as diagram_tools
from backend.agent.tools.generation.diagrams import DiagramToolsMixin
from backend.agent.tools.generation.latex_export_compile import LatexCompileMixin
from backend.agent.types import CompressedContext, UserProfile
from backend.llm import client as llm_client


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ctx() -> CompressedContext:
    return CompressedContext(
        user_profile=UserProfile(user_id="unittest"),
        system_instructions="",
        current_task="runtime-local-paths",
    )


class _DiagramHarness(DiagramToolsMixin):
    pass


class _LatexHarness(LatexCompileMixin):
    async def _emit_status(self, _message: str) -> None:
        return None


class RuntimeLocalPathTests(unittest.TestCase):
    def test_openrouter_cache_file_is_repo_local(self) -> None:
        expected = (_repo_root() / ".local" / "cache" / "openrouter_model_limits.json").resolve()
        self.assertEqual(llm_client._OPENROUTER_CACHE_FILE, expected)

    def test_diagram_generated_dir_is_repo_local(self) -> None:
        expected = (_repo_root() / ".local" / "media" / "generated").resolve()
        self.assertEqual(diagram_tools._GENERATED_DIR, expected)

    def test_tikz_renderer_receives_repo_root(self) -> None:
        captured: dict[str, object] = {}

        def fake_render_tikz_to_svg_bytes(*, tikz: str, preamble: str, timeout_s: float, repo_root: Path) -> dict:
            captured["repo_root"] = repo_root
            return {"success": True, "svg_bytes": b"<svg></svg>"}

        tool = _DiagramHarness()
        ctx = _ctx()
        published = {"sha256": "abc", "filename": "abc.svg", "url": "/api/media/generated/abc.svg", "bytes": 11}

        with patch(
            "backend.agent.tools.generation.diagrams.render_tikz_to_svg_bytes",
            side_effect=fake_render_tikz_to_svg_bytes,
        ):
            with patch(
                "backend.agent.tools.generation.diagrams.publish_generated_bytes",
                new=AsyncMock(return_value=published),
            ):
                result = asyncio.run(tool._tool_tikz_to_svg({"tikz": r"\draw (0,0) -- (1,1);"}, ctx))

        self.assertTrue(result["success"])
        self.assertEqual(captured["repo_root"], _repo_root())

    def test_asy_renderer_receives_repo_root(self) -> None:
        captured: dict[str, object] = {}

        def fake_render_asy_to_svg_bytes(*, asy: str, timeout_s: float, repo_root: Path) -> dict:
            captured["repo_root"] = repo_root
            return {"success": True, "svg_bytes": b"<svg></svg>"}

        tool = _DiagramHarness()
        ctx = _ctx()
        published = {"sha256": "abc", "filename": "abc.svg", "url": "/api/media/generated/abc.svg", "bytes": 11}

        with patch(
            "backend.agent.tools.generation.diagrams.render_asy_to_svg_bytes",
            side_effect=fake_render_asy_to_svg_bytes,
        ):
            with patch(
                "backend.agent.tools.generation.diagrams.publish_generated_bytes",
                new=AsyncMock(return_value=published),
            ):
                result = asyncio.run(tool._tool_asy_to_svg({"asy": "draw((0,0)--(1,1));"}, ctx))

        self.assertTrue(result["success"])
        self.assertEqual(captured["repo_root"], _repo_root())

    def test_latex_compile_uses_repo_local_build_dirs(self) -> None:
        created_dirs: list[Path] = []

        def fake_mkdir(path: Path, parents: bool = False, exist_ok: bool = False) -> None:
            created_dirs.append(Path(path))
            if len(created_dirs) >= 2:
                raise RuntimeError("stop-after-build-dir")

        tool = _LatexHarness()
        ctx = _ctx()
        ctx.working_memory["latex_tex"] = r"\documentclass{article}\begin{document}ok\end{document}"

        with patch("pathlib.Path.mkdir", autospec=True, side_effect=fake_mkdir):
            with self.assertRaisesRegex(RuntimeError, "stop-after-build-dir"):
                asyncio.run(tool._tool_compile_latex_to_pdf({}, ctx))

        self.assertGreaterEqual(len(created_dirs), 2)
        self.assertEqual(created_dirs[0], (_repo_root() / ".local" / "media" / "generated").resolve())
        self.assertEqual(created_dirs[1].parent, (_repo_root() / ".local" / "latex_build").resolve())
