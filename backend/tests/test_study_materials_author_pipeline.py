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

from backend.generation.study_materials.author.blueprint import Blueprint, BlueprintError
from backend.generation.study_materials.author.figures import FigureForge
from backend.generation.study_materials.author.pipeline import (
    AuthorPipelineContext,
    _AuthorPipeline,
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
                "difficulty": "应用",
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

# 长度门恢复 min(target_chars*0.5, min_chars) 后需 ≥200 字符（target 800 → 400，被 min_chars 盖帽）。
FILL_BODY = (
    "本节讲解核心概念：极限描述的是无限逼近的过程，"
    "先用日常例子建立直觉，再过渡到严格表述，并配带步骤的例题与分层自测。"
    "直观上，自变量越靠近目标值，函数值越稳定地靠近某个确定的数，这个数就是极限；"
    "逼近只要求无限接近，并不要求真正到达，这是初学者最容易混淆的地方。"
    "[EX1] 例题：求 x 趋近 2 时 x+1 的极限。步骤：观察趋势，x 越接近 2，x+1 越接近 3。"
    "[Q1] 自测（基础）：用自己的话解释逼近；（应用）：求 x→0 时 2x 的极限。"
    "[A1] 答案：0。评分点：趋势判断正确、表述无循环论证。"
)

AUDIT_JSON = json.dumps(
    {"claims": [{"text": "极限描述无限逼近的过程", "verdict": "supported", "fix": ""}]},
    ensure_ascii=False,
)

# 两个知识点（极限/导数）的蓝图与主干夹具：kp 覆盖校验要求每个输入 kp 有小节标题归属。
TWO_KP_BLUEPRINT_JSON = json.dumps(
    {
        "narrative": "先极限后导数。",
        "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小正数"}],
        "sections": [
            {
                "id": "sec-1",
                "title": "极限的定义",
                "purpose": "建立极限概念",
                "key_points": ["逼近", "直观定义"],
                "target_chars": 800,
                "difficulty": "基础",
                "misconceptions": [],
                "frontier": False,
            },
            {
                "id": "sec-2",
                "title": "导数的定义",
                "purpose": "建立导数概念",
                "key_points": ["变化率", "差商极限"],
                "target_chars": 800,
                "difficulty": "基础",
                "misconceptions": [],
                "frontier": False,
            },
        ],
        "figures": [],
    },
    ensure_ascii=False,
)

TWO_KP_BACKBONE_MD = """# 微积分基础

## 第一章 极限

引入段：本节回答什么是极限。

[[FILL:sec-1]]

衔接段：有了极限，下面定义导数。

[[FILL:sec-2]]

## 总结
"""

# 拆分阶段夹具：fake LLM 返回 3 个知识点；配套蓝图/主干覆盖三者（kp 覆盖校验才能通过）。
SPLIT3_JSON = json.dumps({"knowledge_points": ["极限", "导数", "积分"]}, ensure_ascii=False)

SPLIT3_BLUEPRINT_JSON = json.dumps(
    {
        "narrative": "极限→导数→积分。",
        "terminology": [],
        "sections": [
            {
                "id": "sec-1",
                "title": "极限的定义",
                "purpose": "建立极限概念",
                "key_points": ["逼近"],
                "target_chars": 800,
                "difficulty": "基础",
                "misconceptions": [],
                "frontier": False,
            },
            {
                "id": "sec-2",
                "title": "导数的定义",
                "purpose": "建立导数概念",
                "key_points": ["变化率"],
                "target_chars": 800,
                "difficulty": "基础",
                "misconceptions": [],
                "frontier": False,
            },
            {
                "id": "sec-3",
                "title": "积分的定义",
                "purpose": "建立积分概念",
                "key_points": ["分割求和"],
                "target_chars": 800,
                "difficulty": "基础",
                "misconceptions": [],
                "frontier": False,
            },
        ],
        "figures": [],
    },
    ensure_ascii=False,
)

SPLIT3_BACKBONE_MD = """# 微积分基础

引入段。

[[FILL:sec-1]]

衔接段。

[[FILL:sec-2]]

衔接段。

[[FILL:sec-3]]

## 总结
"""


