"""作者流水线（run_author_pipeline）端到端测试：假 LLM/假检索/假 figure forge。

驱动 research→blueprint→backbone→fill→assemble 全流程，断言 TODO 清零、
占位符清零、事件序列、参考文献渲染与 backbone 缺占位符的失败终态。
"""

import asyncio
import json
import re
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from backend.generation.study_materials.author.blueprint import Blueprint, BlueprintError
from backend.generation.study_materials.author.figures import FigureForge
from backend.generation.study_materials.author.pipeline import (
    AuthorPipelineContext,
    _authority_search_query,
    _AuthorPipeline,
    _distribute_section_quota,
    _task_authority_queries,
    run_author_pipeline,
)
from backend.generation.study_materials.author.research_tools import ResearchToolbox
from backend.generation.study_materials.author.todos import TodoList
from backend.generation.study_materials.learning_contract import (
    inspect_learning_contract,
    renumber_learning_tags_by_section,
)
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
    "[Q1][基础] 用自己的话解释逼近，并求 x→0 时 2x 的极限。"
    "[A1] 答案：0。评分点：趋势判断正确、表述无循环论证。"
)

_QUOTA_LEVELS = ["基础", "应用", "迁移"]


class SectionQuotaDistributionTests(unittest.TestCase):
    def test_whole_book_quota_is_not_ceil_duplicated_per_section(self):
        questions = _distribute_section_quota(total=12, count=10, cap=4)
        examples = _distribute_section_quota(total=4, count=10, cap=2)

        self.assertEqual(sum(questions), 12)
        self.assertEqual(sum(examples), 4)
        self.assertEqual(len(questions), 10)
        self.assertEqual(len(examples), 10)
        self.assertLessEqual(max(questions), 4)
        self.assertLessEqual(max(examples), 2)
        self.assertEqual(sum(value > 0 for value in examples), 4)

    def test_per_section_caps_leave_only_true_overflow_for_global_repair(self):
        self.assertEqual(_distribute_section_quota(total=12, count=2, cap=4), [4, 4])
        self.assertEqual(_distribute_section_quota(total=4, count=2, cap=2), [2, 2])


def _grounded_fill_body(user: str, body: str = FILL_BODY) -> str:
    """Make fake writers behave like a competent model following the payload:
    cite the first source made available to that section, and satisfy the
    per-section learning quotas（本节学习闭环硬性配额）announced in the payload."""

    text = str(user or "")
    source_ids = re.findall(r"^\s*[-*+]\s*\[\^(\d+)\]", text, re.MULTILINE)
    clean = re.sub(r"\[\^\d+\]", "", body)

    ex_match = re.search(r"至少 (\d+) 个 \[EXn\]", text)
    q_match = re.search(r"至少 (\d+) 道 \[Qn\]", text)
    min_examples = int(ex_match.group(1)) if ex_match else 0
    min_questions = int(q_match.group(1)) if q_match else 0
    # FILL_BODY 自带 [EX1]/[Q1]/[A1]；配额高于 1 时按编号与层级轮转补足其余。
    for n in range(2, min_examples + 1):
        clean += f"\n\n**[EX{n}]** 补充例题。步骤：先分析条件，再逐步推导，最后检验结果。"
    for n in range(2, min_questions + 1):
        level = _QUOTA_LEVELS[(n - 1) % len(_QUOTA_LEVELS)]
        clean += f"\n\n**[Q{n}]**[{level}] 补充自测题？\n**[A{n}]** 答案要点。评分点：判断依据完整。"
    return clean + (f"\n\n本节关键事实可由给定来源核对。[^{source_ids[0]}]" if source_ids else "")

AUDIT_JSON = json.dumps(
    {"claims": [{"text": "极限描述无限逼近的过程", "verdict": "supported", "fix": ""}]},
    ensure_ascii=False,
)

LEARNING_APPENDIX = """## 学习目标（补全）
- 能解释极限的核心含义。
- 能按步骤计算基础极限。
- 能辨析极限中的常见误区。

## 前置知识（补全）
需要掌握基础代数运算、函数记号与变量趋近的直观含义。

## 带步骤例题（补全）
**[EX2]** 求一个一次函数的极限。
步骤：先识别趋近点，再代入连续函数，最后检查结果。

**[EX3]** 判断一段极限推理是否成立。
步骤：先核对前提，再逐项验证，最后说明边界。

## 全书自测题（补全）
- [Q2][基础] 极限描述什么过程？
- [Q3][基础] 连续函数如何求极限？
- [Q4][应用] 如何检查代入法的适用条件？
- [Q5][应用] 如何识别一个错误推理？
- [Q6][迁移] 条件改变时结论可能如何变化？
- [Q7][迁移] 如何构造一个边界案例？

## 答案与评分点（补全）
- [A2] 描述无限逼近；评分点：说清趋近与取值的区别。
- [A3] 在连续条件下代入；评分点：写出条件与结果。
- [A4] 核对连续性；评分点：说明适用边界。
- [A5] 逐项核对前提；评分点：指出失效步骤。
- [A6] 重新检查前提；评分点：说明变化链。
- [A7] 选择边界条件；评分点：案例与结论一致。
"""

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
        return _grounded_fill_body(user)

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
        return _grounded_fill_body(user)

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

    def test_backbone_unknown_placeholder_fails_after_one_retry(self):
        counter = {}
        backbone = BACKBONE_MD + "\n\n[[FILL:rogue-section]]\n"

        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(backbone_text=backbone, counter=counter),
                    toolbox=_fake_toolbox(),
                    emit=lambda _event: None,
                    forge=None,
                )
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "backbone_placeholder_missing")
        self.assertEqual(counter.get("backbone"), 2)
        self.assertTrue(
            any("主干含未知占位符" in note and "[[FILL:rogue-section]]" in note for note in result["quality_notes"]),
            result["quality_notes"],
        )

    def test_blueprint_invalid_fails_after_one_retry(self):
        events = []

        async def bad_blueprint_llm(system, user):
            if "总编" in system:
                return "这不是 JSON"
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

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
                return _grounded_fill_body(user)  # 汇编补写成功，保证流程走到 ACCEPT
            if "极限的直观概念" in user:
                return ""  # sec-1 填充与作者改写均交空 → fill todo 以 failed 终态残留
            return _grounded_fill_body(user)

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

    def test_placeholder_from_author_rewrite_fails_before_delivery(self):
        """子写手和作者补写都不能把 [[FILL: 残留带入可交付成稿。"""

        async def placeholder_fill_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            if "极限的严格定义" in user:
                return _grounded_fill_body(user) + "\n\n承接 [[FILL:ghost_sec]] 小节的讨论。\n"
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, llm_func=placeholder_fill_llm)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "assemble_failed")
        self.assertEqual(result["error"]["stage"], "assemble")
        self.assertTrue(any(note.startswith("author_fill_invalid:") for note in result["quality_notes"]))
        # 硬失败终态不附带任何成功/交付载荷
        self.assertNotIn("markdown", result)
        self.assertNotIn("material", result)
        self.assertNotIn("degraded", result)


