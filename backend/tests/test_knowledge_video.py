from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.shared.tasks.runtime import RuntimeTask


class TestKnowledgeVideoLLM(unittest.TestCase):
    def test_parse_generated_package_strips_code_fence_from_code_field(self) -> None:
        from backend.generation.knowledge_video.llm import parse_generated_package

        text = """
{
  "scene_name": "KnowledgeVideoScene",
  "code": "```python\\nfrom manim import *\\nclass KnowledgeVideoScene(Scene):\\n    def construct(self):\\n        self.wait(1)\\n```",
  "subtitles": [],
  "metadata": {}
}
"""

        package = parse_generated_package(text)

        self.assertTrue(package.code.startswith("from manim import *"))
        self.assertNotIn("```", package.code)


class TestKnowledgeVideoSafety(unittest.TestCase):
    def test_allows_python_imports_without_content_blacklist(self) -> None:
        from backend.generation.knowledge_video.safety import validate_manim_code

        code = """
from manim import *
import os
import subprocess

class KnowledgeVideoScene(Scene):
    def construct(self):
        os.system("echo unsafe")
        subprocess.run(["python", "--version"])
"""

        validate_manim_code(code, scene_name="KnowledgeVideoScene")

    def test_rejects_missing_scene_class(self) -> None:
        from backend.generation.knowledge_video.safety import UnsafeManimCodeError, validate_manim_code

        with self.assertRaises(UnsafeManimCodeError):
            validate_manim_code("from manim import *\n", scene_name="KnowledgeVideoScene")

    def test_allows_basic_manim_scene(self) -> None:
        from backend.generation.knowledge_video.safety import validate_manim_code

        code = """
from manim import *

class KnowledgeVideoScene(Scene):
    def construct(self):
        title = Text("导数")
        self.play(Write(title))
        self.wait(1)
"""

        validate_manim_code(code, scene_name="KnowledgeVideoScene")


