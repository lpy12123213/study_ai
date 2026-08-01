# 作者 Agent 制自学资料生成 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把自学资料生成从「流水线拼装」改为「单一作者 agent + 一层填充子 agent + MCP 配图子 AI」，成稿连贯、可信、图文配套、过程全透明、TODO 驱动不漏点。

**Architecture:** 设计全文见 `docs/plans/2026-08-01-author-agent-study-materials-design.md`（下称「设计稿」，§n 指其章节）。核心：主 agent 完成 RESEARCH→BLUEPRINT→BACKBONE→TODO 分解；一层子 agent 并行填充 `[[FILL:sec-id]]`；figure-forge MCP 异步回填 `[[FIG:n]]`；确定性汇编器替换占位符并渲染书目；TODO 清零/占位符清零成为验收硬门槛；所有 LLM/工具调用发统一 trace 事件（含 `thinking_delta`）。

**Tech Stack:** Python 3.13 / FastAPI / unittest / Ruff(120 列)；前端 Vite6 + React18 + TS strict + Vitest + Playwright(win32 快照)。

**执行约定（每个 Task 都必须遵守）:**

- 后端测试用 unittest（**不是 pytest**）: `python -m unittest backend.tests.test_xxx -v`；全量 `python -m unittest discover -s backend/tests -p "test_*.py"`。
- Python lint: `python -m ruff check backend scripts`；前端: `cd frontend && npm run test` / `npm run build` / `npm run lint`。
- 文中行号锚点以 2026-08-01 代码为准，**执行时先回读确认再改**；发现锚点漂移以实际代码为准并在 commit message 里说明。
- 每个 Task 末尾的 commit 步骤不可省略（Conventional Commits，如 `feat(study-materials): ...`）。
- 遵守 `AGENTS.md`：不得查看/恢复历史前端源码；不改无关文件；`.env` 不提交。
- TDD：先写失败测试 → 跑确认失败 → 最小实现 → 跑确认通过 → commit。

---

## Phase 0: 基线确认

**Step 0.1: 跑基线，记录既有失败（不要修）**

```bash
python -m unittest discover -s backend/tests -p "test_*.py" 2>&1 | tail -5
python -m ruff check backend scripts
cd frontend && npm run test 2>&1 | tail -5 && npm run build 2>&1 | tail -3
```

Expected: 全绿或仅有既有失败；把既有失败清单贴到首个 commit message 里，后续不得新增失败。

**Step 0.2（可选）: 建 worktree 隔离**

参考 @superpowers:using-git-worktrees；不建则在当前工作区执行，注意不覆盖他人未提交改动（先 `git status`）。

---

## Phase 1: 检索薄封装 + 笔记/TODO/trace 基建

新代码集中在 `backend/generation/study_materials/author/` 新包；**legacy 路径（`web_search_knowledge`、AgentCore）本阶段一律不动**，退役留到 Phase 5。

### Task 1: TODO 模型与持久化

**Files:**
- Create: `backend/generation/study_materials/author/__init__.py`（空）
- Create: `backend/generation/study_materials/author/todos.py`
- Test: `backend/tests/test_study_materials_author_todos.py`

**Step 1: 写失败测试**

