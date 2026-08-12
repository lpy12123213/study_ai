"""自学资料 benchmark 的离线单元测试：全部 fixture 内联，不触网、不调 LLM。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.evals.study_materials.case_schema import (
    BENCHMARK_OUTPUT_CONTRACT,
    CaseValidationError,
    benchmark_output_contract,
    default_cases_dir,
    load_case_file,
    load_cases,
    parse_case,
)
from backend.evals.study_materials.graders.aesthetics import grade_aesthetics
from backend.evals.study_materials.graders.citations import grade_citations
from backend.evals.study_materials.graders.common import DIMENSION_MAX, PROCESS_DIMENSION_MAX, validate_weights
from backend.evals.study_materials.graders.events import EventStats, grade_research, grade_subagents
from backend.evals.study_materials.graders.knowledge import grade_knowledge
from backend.evals.study_materials.graders.learning import grade_learning
from backend.evals.study_materials.graders.rubric import grade_rubric
from backend.evals.study_materials.graders.structure import grade_structure
from backend.evals.study_materials.runner import (
    _effective_parallel,
    _extract_markdown,
    _resolve_cases,
    _select_shard,
    resolve_markdown,
)
from backend.evals.study_materials.scorecard import grade_case
from backend.generation.study_materials.coverage import match_kp_headings

_CASE_DIR = default_cases_dir()


def _mini_case(**overrides) -> dict:
    base = {
        "id": "mini",
        "title": "迷你用例",
        "query": "学习迷你主题",
        "preset": "standard",
        "expected_knowledge_points": ["知识点甲", "知识点乙"],
        "min_unique_sources": 4,
        "expected_domains": ["wikipedia.org", "example.edu"],
        "required_facts": [
            {
                "id": "f1",
                "description": "定义点",
                "match": {"all": ["定义甲"], "any": ["概念|内涵"]},
                "source_urls": ["https://example.edu/definition"],
            },
            {
                "id": "f2",
                "description": "性质点",
                "match": {"all": ["性质乙"], "any": ["定理|结论"]},
                "source_urls": ["https://wikipedia.org/property"],
            },
        ],
        "traps": [
            {"id": "t1", "description": "误解", "wrong_pattern": "错误说法", "correct_pattern": "正确澄清"},
        ],
        "contrasts": [["概念甲", "概念乙"]],
        "format_requirements": {"key_formulas": ["\\\\alpha"], "min_figures": 1, "min_tables": 1, "min_chars": 200},
    }
    base.update(overrides)
    return base


def _frame(ftype: str, data: dict) -> dict:
    return {"taskId": "t-1", "seq": 1, "type": ftype, "data": data}


def _tool_call(name: str, args: dict | None = None) -> dict:
    return _frame("tool_call", {"step_id": "s1", "name": name, "title": name, "arguments": args or {}})


def _tool_result(name: str, output) -> dict:
    return _frame("tool_result", {"step_id": "s1", "name": name, "success": True, "output": output, "error": ""})


def _search_result(urls: list[str]) -> dict:
    return {"sources": [{"url": u, "title": "t", "snippet": "s"} for u in urls]}


class CaseSchemaTests(unittest.TestCase):
    def test_all_shipped_cases_load_and_validate(self) -> None:
        cases = load_cases(_CASE_DIR)
        self.assertEqual(len(cases), 40)
        tier_counts = {tier: sum(case.tier == tier for case in cases) for tier in ("smoke", "core", "extended")}
        self.assertEqual(tier_counts, {"smoke": 8, "core": 4, "extended": 28})
        for case in cases:
            self.assertGreaterEqual(len(case.required_facts), 5, case.id)
            self.assertGreaterEqual(len(case.traps), 2, case.id)
            self.assertGreaterEqual(len(case.contrasts), 2, case.id)
            self.assertGreaterEqual(len(case.expected_knowledge_points), 5, case.id)
            self.assertGreaterEqual(len(case.expected_domains), 3, case.id)
            self.assertGreaterEqual(case.min_unique_sources, 8, case.id)
            self.assertGreaterEqual(case.format_requirements.min_chars, 6000, case.id)
            self.assertEqual(case.options.get("prefer_local_archive"), False, case.id)
            self.assertEqual(case.options.get("with_questions"), True, case.id)
            payload = case.request_payload()
            self.assertEqual(payload["query"], case.query)
            self.assertEqual(payload["preset"], case.preset)
            self.assertTrue(payload["with_questions"])
            self.assertFalse(payload["prefer_local_archive"])
            self.assertTrue(
                payload["requirements"].startswith(
                    benchmark_output_contract(
                        case.learning_requirements,
                        curriculum_scope=case.curriculum_scope,
                        extension_topics=case.extension_topics,
                        min_knowledge_sections=case.min_knowledge_sections,
                    )
                ),
                case.id,
            )
            self.assertLessEqual(len(payload["requirements"]), 600)

    def test_case_pack_deep_merges_nested_defaults(self) -> None:
        import tempfile

        defaults = _mini_case()
        for key in ("id", "title", "query"):
            defaults.pop(key)
        defaults["tier"] = "extended"
        defaults["options"] = {
            "with_questions": True,
            "with_diagrams": True,
            "max_points": 8,
            "prefer_local_archive": False,
        }
        pack = {
            "pack_version": 1,
            "defaults": defaults,
            "cases": [
                {
                    "id": "packed_a",
                    "title": "包内 A",
                    "query": "学习 A",
                    "options": {"max_points": 5},
                    "format_requirements": {"min_chars": 999},
                },
                {"id": "packed_b", "title": "包内 B", "query": "学习 B"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            cases = load_case_file(path)
        self.assertEqual([case.id for case in cases], ["packed_a", "packed_b"])
        self.assertEqual(cases[0].tier, "extended")
        self.assertEqual(cases[0].options["max_points"], 5)
        self.assertTrue(cases[0].options["with_diagrams"])
        self.assertEqual(cases[0].format_requirements.min_chars, 999)
        self.assertEqual(cases[0].format_requirements.min_tables, 1)

    def test_reject_invalid_tier_and_pack_version(self) -> None:
        import tempfile

        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(tier="impossible"))
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(curriculum_scope="university"))
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(curriculum_scope="high_school_plus"))
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(curriculum_scope="high_school", extension_topics=["越界拓展"]))
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(curriculum_scope="high_school_plus", extension_topics="不是数组"))
        with self.assertRaises(CaseValidationError):
            parse_case(
                _mini_case(
                    curriculum_scope="high_school_plus",
                    extension_topics=["受控拓展"],
                    options={"max_points": 1},
                )
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text(json.dumps({"pack_version": 99, "cases": [_mini_case()]}), encoding="utf-8")
            with self.assertRaises(CaseValidationError):
                load_case_file(path)

    def test_case_ids_unique(self) -> None:
        ids = [c.id for c in load_cases(_CASE_DIR)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_reject_empty_facts(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(required_facts=[]))

    def test_reject_unsourced_fact(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(
                _mini_case(
                    required_facts=[{"id": "f1", "description": "x", "match": {"all": ["x"]}}]
                )
            )

    def test_reject_non_http_fact_source(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(
                _mini_case(
                    required_facts=[
                        {
                            "id": "f1",
                            "description": "x",
                            "match": {"all": ["x"]},
                            "source_urls": ["doi:10.1000/example"],
                        }
                    ]
                )
            )

    def test_reject_missing_adversarial_checks(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(traps=[]))
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(contrasts=[]))

    def test_reject_bad_regex(self) -> None:
        bad = _mini_case(required_facts=[{"id": "f1", "description": "x", "match": {"all": ["(["]}}])
        with self.assertRaises(CaseValidationError):
            parse_case(bad)

    def test_reject_duplicate_fact_ids(self) -> None:
        dup = _mini_case(
            required_facts=[
                {"id": "f1", "description": "a", "match": {"all": ["x"]}},
                {"id": "f1", "description": "b", "match": {"all": ["y"]}},
            ]
        )
        with self.assertRaises(CaseValidationError):
            parse_case(dup)

    def test_reject_bad_preset(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(preset="extreme"))

    def test_reject_more_answers_than_questions(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(learning_requirements={"min_practice_questions": 3, "min_answered_questions": 4}))

    def test_weights_sum_to_100(self) -> None:
        validate_weights()
        self.assertAlmostEqual(sum(DIMENSION_MAX.values()), 100.0)


class EventGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_empty_events_score_zero(self) -> None:
        self.assertEqual(grade_research(self.case, []).score, 0.0)
        self.assertEqual(grade_subagents(self.case, []).score, 0.0)

    def test_react_path_without_subagents_scores_zero_on_s(self) -> None:
        events = [
            _tool_call("web_search_knowledge", {"query": "迷你主题"}),
            _tool_result("web_search_knowledge", _search_result(["https://a.test/1"])),
            _tool_call("generate_study_material", {}),
        ]
        result = grade_subagents(self.case, events)
        self.assertEqual(result.score, 0.0)
        self.assertIn("无任何 subagent 事件", result.checks[0].detail)

    def test_rich_research_run_scores_high(self) -> None:
        urls = [f"https://en.wikipedia.org/wiki/p{i}" for i in range(3)]
        urls += ["https://example.edu/notes/1"]
        events = [
            _tool_call("web_search_knowledge", {"query": "q1"}),
            _tool_result("web_search_knowledge", _search_result(urls)),
            _tool_call("wikipedia_search", {"query": "q2"}),
            _tool_result("wikipedia_search", _search_result(["https://zh.wikipedia.org/wiki/x"])),
            _tool_call("mediawiki_search", {"query": "q3"}),
            _tool_call("browse_web_pages", {"urls": ["https://en.wikipedia.org/wiki/p0"]}),
            _tool_call("browse_web_pages", {"urls": ["https://example.edu/notes/1"]}),
            _tool_call("web_search_knowledge", {"query": "q1 改写"}),
            _tool_call("web_search_knowledge", {"query": "q1 再改写"}),
        ]
        result = grade_research(self.case, events)
        self.assertGreaterEqual(result.score, DIMENSION_MAX["R"] * 0.9)

    def test_subagent_events_drive_s(self) -> None:
        events = [
            _frame("subagent_start", {"subagent_id": "sa-0", "kind": "knowledge_research", "knowledge_point": "知识点甲"}),
            _frame("subagent_end", {"subagent_id": "sa-0", "summary": "甲的摘要"}),
            _frame("subagent_start", {"subagent_id": "sa-1", "kind": "knowledge_research", "knowledge_point": "知识点乙"}),
            _frame("subagent_end", {"subagent_id": "sa-1", "summary": "乙的摘要"}),
        ]
        result = grade_subagents(self.case, events)
        self.assertAlmostEqual(result.score, PROCESS_DIMENSION_MAX["S"])

    def test_event_stats_extracts_urls_and_domains(self) -> None:
        events = [_tool_result("web_search_knowledge", _search_result(["https://en.wikipedia.org/wiki/a?x=1"]))]
        stats = EventStats(events)
        self.assertIn("en.wikipedia.org", stats.result_domains())

    def test_task_info_complements_clipped_sse_outputs(self) -> None:
        """SSE 大输出被裁成 "[N items]" 时，task_info 检索摘要补全来源统计。"""
        events = [_tool_result("web_search_knowledge", {"items": [{"results": "[5 items]"}]})]
        task_info = {
            "search_summary_by_kp": {
                "知识点甲": {
                    "provider": "exa-search+decompose",
                    "results": [
                        {"title": "a", "url": "https://en.wikipedia.org/wiki/a", "snippet": "s"},
                        {"title": "b", "url": "https://example.edu/b", "snippet": "s"},
                    ],
                }
            }
        }
        stats = EventStats(events, task_info=task_info)
        self.assertIn("https://example.edu/b", stats.result_urls())
        result = grade_research(self.case, events, task_info=task_info)
        by_id = {c.id: c for c in result.checks}
        self.assertGreater(by_id["R3_unique_sources"].score, 0.0)
        self.assertGreater(by_id["R5_authority_domains"].score, 0.0)


class AuthorEventGraderTests(unittest.TestCase):
    """author 运行时事件（tool_call 帧 data.tool=search/browse 形状）驱动 R 维度评分。"""

    def setUp(self) -> None:
        self.kps = [f"知识点{i}" for i in range(1, 7)]
        self.case = parse_case(_mini_case(
            expected_knowledge_points=self.kps,
            min_unique_sources=8,
            expected_domains=["wikipedia.org", "example.edu"],
        ))

    def _author_events(self) -> list:
        """合成 author 事件流：6 kp × (2 serp + 1 wiki + 1 browse)，search 完成帧带 urls。"""
        events = []
        for kp in self.kps:
            queries = [
                (f"{kp} 数学", "tavily", [f"https://example.edu/{kp}/a", f"https://example.edu/{kp}/b"]),
                (f"{kp} 常见错误 误区", "tavily", [f"https://notes.test/{kp}"]),
                (kp, "wikipedia", [f"https://zh.wikipedia.org/wiki/{kp}"]),
            ]
            for query, provider, urls in queries:
                events.append(_frame("tool_call", {
                    "tool": "search", "query": query, "provider": provider, "status": "start",
                }))
                events.append(_frame("tool_call", {
                    "tool": "search", "query": query, "provider": provider,
                    "result_count": len(urls), "urls": urls,
                }))
            events.append(_frame("tool_call", {"tool": "browse", "url": f"https://example.edu/{kp}/a", "status": "ok"}))
        return events

    def test_author_event_stream_scores_r_dimension(self) -> None:
        result = grade_research(self.case, self._author_events())
        by_id = {c.id: c for c in result.checks}
        # R1：tavily→web + wikipedia → 2 类
        self.assertIn("2 类", by_id["R1_source_classes"].detail)
        self.assertGreaterEqual(by_id["R1_source_classes"].score, by_id["R1_source_classes"].max_score * 0.6)
        # R2：6 次深读 / 6 个知识点 → 满分
        self.assertAlmostEqual(by_id["R2_deep_reads"].score, by_id["R2_deep_reads"].max_score)
        # R3：24 个唯一 URL ≥ 8 → 满分
        self.assertAlmostEqual(by_id["R3_unique_sources"].score, by_id["R3_unique_sources"].max_score)
        # R4：18 个不同 query ≥ 2×6 → 满分
        self.assertAlmostEqual(by_id["R4_multi_round"].score, by_id["R4_multi_round"].max_score)
        # R5：wikipedia.org 与 example.edu 均命中 → 满分
        self.assertAlmostEqual(by_id["R5_authority_domains"].score, by_id["R5_authority_domains"].max_score)

    def test_author_stats_skip_start_frames_and_collect_urls(self) -> None:
        stats = EventStats(self._author_events())
        self.assertEqual(stats.deep_read_count(), 6)
        self.assertEqual(stats.distinct_search_payloads(), 18)  # start 帧不重复计数
        self.assertEqual(stats.source_classes(), {"web", "wikipedia"})
        self.assertIn("zh.wikipedia.org", stats.result_domains())
        self.assertIn("https://notes.test/知识点1", stats.result_urls())

    def test_legacy_stream_not_misread_as_author_events(self) -> None:
        """legacy data.name 事件不落入 author 识别路径：统计量保持既有行为。"""
        legacy = [
            _tool_call("web_search_knowledge", {"query": "q1"}),
            _tool_call("browse_web_pages", {"urls": ["https://example.edu/a"]}),
        ]
        stats = EventStats(legacy)
        self.assertEqual(stats.source_classes(), {"web"})
        self.assertEqual(stats.deep_read_count(), 1)
        self.assertEqual(stats.distinct_search_payloads(), 1)


_CURRENT_STYLE_MD = """# 自学材料：迷你主题