class AuthorLearningContractTests(unittest.TestCase):
    @staticmethod
    def _ctx_with_questions(work_dir):
        ctx = _ctx(work_dir)
        ctx.options = {"with_questions": True}
        return ctx

    def test_whole_document_gap_gets_one_targeted_appendix(self):
        async def learning_llm(system, user):
            if "练习总编" in system:
                return LEARNING_APPENDIX
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_with_questions(tmp),
                    llm_func=learning_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["degraded"], msg=result["quality_report"])
        self.assertTrue(inspect_learning_contract(result["markdown"])["passed"])
        self.assertLess(result["markdown"].index("## 学习目标（补全）"), result["markdown"].index("## 参考文献"))
        learning_todo = next(todo for todo in result["todos"] if todo["id"] == "learning_contract")
        self.assertEqual(learning_todo["status"], "done")
        self.assertEqual(result["learning_repair_attempts"], 1)
        repair_events = [
            event["data"]
            for event in events
            if event["type"] == "tool_call" and event["data"].get("stage") == "learning_repair"
        ]
        self.assertTrue(repair_events)

    def test_invalid_learning_repair_is_explicitly_degraded(self):
        async def invalid_learning_llm(system, user):
            if "练习总编" in system:
                return "## 学习目标（补全）\n- 仍不完整。"
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_with_questions(tmp),
                    llm_func=invalid_learning_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["degraded"])
        self.assertIn("learning_contract_unmet", result["quality_report"]["failed_checks"])
        learning_todo = next(todo for todo in result["todos"] if todo["id"] == "learning_contract")
        self.assertEqual(learning_todo["status"], "failed")
        self.assertEqual(result["learning_repair_attempts"], 2)

    def test_learning_repair_reads_harder_request_counts(self):
        repair_requests = []

        async def learning_llm(system, user):
            if "练习总编" in system:
                repair_requests.append(user)
                return LEARNING_APPENDIX
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx_with_questions(tmp)
            ctx.requirements = (
                "列出至少5个可检验学习目标；至少4个带完整步骤的例题；"
                "至少12道自测题；答案至少12份一一对应并给评分点。"
            )
            result = asyncio.run(
                run_author_pipeline(
                    ctx,
                    llm_func=learning_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertTrue(result["degraded"])
        self.assertEqual(len(repair_requests), 2)
        # 逐节配额受单节上限约束（2 节各 2 例题、4 题），已在填充时
        # 交齐 4 例题与 [Q1]..[Q8]；整书补齐只需兜底剩余 4 题（[Q9]..[Q12]），例题无需新增。
        for request in repair_requests:
            self.assertIn("- 例题: 无需新增", request)
            self.assertIn("[Q9]/[A9]", request)
            self.assertIn("[Q12]/[A12]", request)
            self.assertNotIn("[Q13]/[A13]", request)
            self.assertIn("学习目标用至少5条列表", request)
            self.assertIn("4题层级依次为", request)

    def test_section_local_question_numbers_are_renumbered_globally(self):
        first, second = renumber_learning_tags_by_section(
            [
                "[EX1] 例题。步骤。\n[Q1][基础] 第一题？\n[A1] 答案。评分点。",
                "[EX1] 例题。步骤。\n[Q1][应用] 第二题？\n[A1] 答案。评分点。",
            ]
        )

        self.assertIn("[EX1]", first)
        self.assertIn("[Q1]", first)
        self.assertIn("[A1]", first)
        self.assertIn("[EX2]", second)
        self.assertIn("[Q2]", second)
        self.assertIn("[A2]", second)
        inspected = inspect_learning_contract(
            "## 自测题\n" + first + "\n" + second,
        )
        self.assertEqual(inspected["question_count"], 2)
        self.assertEqual(inspected["paired_count"], 2)


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
        progress = [event["data"]["progress"] for event in events if event["type"] == "progress"]
        self.assertEqual(progress, sorted(progress))
        self.assertEqual((progress[0], progress[-1]), (5.0, 96.0))

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
            return _grounded_fill_body(user)

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
            return _grounded_fill_body(user)

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

    def test_author_rewrite_remaps_hallucinated_citation_to_supplied_source(self):
        async def hallucinated_citation_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            body = _grounded_fill_body(user)
            if "极限的直观概念" in user:
                return re.sub(r"\[\^\d+\]", "[^999]", body)
            return body

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=hallucinated_citation_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("[^999]", result["markdown"])
        self.assertTrue(any(note.startswith("author_fill_citations_remapped:sec-1:") for note in result["quality_notes"]))
        todo = next(t for t in result["todos"] if t["id"] == "fill:sec-1")
        self.assertEqual(todo["status"], "done")
        self.assertEqual(todo["note"], "author_rewrite")

    def test_author_rewrite_restores_label_for_existing_example_block(self):
        async def missing_example_label_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            body = _grounded_fill_body(user)
            if "极限的直观概念" in user:
                # 零学习配额时缺少 [EXn] 本身不应再强制重写；用同一次输出中的
                # 越界引用触发作者重写，再锁定已有例题块的确定性标签修复。
                return re.sub(r"\[\^\d+\]", "[^999]", body.replace("[EX1] ", ""))
            return body

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=missing_example_label_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertIn("**[EX1]**", result["markdown"])
        self.assertTrue(any(note == "author_fill_example_tag_inserted:sec-1" for note in result["quality_notes"]))
        todo = next(t for t in result["todos"] if t["id"] == "fill:sec-1")
        self.assertEqual(todo["status"], "done")
        self.assertEqual(todo["note"], "author_rewrite")

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
            return _grounded_fill_body(user)

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

    def test_fallback_leak_is_rewritten_once_instead_of_misparsed_as_missing_id(self):
        async def leaky_fill_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            if "本节含机器兜底说明" in user:
                return _grounded_fill_body(user)
            return _grounded_fill_body(user) + "\n> 本段未成功使用模型生成（source=llm_sectioned）\n"

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=leaky_fill_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("未成功使用模型生成", result["markdown"])
        self.assertIn("assemble_failed:fallback note leaked into content", result["quality_notes"])
        repair_calls = [
            event["data"]
            for event in events
            if event["type"] == "tool_call" and event["data"].get("stage") == "assembly_repair"
        ]
        self.assertEqual({call.get("sec_id") for call in repair_calls}, {"sec-1", "sec-2"})

    def test_failed_audit_revision_rolls_back_to_last_good_document(self):
        unsupported_audit = json.dumps(
            {"claims": [{"text": "极限就是代入", "verdict": "unsupported", "fix": "删除"}]},
            ensure_ascii=False,
        )

        async def leaky_revision_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                return unsupported_audit
            if "骨架" in system:
                return BACKBONE_MD
            if "以下断言无研究笔记支持" in user:
                return _grounded_fill_body(user) + "\n> 兜底内容\n"
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=leaky_revision_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["degraded"])
        self.assertNotIn("兜底内容", result["markdown"])
        self.assertIn("revision_rolled_back:assembly_failed", result["quality_notes"])
        revision = next(todo for todo in result["todos"] if todo["id"] == "revision")
        self.assertEqual(revision["status"], "failed")

    def test_audit_exception_delivers_last_good_document_as_degraded(self):
        async def audit_down_llm(system, user):
            if "总编" in system:
                return BLUEPRINT_JSON
            if "核查" in system:
                raise ConnectionError("audit unavailable")
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=audit_down_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["degraded"])
        self.assertTrue(result["markdown"].startswith("# 极限入门"))
        audit = next(todo for todo in result["todos"] if todo["id"] == "audit")
        self.assertEqual(audit["status"], "failed")