class TestKnowledgeVideoDockerRenderer(unittest.TestCase):
    def test_docker_command_has_strict_sandbox_flags(self) -> None:
        from backend.generation.knowledge_video.renderer import DockerRenderConfig, build_docker_run_command

        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = build_docker_run_command(
                task_dir=Path(tmpdir),
                script_name="scene.py",
                scene_name="KnowledgeVideoScene",
                config=DockerRenderConfig(image="study-ai/manim-sandbox:test", quality="low"),
            )

        joined = " ".join(cmd)
        self.assertIn("--network none", joined)
        self.assertIn("--name", cmd)
        self.assertIn("--ipc", cmd)
        self.assertIn("none", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("--cap-drop", cmd)
        self.assertIn("ALL", cmd)
        self.assertIn("--security-opt", cmd)
        self.assertIn("no-new-privileges", cmd)
        self.assertIn("--user", cmd)
        self.assertIn("--pids-limit", cmd)
        self.assertIn("--ulimit", cmd)
        self.assertIn("--memory", cmd)
        self.assertIn("--cpus", cmd)
        self.assertIn("--tmpfs", cmd)
        self.assertIn("study-ai/manim-sandbox:test", cmd)
        self.assertIn("manim", cmd)
        self.assertIn("scene.py", cmd)
        self.assertIn("KnowledgeVideoScene", cmd)


class TestKnowledgeVideoRunner(unittest.IsolatedAsyncioTestCase):
    async def test_successful_run_publishes_video_subtitles_and_script(self) -> None:
        from backend.generation.knowledge_video.models import GeneratedVideoPackage, RenderResult
        from backend.generation.knowledge_video.service import run_knowledge_video_task

        task = RuntimeTask(
            task_id="kv-1",
            user_id="u-1",
            task_type="knowledge_video",
            title="知识视频：导数",
            request={"topic": "导数", "duration_seconds": 20},
        )
        package = GeneratedVideoPackage(
            code="from manim import *\nclass KnowledgeVideoScene(Scene):\n    def construct(self):\n        self.wait(1)\n",
            scene_name="KnowledgeVideoScene",
            subtitles=[{"start": 0, "end": 2, "text": "导数表示瞬时变化率。"}],
            metadata={"duration_seconds": 20},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "KnowledgeVideoScene.mp4"
            video_path.write_bytes(b"mp4")
            render_result = RenderResult(success=True, video_path=video_path, stdout="ok", stderr="", returncode=0)

            with (
                patch("backend.generation.knowledge_video.service.generate_manim_package", new=AsyncMock(return_value=package)),
                patch("backend.generation.knowledge_video.service.ensure_sandbox_available", new=AsyncMock()),
                patch("backend.generation.knowledge_video.service.render_with_docker", new=AsyncMock(return_value=render_result)),
                patch("backend.generation.knowledge_video.service.publish_generated_bytes", new=AsyncMock(side_effect=[
                    {"url": "/api/media/generated/video.mp4", "filename": "video.mp4", "bytes": 3},
                ])),
                patch("backend.generation.knowledge_video.service.publish_generated_text", new=AsyncMock(side_effect=[
                    {"url": "/api/media/generated/subtitle.srt", "filename": "subtitle.srt", "bytes": 20},
                    {"url": "/api/media/generated/script.py", "filename": "script.py", "bytes": 80},
                    {"url": "/api/media/generated/meta.json", "filename": "meta.json", "bytes": 20},
                ])),
                patch("backend.generation.knowledge_video.service.task_runtime.append_event", new=AsyncMock()),
                patch("backend.generation.knowledge_video.service.task_runtime.complete_task", new=AsyncMock()) as complete_task,
                patch("backend.generation.knowledge_video.service.task_runtime.fail_task", new=AsyncMock()) as fail_task,
            ):
                await run_knowledge_video_task(task, user_id="u-1")

        fail_task.assert_not_awaited()
        result = complete_task.await_args.kwargs["result"]
        self.assertEqual(result["video_url"], "/api/media/generated/video.mp4")
        self.assertEqual(result["subtitle_url"], "/api/media/generated/subtitle.srt")
        self.assertEqual(result["script_url"], "/api/media/generated/script.py")
        self.assertEqual(result["metadata"]["attempts"], 1)

    async def test_failed_render_triggers_bounded_repair_attempts(self) -> None:
        from backend.generation.knowledge_video.models import GeneratedVideoPackage, RenderResult
        from backend.generation.knowledge_video.service import run_knowledge_video_task

        task = RuntimeTask(
            task_id="kv-2",
            user_id="u-1",
            task_type="knowledge_video",
            title="知识视频：导数",
            request={"topic": "导数", "duration_seconds": 20},
        )
        package = GeneratedVideoPackage(
            code="from manim import *\nclass KnowledgeVideoScene(Scene):\n    def construct(self):\n        self.wait(1)\n",
            scene_name="KnowledgeVideoScene",
            subtitles=[],
            metadata={},
        )
        failed_render = RenderResult(success=False, video_path=None, stdout="", stderr="NameError: bad", returncode=1)

        with (
            patch("backend.generation.knowledge_video.service.generate_manim_package", new=AsyncMock(return_value=package)) as generator,
            patch("backend.generation.knowledge_video.service.ensure_sandbox_available", new=AsyncMock()),
            patch("backend.generation.knowledge_video.service.render_with_docker", new=AsyncMock(return_value=failed_render)),
            patch("backend.generation.knowledge_video.service.task_runtime.append_event", new=AsyncMock()),
            patch("backend.generation.knowledge_video.service.task_runtime.complete_task", new=AsyncMock()) as complete_task,
            patch("backend.generation.knowledge_video.service.task_runtime.fail_task", new=AsyncMock()) as fail_task,
        ):
            await run_knowledge_video_task(task, user_id="u-1", max_attempts=3)

        self.assertEqual(generator.await_count, 3)
        complete_task.assert_not_awaited()
        fail_task.assert_awaited_once()
        self.assertEqual(fail_task.await_args.args[1], "render_failed")