def _llm_with_fixtures(*, blueprint_json, backbone_md, split_json=None):
    """按 prompt 关键词路由的夹具 LLM：split（knowledge_points）/blueprint/backbone/audit/fill。"""

    async def fake_llm(system, user):
        if split_json is not None and "knowledge_points" in system:
            return split_json
        if "总编" in system:
            return blueprint_json
        if "核查" in system:
            return AUDIT_JSON
        if "骨架" in system:
            return backbone_md
        return FILL_BODY

    return fake_llm


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

    def test_placeholder_residual_hard_fails_instead_of_degraded_delivery(self):
        """占位符残留绝不交付：成稿带 [[FILL: 时必须是 failed 终态，而不是 degraded 降级交付。

        构造路径（真实缺陷形态）：作者补写正文未经 FillRunner 验收，把占位符写进小节
        正文；汇编器只扫骨架不重扫替换文本，占位符随之进入成稿。
        """

        async def placeholder_fill_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            if "极限的严格定义" in user:
                return FILL_BODY + "\n\n承接 [[FILL:ghost_sec]] 小节的讨论。\n"
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, llm_func=placeholder_fill_llm)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "placeholder_residual")
        self.assertEqual(result["error"]["stage"], "accept")
        self.assertIn("[[FILL:", result["error"]["detail"])
        # 硬失败终态不附带任何成功/交付载荷
        self.assertNotIn("markdown", result)
        self.assertNotIn("material", result)
        self.assertNotIn("degraded", result)


class AuthorPipelineObservabilityTests(unittest.TestCase):
    """I-1：research 的 search 与各 LLM 阶段调用必须发 tool_call 事件（无隐藏调用）。"""

    @staticmethod
    def _tool_calls(events, tool):
        return [e["data"] for e in events if e["type"] == "tool_call" and e["data"].get("tool") == tool]

    def test_search_and_llm_stage_events_emitted(self):
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

        self.assertEqual(result["status"], "ok")
        # research：每次 search 调用前有 start、完成后带 result_count
        search_calls = self._tool_calls(events, "search")
        self.assertTrue(search_calls)
        self.assertTrue(any(d.get("status") == "start" and d.get("query") for d in search_calls))
        self.assertTrue(any(d.get("result_count") == 1 for d in search_calls))
        # LLM 阶段：blueprint/backbone/audit 均可观测，完成时带 chars
        llm_calls = self._tool_calls(events, "llm")
        self.assertTrue({"blueprint", "backbone", "audit"} <= {d.get("stage") for d in llm_calls})
        audit_done = [d for d in llm_calls if d.get("stage") == "audit" and "chars" in d]
        self.assertTrue(audit_done)
        self.assertTrue(all(d.get("sec_id") == "sec-1" for d in audit_done))

    def test_search_failure_emits_error_event(self):
        async def failing_serp(query, n):
            raise RuntimeError("serp down")

        async def fake_fetch(url):
            return "页面正文"

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(),
                    toolbox=ResearchToolbox(serp_func=failing_serp, fetch_func=fake_fetch),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")  # 检索失败不阻断成书
        search_calls = self._tool_calls(events, "search")
        self.assertTrue(any("error" in d for d in search_calls))

    def test_revision_stage_event_on_unsupported_claims(self):
        unsupported_audit = json.dumps(
            {"claims": [{"text": "极限就是直接代入", "verdict": "unsupported", "fix": "删除该断言"}]},
            ensure_ascii=False,
        )

        async def revising_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return unsupported_audit
            if "骨架" in system:
                return BACKBONE_MD
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=revising_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["revision_attempts"], 1)
        revision_calls = [d for d in self._tool_calls(events, "llm") if d.get("stage") == "revision"]
        self.assertTrue(any(d.get("sec_id") == "sec-1" and "chars" in d for d in revision_calls))


class AuthorPipelineFaultToleranceTests(unittest.TestCase):
    """I-2：fill/figure 子调用异常不炸掉整本书，走结构化降级，不向上抛。"""

    def test_fill_exception_falls_back_to_author_rewrite(self):
        async def flaky_fill_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            if "极限的直观概念" in user and "请作者亲自撰写" not in user:
                raise ConnectionError("llm stack down")  # 填充子代理整个炸掉
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=flaky_fill_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["degraded"])
        self.assertTrue(any(n.startswith("fill_error:sec-1") for n in result["quality_notes"]))
        todo = next(t for t in result["todos"] if t["id"] == "fill:sec-1")
        self.assertEqual(todo["status"], "done")
        self.assertEqual(todo["note"], "author_rewrite")
        # 作者补写作为独立 LLM 阶段可被观测
        author_fill = [
            e["data"] for e in events
            if e["type"] == "tool_call" and e["data"].get("tool") == "llm" and e["data"].get("stage") == "author_fill"
        ]
        self.assertTrue(any(d.get("sec_id") == "sec-1" and "chars" in d for d in author_fill))

    def test_fill_and_author_rewrite_both_raise_marks_section_failed(self):
        async def fill_down_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            if "极限的直观概念" in user:
                raise ConnectionError("llm stack down")  # 填充与作者补写都炸
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(  # 不向上抛未捕获异常
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=fill_down_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "failed")
        todo = next(t for t in result["todos"] if t["id"] == "fill:sec-1")
        self.assertEqual(todo["status"], "failed")
        self.assertTrue(any(n.startswith("author_fill_error:sec-1") for n in result["quality_notes"]))

    def test_figure_forge_exception_strips_fig_and_waives(self):
        class _ExplodingForge:
            async def generate(self, spec):
                raise TypeError("render engine exploded")  # 不在旧捕获列表 (ValueError, RuntimeError) 内

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_ExplodingForge(),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("[[FIG:", result["markdown"])
        self.assertTrue(any(n.startswith("figure_failed:1") for n in result["quality_notes"]))
        todo = next(t for t in result["todos"] if t["id"] == "fig:1")
        self.assertEqual(todo["status"], "waived")