class AuthorBackboneFigValidationTests(unittest.TestCase):
    """Optional figure placement is repaired from its declared section anchor."""

    def test_backbone_missing_fig_placeholder_is_inserted_without_retry(self):
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

        self.assertEqual(result["status"], "ok")
        self.assertEqual(counter.get("backbone"), 1)
        self.assertIn("![图1 逼近过程](/media/generated/f1.svg)", result["markdown"])
        self.assertIn("backbone_figure_placeholder_inserted:1:sec-1", result["quality_notes"])

    def test_duplicate_fill_placeholder_is_collapsed_without_retry(self):
        duplicate = BACKBONE_MD.replace(
            "[[FILL:sec-1]]",
            "[[FILL:sec-1]]\n\n重复说明中的占位符：[[FILL:sec-1]]",
        )
        events = []
        counter = {}
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=_fake_llm(backbone_text=duplicate, counter=counter),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(counter.get("backbone"), 1)
        self.assertNotIn("[[FILL:", result["markdown"])
        self.assertIn("backbone_placeholder_deduplicated:[[FILL:sec-1]]:2->1", result["quality_notes"])


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
        # 首次蓝图 difficulty 自造词（无别名可机械修复），重试带反馈后修正 → 流水线继续。
        bad_difficulty = self._blueprint_variant(sections={"difficulty": "进阶"})
        blueprint_users = []

        async def flaky_blueprint_llm(system, user):
            if "总编" in system:
                blueprint_users.append(user)
                return bad_difficulty if len(blueprint_users) == 1 else BLUEPRINT_JSON
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

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
        self.assertIn("unknown difficulty", blueprint_users[1])
        self.assertIn("进阶", blueprint_users[1])

    def test_retry_exhausted_returns_both_error_details(self):
        # 两次蓝图各自不同的语义校验错误 → failed 结果必须带齐两条详情。
        bad_difficulty = self._blueprint_variant(sections={"difficulty": "进阶"})
        bad_figure_ref = self._blueprint_variant(figures={"sec_id": "sec-ghost"})
        responses = iter([bad_difficulty, bad_figure_ref])

        async def always_bad_blueprint_llm(system, user):
            if "总编" in system:
                return next(responses)
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

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
        self.assertIn("unknown difficulty", detail)
        self.assertIn("unknown section", detail)

    def test_mechanical_shape_slips_are_repaired_without_llm_retry(self):
        """figure kind 自造词有文档化缺省（mermaid），机械修复省一次全量蓝图重试。"""

        bad_kind = self._blueprint_variant(figures={"kind": "diagram"})
        blueprint_users = []

        async def bad_kind_blueprint_llm(system, user):
            if "总编" in system:
                blueprint_users.append(user)
                return bad_kind
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return BACKBONE_MD
            return _grounded_fill_body(user)

        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    _ctx(tmp),
                    llm_func=bad_kind_blueprint_llm,
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(blueprint_users), 1)
        self.assertTrue(
            any(
                note.startswith("blueprint_mechanical_repair:") and "figure_kind:diagram->mermaid" in note
                for note in result["quality_notes"]
            ),
            msg=result["quality_notes"],
        )


