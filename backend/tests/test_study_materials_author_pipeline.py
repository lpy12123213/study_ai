"""作者流水线（run_author_pipeline）端到端测试：假 LLM/假检索/假 figure forge。

驱动 research→blueprint→backbone→fill→assemble 全流程，断言 TODO 清零、
占位符清零、事件序列、参考文献渲染与 backbone 缺占位符的失败终态。
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.generation.study_materials.author.figures import FigureForge
from backend.generation.study_materials.author.pipeline import (
    AuthorPipelineContext,
    run_author_pipeline,
)
from backend.generation.study_materials.author.research_tools import ResearchToolbox
from backend.generation.study_materials.author.todos import TodoList
from backend.generation.study_materials.quality_gate import draft_hash

BLUEPRINT_JSON = json.dumps(
    {
        "narrative": "先建立直觉，再严格化。",
        "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小正数"}],
        "sections": [
            {
                "id": "sec-1",
                "title": "极限的直观概念",
                "purpose": "建立直觉",
                "key_points": ["逼近", "直观定义"],
                "target_chars": 800,
                "difficulty": "基础",
                "misconceptions": [{"claim": "极限就是直接代入", "source_url": "https://example.com/misconception"}],
                "frontier": True,
            },
            {
                "id": "sec-2",
                "title": "极限的严格定义",
                "purpose": "严格化",
                "key_points": ["epsilon-delta 定义"],
                "target_chars": 800,
                "difficulty": "进阶",
                "misconceptions": [],
                "frontier": False,
            },
        ],
        "figures": [{"n": 1, "sec_id": "sec-1", "intent": "逼近示意", "kind": "mermaid", "caption": "图1 逼近过程"}],
    },
    ensure_ascii=False,
)

BACKBONE_MD = """# 极限入门

## 第一章 直观

引入段：本节回答什么是逼近。

[[FILL:sec-1]]

[[FIG:1]]

衔接段：有了直觉，下面严格化。

[[FILL:sec-2]]