class AuthorBackboneFigValidationTests(unittest.TestCase):
    """M-2：BACKBONE 校验覆盖 [[FIG:n]]，缺失与 FILL 缺失同等处理（重试 1 次 → failed）。"""

    def test_backbone_missing_fig_placeholder_fails_after_one_retry(self):
        backbone_no_fig = "# 极限入门\n\n[[FILL:sec-1]]\n\n衔接段。\n\n[[FILL:sec-2]]\n"
        events = []
        counter = {}
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(backbone_text=backbone_no_fig, counter=counter),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "backbone_placeholder_missing")
        self.assertEqual(counter.get("backbone"), 2)  # 首次 + 重试 1 次
        self.assertTrue(any("[[FIG:1]]" in n for n in result["quality_notes"]))


class AuthorBlueprintRetryFeedbackTests(unittest.TestCase):
    """蓝图校验失败的重试必须把失败原因喂回模型；重试仍失败时失败详情透出到 error.detail。"""

    @staticmethod
    def _blueprint_variant(**mutations):
        data = json.loads(BLUEPRINT_JSON)
        figures = mutations.get("figures")
        if figures:
            data["figures"][0].update(figures)
        sections = mutations.get("sections")
        if sections:
            data["sections"][0].update(sections)
        return json.dumps(data, ensure_ascii=False)

    def test_retry_user_message_contains_validation_error(self):
        # 首次蓝图 figures[].kind 自造词（真实失败模式），重试带反馈后修正 → 流水线继续。
        bad_kind = self._blueprint_variant(figures={"kind": "diagram"})
        blueprint_users = []

        async def flaky_blueprint_llm(system, user):
            if "总编" in system:
                blueprint_users.append(user)
                return bad_kind if len(blueprint_users) == 1 else BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=flaky_blueprint_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(blueprint_users), 2)
        self.assertIn("unknown figure kind", blueprint_users[1])
        self.assertIn("diagram", blueprint_users[1])

    def test_retry_exhausted_returns_both_error_details(self):
        # 两次蓝图各自不同的校验错误 → failed 结果必须带齐两条详情。
        bad_kind = self._blueprint_variant(figures={"kind": "diagram"})
        bad_difficulty = self._blueprint_variant(sections={"difficulty": "进阶"})
        responses = iter([bad_kind, bad_difficulty])

        async def always_bad_blueprint_llm(system, user):
            if "总编" in system:
                return next(responses)
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=always_bad_blueprint_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "blueprint_invalid")
        detail = result["error"]["detail"]
        self.assertIn("unknown figure kind", detail)
        self.assertIn("unknown difficulty", detail)