```python
# backend/tests/test_study_materials_author_todos.py
import tempfile
import unittest
from pathlib import Path

from backend.generation.study_materials.author.todos import TodoItem, TodoList


class TodoModelTests(unittest.TestCase):
    def test_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            TodoItem(id="t1", type="bogus")

    def test_all_cleared_requires_done_or_waived(self):
        tl = TodoList(items=[
            TodoItem(id="t1", type="fill", ref="sec-1", status="done"),
            TodoItem(id="t2", type="fig", ref="1", status="waived", note="engine down"),
        ])
        self.assertTrue(tl.all_cleared())
        tl.items[1].status = "pending"
        self.assertFalse(tl.all_cleared())

    def test_roundtrip_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "todos.json"
            tl = TodoList(items=[TodoItem(id="t1", type="research", acceptance=">=3 sources")])
            tl.save(p)
            loaded = TodoList.load(p)
            self.assertEqual(loaded.items[0].acceptance, ">=3 sources")
            self.assertFalse(p.with_suffix(".json.tmp").exists())

    def test_next_pending_respects_deps(self):
        tl = TodoList(items=[
            TodoItem(id="a", type="backbone"),
            TodoItem(id="b", type="fill", ref="sec-1", deps=["a"]),
        ])
        self.assertEqual(tl.next_pending().id, "a")
        tl.mark("a", "done")
        self.assertEqual(tl.next_pending().id, "b")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: 跑确认失败**

Run: `python -m unittest backend.tests.test_study_materials_author_todos -v`
Expected: FAIL `ModuleNotFoundError: ...author`

**Step 3: 最小实现**

```python
# backend/generation/study_materials/author/todos.py
"""TODO model for the author-agent study materials pipeline (design doc §5.3)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

TODO_TYPES = frozenset({"research", "backbone", "fill", "fig", "audit", "revision"})
TODO_STATUSES = frozenset({"pending", "in_progress", "done", "waived", "failed"})


@dataclass
class TodoItem:
    id: str
    type: str
    ref: str = ""
    acceptance: str = ""
    deps: List[str] = field(default_factory=list)
    status: str = "pending"
    retries: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        if self.type not in TODO_TYPES:
            raise ValueError(f"unknown todo type: {self.type}")
        if self.status not in TODO_STATUSES:
            raise ValueError(f"unknown todo status: {self.status}")


class TodoList:
    def __init__(self, items: Optional[List[TodoItem]] = None) -> None:
        self.items: List[TodoItem] = list(items or [])

    def get(self, todo_id: str) -> TodoItem:
        for it in self.items:
            if it.id == todo_id:
                return it
        raise KeyError(todo_id)

    def mark(self, todo_id: str, status: str, note: str = "") -> None:
        it = self.get(todo_id)
        if status not in TODO_STATUSES:
            raise ValueError(f"unknown todo status: {status}")
        it.status = status
        if note:
            it.note = note

    def all_cleared(self) -> bool:
        return all(it.status in {"done", "waived"} for it in self.items)

    def pending(self) -> List[TodoItem]:
        done = {it.id for it in self.items if it.status in {"done", "waived"}}
        return [
            it for it in self.items
            if it.status in {"pending", "failed"} and all(d in done for d in it.deps)
        ]

    def next_pending(self) -> Optional[TodoItem]:
        items = self.pending()
        return items[0] if items else None

    def to_json(self) -> list:
        return [asdict(it) for it in self.items]

    @classmethod
    def from_json(cls, data: list) -> "TodoList":
        return cls(items=[TodoItem(**raw) for raw in data])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_json(), fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path: Path) -> "TodoList":
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))
```

**Step 4: 跑确认通过**

Run: `python -m unittest backend.tests.test_study_materials_author_todos -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/generation/study_materials/author/ backend/tests/test_study_materials_author_todos.py
git commit -m "feat(study-materials): add author-pipeline todo model with atomic persistence"
```

### Task 2: 作者笔记存储（notes store）

**Files:**
- Create: `backend/generation/study_materials/author/notes.py`
- Test: `backend/tests/test_study_materials_author_notes.py`

**Step 1: 写失败测试**

```python
import tempfile
import unittest
from pathlib import Path

from backend.generation.study_materials.author.notes import NotesStore


class NotesStoreTests(unittest.TestCase):
    def test_write_read_append_and_events(self):
        events = []
        with tempfile.TemporaryDirectory() as d:
            store = NotesStore(Path(d), on_write=lambda name, n: events.append((name, n)))
            store.write("research", "# 研究笔记\n## 极限")
            store.append("research", "fact: 夹逼定理 | src: https://a | conf: 0.9")
            text = store.read("research")
            self.assertIn("夹逼定理", text)
            self.assertEqual(events, [("research", len("# 研究笔记\n## 极限")),
                                      ("research", len(text))])
            self.assertTrue((Path(d) / "research.md").exists())

    def test_read_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(NotesStore(Path(d)).read("blueprint"), "")

    def test_rejects_path_traversal_name(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                NotesStore(Path(d)).write("../evil", "x")


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** `python -m unittest backend.tests.test_study_materials_author_notes -v` → FAIL（模块不存在）

**Step 3: 最小实现**

```python
# backend/generation/study_materials/author/notes.py
"""Durable author notes (research / blueprint / backbone / section summaries).

Design doc §4: the author relies on external notes, not raw context. Every write
can emit a `note_write` trace event via the `on_write` callback.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


class NotesStore:
    def __init__(self, root: Path, on_write: Optional[Callable[[str, int], None]] = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._on_write = on_write

    def _path(self, name: str) -> Path:
        if not _NAME_RE.match(name):
            raise ValueError(f"invalid note name: {name!r}")
        return self.root / f"{name}.md"

    def write(self, name: str, content: str) -> Path:
        p = self._path(name)
        p.write_text(content, encoding="utf-8")
        if self._on_write:
            self._on_write(name, len(content))
        return p

    def append(self, name: str, line: str) -> Path:
        p = self._path(name)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if p.stat().st_size else "") + line)
        if self._on_write:
            self._on_write(name, p.stat().st_size)
        return p

    def read(self, name: str) -> str:
        p = self._path(name)
        return p.read_text(encoding="utf-8") if p.exists() else ""
```

**Step 4:** 跑测试 → 3 passed；`python -m ruff check backend/generation/study_materials/author`

**Step 5: Commit** `feat(study-materials): add author notes store with note_write hook`

### Task 3: 统一 trace 事件助手（agent_path）

**Files:**
- Create: `backend/generation/study_materials/author/trace.py`
- Test: `backend/tests/test_study_materials_author_trace.py`
- 回读: `backend/generation/study_materials/orchestrator.py:998-1160`（事件发射与 seq 分配方式）

**Step 1: 写失败测试**

```python
import unittest

from backend.generation.study_materials.author.trace import TRACE_EVENT_TYPES, make_event


class TraceTests(unittest.TestCase):
    def test_event_carries_agent_path(self):
        ev = make_event("thinking_delta", agent_path="fill:sec-1.2", data={"text": "嗯"})
        self.assertEqual(ev["type"], "thinking_delta")
        self.assertEqual(ev["agent_path"], "fill:sec-1.2")

    def test_declared_types_cover_design_contract(self):
        for t in {"thinking_delta", "note_write", "todo_update", "figure_trace"}:
            self.assertIn(t, TRACE_EVENT_TYPES)

    def test_rejects_undeclared_type(self):
        with self.assertRaises(ValueError):
            make_event("mystery", agent_path="main", data={})


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** 跑 → FAIL

**Step 3: 实现**

