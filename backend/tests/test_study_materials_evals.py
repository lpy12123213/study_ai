"""自学资料 benchmark 的离线单元测试：全部 fixture 内联，不触网、不调 LLM。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.evals.study_materials.case_schema import (
    CaseValidationError,
    default_cases_dir,
    load_cases,
    parse_case,
)
from backend.evals.study_materials.graders.aesthetics import grade_aesthetics
from backend.evals.study_materials.graders.citations import grade_citations
from backend.evals.study_materials.graders.common import DIMENSION_MAX, validate_weights
from backend.evals.study_materials.graders.events import EventStats, grade_research, grade_subagents
from backend.evals.study_materials.graders.knowledge import grade_knowledge
from backend.evals.study_materials.graders.structure import grade_structure
from backend.evals.study_materials.runner import _extract_markdown
from backend.evals.study_materials.scorecard import grade_case

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
            {"id": "f1", "description": "定义点", "match": {"all": ["定义甲"], "any": ["概念|内涵"]}},
            {"id": "f2", "description": "性质点", "match": {"all": ["性质乙"], "any": ["定理|结论"]}},
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
        self.assertEqual(len(cases), 6)
        for case in cases:
            self.assertTrue(case.required_facts, case.id)
            self.assertTrue(case.traps, case.id)
            self.assertTrue(case.expected_knowledge_points, case.id)
            self.assertEqual(case.options.get("prefer_local_archive"), False, case.id)
            payload = case.request_payload()
            self.assertEqual(payload["query"], case.query)
            self.assertEqual(payload["preset"], case.preset)

    def test_case_ids_unique(self) -> None:
        ids = [c.id for c in load_cases(_CASE_DIR)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_reject_empty_facts(self) -> None:
        with self.assertRaises(CaseValidationError):
            parse_case(_mini_case(required_facts=[]))

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
        self.assertAlmostEqual(result.score, DIMENSION_MAX["S"])

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
        md = "定义甲是一种概念。性质乙是重要定理。概念甲与概念乙在此同段对比。正确澄清。"
        gated = grade_knowledge(self.case, md, citation_ratio=0.0)
        full = grade_knowledge(self.case, md, citation_ratio=1.0)
        gated_k1 = {c.id: c for c in gated.checks}["K1_facts"]
        full_k1 = {c.id: c for c in full.checks}["K1_facts"]
        self.assertAlmostEqual(full_k1.score, full_k1.max_score)
        self.assertLess(gated_k1.score, gated_k1.max_score * 0.2)
        self.assertIn("溯源系数", gated_k1.detail)

    def test_fact_miss_and_llm_rescue(self) -> None:
        md = "定义甲是一种概念。正确澄清。"
        judged = grade_knowledge(self.case, md, llm_judge=lambda md_, desc, urls: True, citation_ratio=1.0)
        by_id = {c.id: c for c in judged.checks}
        self.assertAlmostEqual(by_id["K1_facts"].score, by_id["K1_facts"].max_score)

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
        near = "概念甲……" + "填充" * 10 + "……概念乙"
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
        )
        result = grade_citations(self.case, md, link_checker=lambda url: True)
        by_id = {c.id: c for c in result.checks}
        self.assertAlmostEqual(by_id["C1_references_section"].score, by_id["C1_references_section"].max_score)
        self.assertGreater(by_id["C2_inline_markers"].score, 0.0)
        self.assertGreater(by_id["C3_link_check"].score, 0.0)

    def test_links_checked_only_when_enabled(self) -> None:
        md = "## 参考文献\n- https://example.edu/a\n- https://wikipedia.org/b\n"
        offline = grade_citations(self.case, md)
        by_id = {c.id: c for c in offline.checks}
        self.assertEqual(by_id["C3_link_check"].score, 0.0)
        self.assertIn("--check-links", by_id["C3_link_check"].detail)


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
        self.assertEqual([d.dimension for d in card.dimensions], ["R", "K", "S", "F", "A", "C"])
        self.assertGreaterEqual(card.total, 0.0)
        self.assertLessEqual(card.total, 100.0)
        payload = card.to_dict()
        self.assertEqual(payload["case_id"], "mini")
        json.dumps(payload, ensure_ascii=False)

    def test_current_style_run_scores_below_20(self) -> None:
        """难度锚：模拟现行默认链路产物（无子代理/无引用/纯文本目录），总分必须 <20。"""
        case = parse_case(_mini_case(min_unique_sources=12))
        card = grade_case(case, _LEGACY_EVENTS, _CURRENT_STYLE_MD)
        self.assertLess(card.total, 20.0)
        by_dim = {d.dimension: d for d in card.dimensions}
        self.assertEqual(by_dim["S"].score, 0.0)
        self.assertEqual(by_dim["C"].score, 0.0)

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
            self.assertIn("总分", paths["report"].read_text(encoding="utf-8"))


class RunnerHelperTests(unittest.TestCase):
    def test_extract_markdown_shapes(self) -> None:
        self.assertEqual(_extract_markdown({"material": {"markdown": "正文"}}), "正文")
        self.assertEqual(_extract_markdown({"material": "正文"}), "正文")
        self.assertEqual(_extract_markdown({"markdown": "正文"}), "正文")
        self.assertEqual(_extract_markdown({}), "")

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
                    ["--case", "all", "--cases-dir", str(cases_dir), "--parallel", "2", "--out", str(Path(tmp) / "out")]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(sorted(ran), ["mini_a", "mini_b"])


if __name__ == "__main__":
    unittest.main()