## 总结
"""

FILL_BODY = (
    "本节讲解核心概念：极限描述的是无限逼近的过程，"
    "先用日常例子建立直觉，再过渡到严格表述，并配带步骤的例题与分层自测。"
    "[EX1] 例题：求 x 趋近 2 时 x+1 的极限。步骤：观察趋势，x 越接近 2，x+1 越接近 3。"
    "[Q1] 自测（基础）：用自己的话解释逼近；（应用）：求 x→0 时 2x 的极限。"
    "[A1] 答案：0。评分点：趋势判断正确、表述无循环论证。"
)

AUDIT_JSON = json.dumps(
    {"claims": [{"text": "极限描述无限逼近的过程", "verdict": "supported", "fix": ""}]},
    ensure_ascii=False,
)


def _fake_llm(backbone_text=BACKBONE_MD, counter=None):
    async def fake_llm(system, user):
        if "总编" in system:
            return BLUEPRINT_JSON
        if "核查" in system:
            return AUDIT_JSON
        if "骨架" in system:
            if counter is not None:
                counter["backbone"] = counter.get("backbone", 0) + 1
            return backbone_text
        return FILL_BODY

    return fake_llm


def _fake_toolbox():
    async def fake_serp(query, n):
        return [
            {
                "title": "极限 通俗解释",
                "url": "https://example.com/limits",
                "content": "极限是无限逼近的严格化",
                "score": 0.9,
            }
        ]

    async def fake_fetch(url):
        return "页面正文"

    return ResearchToolbox(serp_func=fake_serp, fetch_func=fake_fetch)


def _fake_forge(events):
    async def fake_codegen(spec):
        return "graph LR; A-->B"

    async def fake_render(kind, code):
        return {"url": "/media/generated/f1.svg", "engine": kind}

    return FigureForge(llm_codegen=fake_codegen, render_func=fake_render, on_trace=events.append)


def _ctx(work_dir):
    return AuthorPipelineContext(
        task_id="t-author-1",
        topic="极限",
        subject="数学",
        work_dir=Path(work_dir),
        user_id="u-1",
        preset="standard",
        knowledge_points=["极限"],
    )


class AuthorPipelineTests(unittest.TestCase):
    def test_full_run_happy_path(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

            # 1. todos 全部 done 或 waived
            self.assertEqual(result["status"], "ok")
            todos = TodoList.from_json(result["todos"])
            self.assertTrue(todos.all_cleared(), msg=result["todos"])

            # 2. 成稿无占位符
            markdown = result["markdown"]
            self.assertNotIn("[[FILL:", markdown)
            self.assertNotIn("[[FIG:", markdown)

            # 4. 参考文献从研究笔记的 src URL 渲染
            self.assertIn("## 参考文献", markdown)
            self.assertIn("https://example.com/limits", markdown)
            self.assertIn("![图1 逼近过程](/media/generated/f1.svg)", markdown)

            # 笔记与 todos.json 落盘
            notes = Path(tmp) / "notes"
            self.assertIn("https://example.com/limits", (notes / "research.md").read_text(encoding="utf-8"))
            self.assertTrue((notes / "blueprint.md").exists())
            self.assertTrue((notes / "backbone.md").exists())
            self.assertTrue((Path(tmp) / "todos.json").exists())

        # 3. 事件序列含 todo_update / note_write / section_fill
        types = [e["type"] for e in events]
        self.assertIn("todo_update", types)
        self.assertIn("note_write", types)
        self.assertIn("section_fill", types)

    def test_backbone_missing_placeholder_fails_after_one_retry(self):
        events = []
        counter = {}
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(backbone_text="# 书\n\n没有任何占位符的主干。\n", counter=counter),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        # 不抛未捕获异常：任务以 failed 终态返回
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "backbone_placeholder_missing")
        self.assertEqual(counter.get("backbone"), 2)  # 首次 + 重试 1 次
        todo_events = [e for e in events if e["type"] == "todo_update"]
        self.assertTrue(any(e["data"]["todo"]["status"] == "failed" for e in todo_events))

    def test_blueprint_invalid_fails_after_one_retry(self):
        events = []

        async def bad_blueprint_llm(system, user):
            if "总编" in system:
                return "这不是 JSON"
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return FILL_BODY

        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=bad_blueprint_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "blueprint_invalid")


class AuthorAcceptanceGateTests(unittest.TestCase):
    """W1：ACCEPT 段改用 author 专用门 evaluate_author_acceptance 决定交付终态。"""

    def _run(self, tmp, events, llm_func=None):
        return asyncio.run(
            run_author_pipeline(
                _ctx(tmp),
                llm_func=llm_func or _fake_llm(),
                toolbox=_fake_toolbox(),
                emit=events.append,
                forge=_fake_forge(events),
            )
        )

    def test_happy_path_not_degraded_and_has_acceptance(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events)

        self.assertEqual(result["status"], "ok")
        # todos 全清、无占位符残留 → author 门通过，不再恒定 degraded
        self.assertFalse(result.get("degraded"), msg=result.get("quality_report"))
        acceptance = result.get("acceptance") or {}
        self.assertTrue(acceptance.get("accepted"), msg=result.get("acceptance"))
        self.assertEqual(acceptance.get("draft_hash"), draft_hash(result["markdown"]))
        self.assertTrue(result["quality_report"]["passed"])

    def test_uncleared_todo_degrades_delivery(self):
        async def flaky_fill_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            if "汇编缺少小节" in user:
                return FILL_BODY  # 汇编补写成功，保证流程走到 ACCEPT
            if "极限的直观概念" in user:
                return ""  # sec-1 填充与作者改写均交空 → fill todo 以 failed 终态残留
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, llm_func=flaky_fill_llm)

        # 明确降级终态，不静默成功
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["degraded"])
        self.assertFalse(result.get("acceptance"))
        self.assertIn("todos_not_cleared", result["quality_report"]["failed_checks"])
        self.assertIn("todos_not_cleared", result["material"]["issues"])

    def test_legacy_acceptance_kept_as_diagnostic_only(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events)

        legacy = result.get("legacy_acceptance")
        self.assertIsInstance(legacy, dict)
        self.assertIn("passed", legacy)
        # legacy 门因缺 review.dimensions 不过，但不再决定交付终态
        self.assertFalse(legacy["passed"])
        self.assertFalse(result["degraded"])

    def test_legacy_acceptance_failure_does_not_block(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "backend.generation.study_materials.author.pipeline.evaluate_acceptance",
                side_effect=RuntimeError("boom"),
            ):
                result = self._run(tmp, events)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["degraded"])
        self.assertTrue((result.get("acceptance") or {}).get("accepted"))
        self.assertIn("error", result["legacy_acceptance"])


if __name__ == "__main__":
    unittest.main()