class AuthorInlineCitationTests(unittest.TestCase):
    """C2/G0 真实运行修复：[^n] 内联引用体系、骨架净化与收尾 footer 的端到端验证。"""

    # fake 正文带合法内联引用 [^1]（对应 fake 检索唯一来源 https://example.com/limits）。
    CITED_FILL_BODY = FILL_BODY + "这一直观解释有检索来源支持[^1]。"

    # 真实缺陷形态：骨架 LLM 在占位符上方自加「正文占位」空标题。
    BACKBONE_WITH_BOGUS_HEADINGS = BACKBONE_MD.replace(
        "# 极限入门",
        "# 极限入门\n\n> 骨架说明：[[FILL:...]] 是正文位置，[[FIG:n]] 是配图位置。",
    ).replace(
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
            self.assertNotIn("[[FILL:...]]", markdown)
            self.assertNotIn("[[FIG:n]]", markdown)
            self.assertIn("正文填充标记", markdown)
            self.assertIn("配图标记", markdown)

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
            return _grounded_fill_body(user)

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

    def test_authority_query_adds_subject_specific_cross_language_source_hints(self):
        math_query = _authority_search_query("导数符号与单调区间", "高中数学")
        biology_query = _authority_search_query("光合作用限制因素", "高中生物")
        fallback_query = _authority_search_query("未知主题", "跨学科")

        self.assertIn("OpenStax Khan Academy Mathcentre MathsIsFun", math_query)
        self.assertIn("OpenStax NCBI Khan Academy LibreTexts", biology_query)
        self.assertIn("官方 权威 来源 official documentation", fallback_query)
        self.assertTrue(math_query.startswith("导数符号与单调区间 高中数学"))

    def test_lean_task_authority_queries_are_topic_specific_and_real_domains(self):
        derivative = _task_authority_queries("导数、极值与牛顿迭代", "高中数学")
        diagnosis = _task_authority_queries("条件概率与医学筛查诊断", "高中数学")
        history = _task_authority_queries("法国大革命成因", "高中历史")

        self.assertEqual(len(derivative), 2)
        self.assertIn("site:openstax.org", derivative[0])
        self.assertIn("site:khanacademy.org", derivative[1])
        self.assertIn("site:cdc.gov", diagnosis[1])
        self.assertIn("site:britannica.com", history[0])

    def test_deep_preset_adds_wikipedia_query_and_two_deep_reads_per_kp(self):
        events, log = [], []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, events, log, preset="deep")
            research = (Path(tmp) / "notes" / "research.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "ok")
        # 每个知识点追加 1 条 wikipedia 查询（查询词为知识点本身）
        self.assertEqual([q for kind, q in log if kind == "wiki"], ["极限", "导数"])
        # deep preset：每 kp 在“权威事实/常见误区”两类查询间轮转深读（两 kp 共 4 次 browse）
        fetched = [url for kind, url in log if kind == "fetch"]
        self.assertEqual(len(fetched), 4)
        self.assertTrue(any(url.startswith("https://example.com/p1/极限_数学_权威教材_OpenStax") for url in fetched))
        self.assertTrue(any(url.startswith("https://example.com/p1/极限_常见错误_误区") for url in fetched))
        # 深读摘要（前 500 字）作为 deep_read 行落入研究笔记
        line = next(ln for ln in research.splitlines() if "deep_read" in ln and "p1/极限_数学" in ln)
        self.assertIn("src: https://example.com/p1/极限_数学_权威教材_OpenStax", line)
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

    def test_lean_budget_keeps_per_kp_search_but_caps_wikipedia_and_deep_reads(self):
        events, log = [], []
        knowledge_points = [f"知识点{i}" for i in range(1, 9)]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-lean",
                topic="高中综合主题",
                subject="高中数学",
                work_dir=Path(tmp),
                preset="deep",
                requirements="正文须以至少8个独立知识点二级标题展开。",
                options={"research_budget": "lean"},
                knowledge_points=knowledge_points,
            )
            pipeline = _AuthorPipeline(
                ctx,
                llm_func=_fake_llm(),
                toolbox=self._toolbox(log),
                emit=events.append,
                forge=None,
            )
            asyncio.run(pipeline._research())  # noqa: SLF001 - 聚焦研究调用预算

        # 每个知识点仍保留“权威事实 + 常见误区”两类搜索，并增加 2 次主题级权威教材检索。
        self.assertEqual(len([1 for kind, _ in log if kind == "serp"]), 18)
        # 两次主题权威检索替换两次易失败百科调用；合计仍恰好为轻量门槛所需的 20 次搜索。
        # 深读仍达到 10 次，可覆盖由 8 个最低小节反推的 10 个期望知识点。
        self.assertEqual(
            [query for kind, query in log if kind == "wiki"],
            ["知识点1", "知识点8"],
        )
        self.assertTrue(any("site:openstax.org" in query for kind, query in log if kind == "serp"))
        self.assertTrue(any("site:khanacademy.org" in query for kind, query in log if kind == "serp"))
        self.assertIn("site:openstax.org", pipeline.source_registry[0]["url"])
        self.assertIn("site:khanacademy.org", pipeline.source_registry[1]["url"])
        self.assertEqual(len([1 for kind, _ in log if kind == "fetch"]), 10)
        budget_events = [event["data"] for event in events if event["type"] == "research_budget"]
        self.assertEqual(
            budget_events,
            [{
                "mode": "lean",
                "knowledge_points": 8,
                "search_calls_planned": 20,
                "deep_reads_planned": 10,
                "max_fill_sections": 8,
                "max_figures": 3,
            }],
        )

    def test_browse_failure_records_quality_note_without_blocking(self):
        events, log = [], []
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp,
                events,
                log,
                preset="deep",
                fetch_fail_substr="p1/极限_数学_权威教材_OpenStax",
            )
            research = (Path(tmp) / "notes" / "research.md").read_text(encoding="utf-8")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(any(n.startswith("deep_read_failed:") for n in result["quality_notes"]))
        browse_calls = self._tool_calls(events, "browse")
        self.assertTrue(any(d.get("status") == "error" for d in browse_calls))
        self.assertTrue(any(d.get("status") == "ok" for d in browse_calls))
        # 权威查询 top-1 失败不阻断：误区查询的深读摘要仍落笔记
        self.assertTrue(any("deep_read" in ln and "p1/极限_常见错误" in ln for ln in research.splitlines()))