class AuthorInlineCitationTests(unittest.TestCase):
    """C2/G0 真实运行修复：[^n] 内联引用体系、骨架净化与收尾 footer 的端到端验证。"""

    # fake 正文带合法内联引用 [^1]（对应 fake 检索唯一来源 https://example.com/limits）。
    CITED_FILL_BODY = FILL_BODY + "这一直观解释有检索来源支持[^1]。"

    # 真实缺陷形态：骨架 LLM 在占位符上方自加「正文占位」空标题。
    BACKBONE_WITH_BOGUS_HEADINGS = BACKBONE_MD.replace(
        "[[FILL:sec-1]]", "### 正文占位\n\n[[FILL:sec-1]]"
    ).replace(
        "[[FILL:sec-2]]", "### 正文占位\n\n[[FILL:sec-2]]"
    )

    def _cited_llm(self, backbone_text):
        async def fake_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return backbone_text
            return self.CITED_FILL_BODY

        return fake_llm

    def test_full_run_with_citations_registry_footer_and_sanitized_backbone(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=self._cited_llm(self.BACKBONE_WITH_BOGUS_HEADINGS),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

            self.assertEqual(result["status"], "ok")
            markdown = result["markdown"]

            # 骨架净化：「正文占位」标题不进成稿
            self.assertNotIn("占位", markdown)

            # 内联引用与文末脚注定义一一对应
            self.assertIn("[^1]", markdown)
            self.assertIn("[^1]: 极限 通俗解释 — https://example.com/limits", markdown)

            # 收尾 footer：成稿以句读终止符结束（消除 eof_mid_sentence）
            self.assertIn("本资料由作者代理生成", markdown)
            self.assertTrue(markdown.rstrip().endswith("。"))

            # 来源登记表落进 research.md 头部，facts 行保留 src: url
            research = (Path(tmp) / "notes" / "research.md").read_text(encoding="utf-8")
            self.assertIn("## 来源登记表", research)
            self.assertIn("[^1] 极限 通俗解释 https://example.com/limits", research)
            self.assertIn("src: https://example.com/limits", research)
            self.assertLess(
                research.index("## 来源登记表"), research.index("## 极限"),
                "来源登记表必须位于研究笔记头部",
            )

            # references 透出登记表编号，供 assembler 渲染脚注定义
            self.assertEqual(result["references"][0]["n"], 1)

    def test_sanitized_backbone_snapshot_in_notes(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=self._cited_llm(self.BACKBONE_WITH_BOGUS_HEADINGS),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

            self.assertEqual(result["status"], "ok")
            backbone_note = (Path(tmp) / "notes" / "backbone.md").read_text(encoding="utf-8")
            self.assertNotIn("占位", backbone_note)


class BlueprintDifficultyVocabularyTests(unittest.TestCase):
    """蓝图 difficulty 词表校验（真实运行中模型产出整数难度/自造词）。"""

    @staticmethod
    def _with_difficulty(value):
        data = json.loads(BLUEPRINT_JSON)
        data["sections"][0]["difficulty"] = value
        return data

    def test_integer_difficulty_rejected(self):
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(self._with_difficulty(1))

    def test_unknown_difficulty_word_rejected(self):
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(self._with_difficulty("进阶"))


class AuthorUnderscoreSectionIdTests(unittest.TestCase):
    """端到端回归（真实缺陷）：LLM 产出下划线小节 id（s0_frontmatter），旧 FILL_RE
    字符集不含 _，占位符既不被替换也不报缺失，静默残留成稿并降级交付（8 处残留）。
    修复后全链路必须替换干净、验收通过。"""

    UNDERSCORE_BLUEPRINT_JSON = json.dumps(
        {
            "narrative": "先建立直觉，再严格化。",
            "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小正数"}],
            "sections": [
                {
                    "id": "s0_frontmatter",
                    "title": "极限的直观概念",
                    "purpose": "建立直觉",
                    "key_points": ["逼近", "直观定义"],
                    "target_chars": 800,
                    "difficulty": "基础",
                    "misconceptions": [],
                    "frontier": True,
                },
                {
                    "id": "s1_definition",
                    "title": "极限的严格定义",
                    "purpose": "严格化",
                    "key_points": ["epsilon-delta 定义"],
                    "target_chars": 800,
                    "difficulty": "应用",
                    "misconceptions": [],
                    "frontier": False,
                },
            ],
            "figures": [
                {"n": 1, "sec_id": "s0_frontmatter", "intent": "逼近示意", "kind": "mermaid", "caption": "图1 逼近过程"}
            ],
        },
        ensure_ascii=False,
    )

    UNDERSCORE_BACKBONE_MD = """# 极限入门

## 第一章 直观

引入段：本节回答什么是逼近。

[[FILL:s0_frontmatter]]

[[FIG:1]]

衔接段：有了直觉，下面严格化。

[[FILL:s1_definition]]

## 总结
"""

    def test_full_run_with_underscore_section_ids_ships_clean_document(self):
        async def underscore_llm(system, user):
            if "总编" in system:
                return self.UNDERSCORE_BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return self.UNDERSCORE_BACKBONE_MD
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=underscore_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["degraded"], msg=result.get("quality_report"))
        markdown = result["markdown"]
        self.assertNotIn("[[FILL:", markdown)
        self.assertNotIn("[[FIG:", markdown)
        self.assertIn("## 参考文献", markdown)
        self.assertTrue(result["quality_report"]["passed"])


