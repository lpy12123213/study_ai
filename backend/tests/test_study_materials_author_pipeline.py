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


if __name__ == "__main__":
    unittest.main()