class AuthorLeanGenerationBudgetTests(unittest.TestCase):
    @staticmethod
    def _pipeline(tmp, *, llm, knowledge_points=None):
        ctx = AuthorPipelineContext(
            task_id="t-author-lean-generation",
            topic="微积分基础",
            subject="高中数学",
            work_dir=Path(tmp),
            preset="deep",
            options={"research_budget": "lean"},
            knowledge_points=knowledge_points or ["极限", "导数"],
        )
        return _AuthorPipeline(ctx, llm_func=llm, toolbox=_fake_toolbox(), emit=lambda _event: None, forge=None)

    def test_lean_blueprint_retries_instead_of_adding_fill_only_preface_sections(self):
        oversized = json.loads(TWO_KP_BLUEPRINT_JSON)
        oversized["sections"].append({
            "id": "sec-preface",
            "title": "学习导航",
            "purpose": "介绍学习路径",
            "key_points": ["如何使用本资料"],
            "target_chars": 400,
            "difficulty": "基础",
            "misconceptions": [],
            "frontier": False,
        })
        replies = [json.dumps(oversized, ensure_ascii=False), TWO_KP_BLUEPRINT_JSON]
        users = []

        async def fake_llm(_system, user):
            users.append(user)
            return replies[len(users) - 1]

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp, llm=fake_llm)
            blueprint = asyncio.run(pipeline._blueprint())  # noqa: SLF001 - 聚焦蓝图调用预算

        self.assertIsNotNone(blueprint)
        self.assertEqual(len(users), 2)
        self.assertEqual(len(blueprint.sections), 2)
        self.assertTrue(any("blueprint_section_budget" in note for note in pipeline.quality_notes))

    def test_lean_blueprint_keeps_at_most_three_evenly_distributed_figures(self):
        payload = json.loads(TWO_KP_BLUEPRINT_JSON)
        payload["figures"] = [
            {"n": n, "sec_id": "sec-1" if n < 4 else "sec-2", "intent": f"图{n}", "kind": "mermaid", "caption": f"图{n}"}
            for n in range(1, 6)
        ]

        async def fake_llm(_system, _user):
            return json.dumps(payload, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp, llm=fake_llm)
            blueprint = asyncio.run(pipeline._blueprint())  # noqa: SLF001

        self.assertEqual([figure.n for figure in blueprint.figures], [1, 3, 5])
        self.assertIn("blueprint_figures_trimmed:5/3", pipeline.quality_notes)

    def test_lean_fill_uses_one_worker_attempt_then_targeted_author_fallback(self):
        users = []

        async def fake_llm(_system, user):
            users.append(user)
            return FILL_BODY if "上次填充未通过原因" in user else "太短"

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = self._pipeline(tmp, llm=fake_llm)
            pipeline.blueprint = Blueprint.from_dict(json.loads(TWO_KP_BLUEPRINT_JSON))
            pipeline.blueprint_dict = asdict(pipeline.blueprint)
            pipeline.backbone = TWO_KP_BACKBONE_MD
            pipeline._decompose_todos()  # noqa: SLF001
            asyncio.run(pipeline._fill_and_figures())  # noqa: SLF001

        self.assertEqual(len(users), 4, "两个小节各 1 次 worker + 1 次定向作者兜底")
        self.assertEqual(set(pipeline.sections), {"sec-1", "sec-2"})
        self.assertTrue(all("长度不足" in user for user in users if "上次填充未通过原因" in user))

    def test_missing_section_repairs_run_with_bounded_parallelism(self):
        async def unused_llm(_system, _user):
            return ""

        with tempfile.TemporaryDirectory() as tmp:
            pipeline = self._pipeline(
                tmp,
                llm=unused_llm,
                knowledge_points=["极限", "导数", "积分"],
            )
            pipeline.blueprint = Blueprint.from_dict(json.loads(SPLIT3_BLUEPRINT_JSON))
            pipeline.blueprint_dict = asdict(pipeline.blueprint)
            pipeline.backbone = SPLIT3_BACKBONE_MD
            active = 0
            max_active = 0
            all_started = asyncio.Event()

            async def fake_author_fill(_section, *, note="", stage="author_fill"):
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                if active == 3:
                    all_started.set()
                await all_started.wait()
                active -= 1
                return FILL_BODY

            pipeline._author_fill = fake_author_fill  # type: ignore[method-assign]  # noqa: SLF001
            document = asyncio.run(asyncio.wait_for(pipeline._assemble_with_revise(), timeout=1.0))  # noqa: SLF001

        self.assertIsNotNone(document)
        self.assertEqual(max_active, 3)

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

    def test_registry_cap_is_allocated_across_all_knowledge_points(self):
        async def fake_serp(query, n):
            slug = query.replace(" ", "_")
            return [
                {
                    "title": f"{slug}-{index}",
                    "url": f"https://example.com/{slug}/{index}",
                    "content": f"{query} 的事实 {index}",
                    "score": 0.9,
                }
                for index in range(5)
            ]

        async def fake_fetch(url):
            return "页面正文"

        kps = [f"知识点{index}" for index in range(1, 7)]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-src-fair",
                topic="综合专题",
                subject="数学",
                work_dir=Path(tmp),
                preset="standard",
                knowledge_points=kps,
            )
            pipeline = _AuthorPipeline(
                ctx,
                llm_func=_fake_llm(),
                toolbox=ResearchToolbox(serp_func=fake_serp, fetch_func=fake_fetch),
                emit=lambda event: None,
            )
            asyncio.run(pipeline._research())  # noqa: SLF001

        urls = [entry["url"] for entry in pipeline.source_registry]
        for kp in kps:
            self.assertTrue(any(kp in url for url in urls), (kp, urls))

    def test_registry_cap_preserves_authority_and_misconception_query_per_kp(self):
        async def fake_serp(query, n):
            kp = query.split()[0]
            intent = "misconception" if "常见错误" in query else "authority"
            host = "archive.gov" if intent == "authority" else "teaching.example.com"
            rows = [
                {
                    "title": f"{intent}-{index}",
                    "url": f"https://{host}/{kp}/{intent}/{index}",
                    "content": f"{kp} {intent} 事实 {index}",
                    "score": 0.9 - index * 0.01,
                }
                for index in range(5)
            ]
            if intent == "authority":
                # 高相关博客排在前面；生成链路仍应把低分机构来源排到本查询首位。
                rows.insert(0, {
                    "title": "高相关个人博客",
                    "url": f"https://blog.example.com/{kp}/top",
                    "content": f"{kp} 博客摘要",
                    "score": 0.99,
                })
                rows[-1] = {
                    "title": "国家档案馆",
                    "url": f"https://archive.gov/{kp}/primary",
                    "content": f"{kp} 一手档案",
                    "score": 0.4,
                }
            return rows[:n]

        async def fake_fetch(url):
            return "页面正文"

        kps = [f"知识点{index}" for index in range(1, 10)]
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-src-intents",
                topic="综合专题",
                subject="高中历史",
                work_dir=Path(tmp),
                preset="standard",
                knowledge_points=kps,
            )
            pipeline = _AuthorPipeline(
                ctx,
                llm_func=_fake_llm(),
                toolbox=ResearchToolbox(serp_func=fake_serp, fetch_func=fake_fetch),
                emit=lambda event: None,
            )
            asyncio.run(pipeline._research())  # noqa: SLF001

        urls = [entry["url"] for entry in pipeline.source_registry]
        for kp in kps:
            kp_urls = [url for url in urls if f"/{kp}/" in url]
            self.assertTrue(any("archive.gov" in url for url in kp_urls), (kp, kp_urls))
            self.assertTrue(any("/misconception/" in url for url in kp_urls), (kp, kp_urls))