```python
# backend/generation/study_materials/author/trace.py
"""Unified trace events (design doc §9). Invariant: no hidden LLM/tool calls —
every call must happen at a layer that emits one of these events."""
from __future__ import annotations

from typing import Any, Dict

TRACE_EVENT_TYPES = frozenset({
    "thinking_delta",   # 统一思考增量（替代 legacy thinking / codex reasoning_delta）
    "note_write",       # 笔记落笔 {name, chars}
    "todo_update",      # TODO 状态变更 {todo: {...}}
    "tool_call",        # 工具调用（补 agent_path；沿用现有 data 形状）
    "figure_trace",     # 配图代码/渲染尝试/产物 {figure_id, stage, ...}
    "section_fill",     # 填充开始/完成 {sec_id, status}
    "text_delta",       # 成稿快照（沿用现有）
})


def make_event(event_type: str, *, agent_path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if event_type not in TRACE_EVENT_TYPES:
        raise ValueError(f"undeclared trace event type: {event_type}")
    return {"type": event_type, "agent_path": agent_path, "data": data}
```

seq 分配与落库不在这里做——orchestrator 的事件总线负责；本助手只保证作者链路产生的每条事件形状统一、可归因。

**Step 4:** 跑 → 3 passed

**Step 5: Commit** `feat(study-materials): add unified trace event helper with agent_path`

### Task 4: 作者用薄检索工具（无 decompose / 无内嵌递归引擎）

**Files:**
- Create: `backend/generation/study_materials/author/research_tools.py`
- Test: `backend/tests/test_study_materials_author_research_tools.py`
- 回读: `backend/integrations/mcp/search/tavily.py`（`tavily_search` 签名）、`backend/integrations/mcp/search/exa.py`、`backend/agent/tools/search/browse_web_pages.py`（页面抓取复用点）、`backend/generation/study_materials/tool_executor.py:191-260`（缓存/熔断/并发模式）

**Step 1: 写失败测试**（不访问网络，provider 函数注入）