> 学科：测试学科
> 生成预设：standard

## 使用方式（建议）

- 先按「知识点目录」顺序学习；每个知识点优先阅读「核心讲解」。

## 知识点目录

- 知识点甲
- 知识点乙

## 1、知识点甲

### 核心讲解

这里给出定义甲，并解释其概念与内涵，其余方面从略。""" + ("补充正文。" * 60) + """

## 2、知识点乙

### 核心讲解

概念乙的讲解段落，仅围绕概念乙自身展开，没有展开对比，也没有提到任何常见误解。

---
生成时间：2026-08-01 10:00:00
"""

_CHALLENGE_READY_MD = """# 自学材料：迷你主题

> 学科：测试学科
> 生成预设：standard

## 使用方式（建议）
- 先确认前置知识，再完成例题和闭卷自测。

## 学习目标
- 能准确说明定义甲。
- 能使用性质乙解决问题。
- 能比较概念甲与概念乙。

## 前置知识
学习者需要掌握集合、命题逻辑和基础代数，并能阅读简单数学符号。

## 知识点目录
- [知识点甲](#1知识点甲)
- [知识点乙](#2知识点乙)

## 1、知识点甲

### 核心讲解

#### 定义、辨析与误区
定义甲给出这个概念的内涵。[^1]

概念甲与概念乙相比，前者强调定义，后者强调性质，二者的区别不能混淆。

注意：错误说法并非正确结论；这里给出正确澄清，并说明反例与边界。[^2]

## 2、知识点乙

### 核心讲解

#### 性质与应用
性质乙是一条定理，其条件和结论必须同时核对。[^2]

$$
\\alpha = 1
$$

![关系示意图](diagram.svg)

| 条件 | 结论 |
|---|---|
| 满足定义甲 | 可应用性质乙 |

## 例题

### [EX1] 定义判断
步骤：先核对定义，再代入条件，最后检查边界。

### [EX2] 性质应用
解答：列出已知条件，应用定理并验证结论。

## 自测题
- [Q1][基础] 定义甲是什么？
- [Q2][基础] 性质乙的条件是什么？
- [Q3][应用] 如何应用性质乙？
- [Q4][应用] 何时不能使用该结论？
- [Q5][迁移] 若条件变化，结论如何变化？
- [Q6][迁移] 如何比较概念甲与概念乙？

## 答案与评分点
- [A1] 定义答案；评分点：核心术语。
- [A2] 条件答案；评分点：条件完整。
- [A3] 应用答案；评分点：步骤正确。
- [A4] 边界答案；评分点：给出反例。
- [A5] 迁移答案；评分点：说明变化链。
- [A6] 对比答案；评分点：至少两项区别。

---

## 参考文献
- [^1]: 定义来源 https://example.edu/definition
- [^2]: 性质来源 https://wikipedia.org/property
- [^3]: 补充来源 https://example.edu/example
- [^4]: 对比来源 https://wikipedia.org/contrast

以上来源用于逐条核验。
"""

_LEGACY_EVENTS = [
    _tool_call("web_search_knowledge", {"query": "迷你主题"}),
    _tool_result("web_search_knowledge", _search_result([f"https://en.wikipedia.org/wiki/p{i}" for i in range(3)])),
    _tool_call("web_search_knowledge", {"query": "迷你主题 深入"}),
    _tool_call("generate_study_material", {}),
    _frame("done", {"material": {"markdown": "..."}}),
]


class StructureGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_current_style_markdown_gets_partial_score(self) -> None:
        result = grade_structure(self.case, _CURRENT_STYLE_MD)
        by_id = {c.id: c for c in result.checks}
        # 骨架齐全（逐 kp 小节可匹配），但目录是纯文本 bullet：锚点子项必须 0 分。
        self.assertAlmostEqual(by_id["F1_skeleton"].score, by_id["F1_skeleton"].max_score)
        f2 = by_id["F2_toc_hierarchy"]
        self.assertLess(f2.score, f2.max_score)
        self.assertIn("0/2 可跳转", f2.detail)

    def test_missing_skeleton_and_broken_math_punished(self) -> None:
        result = grade_structure(self.case, "# 只有标题\n\n$$ 未闭合的公式\n正文。\n")
        self.assertLess(result.score, DIMENSION_MAX["F"] * 0.4)

    def test_empty_markdown_scores_zero(self) -> None:
        self.assertEqual(grade_structure(self.case, "").score, 0.0)


class KnowledgeGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_facts_gated_by_traceability(self) -> None:
        ungrounded_md = "定义甲是一种概念。\n\n性质乙是重要定理。\n\n概念甲与概念乙在此对比。正确澄清。"
        grounded_md = (
            "定义甲是一种概念。[^1]\n\n"
            "性质乙是重要定理。[^2]\n\n"
            "概念甲与概念乙在此对比。正确澄清。\n\n"
            "## 参考文献\n"
            "- [^1]: 定义来源 https://example.edu/definition\n"
            "- [^2]: 性质来源 https://wikipedia.org/property\n"
        )
        gated = grade_knowledge(self.case, ungrounded_md, citation_ratio=0.0)
        full = grade_knowledge(self.case, grounded_md, citation_ratio=1.0)
        gated_k1 = {c.id: c for c in gated.checks}["K1_facts"]
        full_k1 = {c.id: c for c in full.checks}["K1_facts"]
        self.assertAlmostEqual(full_k1.score, full_k1.max_score)
        self.assertLess(gated_k1.score, gated_k1.max_score * 0.2)
        self.assertIn("逐事实溯源", gated_k1.detail)

    def test_fact_miss_and_llm_rescue(self) -> None:
        md = "定义甲是一种概念。正确澄清。"
        judged = grade_knowledge(self.case, md, llm_judge=lambda md_, desc, urls: True, citation_ratio=1.0)
        by_id = {c.id: c for c in judged.checks}
        self.assertEqual(by_id["K1_facts"].metrics["matched_count"], 2)
        self.assertEqual(by_id["K1_facts"].metrics["grounded_count"], 0)
        self.assertLess(by_id["K1_facts"].score, by_id["K1_facts"].max_score * 0.2)

    def test_trap_wrong_only_scores_zero(self) -> None:
        md = "定义甲是概念。性质乙是定理。这里有错误说法。"
        result = grade_knowledge(self.case, md, citation_ratio=1.0)
        by_id = {c.id: c for c in result.checks}
        self.assertEqual(by_id["K2_traps"].score, 0.0)

    def test_trap_untouched_also_zero(self) -> None:
        md = "定义甲是概念。性质乙是定理。概念甲 概念乙。"
        result = grade_knowledge(self.case, md, citation_ratio=1.0)
        by_id = {c.id: c for c in result.checks}
        self.assertEqual(by_id["K2_traps"].score, 0.0)

    def test_contrast_requires_window_cooccurrence(self) -> None:
        near = "概念甲与概念乙相比，二者不同……" + "填充" * 10
        far = "概念甲" + "填充" * 500 + "概念乙"
        md_near = f"定义甲 概念。性质乙 定理。正确澄清。{near}"
        md_far = f"定义甲 概念。性质乙 定理。正确澄清。{far}"
        hit = grade_knowledge(self.case, md_near, citation_ratio=1.0)
        miss = grade_knowledge(self.case, md_far, citation_ratio=1.0)
        self.assertGreater(hit.score, miss.score)

    def test_scaffolding_text_does_not_count_as_content(self) -> None:
        """标题/目录里的概念名（query 回显）不算讲解，空壳成稿 K 维度应接近 0。"""
        skeleton = (
            "# 自学材料：概念甲与概念乙 定义甲 性质乙\n\n"
            "> 学科：测试\n\n"
            "## 知识点目录\n"
            "- 概念甲与概念乙：定义甲、性质乙、正确澄清\n\n"
            "## 使用方式（建议）\n"
            "- 先按目录顺序学习。\n"
        )
        result = grade_knowledge(self.case, skeleton, citation_ratio=1.0)
        by_id = {c.id: c for c in result.checks}
        self.assertEqual(by_id["K1_facts"].score, 0.0)
        self.assertEqual(by_id["K2_traps"].score, 0.0)
        self.assertEqual(by_id["K3_contrasts"].score, 0.0)


class LearningGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_current_style_without_learning_loop_scores_zero(self) -> None:
        self.assertEqual(grade_learning(self.case, _CURRENT_STYLE_MD).score, 0.0)

    def test_output_contract_echo_in_metadata_does_not_score(self) -> None:
        md = f"# 迷你主题\n\n> 额外要求：{BENCHMARK_OUTPUT_CONTRACT}\n\n正文尚未生成。"
        self.assertEqual(grade_learning(self.case, md).score, 0.0)

    def test_tagged_learning_contract_scores_full(self) -> None:
        md = """# 迷你主题

## 学习目标
- 能定义概念甲。
- 能证明性质乙。
- 能比较概念甲与概念乙。

## 前置知识
掌握集合、逻辑与基础代数，并能阅读简单公式。

## 例题
### [EX1] 定义判断
步骤：先核对定义，再代入条件，最后检查边界。

### [EX2] 性质应用
解答：列出已知条件，应用定理并验证结论。

## 自测题
- [Q1][基础] 定义甲是什么？
- [Q2][基础] 性质乙的条件是什么？
- [Q3][应用] 如何应用性质乙？
- [Q4][应用] 何时不能使用该结论？
- [Q5][迁移] 若条件变化，结论如何变化？
- [Q6][迁移] 如何比较概念甲与概念乙？

## 答案与评分点
- [A1] 定义答案；评分点：核心术语。
- [A2] 条件答案；评分点：条件完整。
- [A3] 应用答案；评分点：步骤正确。
- [A4] 边界答案；评分点：给出反例。
- [A5] 迁移答案；评分点：说明变化链。
- [A6] 对比答案；评分点：至少两项区别。
"""
        result = grade_learning(self.case, md)
        self.assertAlmostEqual(result.score, DIMENSION_MAX["L"])

    def test_distributed_chapter_exercises_are_aggregated(self) -> None:
        md = """# 迷你主题

## 学习目标
- 能定义概念甲。
- 能应用性质乙。
- 能比较两个概念。

## 前置知识
掌握集合、逻辑与基础代数，并能阅读简单公式。

## 第一章
**[EX1]** 例题一。步骤：先核对定义，再验证边界。

### 自测题（一）
- [Q1][基础] 定义是什么？
- [Q2][应用] 如何应用？
- [Q3][迁移] 条件变化后如何处理？

### 答案与评分点（一）
- [A1] 答案；评分点：术语。
- [A2] 答案；评分点：步骤。
- [A3] 答案；评分点：迁移理由。

## 第二章
**[EX2]** 例题二。解答步骤：列条件、推导、检查。

### 自测题（二）
- [Q4][基础] 条件是什么？
- [Q5][应用] 结论是什么？
- [Q6][迁移] 如何构造反例？

### 答案与评分点（二）
- [A4] 答案；评分点：条件。
- [A5] 答案；评分点：结论。
- [A6] 答案；评分点：反例。
"""
        result = grade_learning(self.case, md)
        self.assertAlmostEqual(result.score, DIMENSION_MAX["L"])


class DeliveryHeadingCoverageTests(unittest.TestCase):
    def test_merged_and_split_headings_match_without_hiding_real_gap(self) -> None:
        md = """# 中心极限定理

## 大数定律与收敛模式
正文。

## 标准化变换
正文。

### Lévy–Lindeberg 中心极限定理的陈述
正文。

## 样本均值标准误
正文。

## Berry–Esseen 误差界
正文。

## 重尾分布与 CLT 反例
正文。

## 中心极限定理
正文。
"""
        expected = [
            "标准化和分布收敛",
            "样本均值标准误",
            "Lindeberg–Lévy 条件",
            "Berry–Esseen 误差界",
            "重尾与相关性反例",
            "中心极限定理与大数定律",
        ]
        matches = match_kp_headings(md, expected)

        self.assertTrue(matches["标准化和分布收敛"])
        self.assertTrue(matches["Lindeberg–Lévy 条件"])
        self.assertTrue(matches["中心极限定理与大数定律"])
        self.assertEqual(matches["重尾与相关性反例"], [])


class CitationGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_current_style_markdown_scores_zero(self) -> None:
        result = grade_citations(self.case, _CURRENT_STYLE_MD)
        self.assertEqual(result.score, 0.0)
        self.assertIn("无参考文献小节", result.checks[0].detail)

    def test_references_with_footnotes_scores(self) -> None:
        md = (
            "正文引用[^1]与第二处[^2]。\n\n"
            "## 参考文献\n"
            "- [^1]: 标题甲 https://example.edu/a\n"
            "- [^2]: 标题乙 https://wikipedia.org/b\n"
            "- [^3]: 标题丙 https://example.edu/c\n"
            "- [^4]: 标题丁 https://wikipedia.org/d\n"
        )
        result = grade_citations(self.case, md, link_checker=lambda url: True)
        by_id = {c.id: c for c in result.checks}
        self.assertAlmostEqual(by_id["C1_references_section"].score, by_id["C1_references_section"].max_score)
        self.assertGreater(by_id["C2_inline_markers"].score, 0.0)
        self.assertGreater(by_id["C3_authority_domains"].score, 0.0)

    def test_links_checked_only_when_enabled(self) -> None:
        md = "## 参考文献\n- https://example.edu/a\n- https://wikipedia.org/b\n"
        offline = grade_citations(self.case, md)
        by_id = {c.id: c for c in offline.checks}
        self.assertGreater(by_id["C3_authority_domains"].score, 0.0)
        self.assertIn("不影响离线分数", by_id["C3_authority_domains"].detail)


class AestheticsGraderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_figures_and_tables_counted(self) -> None:
        md = (
            "# 标题\n\n![示意图](a.svg)\n\n> 图注：示意\n\n"
            "| 列甲 | 列乙 |\n|---|---|\n| 1 | 2 |\n\n"
            "## 节\n\n### 小节\n\n$$\n\\alpha\n$$\n\n- 列表项\n"
        )
        result = grade_aesthetics(self.case, md)
        by_id = {c.id: c for c in result.checks}
        self.assertAlmostEqual(by_id["A1_figures_tables"].score, by_id["A1_figures_tables"].max_score)

    def test_wall_of_text_punished(self) -> None:
        md = "# 标题\n\n" + "长段落。" * 400
        result = grade_aesthetics(self.case, md)
        by_id = {c.id: c for c in result.checks}
        self.assertLess(by_id["A2_typesetting"].score, by_id["A2_typesetting"].max_score)

    def test_empty_markdown_scores_zero(self) -> None:
        result = grade_aesthetics(self.case, "")
        self.assertEqual(result.score, 0.0)

    def test_llm_judge_overrides_proxy(self) -> None:
        result = grade_aesthetics(self.case, "# 标题\n", llm_judge=lambda md, title: 0.5)
        by_id = {c.id: c for c in result.checks}
        self.assertAlmostEqual(by_id["A2_typesetting_llm"].score, by_id["A2_typesetting_llm"].max_score * 0.5)


class ScorecardTests(unittest.TestCase):
    def test_grade_case_assembles_all_dimensions(self) -> None:
        case = parse_case(_mini_case())
        card = grade_case(case, _LEGACY_EVENTS, _CURRENT_STYLE_MD)
        self.assertEqual([d.dimension for d in card.dimensions], ["R", "K", "L", "F", "A", "C"])
        self.assertEqual([d.dimension for d in card.process_diagnostics], ["S"])
        self.assertGreaterEqual(card.total, 0.0)
        self.assertLessEqual(card.total, 100.0)
        payload = card.to_dict()
        self.assertEqual(payload["case_id"], "mini")
        self.assertEqual(payload["scoring_version"], "challenge_v2")
        self.assertIn("raw_total", payload)
        self.assertIn("quality_gates", payload)
        json.dumps(payload, ensure_ascii=False)

    def test_current_style_run_scores_below_20(self) -> None:
        """难度锚：模拟现行默认链路产物（无子代理/无引用/纯文本目录），总分必须 <20。"""
        case = parse_case(_mini_case(min_unique_sources=12))
        card = grade_case(case, _LEGACY_EVENTS, _CURRENT_STYLE_MD)
        self.assertLess(card.total, 20.0)
        by_dim = {d.dimension: d for d in card.dimensions}
        self.assertEqual(by_dim["L"].score, 0.0)
        self.assertEqual(by_dim["C"].score, 0.0)
        self.assertEqual(card.process_diagnostics[0].score, 0.0)
        failed = {gate.id for gate in card.quality_gates if not gate.passed}
        self.assertIn("G2_evidence", failed)
        self.assertIn("G3_learning_loop", failed)
        self.assertLessEqual(card.applied_ceiling, 19.0)

    def test_challenge_ready_fixture_can_clear_all_gates(self) -> None:
        case = parse_case(_mini_case())
        events = [
            _tool_call("web_search_knowledge", {"query": "q1"}),
            _tool_result(
                "web_search_knowledge",
                _search_result([
                    "https://example.edu/a",
                    "https://example.edu/b",
                    "https://wikipedia.org/c",
                    "https://wikipedia.org/d",
                ]),
            ),
            _tool_call("wikipedia_search", {"query": "q2"}),
            _tool_call("mediawiki_search", {"query": "q3"}),
            _tool_call("web_search_knowledge", {"query": "q4"}),
            _tool_call("browse_web_pages", {"urls": ["https://example.edu/a"]}),
            _tool_call("browse_web_pages", {"urls": ["https://wikipedia.org/c"]}),
            _frame("done", {"material": {"markdown": _CHALLENGE_READY_MD}}),
        ]
        card = grade_case(case, events, _CHALLENGE_READY_MD)
        self.assertTrue(all(gate.passed for gate in card.quality_gates), card.to_dict()["quality_gates"])
        self.assertEqual(card.applied_ceiling, 100.0)
        self.assertAlmostEqual(card.total, card.raw_total)
        self.assertGreater(card.total, 85.0)

    def test_generic_complete_fixture_stays_below_20_on_hard_light_cases(self) -> None:
        """难度锚：形式完整但主题无关的教材不能靠结构、练习和引用跨过内容门槛。"""

        events = [_frame("done", {"material": {"markdown": _CHALLENGE_READY_MD}})]
        for case in _resolve_cases("light", _CASE_DIR):
            with self.subTest(case=case.id):
                card = grade_case(case, events, _CHALLENGE_READY_MD)
                correctness = next(gate for gate in card.quality_gates if gate.id == "G1_correctness")
                self.assertFalse(correctness.passed)
                self.assertLess(correctness.metrics["fact_ratio"], 0.5)
                self.assertLess(card.total, 20.0)

    def test_high_school_plus_extension_must_explicitly_connect_back_to_high_school(self) -> None:
        topics = ["概念甲高级视角", "性质乙应用边界"]
        case = parse_case(
            _mini_case(
                curriculum_scope="high_school_plus",
                extension_topics=topics,
            )
        )
        events = [_frame("done", {"material": {"markdown": _CHALLENGE_READY_MD}})]

        missing_bridge = grade_case(case, events, _CHALLENGE_READY_MD)
        missing_g1 = next(gate for gate in missing_bridge.quality_gates if gate.id == "G1_correctness")
        self.assertFalse(missing_g1.passed)
        self.assertEqual(missing_g1.metrics["extension_bridge"]["ratio"], 0.0)

        unpaired_extension = """
## [拓展:概念甲高级视角]
这里展开概念甲，但没有说明对高中学习的作用。

## [拓展:性质乙应用边界]
[高中连接] 由性质乙出发，帮助高中生识别应用题中缺失的条件。
[高中连接] 另一条标记不能替代上一主题自己的高中连接。
"""
        unpaired = grade_case(case, events, _CHALLENGE_READY_MD + unpaired_extension)
        unpaired_g1 = next(gate for gate in unpaired.quality_gates if gate.id == "G1_correctness")
        self.assertFalse(unpaired_g1.passed)
        self.assertEqual(unpaired_g1.metrics["extension_bridge"]["ratio"], 0.5)
        self.assertEqual(
            unpaired_g1.metrics["extension_bridge"]["missing_connections"],
            ["概念甲高级视角"],
        )

        extension = """
## [拓展:概念甲高级视角]
[高中连接] 由定义甲出发，帮助高中生检查定义题的反例与边界。

## [拓展:性质乙应用边界]
[高中连接] 由性质乙出发，帮助高中生识别应用题中缺失的条件。
"""
        bridged = grade_case(case, events, _CHALLENGE_READY_MD + extension)
        bridged_g1 = next(gate for gate in bridged.quality_gates if gate.id == "G1_correctness")
        self.assertTrue(bridged_g1.passed, bridged_g1.to_dict())
        self.assertEqual(bridged_g1.metrics["extension_bridge"]["ratio"], 1.0)

    def test_write_outputs(self) -> None:
        import tempfile

        from backend.evals.study_materials.scorecard import write_outputs

        case = parse_case(_mini_case())
        card = grade_case(case, [], _CURRENT_STYLE_MD)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_outputs(card, Path(tmp))
            self.assertTrue(paths["score"].is_file())
            self.assertTrue(paths["report"].is_file())
            score = json.loads(paths["score"].read_text(encoding="utf-8"))
            self.assertIn("dimensions", score)
            report = paths["report"].read_text(encoding="utf-8")
            self.assertIn("最终成熟度分", report)
            self.assertIn("原始诊断分", report)


class RunnerHelperTests(unittest.TestCase):
    def test_extract_markdown_shapes(self) -> None:
        self.assertEqual(_extract_markdown({"material": {"markdown": "正文"}}), "正文")
        self.assertEqual(_extract_markdown({"material": "正文"}), "正文")
        self.assertEqual(_extract_markdown({"markdown": "正文"}), "正文")
        self.assertEqual(_extract_markdown({}), "")

    def test_resolve_markdown_falls_back_to_last_text_delta_when_done_truncated(self) -> None:
        # 真实事故回归：done 载荷超 DB 上限被整包替换为 _truncated，正文只在事件流里。
        final = "# 成稿\n" + "正文段落。" * 13000  # ~65k chars
        events = [
            _frame("text_delta", {"content": "# 骨架快照"}),
            _frame("text_delta", {"content": final}),
            _frame("done", {"_truncated": True, "original_chars": 209164, "preview": "{"}),
        ]
        markdown, source = resolve_markdown(events)
        self.assertEqual(markdown, final)
        self.assertEqual(source, "text_delta_fallback")

    def test_resolve_markdown_prefers_done_material_over_text_delta(self) -> None:
        events = [
            _frame("text_delta", {"content": "# 快照"}),
            _frame("done", {"material": {"markdown": "# 正式成稿"}}),
        ]
        markdown, source = resolve_markdown(events)
        self.assertEqual(markdown, "# 正式成稿")
        self.assertEqual(source, "done_event")

    def test_resolve_markdown_text_delta_after_md_url_fetch_failure(self) -> None:
        from unittest.mock import patch

        events = [
            _frame("text_delta", {"content": "# 快照成稿"}),
            _frame("done", {"material": {"md_url": "/files/x.md"}}),
        ]
        with patch("backend.evals.study_materials.runner._fetch_url_markdown", return_value=""):
            markdown, source = resolve_markdown(events, base_url="http://127.0.0.1:8000")
        self.assertEqual(markdown, "# 快照成稿")
        self.assertEqual(source, "text_delta_fallback")

    def test_resolve_markdown_text_delta_skips_blank_snapshots(self) -> None:
        events = [
            _frame("text_delta", {"content": "  "}),
            _frame("text_delta", "not-a-dict"),
            _frame("done", {"_truncated": True}),
        ]
        markdown, source = resolve_markdown(events)
        self.assertEqual((markdown, source), ("", "none"))

    def test_regrade_from_saved_artifacts(self) -> None:
        import tempfile

        from backend.evals.study_materials.runner import regrade_run

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "meta.json").write_text(json.dumps({"case_id": "mini", "error": ""}), encoding="utf-8")
            # regrade 走正式用例目录：把一个 mini 用例临时写进 cases_dir
            cases_dir = Path(tmp) / "cases"
            cases_dir.mkdir()
            (cases_dir / "mini.json").write_text(json.dumps(_mini_case(min_unique_sources=12)), encoding="utf-8")
            (run_dir / "events.jsonl").write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in _LEGACY_EVENTS) + "\n", encoding="utf-8"
            )
            (run_dir / "final.md").write_text(_CURRENT_STYLE_MD, encoding="utf-8")
            (run_dir / "task_info.json").write_text(json.dumps({}), encoding="utf-8")
            result = regrade_run(run_dir, cases_dir=cases_dir, llm_judge=False, check_links=False)
            self.assertEqual(result["case_id"], "mini")
            self.assertLess(result["total"], 20.0)
            self.assertTrue((run_dir / "score.json").is_file())
            self.assertIn("regrade", result["notes"][0])

    def test_tier_suites_have_expected_sizes(self) -> None:
        self.assertEqual(len(_resolve_cases("smoke", _CASE_DIR)), 8)
        self.assertEqual(len(_resolve_cases("core", _CASE_DIR)), 12)
        self.assertEqual(len(_resolve_cases("extended", _CASE_DIR)), 28)
        self.assertEqual(len(_resolve_cases("all", _CASE_DIR)), 40)
        self.assertEqual(
            [case.id for case in _resolve_cases("light-probe", _CASE_DIR)],
            ["derivative_monotonicity_optimization"],
        )
        exact = _resolve_cases("chemical_equilibrium_titration", _CASE_DIR)
        self.assertEqual([case.id for case in exact], ["chemical_equilibrium_titration"])

    def test_light_suite_is_high_school_plus_scoped_and_deliberately_hard(self) -> None:
        light = _resolve_cases("light", _CASE_DIR)
        self.assertEqual(
            {case.id for case in light},
            {
                "chemical_equilibrium_titration",
                "circuit_measurement_internal_resistance",
                "conditional_probability_diagnostic_test",
                "derivative_monotonicity_optimization",
                "french_revolution_causes",
                "monsoon_water_cycle_urbanization",
                "photosynthesis_respiration_limits",
                "projectile_motion_energy",
            },
        )
        self.assertEqual(
            {case.subject for case in light},
            {"高中数学", "高中物理", "高中化学", "高中生物", "高中地理", "高中历史"},
        )
        for case in light:
            self.assertEqual(case.curriculum_scope, "high_school_plus", case.id)
            self.assertGreaterEqual(len(case.extension_topics), 2, case.id)
            self.assertLessEqual(len(case.extension_topics), 3, case.id)
            self.assertIn("高中", case.query, case.id)
            self.assertGreaterEqual(len(case.expected_knowledge_points), 10, case.id)
            self.assertGreaterEqual(len(case.required_facts), 10, case.id)
            self.assertGreaterEqual(
                sum(fact.id.endswith("_bridge") for fact in case.required_facts),
                2,
                case.id,
            )
            self.assertGreaterEqual(len(case.traps), 4, case.id)
            self.assertGreaterEqual(len(case.contrasts), 4, case.id)
            self.assertGreaterEqual(case.min_unique_sources, 12, case.id)
            self.assertGreaterEqual(case.format_requirements.min_chars, 10000, case.id)
            self.assertGreaterEqual(case.learning_requirements.min_objectives, 5, case.id)
            self.assertGreaterEqual(case.learning_requirements.min_worked_examples, 4, case.id)
            self.assertGreaterEqual(case.learning_requirements.min_practice_questions, 12, case.id)
            self.assertGreaterEqual(case.learning_requirements.min_answered_questions, 12, case.id)
            requirements = case.request_payload()["requirements"]
            self.assertEqual(case.request_payload()["research_budget"], "lean", case.id)
            required_sections = (len(case.expected_knowledge_points) * 4 + 4) // 5
            self.assertGreaterEqual(int(case.options.get("max_points") or 0), required_sections, case.id)
            self.assertIn(f"至少{required_sections}个独立知识点二级标题", requirements, case.id)
            self.assertIn("至少5个可检验学习目标", requirements, case.id)
            self.assertIn("至少4个带完整步骤的例题", requirements, case.id)
            self.assertIn("至少12道自测题", requirements, case.id)
            self.assertIn("主题主线与作答前提限高中", requirements, case.id)
            self.assertIn("[拓展:上列对应主题全名]", requirements, case.id)
            self.assertIn("[高中连接]", requirements, case.id)
            for topic in case.extension_topics:
                self.assertIn(topic, requirements, case.id)

    def test_light_and_heavy_partition_all_cases(self) -> None:
        light = _resolve_cases("light", _CASE_DIR)
        heavy = _resolve_cases("heavy", _CASE_DIR)
        all_cases = _resolve_cases("all", _CASE_DIR)
        light_ids = {case.id for case in light}
        heavy_ids = {case.id for case in heavy}
        self.assertEqual(len(light), 8)
        self.assertEqual(len(heavy), 32)
        self.assertFalse(light_ids & heavy_ids)
        self.assertEqual(light_ids | heavy_ids, {case.id for case in all_cases})
        self.assertEqual(light_ids, {case.id for case in _resolve_cases("smoke", _CASE_DIR)})

    def test_stable_shards_are_disjoint_and_exhaustive(self) -> None:
        cases = _resolve_cases("all", _CASE_DIR)
        shards = [_select_shard(cases, count=3, index=index) for index in range(3)]
        ids_by_shard = [{case.id for case in shard} for shard in shards]
        self.assertFalse(ids_by_shard[0] & ids_by_shard[1])
        self.assertFalse(ids_by_shard[0] & ids_by_shard[2])
        self.assertFalse(ids_by_shard[1] & ids_by_shard[2])
        self.assertEqual(set().union(*ids_by_shard), {case.id for case in cases})
        reversed_first = _select_shard(list(reversed(cases)), count=3, index=0)
        self.assertEqual([case.id for case in reversed_first], [case.id for case in shards[0]])

    def test_shard_and_parallel_validation(self) -> None:
        cases = _resolve_cases("smoke", _CASE_DIR)
        with self.assertRaises(CaseValidationError):
            _select_shard(cases, count=0, index=0)
        with self.assertRaises(CaseValidationError):
            _select_shard(cases, count=2, index=2)
        with self.assertRaises(CaseValidationError):
            _effective_parallel(-1, len(cases))

    def test_parallel_zero_auto_caps_at_four(self) -> None:
        self.assertEqual(_effective_parallel(0, 1), 1)
        self.assertEqual(_effective_parallel(0, 2), 2)
        self.assertEqual(_effective_parallel(0, 40), 4)
        self.assertEqual(_effective_parallel(1, 40), 1)
        self.assertEqual(_effective_parallel(99, 3), 3)

    def test_parallel_main_runs_all_cases(self) -> None:
        import tempfile
        from unittest.mock import patch

        import backend.evals.study_materials.runner as runner_mod

        with tempfile.TemporaryDirectory() as tmp:
            cases_dir = Path(tmp) / "cases"
            cases_dir.mkdir()
            (cases_dir / "mini_a.json").write_text(json.dumps(_mini_case(id="mini_a")), encoding="utf-8")
            (cases_dir / "mini_b.json").write_text(json.dumps(_mini_case(id="mini_b")), encoding="utf-8")
            ran: list[str] = []

            def fake_run_case(case, **_kwargs):  # noqa: ANN001, ANN202
                ran.append(case.id)
                return {"case_id": case.id, "total": 42.0}

            with patch.object(runner_mod, "run_case", side_effect=fake_run_case):
                rc = runner_mod.main(
                    ["--case", "all", "--cases-dir", str(cases_dir), "--out", str(Path(tmp) / "out")]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(sorted(ran), ["mini_a", "mini_b"])

    def test_run_case_wires_llm_rubric_judge(self) -> None:
        """--llm-judge 开启时 build_llm_rubric_judge 的产出必须传进 grade_case（T14 接线）。"""
        import tempfile
        from unittest.mock import patch

        import backend.evals.study_materials.runner as runner_mod

        case = parse_case(_mini_case())
        called = {"rubric": 0}

        def fake_rubric_judge(system, markdown):  # noqa: ANN001, ANN202
            called["rubric"] += 1
            return {
                "coherence": 4,
                "style": 3,
                "misconception_authenticity": 5,
                "rationale": {"coherence": "承接自然", "style": "稳", "misconception_authenticity": "真实"},
            }

        fake_run = {
            "events": [_frame("done", {"material": {"markdown": _CHALLENGE_READY_MD}})],
            "markdown": _CHALLENGE_READY_MD,
            "markdown_source": "done_event",
            "task_id": "",
            "error": "",
            "elapsed_s": 0.1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(runner_mod, "collect_run", return_value=fake_run),
                patch.object(runner_mod, "build_llm_fact_judge", return_value=lambda md, desc, urls: True),
                patch.object(runner_mod, "build_llm_aesthetics_judge", return_value=lambda md, title: 0.5),
                patch.object(runner_mod, "build_llm_rubric_judge", return_value=fake_rubric_judge),
            ):
                judged = runner_mod.run_case(
                    case, base_url="http://127.0.0.1:9", out_root=Path(tmp),
                    timeout_s=1.0, llm_judge=True, check_links=False,
                )
                unjudged = runner_mod.run_case(
                    case, base_url="http://127.0.0.1:9", out_root=Path(tmp),
                    timeout_s=1.0, llm_judge=False, check_links=False,
                )
        self.assertEqual(called["rubric"], 1)
        self.assertEqual(judged["writing_rubric"]["coherence"], 4)
        self.assertEqual(judged["writing_rubric"]["misconception_authenticity"], 5)
        self.assertIsNone(unjudged["writing_rubric"])

    def test_regrade_wires_llm_rubric_judge(self) -> None:
        import tempfile
        from unittest.mock import patch

        import backend.evals.study_materials.runner as runner_mod

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "meta.json").write_text(json.dumps({"case_id": "mini", "error": ""}), encoding="utf-8")
            cases_dir = Path(tmp) / "cases"
            cases_dir.mkdir()
            (cases_dir / "mini.json").write_text(json.dumps(_mini_case()), encoding="utf-8")
            (run_dir / "events.jsonl").write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in _LEGACY_EVENTS) + "\n", encoding="utf-8"
            )
            (run_dir / "final.md").write_text(_CHALLENGE_READY_MD, encoding="utf-8")
            (run_dir / "task_info.json").write_text(json.dumps({}), encoding="utf-8")
            with (
                patch.object(runner_mod, "build_llm_fact_judge", return_value=lambda md, desc, urls: True),
                patch.object(runner_mod, "build_llm_aesthetics_judge", return_value=lambda md, title: 0.5),
                patch.object(
                    runner_mod,
                    "build_llm_rubric_judge",
                    return_value=lambda system, md: {"coherence": 5, "style": 4, "misconception_authenticity": 3},
                ),
            ):
                result = runner_mod.regrade_run(run_dir, cases_dir=cases_dir, llm_judge=True, check_links=False)
        self.assertEqual(result["writing_rubric"]["coherence"], 5)


class RubricGraderTests(unittest.TestCase):
    """W 维度：LLM rubric 写作诊断（独立字段，不进总分/四门槛/成熟度）。"""

    def setUp(self) -> None:
        self.case = parse_case(_mini_case())

    def test_fake_judge_scores_appear_in_w_dimension(self) -> None:
        captured: dict = {}

        def fake_judge(system: str, markdown: str) -> dict:
            captured["system"] = system
            return {
                "coherence": 4,
                "style": 3,
                "misconception_authenticity": 5,
                "rationale": {
                    "coherence": "节间承接自然",
                    "style": "略有模板腔",
                    "misconception_authenticity": "误区像真实教学错误",
                },
            }

        baseline = grade_case(self.case, _LEGACY_EVENTS, _CURRENT_STYLE_MD)
        card = grade_case(self.case, _LEGACY_EVENTS, _CURRENT_STYLE_MD, llm_rubric_judge=fake_judge)
        rubric = card.writing_rubric
        self.assertIsNotNone(rubric)
        self.assertEqual(rubric["coherence"], 4)
        self.assertEqual(rubric["style"], 3)
        self.assertEqual(rubric["misconception_authenticity"], 5)
        self.assertEqual(rubric["rationale"]["style"], "略有模板腔")
        self.assertIsNone(rubric["error"])
        # system prompt 来自注册表 study.eval.rubric.v1
        self.assertIn("coherence", captured["system"])
        self.assertIn("misconception_authenticity", captured["system"])
        # W 不改变成熟度分与任何既有维度
        self.assertEqual(card.total, baseline.total)
        self.assertEqual(card.raw_total, baseline.raw_total)
        self.assertEqual([d.dimension for d in card.dimensions], ["R", "K", "L", "F", "A", "C"])
        self.assertEqual([d.dimension for d in card.process_diagnostics], ["S"])
        payload = card.to_dict()
        self.assertEqual(payload["writing_rubric"]["coherence"], 4)
        json.dumps(payload, ensure_ascii=False)
        from backend.evals.study_materials.scorecard import render_report

        self.assertIn("写作 rubric", render_report(card))

    def test_judge_disabled_w_is_null_and_dimensions_untouched(self) -> None:
        card = grade_case(self.case, _LEGACY_EVENTS, _CURRENT_STYLE_MD)
        self.assertIsNone(card.writing_rubric)
        self.assertIsNone(card.to_dict()["writing_rubric"])
        self.assertEqual([d.dimension for d in card.dimensions], ["R", "K", "L", "F", "A", "C"])
        # grade_rubric 本身在 judge 未启用时记 null + error，不抛异常
        w = grade_rubric(_CURRENT_STYLE_MD, judge_func=None)["W"]
        self.assertIsNone(w["coherence"])
        self.assertIsNone(w["style"])
        self.assertIsNone(w["misconception_authenticity"])
        self.assertEqual(w["error"], "judge_not_enabled")

    def test_invalid_json_marks_parse_error_without_sinking_scores(self) -> None:
        baseline = grade_case(self.case, _LEGACY_EVENTS, _CURRENT_STYLE_MD)
        card = grade_case(
            self.case,
            _LEGACY_EVENTS,
            _CURRENT_STYLE_MD,
            llm_rubric_judge=lambda system, md: "这不是 JSON，无法解析",
        )
        rubric = card.writing_rubric
        self.assertIsNotNone(rubric)
        self.assertIsNone(rubric["coherence"])
        self.assertIsNone(rubric["style"])
        self.assertIsNone(rubric["misconception_authenticity"])
        self.assertIn("parse_error", rubric["error"])
        self.assertEqual(card.total, baseline.total)

    def test_judge_exception_and_out_of_range_scores_are_sanitized(self) -> None:
        def boom(system: str, markdown: str) -> dict:
            raise RuntimeError("llm down")

        w = grade_rubric(_CURRENT_STYLE_MD, judge_func=boom)["W"]
        self.assertIsNone(w["coherence"])
        self.assertIn("judge_error", w["error"])
        # JSON 字符串返回 + 越界/非法分数截断为 0-5 或 null
        raw = '{"coherence": 9, "style": -1, "misconception_authenticity": "x"}'
        w2 = grade_rubric(_CURRENT_STYLE_MD, judge_func=lambda system, md: raw)["W"]
        self.assertEqual(w2["coherence"], 5)
        self.assertEqual(w2["style"], 0)
        self.assertIsNone(w2["misconception_authenticity"])
        self.assertIsNone(w2["error"])

    def test_fence_wrapped_json_is_parsed_without_retry(self) -> None:
        # 真实缺陷：judge 用 ```json fence 包裹输出 → 直接解析失败（run #4 W=parse_error）。
        calls: list = []

        def fence_judge(system: str, markdown: str) -> str:
            calls.append(markdown)
            return '```json\n{"coherence": 4, "style": 3, "misconception_authenticity": 5}\n```'

        w = grade_rubric(_CURRENT_STYLE_MD, judge_func=fence_judge)["W"]

        self.assertEqual(w["coherence"], 4)
        self.assertEqual(w["style"], 3)
        self.assertIsNone(w["error"])
        self.assertEqual(len(calls), 1)

    def test_prose_prefixed_json_is_parsed_without_retry(self) -> None:
        calls: list = []

        def chatty_judge(system: str, markdown: str) -> str:
            calls.append(markdown)
            return '好的，以下是评审结果：\n{"coherence": 4, "style": 3, "misconception_authenticity": 5}\n希望有帮助。'

        w = grade_rubric(_CURRENT_STYLE_MD, judge_func=chatty_judge)["W"]

        self.assertEqual(w["coherence"], 4)
        self.assertIsNone(w["error"])
        self.assertEqual(len(calls), 1)

    def test_unparseable_output_retried_once_with_json_only_reminder(self) -> None:
        calls: list = []

        def flaky_judge(system: str, markdown: str) -> str:
            calls.append(markdown)
            if len(calls) == 1:
                return "这份资料整体不错，我给出如下评价……（散文，无 JSON）"
            return '{"coherence": 2, "style": 2, "misconception_authenticity": 2}'

        w = grade_rubric(_CURRENT_STYLE_MD, judge_func=flaky_judge)["W"]

        self.assertEqual(w["coherence"], 2)
        self.assertIsNone(w["error"])
        self.assertEqual(len(calls), 2)
        self.assertIn("只输出 JSON", calls[1])

    def test_persistent_garbage_marks_parse_error_with_raw_head_and_single_retry(self) -> None:
        calls: list = []

        def garbage_judge(system: str, markdown: str) -> str:
            calls.append(markdown)
            return "彻底无法解析的输出" * 30

        w = grade_rubric(_CURRENT_STYLE_MD, judge_func=garbage_judge)["W"]

        self.assertIsNone(w["coherence"])
        self.assertIn("parse_error", w["error"])
        self.assertIn("| raw: ", w["error"])
        self.assertIn("彻底无法解析的输出", w["error"])
        # 只重试一次，不得循环重试
        self.assertEqual(len(calls), 2)

    def test_rubric_prompt_registered_with_json_contract(self) -> None:
        from backend.llm.prompts import create_default_prompt_registry

        rendered = create_default_prompt_registry().render("study.eval.rubric.v1")
        self.assertIn("coherence", rendered.content)
        self.assertIn("misconception_authenticity", rendered.content)
        self.assertEqual(rendered.output_contract.validate_prompt_text(rendered.content), [])


if __name__ == "__main__":
    unittest.main()