class AuthorResearchDeepReadTests(unittest.TestCase):
    """研究阶段升级：deep/research preset 追加 wikipedia 查询、深读 serp top URL；事件带 provider/urls。"""

    @staticmethod
    def _toolbox(log, fetch_fail_substr=None):
        async def fake_serp(query, n):
            log.append(("serp", query))
            slug = query.replace(" ", "_")
            return [
                {"title": f"t1 {query}", "url": f"https://example.com/p1/{slug}", "content": f"事实一 {query}", "score": 0.9},
                {"title": f"t2 {query}", "url": f"https://example.com/p2/{slug}", "content": f"事实二 {query}", "score": 0.8},
            ]

        async def fake_wiki(query, n):
            log.append(("wiki", query))
            return [{
                "title": f"百科 {query}",
                "url": f"https://zh.wikipedia.org/wiki/{query}",
                "content": "条目正文",
                "score": 0.8,
            }]

        async def fake_fetch(url):
            log.append(("fetch", url))
            if fetch_fail_substr and fetch_fail_substr in url:
                raise RuntimeError("fetch http 500")
            return "页面正文" * 200  # 1000 字，验证深读摘要截断

        return ResearchToolbox(serp_func=fake_serp, fetch_func=fake_fetch, wiki_func=fake_wiki)

    def _run(self, tmp, events, log, *, preset="deep", fetch_fail_substr=None):
        ctx = AuthorPipelineContext(
            task_id="t-author-deep",
            topic="微积分基础",
            subject="数学",
            work_dir=Path(tmp),
            user_id="u-1",
            preset=preset,
            knowledge_points=["极限", "导数"],
        )
        return asyncio.run(
            run_author_pipeline(
                ctx,
                # 两 kp ctx 的蓝图必须逐 kp 给小节（kp 覆盖校验），故不用默认单 kp 的 BLUEPRINT_JSON。
                llm_func=_llm_with_fixtures(blueprint_json=TWO_KP_BLUEPRINT_JSON, backbone_md=TWO_KP_BACKBONE_MD),
                toolbox=self._toolbox(log, fetch_fail_substr),
                emit=events.append,
                forge=_fake_forge(events),
            )
        )

    @staticmethod
    def _tool_calls(events, tool):
        return [e["data"] for e in events if e["type"] == "tool_call" and e["data"].get("tool") == tool]

    def test_deep_preset_adds_wikipedia_query_and_two_deep_reads_per_kp(self):
        events, log = [], []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, log, preset="deep")
            research = (Path(tmp) / "notes" / "research.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "ok")
        # 每个知识点追加 1 条 wikipedia 查询（查询词为知识点本身）
        self.assertEqual([q for kind, q in log if kind == "wiki"], ["极限", "导数"])
        # deep preset：每 kp 从 serp 结果深读 top-2（两 kp 共 4 次 browse）
        fetched = [url for kind, url in log if kind == "fetch"]
        self.assertEqual(len(fetched), 4)
        self.assertIn("https://example.com/p1/极限_数学", fetched)
        self.assertIn("https://example.com/p2/极限_数学", fetched)
        # 深读摘要（前 500 字）作为 deep_read 行落入研究笔记
        line = next(ln for ln in research.splitlines() if "deep_read" in ln and "p1/极限_数学" in ln)
        self.assertIn("src: https://example.com/p1/极限_数学", line)
        self.assertLessEqual(len(line), 600, "深读摘要必须截断到 ~500 字")

        # search 完成事件带 provider 与前 5 条结果 URL
        search_done = [d for d in self._tool_calls(events, "search") if "result_count" in d]
        self.assertTrue(search_done)
        self.assertTrue(all(d.get("provider") in ("tavily", "wikipedia") for d in search_done))
        self.assertTrue(all(isinstance(d.get("urls"), list) and d["urls"] for d in search_done))
        self.assertTrue(all(len(d["urls"]) <= 5 for d in search_done))
        self.assertTrue(any(d["provider"] == "wikipedia" for d in search_done))
        # browse 事件带 url 与 ok 状态
        browse_calls = self._tool_calls(events, "browse")
        self.assertEqual(len(browse_calls), 4)
        self.assertTrue(all(d.get("status") == "ok" and d.get("url") for d in browse_calls))

    def test_standard_preset_skips_wikipedia_and_deep_reads_top1(self):
        events, log = [], []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, log, preset="standard")

        self.assertEqual(result["status"], "ok")
        self.assertFalse([q for kind, q in log if kind == "wiki"], "quick/standard 不走 wikipedia 通道")
        # 每 kp 仅深读 serp top-1（两 kp 共 2 次 browse）
        fetched = [url for kind, url in log if kind == "fetch"]
        self.assertEqual(len(fetched), 2)
        self.assertEqual(len(self._tool_calls(events, "browse")), 2)
        # standard preset 下 search 事件同样带 provider/urls
        search_done = [d for d in self._tool_calls(events, "search") if "result_count" in d]
        self.assertTrue(all(d.get("provider") == "tavily" for d in search_done))
        self.assertTrue(all(d.get("urls") for d in search_done))

    def test_browse_failure_records_quality_note_without_blocking(self):
        events, log = [], []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, log, preset="deep", fetch_fail_substr="p1/")
            research = (Path(tmp) / "notes" / "research.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(any(n.startswith("deep_read_failed:") for n in result["quality_notes"]))
        browse_calls = self._tool_calls(events, "browse")
        self.assertTrue(any(d.get("status") == "error" for d in browse_calls))
        self.assertTrue(any(d.get("status") == "ok" for d in browse_calls))
        # top-1 失败不阻断：top-2 的深读摘要仍落笔记
        self.assertTrue(any("deep_read" in ln and "p2/极限_数学" in ln for ln in research.splitlines()))


class AuthorSourceRegistryExpansionTests(unittest.TestCase):
    """C1 真实缺陷（run #4 参考文献 URL 5/10）：来源登记表只收录被事实行引用的 URL，
    检索到但未直接引用的结果不登记。修复：每次 search 成功后把结果前 5 条 URL 全部登记
    （去重、保留首次 title，cap 25），事实行的 src 照常引用。"""

    @staticmethod
    def _sparse_serp_toolbox():
        """每条查询返回 5 条不同 URL，仅前 2 条带事实内容（后 3 条旧逻辑不会登记）。"""

        async def fake_serp(query, n):
            fake_serp.calls += 1
            q = fake_serp.calls
            return [
                {
                    "title": f"T{q}-{i}",
                    "url": f"https://example.com/r{q}_{i}",
                    "content": f"事实 {i}" if i < 2 else "",
                    "score": 0.9,
                }
                for i in range(5)
            ]

        fake_serp.calls = 0

        async def fake_fetch(url):
            return "页面正文"

        return ResearchToolbox(serp_func=fake_serp, fetch_func=fake_fetch)

    def _research_only(self, tmp, kps):
        ctx = AuthorPipelineContext(
            task_id="t-author-src",
            topic="综合专题",
            subject="数学",
            work_dir=Path(tmp),
            user_id="u-1",
            preset="standard",
            knowledge_points=kps,
        )
        pipeline = _AuthorPipeline(
            ctx, llm_func=_fake_llm(), toolbox=self._sparse_serp_toolbox(), emit=lambda event: None
        )
        asyncio.run(pipeline._research())  # noqa: SLF001 - 只驱动研究阶段，聚焦登记行为
        return pipeline

    def test_search_results_registered_beyond_fact_cited_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = self._research_only(tmp, ["极限"])

        urls = {entry["url"] for entry in pipeline.source_registry}
        # 2 条查询 × 5 条 URL 全部登记（含无事实内容、旧逻辑遗漏的 3 条）
        self.assertEqual(len(pipeline.source_registry), 10)
        self.assertEqual(
            urls,
            {f"https://example.com/r{q}_{i}" for q in (1, 2) for i in range(5)},
        )

    def test_registry_covers_real_retrieval_surface_with_six_kps(self):
        kps = ["特征值定义", "特征多项式", "对角化", "相似矩阵", "特征向量求法", "谱定理"]
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = self._research_only(tmp, kps)

        # 6 kp × 2 查询 × 5 URL = 60 条候选，cap 25
        self.assertGreaterEqual(len(pipeline.source_registry), 10)
        self.assertLessEqual(len(pipeline.source_registry), 25)

    def test_register_source_dedupes_keeps_first_title_and_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-src-unit",
                topic="极限",
                subject="数学",
                work_dir=Path(tmp),
                user_id="u-1",
                knowledge_points=["极限"],
            )
            pipeline = _AuthorPipeline(
                ctx, llm_func=_fake_llm(), toolbox=_fake_toolbox(), emit=lambda event: None
            )
            first = pipeline._register_source("https://example.com/a", "首次标题")  # noqa: SLF001
            again = pipeline._register_source("https://example.com/a", "重复标题")  # noqa: SLF001

            self.assertEqual(first, again)
            self.assertEqual(pipeline.source_registry[0]["title"], "首次标题")

            for i in range(1, 30):
                pipeline._register_source(f"https://example.com/{i}", f"t{i}")  # noqa: SLF001
            self.assertEqual(len(pipeline.source_registry), 25)