```python
import asyncio
import unittest

from backend.generation.study_materials.author.research_tools import ResearchToolbox


class ResearchToolboxTests(unittest.TestCase):
    def test_search_calls_provider_directly_without_llm(self):
        calls = []

        async def fake_serp(query, n):
            calls.append(query)
            return [{"url": "https://a/x", "title": "t", "snippet": "s"}]

        box = ResearchToolbox(serp_func=fake_serp)
        out = asyncio.run(box.search("拉格朗日 中值定理 常见错误", n=3))
        self.assertEqual(calls, ["拉格朗日 中值定理 常见错误"])
        self.assertEqual(out["results"][0]["url"], "https://a/x")
        self.assertNotIn("sub_questions", out)  # 无 decompose 层

    def test_provider_failure_raises_with_provider_name(self):
        async def boom(query, n):
            raise RuntimeError("http_status_432")

        box = ResearchToolbox(serp_func=boom)
        with self.assertRaises(RuntimeError) as cm:
            asyncio.run(box.search("q", n=1))
        self.assertIn("serp", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** 跑 → FAIL

**Step 3: 实现**（薄封装：直接 SERP + 页面抓取；缓存/熔断复用 tool_executor 的模式简化移植；**严禁**在此层引入任何 LLM 调用——设计稿 §8 不变量）

```python
# backend/generation/study_materials/author/research_tools.py
"""Thin search/browse tools for the author agent (design doc §8).

No LLM calls in this layer: query formulation is the author's own job.
Provider fallback order and health markers mirror tool_executor.py but stay
local and injectable for tests."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

SerpFunc = Callable[[str, int], Awaitable[List[Dict[str, Any]]]]
FetchFunc = Callable[[str], Awaitable[str]]


class ResearchToolbox:
    def __init__(
        self,
        serp_func: Optional[SerpFunc] = None,
        fetch_func: Optional[FetchFunc] = None,
        *,
        timeout_s: float = 30.0,
    ) -> None:
        self._serp = serp_func or self._default_serp
        self._fetch = fetch_func or self._default_fetch
        self._timeout = timeout_s

    async def search(self, query: str, n: int = 5) -> Dict[str, Any]:
        try:
            results = await asyncio.wait_for(self._serp(query, n), timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 - re-raised with provider label for the agent
            raise RuntimeError(f"serp failed: {exc}") from exc
        return {"provider": "serp", "query": query, "results": results[:n]}

    async def browse(self, url: str, *, max_chars: int = 4000) -> Dict[str, Any]:
        try:
            text = await asyncio.wait_for(self._fetch(url), timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"fetch failed: {exc}") from exc
        return {"url": url, "text": text[:max_chars]}

    @staticmethod
    async def _default_serp(query: str, n: int) -> List[Dict[str, Any]]:
        from backend.integrations.mcp.search.tavily import tavily_search  # 回读后按实际签名适配
        return await tavily_search(query, max_results=n)

    @staticmethod
    async def _default_fetch(url: str) -> str:
        from backend.agent.tools.search import browse_web_pages  # 回读后按实际入口适配
        return await browse_web_pages.fetch_text(url)
```

**Step 4:** 跑 → 2 passed；ruff 通过

**Step 5: Commit** `feat(study-materials): add thin LLM-free research toolbox for author agent`

---

## Phase 2: 作者主干 + 填充子 AI + 确定性汇编

### Task 5: 蓝图/主干/填充/核查四个 prompt 注册 + 契约测试

**Files:**
- Modify: `backend/llm/prompts/agentic_registry.py`（在现有 `study.material.*` 注册块附近追加；回读 `:537` 一带确认注册 API）
- Test: `backend/tests/test_study_materials_author_prompts.py`
- 回读: `backend/generation/study_materials/agentic/prompt_contracts.py`（`JsonOutputContract` / `MarkdownOutputContract` 用法）、`backend/tests/test_study_materials_prompt_contracts.py`（测试写法）

**Step 1: 写失败测试**

```python
import unittest

from backend.llm.prompts import create_default_prompt_registry
from backend.generation.study_materials.agentic.prompt_contracts import (
    JsonOutputContract, MarkdownOutputContract,
)


class AuthorPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = create_default_prompt_registry()

    def test_blueprint_prompt_exists_and_is_json_contract(self):
        p = self.reg.render("study.author.blueprint.v1")
        JsonOutputContract().validate(p.content)
        for kw in ["叙事", "小节", "术语", "配图计划", "易错点", "置信"]:
            self.assertIn(kw, p.content)

    def test_fill_prompt_forbids_urls_and_requires_grounded_misconceptions(self):
        p = self.reg.render("study.author.fill.v1")
        MarkdownOutputContract(educational_writing=True).validate(p.content)
        self.assertIn("出处", p.content)      # 易错点必须有出处
        self.assertIn("[EXn]", p.content)     # 学习闭环标签契约

    def test_backbone_prompt_defines_placeholders(self):
        p = self.reg.render("study.author.backbone.v1")
        self.assertIn("[[FILL:", p.content)
        self.assertIn("[[FIG:", p.content)

    def test_audit_prompt_is_json_contract(self):
        p = self.reg.render("study.author.audit.v1")
        JsonOutputContract().validate(p.content)


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** `python -m unittest backend.tests.test_study_materials_author_prompts -v` → FAIL（prompt 未注册）

**Step 3: 注册四个 prompt**（要点，全文写在 registry 里）：

- `study.author.blueprint.v1`(JSON): 输入主题/学科/preset/研究笔记 → 输出 `{narrative, terminology: [{symbol, meaning}], sections: [{id, title, purpose, key_points, target_chars, difficulty, misconceptions: [{claim, source_url}], frontier: bool}], figures: [{n, sec_id, intent, kind, caption}]}`；要求：小节顺序即叙事顺序；易错点只能来自笔记中带出处的条目，没有就空数组；输出严格 JSON、不要 Markdown 代码块。
- `study.author.backbone.v1`(Markdown, educational): 按蓝图写骨架：导言/章导语/学习目标/节间衔接段/小节引入段/总结章/术语表；正文留 `[[FILL:sec-id]]`、图位留 `[[FIG:n]]`；原创改写、不输出 URL。
- `study.author.fill.v1`(Markdown, educational): 只写该小节核心讲解正文；遵守术语表；易错点仅可使用给定笔记切片中带出处的；`[EXn]` 例题带步骤、`[Qn]` 分层自测、`[An]` 答案评分点（与 benchmark `BENCHMARK_OUTPUT_CONTRACT` 对齐，回读 `backend/evals/study_materials/case_schema.py:22-27`）；LaTeX `$...$`/`$$...$$`；禁 URL/引用标记/参考文献。
- `study.author.audit.v1`(JSON): 输入小节正文+笔记切片 → 输出 `{claims: [{text, verdict: supported|unsupported|uncertain, fix}]}`，frontier 节全查。

**Step 4:** 跑 → 4 passed；同时跑既有契约测试确认无回归：
`python -m unittest backend.tests.test_study_materials_prompt_contracts backend.tests.test_agentic_prompt_registry -v`

**Step 5: Commit** `feat(study-materials): register author blueprint/backbone/fill/audit prompts with contract tests`

### Task 6: 蓝图解析与校验

**Files:**
- Create: `backend/generation/study_materials/author/blueprint.py`
- Test: `backend/tests/test_study_materials_author_blueprint.py`

**Step 1: 失败测试**

```python
import unittest

from backend.generation.study_materials.author.blueprint import Blueprint, BlueprintError


VALID = {
    "narrative": "从直观到严格",
    "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小正数"}],
    "sections": [
        {"id": "sec-1", "title": "为什么要极限", "purpose": "动机",
         "key_points": ["直觉"], "target_chars": 1200, "difficulty": "基础",
         "misconceptions": [], "frontier": False},
        {"id": "sec-2", "title": "严格定义", "purpose": "定义",
         "key_points": ["epsilon-delta"], "target_chars": 1800, "difficulty": "应用",
         "misconceptions": [{"claim": "极限=函数值", "source_url": "https://a/x"}],
         "frontier": False},
    ],
    "figures": [{"n": 1, "sec_id": "sec-1", "intent": "趋近过程示意", "kind": "mermaid",
                 "caption": "图1"}],
}


class BlueprintTests(unittest.TestCase):
    def test_parse_valid(self):
        bp = Blueprint.from_dict(VALID)
        self.assertEqual([s.id for s in bp.sections], ["sec-1", "sec-2"])
        self.assertEqual(bp.figures[0].sec_id, "sec-1")

    def test_misconception_without_source_rejected(self):
        bad = dict(VALID, sections=[dict(VALID["sections"][0],
                   misconceptions=[{"claim": "x", "source_url": ""}])])
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(bad)

    def test_figure_refs_unknown_section_rejected(self):
        bad = dict(VALID, figures=[dict(VALID["figures"][0], sec_id="sec-99")])
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(bad)

    def test_duplicate_section_id_rejected(self):
        bad = dict(VALID, sections=[VALID["sections"][0], VALID["sections"][0]])
        with self.assertRaises(BlueprintError):
            Blueprint.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** 跑 → FAIL

**Step 3: 实现**（dataclass `SectionSpec`/`FigureSpec`/`Blueprint`；`from_dict` 做上述三类校验 + 必填字段；`misconceptions[].source_url` 必须 http(s)；`figures[].sec_id` 必须存在于 sections）

**Step 4:** 跑 → 4 passed

**Step 5: Commit** `feat(study-materials): add blueprint schema with grounding validation`

### Task 7: 汇编器（占位符替换 + 书目渲染 + 泄漏防护）

**Files:**
- Create: `backend/generation/study_materials/author/assembler.py`
- Test: `backend/tests/test_study_materials_author_assembler.py`
- 回读: `backend/agent/tools/knowledge/study_archive.py:236-305`（现有骨架顺序与 refs 收集格式，书目字段对齐）

**Step 1: 失败测试**

```python
import unittest

from backend.generation.study_materials.author.assembler import AssemblyError, assemble


BACKBONE = "# 自学材料：极限\n\n引言。\n\n## 一、为什么要极限\n\n引入段。\n\n[[FILL:sec-1]]\n\n[[FIG:1]]\n\n## 总结\n\n收尾。"


class AssembleTests(unittest.TestCase):
    def test_fills_sections_and_figures_and_bibliography(self):
        out = assemble(
            BACKBONE,
            sections={"sec-1": "正文 $x\\to 0$。"},
            figures={1: {"url": "/media/f1.svg", "caption": "趋近过程"}},
            references=[{"title": "Wikipedia: Limit", "url": "https://en.wikipedia.org/wiki/Limit"}],
        )
        self.assertIn("正文 $x\\to 0$。", out)
        self.assertIn("![趋近过程](/media/f1.svg)", out)
        self.assertIn("## 参考文献", out)
        self.assertIn("https://en.wikipedia.org/wiki/Limit", out)
        self.assertNotIn("[[FILL:", out)

    def test_missing_fill_raises(self):
        with self.assertRaises(AssemblyError) as cm:
            assemble(BACKBONE, sections={}, figures={1: {"url": "/m.svg", "caption": "c"}},
                     references=[])
        self.assertIn("sec-1", str(cm.exception))

    def test_fallback_leak_rejected(self):
        leaky = {"sec-1": "> 注：本段讲解未成功使用模型生成（source=llm_sectioned）"}
        with self.assertRaises(AssemblyError):
            assemble(BACKBONE, sections=leaky,
                     figures={1: {"url": "/m.svg", "caption": "c"}}, references=[])


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** 跑 → FAIL

**Step 3: 实现**（要点）：

```python
FILL_RE = re.compile(r"\[\[FILL:([A-Za-z0-9\-]+)\]\]")
FIG_RE = re.compile(r"\[\[FIG:(\d+)\]\]")
_FALLBACK_LEAK_RE = re.compile(r"未成功使用模型生成|兜底内容|source=llm_|退回到摘要")
```

`assemble(backbone, sections, figures, references)`：先对 backbone 与所有片段跑 `_FALLBACK_LEAK_RE`（命中即 `AssemblyError`）；`FILL_RE.sub` 查表替换，缺 key 收集进 missing；`FIG_RE.sub` 替换为 `![caption](url)`；末尾追加 `## 参考文献`（编号列表 `[n] title — url`）；任何 missing → `AssemblyError(", ".join(missing))`。**无占位符时不抛错**（无图书合法）。

**Step 4:** 跑 → 3 passed

**Step 5: Commit** `feat(study-materials): add deterministic assembler with bibliography rendering and leak guard`

### Task 8: 填充子 AI 运行器（有界上下文 + 验收循环 + 作者兜底）

**Files:**
- Create: `backend/generation/study_materials/author/fill.py`
- Test: `backend/tests/test_study_materials_author_fill.py`
- 回读: `backend/generation/study_materials/coverage.py`（lint/维度正则复用）、`backend/agent/tools/knowledge/study_material_generation.py:960-1076`（`_sanitize_explanation_markdown` 与审阅降级模式）

**Step 1: 失败测试**（LLM 注入假函数）

```python
import asyncio
import unittest

from backend.generation.study_materials.author.blueprint import Blueprint
from backend.generation.study_materials.author.fill import FillRunner

BP = Blueprint.from_dict({
    "narrative": "n", "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小"}],
    "sections": [{"id": "sec-1", "title": "t", "purpose": "p", "key_points": ["k"],
                  "target_chars": 800, "difficulty": "基础", "misconceptions": [],
                  "frontier": False}],
    "figures": [],
})


class FillRunnerTests(unittest.TestCase):
    def test_context_pack_is_bounded_and_grounded(self):
        seen = {}

        async def fake_llm(system, user):
            seen["user"] = user
            return "正文含 $\\epsilon$。[EX1] 例 …[Q1] 题 …[A1] 答 …"

        r = FillRunner(llm_func=fake_llm, max_retries=2)
        out = asyncio.run(r.fill(BP.sections[0], backbone_excerpt="衔接段",
                                 research_slice="fact: x | src: https://a",
                                 terminology=BP.terminology))
        self.assertIn("$\\epsilon$", out.text)
        self.assertIn("衔接段", seen["user"])          # 知道接在哪
        self.assertIn("https://a", seen["user"])       # 笔记切片注入
        self.assertLess(len(seen["user"]), 12000)      # 有界

    def test_retry_then_author_fallback_flag(self):
        async def bad_llm(system, user):
            return "太短"

        r = FillRunner(llm_func=bad_llm, max_retries=2, min_chars=100)
        out = asyncio.run(r.fill(BP.sections[0], backbone_excerpt="",
                                 research_slice="", terminology=[]))
        self.assertTrue(out.needs_author_rewrite)
        self.assertEqual(out.attempts, 2)

    def test_url_in_output_rejected(self):
        async def leaky_llm(system, user):
            return "见 https://example.com 详情……" * 20

        r = FillRunner(llm_func=leaky_llm, max_retries=1, min_chars=10)
        out = asyncio.run(r.fill(BP.sections[0], "", "", []))
        self.assertTrue(out.needs_author_rewrite)


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** 跑 → FAIL

**Step 3: 实现** `FillRunner`：`fill()` 构造有界 user payload（backbone_excerpt ≤1500 字 + research_slice ≤4000 字 + 术语表 + 本节规格，总量硬上限 12000 字符）；渲染 `study.author.fill.v1` 为 system；产出校验：长度 ≥ `min(target_chars*0.5, min_chars)`、无 URL/引用标记、无 `[[` 占位符、含 `[EX`/`[Q`/`[A` 标签（缺一则 retry，提示词附缺失项）；重试用尽返回 `FillResult(text="", needs_author_rewrite=True, attempts=n)`；每次尝试发 `section_fill` trace 事件（经回调注入，不在本类里直接碰事件总线）。

**Step 4:** 跑 → 3 passed

**Step 5: Commit** `feat(study-materials): add bounded-context fill runner with acceptance loop`

### Task 9: 作者流水线主体并接入 orchestrator

**Files:**
- Create: `backend/generation/study_materials/author/pipeline.py`
- Modify: `backend/generation/study_materials/orchestrator.py`（回读 `:52-60` runtime 分派与 `:1478 _run_codex_staged` 的接入形状，照其模式加 `_run_author_staged`；`STUDY_MATERIALS_AGENT_RUNTIME=author` 启用）
- Test: `backend/tests/test_study_materials_author_pipeline.py`

**Step 1: 失败测试**（全流程用假 LLM/假检索，驱动 pipeline 走完 research→blueprint→backbone→fill→assemble，断言：todos 全清、成稿无占位符、事件序列含 `todo_update`/`note_write`/`section_fill`、参考文献渲染）

**Step 2:** 跑 → FAIL

**Step 3: 实现** `run_author_pipeline(ctx, *, llm_func, toolbox, emit)` 状态机：

1. **RESEARCH**：对每个知识点调 `toolbox.search`（批量 `asyncio.gather`，并发 3）+ 易错点专项查询（`{kp} 常见错误/误区/misconception`）；事实按 `fact | src | conf` 行 append 进 `notes/research.md`；现有研究门逻辑复用（不达标补查一轮）。
2. **BLUEPRINT**：LLM(JSON) → `Blueprint.from_dict` → 落 `notes/blueprint.md` → 生成 `todos.json`（research/backbone/每节 fill/每图 fig/audit/revision）。
3. **BACKBONE**：LLM(Markdown) → 校验每个 blueprint section 恰有一个 `[[FILL:id]]`（缺/多 → 重试 1 次 → 仍失败任务 failed 且 `recovery_available`）→ 落 `notes/backbone.md` → 推 `text_delta` 骨架快照（前端早期渲染）。
4. **FILL**：`asyncio.gather` 并发跑 `FillRunner`（并发 3，semaphore）；`needs_author_rewrite` 的节由主 LLM 用同一 prompt 亲自补写；全部完成 → ASSEMBLE。
5. **ASSEMBLE**：`assemble()`；`AssemblyError` → 记录并转 REVISE（修主干或补节，限 1 轮）。
6. **AUDIT/REVIEW/REVISE/ACCEPT**：沿用现有 `evaluate_acceptance` 质量门与 `review_content`（回读 `quality_gate.py:218` 接入方式）；REVISE 由主 LLM 执行。

orchestrator 接入：runtime 解析处加 `author` 分支调 `_run_author_staged`；任务快照目录下建 `notes/` 与 `todos.json`；完成仍走 `_upsert_archive_from_resume_state` 等价归档路径（复用现有归档函数，不改表结构）。

**Step 4:** 跑新测试 + 既有 `test_study_materials_workflow.py test_study_materials_resume_state.py` 无回归

**Step 5: Commit** `feat(study-materials): add author pipeline staged runner behind STUDY_MATERIALS_AGENT_RUNTIME=author`

---

## Phase 3: figure-forge 配图 MCP 子 AI

### Task 10: 图规格解析 + 渲染引擎 + 异步回填

**Files:**
- Create: `backend/generation/study_materials/author/figures.py`
- Test: `backend/tests/test_study_materials_author_figures.py`
- 回读: `backend/shared/diagrams/static_render.py`（现有静态图渲染复用点）、`docker/latex-sandbox/` 与 `docker/manim-sandbox/` 的调用方式、`backend/agent/tools/generation/latex_export_compile.py`（沙箱编译调用模式）、`backend/api/media.py`（产物发布到 `.local/media/generated/` 的路径约定）

**Step 1: 失败测试**（渲染器注入假实现，不碰 docker）

```python
import asyncio
import unittest

from backend.generation.study_materials.author.figures import FigureForge


class FigureForgeTests(unittest.TestCase):
    def test_success_returns_artifact_and_trace(self):
        async def fake_render(kind, code):
            return {"url": "/media/generated/f1.svg", "engine": kind}

        async def fake_llm(spec):
            return "graph LR; A-->B"

        trace = []
        forge = FigureForge(llm_codegen=fake_llm, render_func=fake_render,
                            on_trace=lambda ev: trace.append(ev))
        out = asyncio.run(forge.generate(
            {"n": 1, "sec_id": "sec-1", "intent": "流程", "kind": "mermaid", "caption": "图1"}))
        self.assertEqual(out["url"], "/media/generated/f1.svg")
        self.assertTrue(any(e["data"].get("stage") == "render_ok" for e in trace))

    def test_engine_fallback_chain_then_structured_failure(self):
        attempts = []

        async def bad_render(kind, code):
            attempts.append(kind)
            raise RuntimeError("compile failed")

        async def fake_llm(spec):
            return "code"

        forge = FigureForge(llm_codegen=fake_llm, render_func=bad_render,
                            engine_order=["tikz", "mermaid"], on_trace=lambda e: None)
        out = asyncio.run(forge.generate(
            {"n": 2, "sec_id": "s", "intent": "i", "kind": "auto", "caption": "c"}))
        self.assertEqual(attempts, ["tikz", "mermaid"])   # 换引擎重试
        self.assertIsNone(out["url"])
        self.assertEqual(out["status"], "failed")          # 结构化失败，不抛异常

    def test_malformed_spec_rejected(self):
        forge = FigureForge(llm_codegen=None, render_func=None, on_trace=lambda e: None)
        with self.assertRaises(ValueError):
            asyncio.run(forge.generate({"n": 3}))


if __name__ == "__main__":
    unittest.main()
```

**Step 2:** 跑 → FAIL

**Step 3: 实现** `FigureForge.generate(spec)`：校验 spec（`n/sec_id/intent/kind/caption` 必填，`kind ∈ {auto,tikz,mermaid,manim,image}`）；`auto` 按 `engine_order`（默认 `["mermaid","tikz"]`，image/manimpreset 由 preset 决定是否加入）；LLM codegen prompt 注册 `figure.spec.v1`（契约测试并入 Task 5 文件）；渲染：mermaid → 服务端渲染 SVG（优先复用 `static_render.py` 能力，否则 mermaid-cli 进 latex-sandbox 容器）；tikz → latex-sandbox 编译 PDF→SVG；产物发布 generated media 目录取 URL；每阶段发 `figure_trace`（`codegen`/`render_attempt`/`render_ok`/`render_fail`）；**异步集成**：pipeline 的 FILL 阶段并发启动 figure 任务，`[[FIG:n]]` 回填发生在 ASSEMBLE；`status=failed` → 汇编器收到 `{"url": None, "fallback": "table"}` 时由主 LLM 把图位改写为表格/文字并修正引用（进 REVISE todos），兜底说明不进正文。

**Step 4:** 跑 → 3 passed

**Step 5: Commit** `feat(study-materials): add figure-forge async generator with engine fallback and trace`

---

## Phase 4: 全链路 trace 与前端

### Task 11: 后端事件规范化与全量回放端点

**Files:**
- Modify: `backend/generation/study_materials/orchestrator.py`（回读 `:115-149` 追赶压缩与 `:998` stream；压缩逻辑加事件类型白名单，新 trace 类型不折叠、且压缩仅作用于实时追赶）
- Modify: `backend/api/study_materials.py`（回读 `:289` stream 端点；新增 `GET /api/study-materials/tasks/{id}/trace?after_seq=N&limit=M` 全量分页，**不压缩**，上限如 limit≤500）
- Test: `backend/tests/test_study_materials_trace_api.py`

**Step 1: 失败测试**：构造含 900+ `thinking_delta` 的任务事件 → `stream` 追赶仍压缩（现状行为保留），`trace` 端点逐页返回全部事件且每条含 `agent_path`；未知任务 404。

**Step 2:** 跑 → FAIL

**Step 3: 实现**：压缩白名单加 `{"note_write","todo_update","figure_trace","section_fill"}`（永不折叠）；`trace` 端点直接从事件溯源存储按 seq 过滤分页，响应 `{events: [...], next_after_seq, has_more}`；事件骨架保留/TTL 清理留配置项 `STUDY_MATERIALS_TRACE_TTL_S`（默认 0=不清理，本任务只留开关不做清理器）。

**Step 4:** 跑新测试 + `test_study_materials_stream_compact.py` 无回归

**Step 5: Commit** `feat(study-materials): add uncompacted full-trace paging endpoint and compaction whitelist`

### Task 12: 前端过程面板与双栏

**Files:**
- Modify: `frontend/src/features/study-materials/streaming/contract.ts`（回读现有事件解码，约 `:280` 子代理契约一带；新增 `thinking_delta`/`note_write`/`todo_update`/`figure_trace`/`section_fill` 解码，`agentPath` 字段）
- Modify: `frontend/src/features/study-materials/model/reducer.ts`（新增 `todos`、`trace`（按 agentPath 分组的嵌套时间线）、`figures` 状态切片）
- Create: `frontend/src/features/study-materials/ui/process-panel.tsx`（左栏：TODO 清单实时勾选 + 嵌套时间线：思考块折叠/工具调用卡/笔记落笔/子 AI 泳道；复用 chat 域 `tool-step.tsx`/`iteration-timeline.tsx` 视觉语言，回读 `frontend/src/features/chat/ui/`）
- Modify: `frontend/src/features/study-materials/route.tsx`（双栏布局；`stage-progress.tsx` 的视图推断步进器替换为真实 TODO 驱动进度；BACKBONE 快照到达即渲染骨架、`[[FILL:*]]` 显示"撰写中"灰块）
- Test: `frontend/src/features/study-materials/model/__tests__/`（reducer vitest，命名跟随现有测试约定）

**Step 1: 失败测试**（vitest：新事件解码形状、reducer 的 todo 更新、按 agentPath 嵌套分组、旧事件无 agent_path 时降级为 `main`）

**Step 2:** `cd frontend && npm run test -- study-materials` → FAIL

**Step 3: 实现**：解码器给每事件补 `agentPath ?? "main"`；reducer 维护 `todos: Map<id, Todo>`、`trace: OrderedMap<agentPath, Event[]>`（子路径 `fill:*`/`fig:*` 归嵌套泳道）；`ProcessPanel` 纯受控组件；route.tsx 双栏（过程栏固定宽 420px、可折叠）；骨架预览用现有 `text_snapshot` 渲染 + 占位符正则替换为灰块。

**Step 4:** `npm run test` 全绿 + `npm run build` + `npm run lint`；Playwright 快照若涉生成页布局变化则在本机重录（Windows `*-win32.png`）

**Step 5: Commit** `feat(study-materials): add process panel with live todos and nested agent trace`

---

## Phase 5: 质量门、评估与运行时收敛

### Task 13: 验收门新增硬门槛

**Files:**
- Modify: `backend/generation/study_materials/quality_gate.py`（回读 `:218 evaluate_acceptance` 与 `:24 PRESET_PROFILES`；author runtime 的验收追加三项检查）
- Test: `backend/tests/test_study_materials_author_gates.py`

**Step 1: 失败测试**：todos 未清零 → 拒；成稿含 `[[FILL:` → 拒；正文出现术语表外符号的定义冲突 → 记 issue；全清 → 过。

**Step 2/3:** 实现 `evaluate_author_acceptance(todos, markdown, blueprint)`，复用现有 issue 形状（`code/severity/kp`），`QUALITY_POLICY_VERSION` 升 `v3`；只在 author runtime 调用，legacy 门不动。

**Step 4:** 跑新测试 + `test_study_materials_quality_gate.py` 无回归

**Step 5: Commit** `feat(study-materials): add todo-zero, placeholder-zero, terminology gates for author runtime`

### Task 14: benchmark 增加 LLM rubric 维度

**Files:**
- Create: `backend/evals/study_materials/graders/rubric.py`（仅 `--llm-judge` 时启用，与 `aesthetics.py` 的 llm-judge 通道同模式，先回读它）
- Modify: `backend/evals/study_materials/scorecard.py`、`graders/common.py`（rubric 作为 `process_diagnostics` 之外的独立诊断维度 `W`，默认不计入总分，仅 report 展示）
- Test: `backend/tests/test_study_materials_evals.py` 追加用例

**Step 1: 失败测试**：假 judge 返回 `{coherence: 4, style: 3, misconception_authenticity: 5}` → score.json 出现 `W` 维度且不改 maturity；judge 未启用时 `W` 缺省为 null。

**Step 2/3:** 实现 rubric grader：三项 0-5 分 + 各一句理由；prompt 注册 `study.eval.rubric.v1`。

**Step 4:** `python -m backend.evals.study_materials.runner --case all --dry-run` 通过；`--regrade` 对一个既有 artifact 复评验证 W 缺省路径

**Step 5: Commit** `feat(study-materials): add llm rubric diagnostics (coherence/style/misconception) to benchmark`

### Task 15: 运行时收敛（author 设为默认）

**Files:**
- Modify: `backend/generation/study_materials/orchestrator.py:52-60`（默认 runtime 切 `author`；`legacy`/`codex` 保留为显式回退）
- Modify: `backend/agent/tools/search/web_search_knowledge_impl.py`（`STUDY_MATERIALS_WEB_DECOMPOSE` 默认翻为 False；保留开关）
- Modify: `docs/STUDY_MATERIAL_IMPROVEMENTS.md`、`docs/CONFIGURATION.md`（新 runtime、新环境变量、decompose 默认变更）
- Test: 既有全套回归

**Step 1: 失败测试**：runtime 未设置时 dispatch 到 author。

**Step 2/3:** 实现默认值翻转；`deep_research` 内嵌引擎保留但不再被任何默认路径引用（标 `@deprecated`，删除留待观察期后单独 PR）。

**Step 4:** 全量 `python -m unittest discover -s backend/tests -p "test_*.py"` + ruff

**Step 5: Commit** `feat(study-materials): make author runtime the default and disable search decompose by default`

### Task 16: 真实环境验证（需要真实模型与搜索 key）

**Step 1:** 启动后端，用 author runtime 跑 2 个 benchmark case（1 个 standard 经典主题 + 1 个 research 前沿主题）：

```bash
STUDY_MATERIALS_AGENT_RUNTIME=author python -m uvicorn backend.app:app --port 8000
python -m backend.evals.study_materials.runner --case <id> --base-url http://127.0.0.1:8000 --llm-judge
```

**Step 2: 人工核对清单**（逐条打勾，任一不过则回炉，不豁免）：

- [ ] 成稿无占位符、无兜底泄漏、有参考文献且链接可打开
- [ ] 易错点条条有出处；前沿论断经 AUDIT 处置
- [ ] 图至少按计划出现或结构化降级（正文无机器说明）
- [ ] 前端过程面板：思考流、TODO、子 AI 泳道、figure trace 全部可见；断线重连后全量回放一致
- [ ] score.json：成熟度 ≥40 且 W 三维有分；与 legacy 同 case 对比入档

**Step 3: Commit** `test(study-materials): record author-runtime real-run calibration`（结果追加到 `docs/STUDY_MATERIALS_BENCHMARK.md` 校准记录）

---

## 依赖顺序与里程碑

```
Phase 1 (T1-T4) ──┐
                  ├─→ Phase 2 (T5-T9) ─→ Phase 3 (T10) ─→ Phase 4 (T11-T12) ─→ Phase 5 (T13-T16)
                  │        （T10 可与 T8/T9 并行；T11 可在 T9 后先行）
里程碑 M1: T4 完成——检索薄封装+基建可用
里程碑 M2: T9 完成——author runtime 端到端可跑（无图、无新前端）
里程碑 M3: T12 完成——全透明过程前端可见
里程碑 M4: T16 完成——author 为默认运行时，校准入档
```

**风险备查**：T9 是全计划最大单点（状态机+接入），若超预算，先交付「无 AUDIT 轮」的 M2 再补；T10 沙箱不可用时不阻塞 M2/M3（figure 全部结构化失败即可验证兜底链）；T15 默认翻转前必须完成 T16 的真实校准。