class AuthorTaskContractPropagationTests(unittest.TestCase):
    def test_fill_contract_includes_core_question_and_output_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = _AuthorPipeline(
                AuthorPipelineContext(
                    task_id="t-author-task-contract",
                    topic="解释改革受阻为何迫使王室召集三级会议，并区分原因与导火索",
                    subject="高中历史",
                    work_dir=Path(tmp),
                    requirements="必须给出时间顺序和中间机制",
                    knowledge_points=["改革受阻与政治合法性"],
                ),
                llm_func=_fake_llm(),
                toolbox=_fake_toolbox(),
                emit=lambda event: None,
            )

            contract = pipeline._global_fill_requirements()  # noqa: SLF001

        self.assertIn("改革受阻为何迫使王室召集三级会议", contract)
        self.assertIn("区分原因与导火索", contract)
        self.assertIn("时间顺序和中间机制", contract)

    def test_required_markers_are_short_bracket_tags_only(self):
        """硬性标记只允许括号型短标签。

        曾经按学科硬编码的长句结论（如“a>0 时 -√a 为极大点…”）要求逐字复现，
        模型一用 LaTeX 改写即验收失败，重试烧尽后整本书 assemble_failed
        （light-probe 实测：单个标记杀死整次交付）。层级标签按蓝图顺序轮转分配。
        """

        blueprint = Blueprint.from_dict({
            "narrative": "导数主线",
            "terminology": [],
            "sections": [
                {
                    "id": "sec-extrema",
                    "title": "极值、最值与驻点辨析",
                    "purpose": "比较局部与整体",
                    "key_points": ["闭区间端点比较"],
                    "target_chars": 800,
                    "difficulty": "应用",
                    "misconceptions": [],
                    "frontier": False,
                },
                {
                    "id": "sec-parameter",
                    "title": "三次函数f_a的单调性与极值分类",
                    "purpose": "完成含参分类",
                    "key_points": ["a<0、a=0、a>0"],
                    "target_chars": 800,
                    "difficulty": "应用",
                    "misconceptions": [],
                    "frontier": False,
                },
                {
                    "id": "sec-newton",
                    "title": "牛顿迭代与切线近似",
                    "purpose": "比较求根方法",
                    "key_points": ["近似解"],
                    "target_chars": 800,
                    "difficulty": "迁移",
                    "misconceptions": [],
                    "frontier": True,
                },
            ],
            "figures": [],
        })
        requirements = (
            "允许拓展仅限牛顿迭代与切线近似。"
            "每项须用[拓展:上列对应主题全名]逐项标记，并紧跟[高中连接]说明帮助。"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-derivative-markers",
                topic="导数含参分类与牛顿迭代",
                subject="高中数学",
                work_dir=Path(tmp),
                requirements=requirements,
                options={"with_questions": True},
                knowledge_points=[section.title for section in blueprint.sections],
            )
            pipeline = _AuthorPipeline(
                ctx,
                llm_func=_fake_llm(),
                toolbox=_fake_toolbox(),
                emit=lambda event: None,
            )
            pipeline.blueprint = blueprint

            markers = {
                section.id: pipeline._required_markers_for_section(section)  # noqa: SLF001
                for section in blueprint.sections
            }

        # 全部标记都是括号型短标签，长句结论不再出现。
        for section_markers in markers.values():
            for marker in section_markers:
                self.assertRegex(marker, r"^\[[^\[\]]{1,12}\]$")
        # 层级标签按蓝图顺序轮转；受控拓展节额外要求 [高中连接]。
        self.assertEqual(markers["sec-extrema"], ["[基础]"])
        self.assertEqual(markers["sec-parameter"], ["[应用]"])
        self.assertEqual(markers["sec-newton"], ["[高中连接]", "[迁移]"])