class AuthorBlueprintKpCoverageTests(unittest.TestCase):
    """蓝图知识点覆盖校验：用与 benchmark 同源的 split_sections_by_kp 归属逻辑，
    每个输入 kp 必须有小节标题归属；未覆盖名单进重试反馈（共用 1 次重试额度）。

    真实缺陷（benchmark eigen_decomposition 4/6）：LLM 持续把两个 kp 合并成一节，
    成稿按小节标题匹配知识点时合并不掉的那几个 kp 归属为空。
    """

    @staticmethod
    def _ctx_two_kps(work_dir):
        return AuthorPipelineContext(
            task_id="t-author-kp-cov",
            topic="微积分基础",
            subject="数学",
            work_dir=Path(work_dir),
            user_id="u-1",
            preset="standard",
            knowledge_points=["极限", "导数"],
        )

    def test_uncovered_kp_listed_in_retry_feedback_then_recovers(self):
        blueprint_users = []

        async def flaky_blueprint_llm(system, user):
            if "总编" in system:
                blueprint_users.append(user)
                # 首次蓝图两节都是 极限 标题：导数 无小节标题归属
                return BLUEPRINT_JSON if len(blueprint_users) == 1 else TWO_KP_BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return TWO_KP_BACKBONE_MD
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_two_kps(tmp),
                    llm_func=flaky_blueprint_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(blueprint_users), 2)
        self.assertIn("未被任何小节标题覆盖", blueprint_users[1])
        self.assertIn("导数", blueprint_users[1])

    def test_uncovered_kp_exhausts_retry_returns_blueprint_invalid(self):
        async def merged_blueprint_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON  # 始终只覆盖 极限
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return TWO_KP_BACKBONE_MD
            return FILL_BODY

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_two_kps(tmp),
                    llm_func=merged_blueprint_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "blueprint_invalid")
        self.assertIn("未被任何小节标题覆盖", result["error"]["detail"])
        self.assertIn("导数", result["error"]["detail"])

    def test_frontmatter_and_summary_sections_do_not_cover_kps(self):
        """前置/总结小节不顶替 kp 归属：只有前置+总结时两个 kp 均未覆盖。"""
        bp = Blueprint.from_dict({
            "narrative": "n",
            "terminology": [],
            "sections": [
                {
                    "id": "sec-0", "title": "前置知识", "purpose": "p", "key_points": ["k"],
                    "target_chars": 800, "difficulty": "基础", "misconceptions": [], "frontier": False,
                },
                {
                    "id": "sec-9", "title": "全书总结", "purpose": "p", "key_points": ["k"],
                    "target_chars": 800, "difficulty": "基础", "misconceptions": [], "frontier": False,
                },
            ],
            "figures": [],
        })
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = _AuthorPipeline(
                self._ctx_two_kps(tmp), llm_func=_fake_llm(), toolbox=_fake_toolbox(), emit=lambda event: None
            )
            uncovered = pipeline._blueprint_kp_coverage(bp)  # noqa: SLF001
        self.assertEqual(uncovered, ["极限", "导数"])

    def test_kp_covered_by_section_title_containing_kp_name(self):
        bp = Blueprint.from_dict(json.loads(TWO_KP_BLUEPRINT_JSON))
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = _AuthorPipeline(
                self._ctx_two_kps(tmp), llm_func=_fake_llm(), toolbox=_fake_toolbox(), emit=lambda event: None
            )
            uncovered = pipeline._blueprint_kp_coverage(bp)  # noqa: SLF001
        self.assertEqual(uncovered, [])


