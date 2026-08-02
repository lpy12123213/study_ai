"""作者流水线主体（设计稿 §3-§7）：RESEARCH→BLUEPRINT→BACKBONE→FILL∥FIG→ASSEMBLE→AUDIT→ACCEPT。

主 agent（作者）驱动全程：先检索并把事实落进研究笔记，再写蓝图与全书主干；
小节正文委托 FillRunner 有界并行填充（交不出的节由作者亲自补写），配图委托
FigureForge 异步生成（失败不阻塞，移除对应 ``[[FIG:n]]`` 行并记入 quality notes）；
最后由确定性汇编器替换占位符并渲染书目。验收由 author 专用门
``quality_gate.evaluate_author_acceptance`` 决定交付终态（legacy
``evaluate_acceptance`` 仍调用一次，仅作诊断挂回 ``legacy_acceptance``）；所有 LLM/工具
调用都伴随统一 trace 事件（todo_update/note_write/section_fill/figure_trace/tool_call/
text_delta），无隐藏调用（设计稿 §9）。

失败语义：蓝图非法、主干占位符缺/多、汇编修不好、验收发现占位符残留，均以结构化
``status=failed`` 结果返回（任务层据此置 failed 终态），不向上抛未捕获异常。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union
from urllib.parse import urlsplit

from backend.generation.study_materials.author.assembler import AssemblyError, assemble
from backend.generation.study_materials.author.blueprint import Blueprint, SectionSpec
from backend.generation.study_materials.author.fill import (
    _FALLBACK_SYSTEM_PROMPT,
    FILL_PROMPT_ID,
    FillResult,
    FillRunner,
)
from backend.generation.study_materials.author.notes import NotesStore
from backend.generation.study_materials.author.todos import TodoItem, TodoList
from backend.generation.study_materials.author.trace import make_event
from backend.generation.study_materials.coverage import split_sections_by_kp
from backend.generation.study_materials.quality_gate import (
    build_acceptance_record,
    draft_hash,
    evaluate_acceptance,
    evaluate_author_acceptance,
)

BLUEPRINT_PROMPT_ID = "study.author.blueprint.v1"
BACKBONE_PROMPT_ID = "study.author.backbone.v1"
AUDIT_PROMPT_ID = "study.author.audit.v1"

SEARCH_CONCURRENCY = 3
FILL_CONCURRENCY = 3
FIG_CONCURRENCY = 3
NOTE_PAYLOAD_LIMIT = 8000  # 注入蓝图/主干 prompt 的笔记与蓝图文本上限（字符）
EXCERPT_SPAN = 1500        # backbone_excerpt 截取窗口（与 fill.EXCERPT_LIMIT 对齐）

# 骨架净化：LLM 为占位符自加的「正文占位」/「占位」空标题行（真实缺陷：残留成稿触发 lint）。
_BOGUS_PLACEHOLDER_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(?:正文)?占位\s*$", re.M)

# 注册表不可用时的最小降级 prompt（措辞关键词与注册版本保持一致）。
_FALLBACK_BLUEPRINT_PROMPT = (
    "你是严谨的自学教材总编。根据输入的主题、学科、preset 与研究笔记，为全书设计写作蓝图。\n"
    "输出 JSON 对象，字段：narrative、terminology（symbol/meaning）、sections"
    "（id/title/purpose/key_points/target_chars/difficulty/misconceptions/frontier）、"
    "figures（n/sec_id/intent/kind/caption）。易错点只能来自研究笔记中带出处的条目。"
    "figures[].kind 只能是 auto/tikz/mermaid/manim/image 之一（拿不准就用 mermaid）；"
    "difficulty 只能是 基础/应用/迁移 之一（字符串，不要用数字）。"
    "sections[].id 必须是小写字母/数字/连字符/下划线（如 sec-1、s1_definition）。"
    "sections 必须逐一覆盖每个知识点，且每节 title 包含该知识点的名称关键词。"
)
_FALLBACK_BACKBONE_PROMPT = (
    "你是严谨的自学教材作者。根据给定蓝图撰写全书骨架，输出 Markdown。"
    "首行形如 # 自学材料：<主题>，随后依次给出 meta 引用行（含学科与生成预设）、"
    "## 使用方式（建议） 小节、## 知识点目录 小节（每项为可跳转锚点链接）；"
    "正文小节用编号标题 ## N、标题。"
    "小节正文位置只留占位符 [[FILL:sec-id]]，图位留占位符 [[FIG:n]]；"
    "蓝图中每个 section 必须恰好对应一个 [[FILL:sec-id]] 占位符，不得多也不得少；"
    "占位符必须单独占一行，其前后禁止出现任何「占位」字样或仅为占位而设的标题。"
)
_FALLBACK_AUDIT_PROMPT = (
    "你是严谨的事实核查员。输入一个小节的正文与该小节的研究笔记切片，逐条核查正文中的事实性断言。\n"
    "输出 JSON 对象，字段 claims：每项含 text/verdict/fix；"
    "verdict 只能是 supported、unsupported、uncertain 之一。"
)

LlmFunc = Callable[[str, str], Union[str, Awaitable[str]]]
EmitFunc = Callable[[Dict[str, Any]], None]


@dataclass
class AuthorPipelineContext:
    """run_author_pipeline 的输入上下文。work_dir 下建 notes/ 与 todos.json。"""

    task_id: str
    topic: str
    subject: str
    work_dir: Path
    user_id: str = ""
    preset: str = "standard"
    requirements: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
    knowledge_points: List[str] = field(default_factory=list)


async def _call_llm(llm_func: LlmFunc, system: str, user: str) -> str:
    result = llm_func(system, user)
    if inspect.isawaitable(result):
        result = await result
    return str(result or "").strip()


def _render_prompt(prompt_id: str, fallback: str) -> str:
    """从 prompt 注册表取 system prompt；注册表不可用时降级为内置最小指令。"""

    try:
        from backend.llm.prompts import create_default_prompt_registry

        return create_default_prompt_registry().render(prompt_id).content
    except (ImportError, KeyError, ValueError, RuntimeError):
        return fallback


def _extract_json(text: str) -> Any:
    """从 LLM 产出中提取 JSON 载荷（容忍首尾杂讯）；失败抛 ValueError。"""

    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty LLM output")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM output is not JSON") from None
        return json.loads(raw[start:end + 1])


class _AuthorPipeline:
    def __init__(
        self,
        ctx: AuthorPipelineContext,
        *,
        llm_func: LlmFunc,
        toolbox: Any,
        emit: EmitFunc,
        forge: Any = None,
    ) -> None:
        self.ctx = ctx
        self.llm = llm_func
        self.toolbox = toolbox
        self.emit = emit
        self.forge = forge
        self.work_dir = Path(ctx.work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.notes = NotesStore(self.work_dir / "notes", on_write=self._on_note_write)
        self.todos_path = self.work_dir / "todos.json"
        self.todos = TodoList()
        self.quality_notes: List[str] = []

        seen: set = set()
        kps: List[str] = []
        for kp in ctx.knowledge_points or []:
            text = str(kp).strip()
            if text and text not in seen:
                seen.add(text)
                kps.append(text)
        if not kps and str(ctx.topic).strip():
            kps = [str(ctx.topic).strip()]
        self.knowledge_points = kps

        self.research_evidence: Dict[str, List[Dict[str, Any]]] = {}
        # 任务级来源登记：去重 URL → 顺序编号（[^n]），供 fill 内联引用与 assembler 脚注定义共用。
        self.source_registry: List[Dict[str, Any]] = []
        self._source_index: Dict[str, int] = {}
        self.blueprint: Optional[Blueprint] = None
        self.blueprint_dict: Dict[str, Any] = {}
        self._blueprint_errors: List[str] = []  # 蓝图各次校验失败详情，失败终态透出到 error.detail
        self.backbone = ""
        self.sections: Dict[str, str] = {}
        self.figures: Dict[int, Dict[str, str]] = {}
        self.references: List[Dict[str, str]] = []
        self.unsupported_claims: List[Dict[str, Any]] = []
        self.revision_attempts = 0

    # ---- trace / notes / todos plumbing ----

    def _emit(self, event_type: str, data: Dict[str, Any], *, agent_path: str = "main") -> None:
        self.emit(make_event(event_type, agent_path=agent_path, data=data))

    def _on_note_write(self, name: str, chars: int) -> None:
        self._emit("note_write", {"name": name, "chars": chars})

    def _add_todo(self, item: TodoItem) -> None:
        self.todos.items.append(item)
        self.todos.save(self.todos_path)
        self._emit("todo_update", {"todo": asdict(item)})

    def _mark(self, todo_id: str, status: str, note: str = "") -> None:
        self.todos.mark(todo_id, status, note)
        self.todos.save(self.todos_path)
        self._emit("todo_update", {"todo": asdict(self.todos.get(todo_id))})

    def _failed(self, code: str, stage: str, *, detail: str = "") -> Dict[str, Any]:
        error: Dict[str, Any] = {
            "code": code, "message": code, "stage": stage, "issues": list(self.quality_notes),
        }
        if detail:
            error["detail"] = detail
        return {
            "success": False,
            "status": "failed",
            "error": error,
            "todos": self.todos.to_json(),
            "quality_notes": list(self.quality_notes),
        }

    async def _llm_stage(self, stage: str, prompt: str, user: str, *, sec_id: str = "") -> str:
        """主 agent 的 LLM 阶段调用：前后发 tool_call 事件（无隐藏调用，设计稿 §9）。

        事件 data 形状：start ``{"tool": "llm", "stage", "status": "start"}``，
        完成带 ``"chars": len(输出)``，失败带 ``"error"``（原异常继续上抛，由调用方
        的容错路径处理）；有小节上下文时带 ``"sec_id"``。
        """

        def _data(extra: Dict[str, Any]) -> Dict[str, Any]:
            data: Dict[str, Any] = {"tool": "llm", "stage": stage}
            if sec_id:
                data["sec_id"] = sec_id
            data.update(extra)
            return data

        self._emit("tool_call", _data({"status": "start"}))
        try:
            out = await _call_llm(self.llm, prompt, user)
        except Exception as exc:
            self._emit("tool_call", _data({"error": f"{type(exc).__name__}: {exc}"}))
            raise
        self._emit("tool_call", _data({"chars": len(out)}))
        return out

    # ---- 状态机主体 ----

    async def run(self) -> Dict[str, Any]:
        await self._research()
        if await self._blueprint() is None:
            return self._failed("blueprint_invalid", "blueprint", detail=" | ".join(self._blueprint_errors))
        if await self._backbone() is None:
            return self._failed("backbone_placeholder_missing", "backbone")
        await self._fill_and_figures()
        document = await self._assemble_with_revise()
        if document is None:
            return self._failed("assemble_failed", "assemble")
        self._emit("text_delta", {"content": document})
        document = await self._audit_and_revise(document)
        if document is None:
            return self._failed("assemble_failed", "revision")
        return self._accept(document)

    async def _research(self) -> None:
        kps = self.knowledge_points
        preset = str(self.ctx.preset or "standard").strip().lower()
        deep_mode = preset in {"deep", "research"}
        self._add_todo(TodoItem(
            id="research", type="research", ref="、".join(kps),
            acceptance="每个知识点的事实与易错点查询结果落 notes/research.md",
        ))
        self._mark("research", "in_progress")
        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def _search(query: str, provider: str) -> Optional[Dict[str, Any]]:
            async with sem:
                self._emit("tool_call", {"tool": "search", "query": query, "provider": provider, "status": "start"})
                try:
                    if provider == "wikipedia":
                        result = await self.toolbox.search_wikipedia(query, n=3)
                    else:
                        result = await self.toolbox.search(query, n=5)
                except (RuntimeError, asyncio.TimeoutError) as exc:
                    self.quality_notes.append(f"search_failed:{query}:{exc}")
                    self._emit("tool_call", {
                        "tool": "search", "query": query, "provider": provider,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    return None
            rows = result.get("results") if isinstance(result, dict) else None
            urls = [
                str(row.get("url") or "").strip()
                for row in (rows if isinstance(rows, list) else [])
                if isinstance(row, dict) and str(row.get("url") or "").strip()
            ][:5]
            self._emit("tool_call", {
                "tool": "search", "query": query, "provider": provider,
                "result_count": len(rows) if isinstance(rows, list) else 0,
                "urls": urls,
            })
            return result

        async def _deep_read(url: str) -> Optional[str]:
            """深读一个来源页面：成功返回页面摘要（前 500 字）；失败记 quality note，不阻断。"""
            async with sem:
                try:
                    page = await self.toolbox.browse(url)
                except (RuntimeError, asyncio.TimeoutError) as exc:
                    self.quality_notes.append(f"deep_read_failed:{url}:{exc}")
                    self._emit("tool_call", {"tool": "browse", "url": url, "status": "error"})
                    return None
            self._emit("tool_call", {"tool": "browse", "url": url, "status": "ok"})
            text = str(page.get("text") or "").strip() if isinstance(page, dict) else ""
            return text[:500]

        async def _research_kp(kp: str) -> Dict[str, Any]:
            queries = [(f"{kp} {self.ctx.subject}".strip(), "tavily"), (f"{kp} 常见错误 误区", "tavily")]
            if deep_mode:
                queries.append((kp, "wikipedia"))
            results = await asyncio.gather(*[_search(query, provider) for query, provider in queries])
            serp_urls: List[str] = []
            for (_query, provider), result in zip(queries, results):
                if provider != "tavily" or not isinstance(result, dict):
                    continue
                rows = result.get("results")
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    url = str(row.get("url") or "").strip()
                    if url and url not in serp_urls:
                        serp_urls.append(url)
            deep_reads: List[Dict[str, str]] = []
            for url in serp_urls[: 2 if deep_mode else 1]:
                summary = await _deep_read(url)
                if summary:
                    deep_reads.append({"url": url, "summary": summary})
            return {"items": list(zip([provider for _q, provider in queries], results)), "deep_reads": deep_reads}

        outcomes = await asyncio.gather(*[_research_kp(kp) for kp in kps])

        for idx, (kp, outcome) in enumerate(zip(kps, outcomes)):
            self.notes.append("research", f"## {kp}")
            evidence: List[Dict[str, Any]] = []
            for provider, result in outcome["items"]:
                rows = result.get("results") if isinstance(result, dict) else None
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    fact = str(row.get("content") or row.get("snippet") or "").strip()
                    url = str(row.get("url") or "").strip()
                    if not fact:
                        continue
                    conf = row.get("score")
                    conf_text = f"{float(conf):.2f}" if isinstance(conf, (int, float)) and not isinstance(conf, bool) else "0.50"
                    self.notes.append("research", f"- {fact} | src: {url or '（无出处）'} | conf: {conf_text}")
                    if url:
                        self._register_source(url, str(row.get("title") or "").strip())
                    evidence.append({
                        "source_class": "wikipedia" if provider == "wikipedia" else "web_search",
                        "title": str(row.get("title") or "").strip(),
                        "snippet": fact,
                        "url": url,
                    })
            for read in outcome["deep_reads"]:
                self.notes.append("research", f"- deep_read: {read['summary']} | src: {read['url']}")
            if evidence:
                self.research_evidence.setdefault(f"kp-{idx + 1}", []).extend(evidence)
        self._write_source_registry()
        self._mark("research", "done")

    def _register_source(self, url: str, title: str = "") -> int:
        """任务级来源登记：去重 URL → 顺序编号（[^n]）；title 缺省用域名。"""

        if url in self._source_index:
            return self._source_index[url]
        n = len(self.source_registry) + 1
        self._source_index[url] = n
        self.source_registry.append({"n": n, "title": title or urlsplit(url).netloc or url, "url": url})
        return n

    def _write_source_registry(self) -> None:
        """来源登记表写到 notes/research.md 头部（fill 上下文唯一允许的 URL 形态）；facts 行保留 src: url。"""

        if not self.source_registry:
            return
        lines = ["## 来源登记表", ""]
        lines += [f"- [^{entry['n']}] {entry['title']} {entry['url']}" for entry in self.source_registry]
        content = "\n".join(lines)
        existing = self.notes.read("research")
        if existing.strip():
            content += "\n\n" + existing
        self.notes.write("research", content)

    async def _blueprint(self) -> Optional[Blueprint]:
        prompt = _render_prompt(BLUEPRINT_PROMPT_ID, _FALLBACK_BLUEPRINT_PROMPT)
        research_text = self.notes.read("research")
        user = (
            f"主题: {self.ctx.topic}\n学科: {self.ctx.subject}\npreset: {self.ctx.preset}\n"
            f"附加要求: {self.ctx.requirements or '（无）'}\n"
            f"知识点: {'、'.join(self.knowledge_points)}\n\n"
            f"## 研究笔记\n{research_text[:NOTE_PAYLOAD_LIMIT] or '（无）'}"
        )
        for attempt in (1, 2):
            raw = await self._llm_stage("blueprint", prompt, user)
            try:
                blueprint = Blueprint.from_dict(_extract_json(raw))
            except ValueError as exc:  # BlueprintError/JSONDecodeError 均为 ValueError 子类
                detail = str(exc)
                self._blueprint_errors.append(detail)
                self.quality_notes.append(f"blueprint_invalid:attempt{attempt}:{detail}")
                if attempt < 2:
                    # 重试必须把校验失败原因喂回模型（与 backbone 重试同一模式），否则同一错误必然再现。
                    self.quality_notes.append(f"blueprint_retry:{detail}")
                    user += (
                        "\n\n上次蓝图校验未通过：\n"
                        f"- {detail}\n"
                        "请修正后重新输出完整蓝图 JSON。"
                    )
                continue
            self.blueprint = blueprint
            self.blueprint_dict = asdict(blueprint)
            self.notes.write("blueprint", json.dumps(self.blueprint_dict, ensure_ascii=False, indent=2))
            self._decompose_todos()
            return blueprint
        return None

    def _decompose_todos(self) -> None:
        bp = self.blueprint
        assert bp is not None
        self._add_todo(TodoItem(
            id="backbone", type="backbone", deps=["research"],
            acceptance="蓝图中每个 section 恰好对应一个 [[FILL:id]] 占位符",
        ))
        fill_ids: List[str] = []
        for sec in bp.sections:
            tid = f"fill:{sec.id}"
            fill_ids.append(tid)
            self._add_todo(TodoItem(
                id=tid, type="fill", ref=sec.id, deps=["backbone"],
                acceptance=f"约 {sec.target_chars} 字正文，含 [EXn]/[Qn]/[An] 标签",
            ))
        for fig in bp.figures:
            self._add_todo(TodoItem(
                id=f"fig:{fig.n}", type="fig", ref=str(fig.n), deps=["backbone"],
                acceptance=fig.intent or fig.caption,
            ))
        self._add_todo(TodoItem(
            id="audit", type="audit", deps=fill_ids or ["backbone"],
            acceptance="frontier 小节逐条核查，无 unsupported 断言",
        ))
        self._add_todo(TodoItem(
            id="revision", type="revision", deps=["audit"],
            acceptance="无 unsupported 断言、无未填占位符进终稿",
        ))

    async def _backbone(self) -> Optional[str]:
        self._mark("backbone", "in_progress")
        prompt = _render_prompt(BACKBONE_PROMPT_ID, _FALLBACK_BACKBONE_PROMPT)
        user = (
            f"主题: {self.ctx.topic}\n学科: {self.ctx.subject}\n\n"
            f"## 蓝图（JSON）\n{json.dumps(self.blueprint_dict, ensure_ascii=False)[:NOTE_PAYLOAD_LIMIT]}"
        )
        for attempt in (1, 2):
            backbone = self._sanitize_backbone(await self._llm_stage("backbone", prompt, user))
            problems = self._validate_backbone(backbone)
            if not problems:
                self.backbone = backbone
                self.notes.write("backbone", backbone)
                self._emit("text_delta", {"content": backbone})  # 骨架快照，供前端早期渲染
                self._mark("backbone", "done")
                return backbone
            self.quality_notes.append(f"backbone_placeholders:attempt{attempt}:{';'.join(problems)}")
            user += (
                "\n\n上次主干占位符校验未通过：\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\n请重新输出完整主干。"
            )
        self._mark("backbone", "failed", "占位符校验失败")
        return None

    @staticmethod
    def _sanitize_backbone(backbone: str) -> str:
        """删除骨架里「正文占位」/「占位」空标题行（LLM 为占位符自加，残留成稿触发 lint）。"""

        return _BOGUS_PLACEHOLDER_HEADING_RE.sub("", str(backbone or ""))

    def _validate_backbone(self, backbone: str) -> List[str]:
        bp = self.blueprint
        assert bp is not None
        problems: List[str] = []
        for sec in bp.sections:
            count = len(re.findall(r"\[\[FILL:" + re.escape(sec.id) + r"\]\]", backbone))
            if count != 1:
                problems.append(f"小节 {sec.id} 的 [[FILL:{sec.id}]] 出现 {count} 次（应恰好 1 次）")
        for fig in bp.figures:
            count = len(re.findall(r"\[\[FIG:" + re.escape(str(fig.n)) + r"\]\]", backbone))
            if count != 1:
                problems.append(f"图 {fig.n} 的 [[FIG:{fig.n}]] 出现 {count} 次（应恰好 1 次）")
        return problems

    async def _fill_and_figures(self) -> None:
        bp = self.blueprint
        assert bp is not None
        runner = FillRunner(self.llm, on_event=self.emit)
        fill_sem = asyncio.Semaphore(FILL_CONCURRENCY)
        fig_sem = asyncio.Semaphore(FIG_CONCURRENCY)

        async def _fill_one(sec: SectionSpec) -> None:
            tid = f"fill:{sec.id}"
            self._mark(tid, "in_progress")
            async with fill_sem:
                try:
                    result: Optional[FillResult] = await runner.fill(
                        sec,
                        backbone_excerpt=self._backbone_excerpt(sec.id),
                        research_slice=self.notes.read("research"),
                        terminology=bp.terminology,
                    )
                except Exception as exc:  # noqa: BLE001 — LLM/httpx 栈错误不能经 gather 炸掉整本书，降级为作者补写
                    self.quality_notes.append(f"fill_error:{sec.id}:{type(exc).__name__}:{exc}")
                    result = None
            item = self.todos.get(tid)
            if result is not None:
                item.retries = max(0, result.attempts - 1)
                if not result.needs_author_rewrite:
                    self.sections[sec.id] = result.text
                    self._mark(tid, "done")
                    return
            # 子代理交不出或抛异常：作者用同一 fill prompt 亲自补写（计一次 retry，兜底保证没有交不出的节）。
            item.retries += 1
            try:
                text = await self._author_fill(sec, note="填充子代理多次未通过验收，请作者亲自撰写本节正文。")
            except Exception as exc:  # noqa: BLE001 — 补写也失败则该节标 failed（结构化，不抛出）
                self.quality_notes.append(f"author_fill_error:{sec.id}:{type(exc).__name__}:{exc}")
                text = ""
            if text:
                self.sections[sec.id] = text
                self._mark(tid, "done", "author_rewrite")
            else:
                self._mark(tid, "failed", "author_rewrite_empty")

        async def _fig_one(fig: Any) -> None:
            tid = f"fig:{fig.n}"
            self._mark(tid, "in_progress")
            if self.forge is None:
                self.backbone = self._strip_fig(self.backbone, fig.n)
                self.quality_notes.append(f"figure_unavailable:{fig.n}")
                self._mark(tid, "waived", "figure_forge_unavailable")
                return
            async with fig_sem:
                try:
                    out = await self.forge.generate(asdict(fig))
                except Exception as exc:  # noqa: BLE001 — 渲染/沙箱任意异常都走既有结构化失败路径，不炸掉整本书
                    out = {"url": None, "status": "failed", "error": str(exc)}
            if out.get("status") == "ok" and out.get("url"):
                self.figures[fig.n] = {"url": str(out["url"]), "caption": fig.caption}
                self._mark(tid, "done")
                return
            # 失败不阻塞：移除对应 [[FIG:n]] 行并记入 quality notes（降级省略该图）。
            self.backbone = self._strip_fig(self.backbone, fig.n)
            self.quality_notes.append(f"figure_failed:{fig.n}:{out.get('status')}")
            self._mark(tid, "waived", "figure_failed_stripped")

        await asyncio.gather(
            *[_fill_one(sec) for sec in bp.sections],
            *[_fig_one(fig) for fig in bp.figures],
        )

    def _backbone_excerpt(self, sec_id: str, *, span: int = EXCERPT_SPAN) -> str:
        marker = f"[[FILL:{sec_id}]]"
        idx = self.backbone.find(marker)
        if idx < 0:
            return ""
        half = span // 2
        return self.backbone[max(0, idx - half): idx + len(marker) + half]

    async def _author_fill(self, sec: SectionSpec, *, note: str = "", stage: str = "author_fill") -> str:
        prompt = _render_prompt(FILL_PROMPT_ID, _FALLBACK_SYSTEM_PROMPT)
        payload = FillRunner._build_user_payload(
            sec, self._backbone_excerpt(sec.id), self.notes.read("research"), self.blueprint.terminology  # noqa: SLF001
        )
        user = f"{payload}\n\n{note}" if note else payload
        return await self._llm_stage(stage, prompt, user, sec_id=sec.id)

    @staticmethod
    def _strip_fig(backbone: str, n: int) -> str:
        marker = f"[[FIG:{n}]]"
        if marker not in backbone:
            return backbone
        return "\n".join(ln for ln in backbone.splitlines() if marker not in ln)

    async def _assemble_with_revise(self) -> Optional[str]:
        # 书目直接使用任务级来源登记表（含 [^n] 编号），与 fill 内联引用一一对应。
        self.references = [dict(entry) for entry in self.source_registry]
        try:
            return assemble(self.backbone, self.sections, self.figures, self.references)
        except AssemblyError as exc:
            missing = [part.strip() for part in str(exc).split(",") if part.strip()]
            self.quality_notes.append(f"assemble_failed:{exc}")
        # REVISE 一次：缺失小节由作者补写，缺失图占位行移除；仍失败则任务 failed。
        revised = False
        for key in missing:
            if key.startswith("fig:"):
                try:
                    n = int(key[len("fig:"):])
                except ValueError:
                    continue
                self.backbone = self._strip_fig(self.backbone, n)
                self.quality_notes.append(f"figure_stripped:{n}")
                revised = True
                continue
            spec = next((s for s in self.blueprint.sections if s.id == key), None)
            if spec is None:
                continue
            try:
                text = await self._author_fill(spec, note=f"汇编缺少小节 {key} 的正文，请作者补写。")
            except Exception as exc:  # noqa: BLE001 — 与 _fill_one 同一失败矩阵：补写异常不抛出，记结构化失败
                self.quality_notes.append(f"author_fill_error:{key}:{type(exc).__name__}:{exc}")
                text = ""
            if text:
                self.sections[key] = text
                revised = True
        if not revised:
            return None
        try:
            return assemble(self.backbone, self.sections, self.figures, self.references)
        except AssemblyError as exc:
            self.quality_notes.append(f"assemble_failed_after_revise:{exc}")
            return None

    async def _audit_and_revise(self, document: str) -> Optional[str]:
        bp = self.blueprint
        assert bp is not None
        self._mark("audit", "in_progress")
        prompt = _render_prompt(AUDIT_PROMPT_ID, _FALLBACK_AUDIT_PROMPT)
        research_text = self.notes.read("research")
        unsupported: Dict[str, List[Dict[str, Any]]] = {}
        for sec in [s for s in bp.sections if s.frontier]:
            user = (
                f"## 小节正文\n{self.sections.get(sec.id, '')[:NOTE_PAYLOAD_LIMIT]}\n\n"
                f"## 研究笔记切片\n{research_text[:NOTE_PAYLOAD_LIMIT]}"
            )
            raw = await self._llm_stage("audit", prompt, user, sec_id=sec.id)
            try:
                data = _extract_json(raw)
                claims = data.get("claims") if isinstance(data, dict) else []
            except ValueError as exc:
                self.quality_notes.append(f"audit_unparseable:{sec.id}:{exc}")
                claims = []
            for claim in claims if isinstance(claims, list) else []:
                if isinstance(claim, dict) and claim.get("verdict") == "unsupported":
                    unsupported.setdefault(sec.id, []).append(claim)
        self.unsupported_claims = [claim for items in unsupported.values() for claim in items]
        self._mark("audit", "done", f"unsupported={len(self.unsupported_claims)}")

        self._mark("revision", "in_progress")
        if not unsupported:
            self._mark("revision", "waived", "no_unsupported_claims")
            return document
        # REVISE 由作者本人执行：unsupported 断言按其 fix 改写/降级/删除后重新汇编。
        self.revision_attempts += 1
        for sec_id, claims in unsupported.items():
            spec = next((s for s in bp.sections if s.id == sec_id), None)
            if spec is None:
                continue
            fixes = "\n".join(f"- {c.get('text')}: {c.get('fix')}" for c in claims)
            text = await self._author_fill(
                spec,
                note=f"以下断言无研究笔记支持，请修订（改写、降级为推断措辞或删除）：\n{fixes}",
                stage="revision",
            )
            if text:
                self.sections[sec_id] = text
        try:
            document = assemble(self.backbone, self.sections, self.figures, self.references)
        except AssemblyError as exc:
            self.quality_notes.append(f"assemble_failed_after_audit_revise:{exc}")
            self._mark("revision", "failed", str(exc))
            return None
        self._emit("text_delta", {"content": document})
        self._mark("revision", "done", f"revised_sections={len(unsupported)}")
        return document

    def _accept(self, document: str) -> Dict[str, Any]:
        bp = self.blueprint
        assert bp is not None
        plan_points = [
            {"id": f"kp-{i + 1}", "title": kp, "queries": [f"{kp} {self.ctx.subject}".strip()]}
            for i, kp in enumerate(self.knowledge_points)
        ]
        kp_titles = [p["title"] for p in plan_points]
        sections_by_kp = split_sections_by_kp(document, kp_titles) if kp_titles else {}
        coverage_map = {p["id"]: bool(str(sections_by_kp.get(p["title"]) or "").strip()) for p in plan_points}
        review = {
            "passed": not self.unsupported_claims,
            "draft_hash": draft_hash(document),
            "dimensions": {},
            "issues": [str(c.get("text") or "") for c in self.unsupported_claims],
        }
        # author 专用验收门决定交付终态：占位符残留硬失败，todos 未清零降级交付。
        report = evaluate_author_acceptance(todos=self.todos, markdown=document, blueprint=bp)
        report["draft_hash"] = review["draft_hash"]  # build_acceptance_record 需要该字段
        failed_checks = [str(check) for check in report.get("failed_checks") or []]
        if "placeholder_residual" in failed_checks:
            # 占位符残留绝不交付（真实缺陷：下划线小节 id 绕过旧 FILL_RE 后，含 [[FILL:
            # 的成稿被降级交付给读者）；与其他 _failed 终态同形状，任务层据此置 failed。
            residual = next(
                (
                    issue
                    for issue in report.get("issues") or []
                    if isinstance(issue, dict) and issue.get("code") == "placeholder_residual"
                ),
                {},
            )
            self.quality_notes.append("accept_failed:placeholder_residual")
            return self._failed(
                "placeholder_residual",
                "accept",
                detail=str(residual.get("detail") or "成稿残留未替换占位符"),
            )
        legacy_report = self._legacy_acceptance_diagnostic(plan_points, review, coverage_map, document)
        degraded = not report["passed"]
        acceptance = (
            {}
            if degraded
            else build_acceptance_record(report=report, preset=self.ctx.preset, options=self.ctx.options)
        )
        issues = list(self.quality_notes)
        if degraded:
            issues += [str(check) for check in report.get("failed_checks") or []]
        return {
            "success": True,
            "status": "ok",
            "markdown": document,
            "material": {
                "topic": self.ctx.topic,
                "subject": self.ctx.subject,
                "markdown": document,
                "iteration": self.revision_attempts + 1,
                "passed": not degraded,
                "issues": issues,
                "error": None,
            },
            "blueprint": self.blueprint_dict,
            "sections": [asdict(sec) for sec in bp.sections],
            "todos": self.todos.to_json(),
            "references": self.references,
            "audit": {
                "frontier_sections": [sec.id for sec in bp.sections if sec.frontier],
                "unsupported": self.unsupported_claims,
                "passed": not self.unsupported_claims,
            },
            "quality_notes": list(self.quality_notes),
            "quality_report": report,
            "legacy_acceptance": legacy_report,
            "review": review,
            "acceptance": acceptance,
            "degraded": degraded,
            "revision_attempts": self.revision_attempts,
            "plan": {"knowledge_points": plan_points},
            "research": self.research_evidence,
            "coverage_map": coverage_map,
        }

    def _legacy_acceptance_diagnostic(
        self,
        plan_points: List[Dict[str, Any]],
        review: Dict[str, Any],
        coverage_map: Dict[str, bool],
        document: str,
    ) -> Dict[str, Any]:
        """legacy ``evaluate_acceptance`` 仅作诊断：author 流水线没有 review.dimensions，
        该门恒定不过，故不再决定交付终态；调用本身失败也不阻断交付。"""

        gate_state = {
            "preset": self.ctx.preset,
            "plan": {"knowledge_points": plan_points},
            "research": self.research_evidence,
            "markdown": document,
            "review": review,
            "coverage_map": coverage_map,
        }
        try:
            return evaluate_acceptance(state=gate_state)
        except Exception as exc:  # noqa: BLE001 — 诊断门，失败不阻断交付
            return {"passed": None, "failed_checks": [], "error": f"{type(exc).__name__}: {exc}"}


async def run_author_pipeline(
    ctx: AuthorPipelineContext,
    *,
    llm_func: LlmFunc,
    toolbox: Any,
    emit: EmitFunc,
    forge: Any = None,
) -> Dict[str, Any]:
    """驱动作者流水线。返回结构化结果：成功 ``status=ok``，失败 ``status=failed``（不抛未捕获异常）。"""

    pipeline = _AuthorPipeline(ctx, llm_func=llm_func, toolbox=toolbox, emit=emit, forge=forge)
    return await pipeline.run()