class AuthorResearchSliceTests(unittest.TestCase):
    def test_fill_receives_its_own_kp_evidence_instead_of_note_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AuthorPipelineContext(
                task_id="t-author-slice",
                topic="微积分",
                subject="数学",
                work_dir=Path(tmp),
                knowledge_points=["极限", "导数"],
            )
            pipeline = _AuthorPipeline(
                ctx, llm_func=_fake_llm(), toolbox=_fake_toolbox(), emit=lambda event: None
            )
            pipeline.blueprint = Blueprint.from_dict(json.loads(TWO_KP_BLUEPRINT_JSON))
            pipeline._register_source("https://example.com/limit", "极限来源")  # noqa: SLF001
            pipeline._register_source("https://example.com/derivative", "导数来源")  # noqa: SLF001
            pipeline.notes.write(
                "research",
                """## 来源登记表

- [^1] 极限来源 https://example.com/limit
- [^2] 导数来源 https://example.com/derivative

## 极限
- 极限事实 | src: https://example.com/limit | conf: 0.90

## 导数
- 导数专属事实 | src: https://example.com/derivative | conf: 0.95
""",
            )

            research = pipeline._research_slice_for_section(pipeline.blueprint.sections[1])  # noqa: SLF001

        self.assertIn("导数专属事实", research)
        self.assertIn("https://example.com/derivative", research)
        self.assertNotIn("极限事实", research)
        self.assertNotIn("https://example.com/limit", research)

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
            invalid_relative = pipeline._register_source("/goto?url=opaque", "搜索跳转")  # noqa: SLF001
            invalid_scheme = pipeline._register_source("javascript:alert(1)", "脚本")  # noqa: SLF001

            self.assertEqual(first, again)
            self.assertEqual(invalid_relative, -1)
            self.assertEqual(invalid_scheme, -1)
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
            return _grounded_fill_body(user)

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
            return _grounded_fill_body(user)

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

    def test_split_reserves_required_extension_topics_and_receives_full_contract(self):
        seen = []

        async def split_llm(system, user):
            seen.append(user)
            return json.dumps({"knowledge_points": ["导数定义", "导数应用"]}, ensure_ascii=False)

        requirements = (
            "正文须以至少4个独立知识点二级标题展开；主题主线与作答前提限高中；"
            "允许拓展仅限牛顿迭代与切线近似、拉格朗日中值定理。"
            "每项须用[拓展:上列对应主题全名]逐项标记，并紧跟[高中连接]说明帮助。"
        )
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx_no_kps(
                tmp,
                options={"max_points": 4},
                requirements=requirements,
            )
            pipeline = _AuthorPipeline(
                ctx, llm_func=split_llm, toolbox=_fake_toolbox(), emit=lambda event: None
            )
            asyncio.run(pipeline._decompose_kps())  # noqa: SLF001

        self.assertEqual(
            pipeline.knowledge_points,
            ["导数定义", "导数应用", "牛顿迭代与切线近似", "拉格朗日中值定理"],
        )
        self.assertIn("正文须以至少4个独立知识点", seen[0])
        self.assertIn("min_points: 4", seen[0])
        self.assertIn("牛顿迭代与切线近似", seen[0])
        self.assertIn("参数分支/步骤/算例必须合并", seen[0])
        self.assertIn("边界反例、概念辨析和应用", seen[0])

    def test_controlled_extensions_survive_full_pipeline_and_acceptance(self):
        requirements = (
            "正文须以至少4个独立知识点二级标题展开；主题主线与作答前提限高中；"
            "允许拓展仅限牛顿迭代与切线近似、拉格朗日中值定理。"
            "每项须用[拓展:上列对应主题全名]逐项标记，并紧跟[高中连接]说明帮助。"
        )
        blueprint = json.dumps(
            {
                "narrative": "高中导数主线后连接两个拓展。",
                "terminology": [],
                "sections": [
                    {
                        "id": section_id,
                        "title": title,
                        "purpose": "形成可迁移理解",
                        "key_points": [title],
                        "target_chars": 800,
                        "difficulty": "应用",
                        "misconceptions": [],
                        "frontier": False,
                    }
                    for section_id, title in (
                        ("sec-definition", "导数定义"),
                        ("sec-application", "导数应用"),
                        ("sec-newton", "牛顿迭代与切线近似"),
                        ("sec-mvt", "拉格朗日中值定理"),
                    )
                ],
                "figures": [],
            },
            ensure_ascii=False,
        )
        backbone = """# 高中导数

[[FILL:sec-definition]]

[[FILL:sec-application]]

[[FILL:sec-newton]]

[[FILL:sec-mvt]]
"""

        async def extension_llm(system, user):
            if "knowledge_points" in system:
                return json.dumps({"knowledge_points": ["导数定义", "导数应用"]}, ensure_ascii=False)
            if "总编" in system:
                return blueprint
            if "核查" in system:
                return AUDIT_JSON
            if "骨架" in system:
                return backbone
            body = _grounded_fill_body(user)
            if "本节硬性标记" in user:
                body += "\n\n[高中连接] 从高中切线与变化率出发，帮助检查导数题的条件和近似误差。"
            if "解析求根与牛顿迭代近似的区别" in user:
                body += "\n\n解析求根与牛顿迭代近似的区别：前者给精确表达，后者逐步逼近数值解。"
            return body

        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx_no_kps(
                tmp,
                options={"max_points": 4},
                requirements=requirements,
            )
            result = asyncio.run(
                run_author_pipeline(
                    ctx,
                    llm_func=extension_llm,
                    toolbox=_fake_toolbox(),
                    emit=lambda event: None,
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["degraded"], result["quality_report"])
        markdown = result["markdown"]
        for topic in ("牛顿迭代与切线近似", "拉格朗日中值定理"):
            self.assertIn(f"[拓展:{topic}]", markdown)
        self.assertEqual(markdown.count("[高中连接]"), 2)
        self.assertTrue(result["quality_report"]["passed"])


class AuthorStageSplitTests(unittest.TestCase):
    """阶段评测拆分：benchmark_stage=research 只跑检索并落盘快照；
    research_fixture_dir 注入研究夹具后撰写阶段不得触发任何真实检索。"""

    @staticmethod
    def _ctx_with_options(work_dir, **options):
        ctx = _ctx(work_dir)
        ctx.options = {**ctx.options, **options}
        return ctx

    def test_research_stage_stops_before_writing_and_snapshots(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_with_options(tmp, benchmark_stage="research"),
                    llm_func=_fake_llm(),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=None,
                )
            )
            snapshot = Path(tmp) / "research_snapshot"
            for name in ("knowledge_points.json", "research.md", "source_registry.json", "research_evidence.json"):
                self.assertTrue((snapshot / name).is_file(), name)
            registry = json.loads((snapshot / "source_registry.json").read_text(encoding="utf-8"))
            self.assertTrue(registry)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["stage"], "research")
        self.assertNotIn("markdown", result)
        report = result["research_report"]
        self.assertGreaterEqual(int(report["unique_sources"]), 1)
        self.assertIn("https://example.com/limits", report["source_urls"])
        # 研究 todo 完成；不进入撰写：无蓝图/骨架 LLM 调用、无填充事件
        todos = TodoList.from_json(result["todos"])
        self.assertEqual(todos.get("research").status, "done")
        llm_stages = {
            event["data"].get("stage")
            for event in events
            if event.get("type") == "tool_call" and event["data"].get("tool") == "llm"
        }
        self.assertNotIn("blueprint", llm_stages)
        self.assertNotIn("backbone", llm_stages)
        self.assertFalse(any(event.get("type") == "section_fill" for event in events))

    def test_write_stage_uses_fixture_and_never_searches(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp) / "fixture"
            fixture_dir.mkdir()
            (fixture_dir / "knowledge_points.json").write_text(
                json.dumps(["极限的直观概念", "极限的严格定义"], ensure_ascii=False), encoding="utf-8",
            )
            (fixture_dir / "research.md").write_text(
                "## 来源登记表\n\n- [^1] 极限讲义 https://example.com/limits\n\n"
                "## 极限的直观概念\n- 极限是无限逼近的严格化 | src: [^1] | conf: 0.90\n\n"
                "## 极限的严格定义\n- epsilon-delta 定义刻画逼近 | src: [^1] | conf: 0.90\n",
                encoding="utf-8",
            )
            (fixture_dir / "source_registry.json").write_text(
                json.dumps([{"n": 1, "title": "极限讲义", "url": "https://example.com/limits"}]),
                encoding="utf-8",
            )

            def forbidden_search(*args, **kwargs):
                raise AssertionError("write 阶段不得触发真实检索")

            events = []
            work_dir = Path(tmp) / "work"
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_with_options(str(work_dir), research_fixture_dir=str(fixture_dir)),
                    llm_func=_fake_llm(),
                    toolbox=ResearchToolbox(serp_func=forbidden_search, fetch_func=forbidden_search),
                    emit=events.append,
                    forge=_fake_forge(events),
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertIn("[^1]", result["markdown"])
        self.assertIn("https://example.com/limits", result["markdown"])
        self.assertTrue(
            any(note.startswith("research_fixture_used") for note in result["quality_notes"]),
            result["quality_notes"],
        )
        llm_stages = {
            event["data"].get("stage")
            for event in events
            if event.get("type") == "tool_call" and event["data"].get("tool") == "llm"
        }
        self.assertNotIn("split", llm_stages)
        self.assertFalse(
            any(
                event.get("type") == "tool_call" and event["data"].get("tool") in {"search", "browse"}
                for event in events
            )
        )

    def test_invalid_fixture_fails_fast(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(
                run_author_pipeline(
                    self._ctx_with_options(tmp, research_fixture_dir=str(Path(tmp) / "missing")),
                    llm_func=_fake_llm(),
                    toolbox=_fake_toolbox(),
                    emit=events.append,
                    forge=None,
                )
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "research_fixture_invalid")
        self.assertEqual(result["error"]["stage"], "research")


if __name__ == "__main__":
    unittest.main()