class AuthorKpSplitTests(unittest.TestCase):
    """知识点拆分阶段（split）：ctx 未给知识点时先拆题，研究按拆分结果逐 kp 检索。

    真实缺陷（benchmark eigen_decomposition 实跑）：请求侧不给知识点时整条 pipeline
    把整段 query 当 1 个知识点，deep preset 全程只有 1 个 kp 的检索量。
    """

    @staticmethod
    def _ctx_no_kps(work_dir, **overrides):
        params = dict(
            task_id="t-author-split",
            topic="微积分基础",
            subject="数学",
            work_dir=Path(work_dir),
            user_id="u-1",
            preset="standard",
        )
        params.update(overrides)
        return AuthorPipelineContext(**params)

    @staticmethod
    def _llm_stages(events, stage):
        return [
            e["data"] for e in events
            if e["type"] == "tool_call" and e["data"].get("tool") == "llm" and e["data"].get("stage") == stage
        ]

    @staticmethod
    def _search_starts(events):
        return [
            e["data"] for e in events
            if e["type"] == "tool_call" and e["data"].get("tool") == "search" and e["data"].get("status") == "start"
        ]

    def test_split_fans_out_research_per_kp(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_no_kps(tmp),
                    llm_func=_llm_with_fixtures(
                        blueprint_json=SPLIT3_BLUEPRINT_JSON,
                        backbone_md=SPLIT3_BACKBONE_MD,
                        split_json=SPLIT3_JSON,
                    ),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )
            research = (Path(tmp) / "notes" / "research.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "ok")
        # split 阶段可观测：LLM 调用完成带 chars
        self.assertTrue(any("chars" in d for d in self._llm_stages(events, "split")))
        # standard preset 每 kp 2 条查询：3 个拆分知识点 → 6 次 search
        starts = self._search_starts(events)
        self.assertEqual(len(starts), 6)
        queries = [d["query"] for d in starts]
        for kp in ("极限", "导数", "积分"):
            self.assertTrue(any(q.startswith(kp) for q in queries), msg=queries)
        # plan 透出拆分结果；拆分行落在研究笔记头部（kp 小节之前）
        self.assertEqual([p["title"] for p in result["plan"]["knowledge_points"]], ["极限", "导数", "积分"])
        self.assertIn("## 知识点拆分：极限、导数、积分", research)
        self.assertLess(research.index("## 知识点拆分"), research.index("\n## 极限\n"))

    def test_split_invalid_output_falls_back_to_topic(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-split-fallback",
                topic="极限",
                subject="数学",
                work_dir=Path(tmp),
                user_id="u-1",
                preset="standard",
            )
            result = asyncio.run(
                run_author_pipeline(
                    ctx,
                    llm_func=_llm_with_fixtures(
                        blueprint_json=BLUEPRINT_JSON, backbone_md=BACKBONE_MD, split_json="这不是 JSON"
                    ),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        # 回退 [topic]：1 个 kp × 2 查询；quality note 记录回退
        self.assertEqual(len(self._search_starts(events)), 2)
        self.assertTrue(any(n.startswith("kp_split_fallback:") for n in result["quality_notes"]))
        self.assertEqual([p["title"] for p in result["plan"]["knowledge_points"]], ["极限"])

    def test_split_skipped_when_ctx_provides_kps(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-split-skip",
                topic="微积分基础",
                subject="数学",
                work_dir=Path(tmp),
                user_id="u-1",
                preset="standard",
                knowledge_points=["极限", "导数"],
            )
            result = asyncio.run(
                run_author_pipeline(
                    ctx,
                    llm_func=_llm_with_fixtures(
                        blueprint_json=TWO_KP_BLUEPRINT_JSON,
                        backbone_md=TWO_KP_BACKBONE_MD,
                        split_json=SPLIT3_JSON,  # 若被调用会返回 3 个点——必须不被调用
                    ),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._llm_stages(events, "split"), [])
        self.assertEqual([p["title"] for p in result["plan"]["knowledge_points"]], ["极限", "导数"])

    def test_split_result_clamped_to_max_points(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_no_kps(tmp, options={"max_points": 2}),
                    llm_func=_llm_with_fixtures(
                        blueprint_json=TWO_KP_BLUEPRINT_JSON,
                        backbone_md=TWO_KP_BACKBONE_MD,
                        split_json=SPLIT3_JSON,
                    ),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        # max_points=2：拆分 3 个点截到前 2 个（保留学习顺序在前的）
        self.assertEqual(len(self._search_starts(events)), 4)
        self.assertEqual([p["title"] for p in result["plan"]["knowledge_points"]], ["极限", "导数"])

    def test_split_runs_when_ctx_kps_is_topic_wrap(self):
        """编排层把整段 query 兜底包装成单个“知识点”（== topic）时视同未给，照常拆分。"""
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-split-wrap",
                topic="极限",
                subject="数学",
                work_dir=Path(tmp),
                user_id="u-1",
                preset="standard",
                knowledge_points=["极限"],  # == topic：编排层兜底包装
            )
            result = asyncio.run(
                run_author_pipeline(
                    ctx,
                    llm_func=_llm_with_fixtures(
                        blueprint_json=TWO_KP_BLUEPRINT_JSON,
                        backbone_md=TWO_KP_BACKBONE_MD,
                        split_json=json.dumps({"knowledge_points": ["极限", "导数"]}, ensure_ascii=False),
                    ),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(self._llm_stages(events, "split"))
        self.assertEqual(len(self._search_starts(events)), 4)
        self.assertEqual([p["title"] for p in result["plan"]["knowledge_points"]], ["极限", "导数"])


if __name__ == "__main__":
    unittest.main()
