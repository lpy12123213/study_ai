"""作者流水线主体（设计稿 §3-§7）：SPLIT→RESEARCH→BLUEPRINT→BACKBONE→FILL∥FIG→ASSEMBLE→AUDIT→ACCEPT。

主 agent（作者）驱动全程：请求侧未给知识点时先按请求的最少/最多数量拆分主题，失败会
重试并在最终验收中显式降级；再检索并把事实落进研究笔记，然后写蓝图与全书主干；
小节正文委托 FillRunner 有界并行填充（交不出的节由作者亲自补写），配图委托
FigureForge 异步生成（失败不阻塞，移除对应 ``[[FIG:n]]`` 行并记入 quality notes）；
最后由确定性汇编器替换占位符并渲染书目。验收由 author 专用门
``quality_gate.evaluate_author_acceptance`` 决定交付终态（legacy
``evaluate_acceptance`` 仍调用一次，仅作诊断挂回 ``legacy_acceptance``）；所有 LLM/工具
调用都伴随统一 trace 事件（todo_update/note_write/section_fill/figure_trace/tool_call/
research_budget/text_delta），无隐藏调用（设计稿 §9）。

失败语义：蓝图非法、主干占位符缺/多、汇编修不好、验收发现占位符残留，均以结构化
``status=failed`` 结果返回（任务层据此置 failed 终态），不向上抛未捕获异常。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit

from backend.generation.study_materials.author.assembler import (
    AssemblyError,
    assemble,
    has_fallback_note,
    strip_fallback_notes,
)
from backend.generation.study_materials.author.blueprint import (
    DIFFICULTY_LEVELS,
    FIGURE_KINDS,
    Blueprint,
    SectionSpec,
)
from backend.generation.study_materials.author.fill import (
    _FALLBACK_SYSTEM_PROMPT,
    FILL_PROMPT_ID,
    FillResult,
    FillRunner,
    normalize_fill_output,
    remap_out_of_scope_citations,
    restore_missing_example_tag,
    source_ids_in_slice,
)
from backend.generation.study_materials.author.notes import NotesStore
from backend.generation.study_materials.author.todos import TodoItem, TodoList
from backend.generation.study_materials.author.trace import make_event
from backend.generation.study_materials.coverage import split_sections_by_kp, unmatched_kp_titles
from backend.generation.study_materials.learning_contract import (
    LearningContractRequirements,
    inspect_learning_contract,
    renumber_learning_tags_by_section,
)
from backend.generation.study_materials.quality_gate import (
    build_acceptance_record,
    draft_hash,
    evaluate_acceptance,
    evaluate_author_acceptance,
)
from backend.generation.study_materials.scope_contract import (
    parse_extension_topics,
    parse_min_knowledge_sections,
)

BLUEPRINT_PROMPT_ID = "study.author.blueprint.v1"
BACKBONE_PROMPT_ID = "study.author.backbone.v1"
AUDIT_PROMPT_ID = "study.author.audit.v1"
SPLIT_PROMPT_ID = "study.author.split.v1"
LEARNING_REPAIR_PROMPT_ID = "study.author.learning_repair.v1"
FIGURE_TABLE_PROMPT_ID = "study.author.figure_table_fallback.v1"

SEARCH_CONCURRENCY = 3
FILL_CONCURRENCY = 3       # 默认填充并发；可用环境变量 STUDY_MATERIALS_FILL_CONCURRENCY 覆盖（1-16）
FIG_CONCURRENCY = 3
LEAN_MAX_FIGURES = 3
NOTE_PAYLOAD_LIMIT = 8000  # 注入蓝图/主干 prompt 的笔记与蓝图文本上限（字符）
EXCERPT_SPAN = 1500        # backbone_excerpt 截取窗口（与 fill.EXCERPT_LIMIT 对齐）
SOURCE_REGISTRY_CAP = 25   # 来源登记表容量下限（检索即登记后防止 fill 上下文被来源清单挤占）
PER_KP_SOURCE_QUOTA = 3    # 动态登记容量：每知识点预留的最低可引来源数（防止尾部小节被饿死）
RESEARCH_CACHE_LIMIT = 200  # 检索缓存条目上限（search 与 browse 各自截断）

# 审计预筛：无引用的长事实段落达到阈值的小节才进入 LLM 审计（frontier 小节始终审计）。
AUDIT_PRESCREEN_MIN_PARAGRAPH_CHARS = 120
AUDIT_PRESCREEN_MIN_UNCITED = 2
AUDIT_EXTRA_LIMIT_LEAN = 3
AUDIT_EXTRA_LIMIT = 6

# 逐节学习闭环配额的单节上限（全书余量仍由验收后的整书补齐兜底）。
SECTION_QUESTION_QUOTA_CAP = 4
SECTION_EXAMPLE_QUOTA_CAP = 2

# 骨架净化：LLM 为占位符自加的「正文占位」/「占位」空标题行（真实缺陷：残留成稿触发 lint）。
_BOGUS_PLACEHOLDER_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(?:正文)?占位\s*$", re.M)
_FENCED_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_BACKBONE_EXAMPLE_TOKEN_RE = re.compile(r"\[\[(?:FILL:\.{3}|FIG:n)\]\]", re.IGNORECASE)
_BACKBONE_PLACEHOLDER_RE = re.compile(r"\[\[(?:FILL|FIG):[^\]\r\n]+\]\]", re.IGNORECASE)
_INSTITUTIONAL_HOST_LABELS = frozenset({"ac", "edu", "gov", "gouv", "mil"})
_INSTITUTIONAL_HOST_HINTS = (
    "archive", "archives", "museum", "musee", "university", "college",
    "academy", "institute", "library", "observatory",
)
_INSTITUTIONAL_TITLE_RE = re.compile(
    r"(?:官方|政府|国家|档案馆|博物馆|大学|学院|研究院|科学院|图书馆|"
    r"official|government|archive|museum|university|college|academy|institute|library)",
    re.IGNORECASE,
)
_CURATED_AUTHORITY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("数学", "math"), "OpenStax Khan Academy Mathcentre MathsIsFun"),
    (("物理", "physics"), "OpenStax Physics Classroom PhET NASA"),
    (("化学", "chemistry"), "OpenStax LibreTexts IUPAC RSC NIST"),
    (("生物", "biology"), "OpenStax NCBI Khan Academy LibreTexts"),
    (("地理", "geography", "climate", "earth science"), "NOAA USGS Met Office NASA"),
    (("历史", "history"), "Britannica national archives official museum"),
)

# 注册表不可用时的最小降级 prompt（措辞关键词与注册版本保持一致）。
_FALLBACK_SPLIT_PROMPT = (
    "你是严谨的自学教材结构设计助手。根据输入的主题、学科、preset、知识点数量范围"
    " min_points~max_points 与全局输出要求，"
    "把主题拆分为适合自学的知识点列表。\n"
    "输出 JSON 对象，字段：knowledge_points（知识点名称列表，字符串数组）。\n"
    "数量 min_points~max_points 个，不得超出范围；按学习顺序排列；"
    "每个知识点是独立可教学的概念点，知识点之间不重叠、不互相包含。"
    "同一公式、机制或操作的参数取值、步骤与算例必须合并到一个分类/流程知识点，"
    "不得分别占用多个名额；名额有限时优先覆盖定义与意义、成立条件、核心机制、"
    "边界与反例、易混概念辨析、综合应用。"
    "若输入列出必须逐字包含的受控拓展主题，须各自保留为独立知识点并放在高中主线之后。"
)
_FALLBACK_BLUEPRINT_PROMPT = (
    "你是严谨的自学教材总编。根据输入的主题、学科、preset 与研究笔记，为全书设计写作蓝图。\n"
    "输出 JSON 对象，字段：narrative、terminology（symbol/meaning）、sections"
    "（id/title/purpose/key_points/target_chars/difficulty/misconceptions/frontier）、"
    "figures（n/sec_id/intent/kind/caption）。易错点只能来自研究笔记中带出处的条目。"
    "figures[].kind 只能是 auto/tikz/mermaid/manim/image 之一（拿不准就用 mermaid）；"
    "difficulty 只能是 基础/应用/迁移 之一（字符串，不要用数字）。"
    "sections[].id 必须是小写字母/数字/连字符/下划线（如 sec-1、s1_definition）。"
    "sections 与输入知识点一一对应：每个输入知识点恰好对应一个 section，"
    "不得合并多个知识点为一节、不得拆分一个知识点为多节；"
    "该节 title 必须完整包含对应知识点的名称关键词。"
    "前置说明与总结由全书骨架负责，不得创建不对应知识点的额外 section。"
    "必须把主题与附加要求中的每一项明确任务逐项分配到最相关 section.key_points；"
    "时间顺序、因果中间机制、误区纠正不得遗漏；辨析/对比任务必须列出要比较双方。"
    "deep/research 资料须主动安排至少4组与主题直接相关的易混概念辨析，"
    "每组在 key_points 同时点名双方；研究笔记有足够出处时，还须分散安排至少4个互不重复的真实误区及明确纠正。"
    "受控拓展 section 的 title 必须使用精确的 [拓展:主题全名] 标记，"
    "key_points 必须要求正文给出 [高中连接]。"
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
_FALLBACK_LEARNING_REPAIR_PROMPT = (
    "你是严谨的自学教材练习总编。只输出一个可直接插入现有教材的 Markdown 补全片段。\n"
    "严格按用户给出的数量、标签和编号生成：可检验学习目标、有效前置知识、带完整步骤的例题、"
    "覆盖用户指定层级（如[基础][应用][迁移]）的自测题，以及题号一一对应且逐题含评分点的答案。"
    "不得输出代码围栏、H1、参考文献小节、脚注定义、URL 或 [[...]] 占位符；"
    "不得引入教材正文之外的新事实。"
)
_FALLBACK_FIGURE_TABLE_PROMPT = (
    "你是严谨的自学教材编辑。一张示意图渲染失败，请把该图要传达的信息改写为一个 Markdown 表格，"
    "作为学习者可见的降级替代。\n"
    "只输出一个表格：表头行、分隔行与至少两行数据；内容基于给定的配图意图、小节要点与图注，"
    "不得引入新事实。\n"
    "禁止输出代码围栏、URL、脚注、[[...]] 占位符或表格之外的说明文字。"
)

LlmFunc = Callable[[str, str], Union[str, Awaitable[str]]]
EmitFunc = Callable[[Dict[str, Any]], None]


def _source_authority_tier(url: str, title: str = "", provider: str = "") -> int:
    """Return 0 for institutional sources, 1 for curated references, else 2."""

    host = (urlsplit(str(url or "")).hostname or "").casefold()
    labels = set(host.split("."))
    if labels & _INSTITUTIONAL_HOST_LABELS or any(hint in host for hint in _INSTITUTIONAL_HOST_HINTS):
        return 0
    if _INSTITUTIONAL_TITLE_RE.search(str(title or "")):
        return 1
    if provider == "wikipedia" or host.endswith("wikipedia.org") or host.endswith("britannica.com"):
        return 1
    return 2


def _rank_search_rows(rows: Any, *, provider: str) -> List[Dict[str, Any]]:
    """Prefer institutions, then relevance, while preserving stable provider order."""

    indexed = [(index, row) for index, row in enumerate(rows or []) if isinstance(row, dict)]

    def _key(item: tuple[int, Dict[str, Any]]) -> tuple[int, float, int]:
        index, row = item
        score = row.get("score")
        relevance = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.0
        return (
            _source_authority_tier(str(row.get("url") or ""), str(row.get("title") or ""), provider),
            -relevance,
            index,
        )

    return [row for _, row in sorted(indexed, key=_key)]


def _interleave_ranked_rows(
    items: List[tuple[str, Any]],
    *,
    providers: Optional[set[str]] = None,
) -> List[tuple[str, Dict[str, Any]]]:
    """Round-robin ranked rows across query intents before a finite source cap."""

    groups: List[tuple[str, List[Dict[str, Any]]]] = []
    for provider, result in items:
        if providers is not None and provider not in providers:
            continue
        rows = result.get("results") if isinstance(result, dict) else None
        ranked = _rank_search_rows(rows, provider=provider)
        if ranked:
            groups.append((provider, ranked))
    interleaved: List[tuple[str, Dict[str, Any]]] = []
    for rank in range(max((len(rows) for _, rows in groups), default=0)):
        for provider, rows in groups:
            if rank < len(rows):
                interleaved.append((provider, rows[rank]))
    return interleaved


def _authority_search_query(knowledge_point: str, subject: str) -> str:
    """Ask for well-known primary/curated sources without hiding the topic.

    A generic Chinese ``官方 权威`` suffix mostly returns high-ranking blogs and
    aggregators.  Adding a small subject-level source vocabulary gives the
    search provider enough cross-language intent to surface textbooks and
    institutions while keeping the actual knowledge point in the query.
    """

    normalized_subject = str(subject or "").casefold()
    for keywords, hints in _CURATED_AUTHORITY_HINTS:
        if any(keyword.casefold() in normalized_subject for keyword in keywords):
            return f"{knowledge_point} {subject} 权威教材 {hints}".strip()
    return f"{knowledge_point} {subject} 官方 权威 来源 official documentation".strip()


def _task_authority_queries(topic: str, subject: str) -> tuple[str, ...]:
    """Return two real, topic-level searches for stable reference works.

    Per-knowledge-point Chinese queries are good at finding teaching examples,
    but their first page can collapse onto one provider.  Two English
    task-level queries complement those results with a textbook/institutional
    source while remaining useful evidence for the actual topic.  They replace
    two of the four supplemental Wikipedia calls in the lean budget, so the
    planned search-call count remains unchanged.
    """

    blob = f"{topic} {subject}".casefold()
    if any(term in blob for term in ("历史", "history", "法国大革命", "french revolution")):
        return (
            "site:britannica.com French Revolution causes 1789 Estates-General",
            "site:history.com French Revolution causes 1789",
        )
    if any(term in blob for term in ("化学", "chemistry")):
        return (
            "site:openstax.org chemistry equilibrium weak acid base titration",
            "site:chem.libretexts.org equilibrium acid base titration buffer",
        )
    if any(term in blob for term in ("生物", "biology")):
        return (
            "site:openstax.org biology photosynthesis cellular respiration",
            "site:khanacademy.org photosynthesis cellular respiration biology",
        )
    if any(term in blob for term in ("物理", "physics")):
        if any(term in blob for term in ("电路", "电流", "电压", "内阻", "circuit")):
            return (
                "site:openstax.org physics electric circuits voltage current resistance",
                "site:physicsclassroom.com electric circuits voltage current resistance",
            )
        return (
            "site:openstax.org physics projectile motion mechanical energy",
            "site:physicsclassroom.com projectile motion mechanical energy",
        )
    if any(term in blob for term in ("地理", "geography", "季风", "monsoon")):
        return (
            "site:noaa.gov monsoon water cycle precipitation climate",
            "site:usgs.gov urban runoff infiltration flood hydrograph",
        )
    if any(term in blob for term in ("数学", "math")):
        if any(term in blob for term in (
            "条件概率", "贝叶斯", "筛查", "诊断", "灵敏度", "特异度", "roc", "probability", "bayes",
        )):
            return (
                "site:openstax.org introductory statistics probability Bayes theorem",
                "site:cdc.gov diagnostic test sensitivity specificity screening",
            )
        return (
            "site:openstax.org calculus derivatives extrema optimization",
            "site:khanacademy.org calculus derivatives extrema optimization",
        )
    return ()


def _evenly_spaced_indexes(count: int, limit: int) -> set[int]:
    """Pick at most ``limit`` deterministic indexes while retaining both ends."""

    count = max(0, int(count))
    limit = max(0, min(int(limit), count))
    if limit == 0:
        return set()
    if limit == 1:
        return {0}
    return {round(slot * (count - 1) / (limit - 1)) for slot in range(limit)}


def _distribute_section_quota(total: int, count: int, cap: int) -> List[int]:
    """Distribute a whole-book quota exactly across sections, up to a per-section cap.

    The previous ceil-per-section calculation duplicated the remainder into every
    section (12 questions over 10 sections became 20).  Keep the total exact and
    spread remainder-bearing sections across the book so examples do not cluster
    only at the beginning.  Any amount above ``cap * count`` remains for the
    whole-book learning-contract repair.
    """

    count = max(0, int(count))
    cap = max(0, int(cap))
    if count == 0 or cap == 0:
        return [0] * count
    deliverable = min(max(0, int(total)), cap * count)
    base, remainder = divmod(deliverable, count)
    extras = _evenly_spaced_indexes(count, remainder)
    return [min(cap, base + (1 if index in extras else 0)) for index in range(count)]


def _fill_concurrency() -> int:
    """填充并发度：默认 FILL_CONCURRENCY，环境变量 STUDY_MATERIALS_FILL_CONCURRENCY 覆盖（1-16）。"""

    raw = os.environ.get("STUDY_MATERIALS_FILL_CONCURRENCY", "").strip()
    try:
        value = int(raw)
    except ValueError:
        value = FILL_CONCURRENCY
    return max(1, min(value, 16))


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


_DIFFICULTY_ALIASES = {
    "1": "基础", "basic": "基础", "easy": "基础", "beginner": "基础", "foundation": "基础",
    "2": "应用", "application": "应用", "applied": "应用", "medium": "应用", "intermediate": "应用",
    "3": "迁移", "transfer": "迁移", "advanced": "迁移", "hard": "迁移",
}
_SECTION_ID_INVALID_CHAR_RE = re.compile(r"[^a-z0-9_-]+")


def _repair_blueprint_payload(data: Any) -> Tuple[Any, List[str]]:
    """蓝图 JSON 的机械形状修复（重试前移：省一次全量 LLM 重试）。

    只修不改语义、可确定性判定的字段形状：section id 字符集/去重、难度别名、
    数字字符串/浮点、figure kind 缺省（文档承诺"拿不准就用 mermaid"）、
    figure.sec_id 随 id 重写同步。语义缺陷（缺字段、kp 不覆盖）仍走校验重试。
    返回 (data, repairs)；repairs 非空时调用方记 quality note。
    """

    repairs: List[str] = []
    if not isinstance(data, dict):
        return data, repairs
    sections = data.get("sections")
    id_map: Dict[str, str] = {}
    seen_ids: set = set()
    if isinstance(sections, list):
        for index, sec in enumerate(sections):
            if not isinstance(sec, dict):
                continue
            raw_id = sec.get("id")
            if isinstance(raw_id, str) and raw_id.strip():
                normalized = _SECTION_ID_INVALID_CHAR_RE.sub("-", raw_id.strip().lower()).strip("-_")
                if not normalized:
                    normalized = f"sec-{index + 1}"
                candidate = normalized
                suffix = 2
                while candidate in seen_ids:
                    candidate = f"{normalized}-{suffix}"
                    suffix += 1
                if candidate != raw_id:
                    repairs.append(f"section_id:{raw_id}->{candidate}")
                    id_map[raw_id] = candidate
                    sec["id"] = candidate
                seen_ids.add(candidate)
            difficulty = sec.get("difficulty")
            if difficulty is not None and str(difficulty).strip() not in DIFFICULTY_LEVELS:
                key = str(difficulty).strip().casefold()
                if isinstance(difficulty, (int, float)) and not isinstance(difficulty, bool):
                    key = str(int(difficulty))
                mapped = _DIFFICULTY_ALIASES.get(key)
                if mapped:
                    repairs.append(f"difficulty:{difficulty}->{mapped}")
                    sec["difficulty"] = mapped
            target = sec.get("target_chars")
            if isinstance(target, str) and target.strip().isdigit():
                sec["target_chars"] = int(target.strip())
                repairs.append(f"target_chars:{target}")
            elif isinstance(target, float) and not isinstance(target, bool) and target > 0:
                sec["target_chars"] = int(round(target))
                repairs.append(f"target_chars:{target}")
    figures = data.get("figures")
    if isinstance(figures, list):
        for index, fig in enumerate(figures):
            if not isinstance(fig, dict):
                continue
            kind = fig.get("kind")
            if not (isinstance(kind, str) and kind in FIGURE_KINDS):
                repairs.append(f"figure_kind:{kind}->mermaid")
                fig["kind"] = "mermaid"
            n = fig.get("n")
            if isinstance(n, str) and n.strip().isdigit():
                fig["n"] = int(n.strip())
                repairs.append(f"figure_n:{n}")
            elif isinstance(n, float) and not isinstance(n, bool) and float(n).is_integer():
                fig["n"] = int(n)
                repairs.append(f"figure_n:{n}")
            sec_id = fig.get("sec_id")
            if isinstance(sec_id, str) and sec_id in id_map:
                fig["sec_id"] = id_map[sec_id]
    return data, repairs


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
        self.extension_topics = parse_extension_topics(ctx.requirements)
        self.min_knowledge_sections = parse_min_knowledge_sections(ctx.requirements)

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
        # 登记容量在 _research 按知识点数动态抬高（下限 SOURCE_REGISTRY_CAP）。
        self._registry_cap = SOURCE_REGISTRY_CAP
        # 阶段耗时（秒）：随 progress 事件透出，并进入终态 result，供成本定位。
        self.stage_timings: Dict[str, float] = {}
        self._stage_clock = time.monotonic()
        # 检索缓存：同任务重试/修复时避免重复外呼（work_dir 内落盘）。
        self._research_cache_path = self.work_dir / "research_cache.json"
        self._research_cache = self._load_research_cache()
        self.blueprint: Optional[Blueprint] = None
        self.blueprint_dict: Dict[str, Any] = {}
        self._blueprint_errors: List[str] = []  # 蓝图各次校验失败详情，失败终态透出到 error.detail
        self.backbone = ""
        self.sections: Dict[str, str] = {}
        self.figures: Dict[int, Dict[str, str]] = {}
        self.references: List[Dict[str, str]] = []
        self.unsupported_claims: List[Dict[str, Any]] = []
        self._fill_issues: Dict[str, List[str]] = {}
        self.revision_attempts = 0
        self.learning_repair_attempts = 0
        self._last_assembly_error = ""

    # ---- trace / notes / todos plumbing ----

    def _emit(self, event_type: str, data: Dict[str, Any], *, agent_path: str = "main") -> None:
        self.emit(make_event(event_type, agent_path=agent_path, data=data))

    def _progress(self, progress: float, stage: str) -> None:
        """进度事件 + 阶段耗时打点（距上一个阶段边界的墙钟秒数）。"""

        now = time.monotonic()
        self.stage_timings[stage] = round(now - self._stage_clock, 3)
        self._stage_clock = now
        self._emit("progress", {"progress": progress, "stage": stage, "elapsed_s": self.stage_timings[stage]})

    def _load_research_cache(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self._research_cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"search": {}, "browse": {}}
        search = data.get("search") if isinstance(data, dict) else None
        browse = data.get("browse") if isinstance(data, dict) else None
        return {
            "search": dict(search) if isinstance(search, dict) else {},
            "browse": dict(browse) if isinstance(browse, dict) else {},
        }

    def _save_research_cache(self) -> None:
        payload = {
            "search": dict(list(self._research_cache["search"].items())[-RESEARCH_CACHE_LIMIT:]),
            "browse": dict(list(self._research_cache["browse"].items())[-RESEARCH_CACHE_LIMIT:]),
        }
        try:
            self._research_cache_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            self.quality_notes.append("research_cache_write_failed")

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
            "stage_timings": dict(self.stage_timings),
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
        fixture_dir = self._research_fixture_dir()
        if fixture_dir:
            # 撰写阶段评测：研究由夹具注入，跳过拆分与检索（不烧检索配额与拆分调用）。
            fixture_error = self._apply_research_fixture(fixture_dir)
            if fixture_error:
                return self._failed("research_fixture_invalid", "research", detail=fixture_error)
            self._progress(20.0, "research")
        else:
            await self._decompose_kps()
            self._progress(5.0, "split")
            await self._research()
            self._progress(20.0, "research")
        if self._benchmark_stage() == "research":
            # 检索阶段评测：落盘研究快照后即终态，不进入撰写（不烧撰写 token）。
            return self._finish_research_stage()
        if await self._blueprint() is None:
            return self._failed("blueprint_invalid", "blueprint", detail=" | ".join(self._blueprint_errors))
        self._progress(30.0, "blueprint")
        if await self._backbone() is None:
            return self._failed("backbone_placeholder_missing", "backbone")
        self._progress(38.0, "backbone")
        await self._fill_and_figures()
        self._progress(75.0, "fill")
        document = await self._assemble_with_revise()
        if document is None:
            return self._failed("assemble_failed", "assemble", detail=self._last_assembly_error)
        self._progress(82.0, "assemble")
        self._emit("text_delta", {"content": document})
        document = await self._audit_and_revise(document)
        if document is None:
            return self._failed("assemble_failed", "revision", detail=self._last_assembly_error)
        self._progress(90.0, "revision")
        document = await self._ensure_learning_contract(document)
        self._progress(96.0, "accept")
        return self._accept(document)

    def _needs_kp_split(self) -> bool:
        """请求侧未给知识点时才拆分；编排层把整段 query 兜底包装成单个“知识点”
        （== topic）视同未给（真实缺陷：benchmark 不给知识点时全程只有 1 个 kp 的检索量）。"""

        provided = [str(kp).strip() for kp in (self.ctx.knowledge_points or []) if str(kp).strip()]
        if not provided:
            return True
        return provided == [str(self.ctx.topic).strip()]

    def _max_points(self) -> int:
        """拆分数量上限：读 ctx.options["max_points"]（请求契约 1-15），缺省 6。

        请求同时写明「至少 N 个知识点小节」且 N 高于 max_points 时，请求自相矛盾；
        取学习者可见的输出协议（N）作为有效上限（仍受 API 上限 15 封顶），
        否则拆分永远够不到成稿协议，交付必然降级。
        """

        raw = self.ctx.options.get("max_points") if isinstance(self.ctx.options, dict) else None
        try:
            value = int(raw) if raw is not None else 6
        except (TypeError, ValueError):
            value = 6
        value = max(1, min(value, 15))
        if self.min_knowledge_sections > value:
            value = min(self.min_knowledge_sections, 15)
        return value

    def _research_budget(self) -> str:
        raw = str(self.ctx.options.get("research_budget") or "balanced").strip().lower()
        return raw if raw in {"lean", "balanced"} else "balanced"

    def _benchmark_stage(self) -> str:
        """阶段评测模式（benchmark 专用）：目前只支持 research（跑到检索为止）。"""

        raw = str(self.ctx.options.get("benchmark_stage") or "").strip().lower()
        return raw if raw == "research" else ""

    def _research_fixture_dir(self) -> str:
        return str(self.ctx.options.get("research_fixture_dir") or "").strip()

    def _apply_research_fixture(self, fixture_dir: str) -> str:
        """从研究快照夹具注入知识点/笔记/来源登记表；返回错误详情（空串=成功）。

        夹具配置错误必须硬失败而不是回退真实检索：阶段评测的目的就是不烧检索，
        静默回退会花掉本想省下的配额且让评测口径失真。
        """

        base = Path(fixture_dir)
        try:
            kps_raw = json.loads((base / "knowledge_points.json").read_text(encoding="utf-8"))
            research_md = (base / "research.md").read_text(encoding="utf-8")
            registry_raw = json.loads((base / "source_registry.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"{type(exc).__name__}: {exc}"
        kps = [str(kp).strip() for kp in kps_raw if str(kp).strip()] if isinstance(kps_raw, list) else []
        if not kps:
            return "knowledge_points.json 必须是非空字符串数组"
        if not isinstance(registry_raw, list):
            return "source_registry.json 必须是数组"
        self.knowledge_points = list(dict.fromkeys(kps))
        self.notes.write("research", research_md)
        entries = sorted(
            (entry for entry in registry_raw if isinstance(entry, dict)),
            key=lambda entry: int(entry.get("n") or 0),
        )
        self.source_registry = []
        self._source_index = {}
        self._registry_cap = max(
            SOURCE_REGISTRY_CAP,
            len(entries),
            PER_KP_SOURCE_QUOTA * len(self.knowledge_points),
        )
        for entry in entries:
            self._register_source(str(entry.get("url") or ""), str(entry.get("title") or ""))
        try:
            evidence_raw = json.loads((base / "research_evidence.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            evidence_raw = {}
        if isinstance(evidence_raw, dict):
            self.research_evidence = {
                str(key): list(items)
                for key, items in evidence_raw.items()
                if isinstance(items, list)
            }
        self._add_todo(TodoItem(
            id="research", type="research", ref="、".join(self.knowledge_points),
            acceptance="研究夹具注入（阶段评测），无真实检索",
        ))
        self._mark("research", "done", "fixture")
        self.quality_notes.append(f"research_fixture_used:{base.name}")
        return ""

    def _finish_research_stage(self) -> Dict[str, Any]:
        """检索阶段评测终态：把研究产物落盘为可复用快照，返回结构化研究报告。"""

        snapshot_dir = self.work_dir / "research_snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        research_md = self.notes.read("research")
        (snapshot_dir / "knowledge_points.json").write_text(
            json.dumps(self.knowledge_points, ensure_ascii=False, indent=1), encoding="utf-8",
        )
        (snapshot_dir / "research.md").write_text(research_md, encoding="utf-8")
        (snapshot_dir / "source_registry.json").write_text(
            json.dumps(self.source_registry, ensure_ascii=False, indent=1), encoding="utf-8",
        )
        (snapshot_dir / "research_evidence.json").write_text(
            json.dumps(self.research_evidence, ensure_ascii=False), encoding="utf-8",
        )
        report = {
            "knowledge_points": list(self.knowledge_points),
            "unique_sources": len(self.source_registry),
            "source_urls": [str(entry.get("url") or "") for entry in self.source_registry],
            "evidence_kp_count": sum(1 for items in self.research_evidence.values() if items),
            "notes_chars": len(research_md),
            "snapshot_dir": str(snapshot_dir),
        }
        self._emit("research_report", dict(report))
        return {
            "success": True,
            "status": "ok",
            "stage": "research",
            "research_report": report,
            "todos": self.todos.to_json(),
            "quality_notes": list(self.quality_notes),
            "stage_timings": dict(self.stage_timings),
        }

    def _merge_required_extension_topics(self, points: List[str], *, max_points: int) -> List[str]:
        """Reserve tail slots for exact controlled-extension topics without exceeding max_points."""

        required = self.extension_topics[:max_points]
        core = [
            str(point).strip()
            for point in points
            if str(point).strip()
            and not any(topic in str(point) for topic in required)
        ]
        merged = core[: max(0, max_points - len(required))] + required
        return list(dict.fromkeys(merged))

    def _minimum_split_points(self, *, max_points: int) -> int:
        default_minimum = min(2, max_points)
        return max(default_minimum, min(self.min_knowledge_sections, max_points))

    def _requires_learning_contract(self) -> bool:
        return bool(self.ctx.options.get("with_questions")) if isinstance(self.ctx.options, dict) else False

    def _learning_requirements(self) -> LearningContractRequirements:
        """读取请求中的显式数量；无显式契约时保持公开默认值。"""

        defaults = LearningContractRequirements()
        text = str(self.ctx.requirements or "")

        def _count(pattern: str, fallback: int) -> int:
            match = re.search(pattern, text)
            if not match:
                return fallback
            return max(1, int(match.group(1)))

        questions = _count(r"至少(\d+)道自测题", defaults.min_practice_questions)
        return LearningContractRequirements(
            min_objectives=_count(r"至少(\d+)个可检验学习目标", defaults.min_objectives),
            min_worked_examples=_count(r"至少(\d+)个带完整步骤的例题", defaults.min_worked_examples),
            min_practice_questions=questions,
            min_answered_questions=min(
                questions,
                _count(r"至少(\d+)份一一对应", defaults.min_answered_questions),
            ),
            required_levels=list(defaults.required_levels),
        )

    def _global_fill_requirements(self) -> str:
        """Keep the original learning question visible at every independent fill call."""

        parts = [f"核心学习问题（不得遗漏与本节相关的任务）：{str(self.ctx.topic).strip()}"]
        if str(self.ctx.requirements or "").strip():
            parts.append(f"输出要求：{str(self.ctx.requirements).strip()}")
        if self._requires_learning_contract():
            parts.append(
                "学习闭环分配纪律：整书学习目标、例题、自测题与答案总量由流水线统一分配；"
                "本节只执行用户载荷中的“本节学习闭环硬性配额”，不得把整书数量重复生成到每个小节；"
                "未分配或配额为 0 的标签类型本节无需生成。"
            )
        return "\n".join(parts)

    async def _decompose_kps(self) -> None:
        """SPLIT 阶段：按请求契约拆成 min_points~max_points 个知识点。

        LLM 异常或数量不足会重试一次；仍失败时先继续后续阶段，但记录 quality note，
        最终由作者验收把数量不足显式标为降级。受控拓展主题会预留在列表尾部。
        """

        max_points = self._max_points()
        if not self._needs_kp_split():
            self.knowledge_points = self._merge_required_extension_topics(
                self.knowledge_points,
                max_points=max_points,
            )
            return
        topic = str(self.ctx.topic).strip()
        min_points = self._minimum_split_points(max_points=max_points)
        prompt = _render_prompt(SPLIT_PROMPT_ID, _FALLBACK_SPLIT_PROMPT)
        user = (
            f"主题: {self.ctx.topic}\n学科: {self.ctx.subject}\n"
            f"preset: {self.ctx.preset}\nmin_points: {min_points}\nmax_points: {max_points}\n"
            f"全局输出要求: {self.ctx.requirements or '（无）'}\n"
            "拆分纪律: 同一公式、机制或操作的参数分支/步骤/算例必须合并为一个分类或流程知识点；"
            "有限名额优先覆盖定义与意义、条件、机制、边界反例、概念辨析和应用。\n"
            "必须逐字包含的受控拓展知识点: "
            + ("、".join(self.extension_topics) if self.extension_topics else "（无）")
        )
        kps: List[str] = []
        last_error = ""
        for attempt in (1, 2):
            try:
                raw = await self._llm_stage("split", prompt, user)
                data = _extract_json(raw)
                items = data.get("knowledge_points") if isinstance(data, dict) else None
                if not isinstance(items, list):
                    raise ValueError("knowledge_points is not a list")
                candidate = list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))
                if not candidate:
                    raise ValueError("knowledge_points is empty")
                candidate = self._merge_required_extension_topics(candidate, max_points=max_points)
                if len(candidate) >= len(kps):
                    kps = candidate
                if len(candidate) >= min_points:
                    break
                last_error = f"knowledge_points count {len(candidate)} < min_points {min_points}"
            except Exception as exc:  # noqa: BLE001 — 第二次失败后走显式降级，不中断整条流水线
                last_error = f"{type(exc).__name__}:{exc}"
            if attempt < 2:
                user += (
                    f"\n\n上次拆分未达标：{last_error}。"
                    f"请返回 {min_points}~{max_points} 个知识点并保留所有必需拓展主题。"
                )
        if not kps:
            kps = self._merge_required_extension_topics([topic] if topic else [], max_points=max_points)
            self.quality_notes.append(f"kp_split_fallback:{last_error or 'empty'}")
        elif len(kps) < min_points:
            self.quality_notes.append(f"kp_split_count_unmet:{len(kps)}/{min_points}:{last_error}")
        if kps:
            self.knowledge_points = kps
            self.notes.append("research", f"## 知识点拆分：{'、'.join(kps)}")

    async def _research(self) -> None:
        kps = self.knowledge_points
        preset = str(self.ctx.preset or "standard").strip().lower()
        deep_mode = preset in {"deep", "research"}
        budget = self._research_budget()
        authority_queries = (
            _task_authority_queries(self.ctx.topic, self.ctx.subject)
            if budget == "lean" and deep_mode
            else ()
        )
        # 登记容量随知识点数动态抬高：固定 25 条时前几个知识点会耗尽名额，
        # 尾部小节（含受控拓展）拿不到可引来源，只能幻觉引用或裸写断言。
        self._registry_cap = max(
            SOURCE_REGISTRY_CAP,
            PER_KP_SOURCE_QUOTA * len(kps) + len(authority_queries),
        )
        if budget == "lean":
            wikipedia_limit = max(0, 4 - len(authority_queries))
            wikipedia_indexes = _evenly_spaced_indexes(len(kps), wikipedia_limit) if deep_mode else set()
            # 一次/KP 保住证据覆盖；最低小节数是 expected KP 的 80%，据此反推
            # 最多需要的深读量，并把少量第二次深读均匀分给首尾及中间知识点。
            inferred_expected_points = (5 * self.min_knowledge_sections) // 4
            deep_read_target = min(
                2 * len(kps),
                max(len(kps), inferred_expected_points),
            )
            deep_read_quotas = [1] * len(kps)
            for index in _evenly_spaced_indexes(len(kps), deep_read_target - len(kps)):
                deep_read_quotas[index] += 1
        else:
            wikipedia_indexes = set(range(len(kps))) if deep_mode else set()
            deep_read_quotas = [2 if deep_mode else 1] * len(kps)
        budget_event = {
            "mode": budget,
            "knowledge_points": len(kps),
            "search_calls_planned": 2 * len(kps) + len(wikipedia_indexes) + len(authority_queries),
            "deep_reads_planned": sum(deep_read_quotas),
        }
        if budget == "lean":
            budget_event.update({"max_fill_sections": len(kps), "max_figures": LEAN_MAX_FIGURES})
        self._emit("research_budget", budget_event)
        self._add_todo(TodoItem(
            id="research", type="research", ref="、".join(kps),
            acceptance="每个知识点的事实与易错点查询结果落 notes/research.md",
        ))
        self._mark("research", "in_progress")
        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def _search(query: str, provider: str) -> Optional[Dict[str, Any]]:
            cache_key = f"{provider}:{query}"
            cached = self._research_cache["search"].get(cache_key)
            if isinstance(cached, dict):
                self._emit("tool_call", {
                    "tool": "search", "query": query, "provider": provider, "status": "cached",
                })
                return cached
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
            if isinstance(result, dict):
                self._research_cache["search"][cache_key] = result
            return result

        async def _deep_read(url: str) -> Optional[str]:
            """深读一个来源页面：成功返回页面摘要（前 500 字）；失败记 quality note，不阻断。"""
            cached = self._research_cache["browse"].get(url)
            if isinstance(cached, str) and cached:
                self._emit("tool_call", {"tool": "browse", "url": url, "status": "cached"})
                return cached
            async with sem:
                try:
                    page = await self.toolbox.browse(url)
                except (RuntimeError, asyncio.TimeoutError) as exc:
                    self.quality_notes.append(f"deep_read_failed:{url}:{exc}")
                    self._emit("tool_call", {"tool": "browse", "url": url, "status": "error"})
                    return None
            self._emit("tool_call", {"tool": "browse", "url": url, "status": "ok"})
            text = str(page.get("text") or "").strip() if isinstance(page, dict) else ""
            summary = text[:500]
            if summary:
                self._research_cache["browse"][url] = summary
            return summary

        async def _research_kp(index: int, kp: str) -> Dict[str, Any]:
            queries = [
                (_authority_search_query(kp, self.ctx.subject), "tavily"),
                (f"{kp} 常见错误 误区", "tavily"),
            ]
            if index in wikipedia_indexes:
                queries.append((kp, "wikipedia"))
            results = await asyncio.gather(*[_search(query, provider) for query, provider in queries])
            items = list(zip([provider for _query, provider in queries], results))
            serp_urls: List[str] = []
            for _provider, row in _interleave_ranked_rows(items, providers={"tavily"}):
                url = str(row.get("url") or "").strip()
                if url and url not in serp_urls:
                    serp_urls.append(url)
            deep_reads: List[Dict[str, str]] = []
            read_limit = deep_read_quotas[index]
            for url in serp_urls[:read_limit]:
                summary = await _deep_read(url)
                if summary:
                    deep_reads.append({"url": url, "summary": summary})
            return {"items": items, "deep_reads": deep_reads}

        authority_results, outcomes = await asyncio.gather(
            asyncio.gather(*[_search(query, "tavily") for query in authority_queries]),
            asyncio.gather(*[_research_kp(index, kp) for index, kp in enumerate(kps)]),
        )
        authority_items = list(zip(["tavily"] * len(authority_queries), authority_results))

        # Reserve one bibliography slot per task-level authority intent before
        # the 25-source cap is allocated round-robin across knowledge points.
        # This guarantees that a real textbook/institution source discovered by
        # the search remains visible in the delivered references.
        for provider, result in authority_items:
            rows = result.get("results") if isinstance(result, dict) else None
            for row in _rank_search_rows(rows, provider=provider):
                url = str(row.get("url") or "").strip()
                if self._register_source(url, str(row.get("title") or "").strip()) >= 0:
                    break

        # Allocate the finite bibliography registry round-robin across knowledge
        # points. Sequential registration lets the first 2-3 points consume all
        # 25 slots and leaves later sections unable to cite their own evidence.
        source_candidates: List[List[tuple[str, str]]] = []
        for outcome in outcomes:
            candidates: List[tuple[str, str]] = []
            seen_urls: set[str] = set()
            for _provider, row in _interleave_ranked_rows(outcome["items"]):
                url = str(row.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append((url, str(row.get("title") or "").strip()))
            source_candidates.append(candidates)
        for rank in range(max((len(items) for items in source_candidates), default=0)):
            for candidates in source_candidates:
                if rank < len(candidates):
                    self._register_source(*candidates[rank])

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
                    url = str(row.get("url") or "").strip()
                    # 所有检索结果都进入来源登记（即使摘要为空）；在 gather 完成后按
                    # kp/query 顺序登记，避免并发完成顺序随机挤满 25 条容量。
                    if url:
                        self._register_source(url, str(row.get("title") or "").strip())
                    fact = str(row.get("content") or row.get("snippet") or "").strip()
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
        self._save_research_cache()
        self._mark("research", "done")

    def _register_source(self, url: str, title: str = "") -> int:
        """任务级来源登记：去重 URL → 顺序编号（[^n]）；title 缺省用域名，保留首次出现的 title。
        仅接收可查证的 HTTP(S) 绝对 URL；已登记返回既有编号；达到动态容量
        （下限 SOURCE_REGISTRY_CAP，随知识点数抬高）或 URL 无效时返回 -1。"""

        url = str(url or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            return -1
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            return -1
        if url in self._source_index:
            return self._source_index[url]
        if len(self.source_registry) >= self._registry_cap:
            return -1
        n = len(self.source_registry) + 1
        self._source_index[url] = n
        self.source_registry.append({"n": n, "title": title or parsed.netloc or url, "url": url})
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

    def _research_slice_for_section(self, section: SectionSpec) -> str:
        """Return the matching KP evidence plus only its usable numbered sources."""

        research = self.notes.read("research")
        point = next(
            (kp for kp in self.knowledge_points if self._section_covers_point(section, kp)),
            "",
        )
        if not point:
            return research[:NOTE_PAYLOAD_LIMIT]
        body = str(split_sections_by_kp(research, self.knowledge_points).get(point) or "").strip()
        if not body:
            return research[:NOTE_PAYLOAD_LIMIT]
        urls = set(re.findall(r"src:\s*(https?://[^\s|]+)", body))
        sources = [entry for entry in self.source_registry if entry.get("url") in urls]
        parts: List[str] = []
        if sources:
            parts.append(
                "## 来源登记表\n\n"
                + "\n".join(
                    f"- [^{entry['n']}] {entry['title']} {entry['url']}"
                    for entry in sources
                )
            )
        parts.append(f"## {point}\n{body}")
        return "\n\n".join(parts)

    async def _blueprint(self) -> Optional[Blueprint]:
        prompt = _render_prompt(BLUEPRINT_PROMPT_ID, _FALLBACK_BLUEPRINT_PROMPT)
        research_text = self.notes.read("research")
        user = (
            f"主题: {self.ctx.topic}\n学科: {self.ctx.subject}\npreset: {self.ctx.preset}\n"
            f"附加要求: {self.ctx.requirements or '（无）'}\n"
            f"知识点: {'、'.join(self.knowledge_points)}\n\n"
            f"## 研究笔记\n{research_text[:NOTE_PAYLOAD_LIMIT] or '（无）'}"
        )
        if self._research_budget() == "lean":
            user += (
                f"\n\n轻量生成硬约束：sections 必须恰好 {len(self.knowledge_points)} 个，"
                "与知识点一一对应；前置说明和总结写入骨架，不得创建额外填充 section；"
                f"figures 最多 {LEAN_MAX_FIGURES} 个。"
            )
        for attempt in (1, 2):
            raw = await self._llm_stage("blueprint", prompt, user)
            try:
                data, repairs = _repair_blueprint_payload(_extract_json(raw))
                if repairs:
                    self.quality_notes.append(
                        f"blueprint_mechanical_repair:attempt{attempt}:" + "|".join(repairs)
                    )
                blueprint = Blueprint.from_dict(data)
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
            self._align_extension_blueprint(blueprint)
            if self._research_budget() == "lean" and len(blueprint.sections) != len(self.knowledge_points):
                detail = (
                    f"lean sections count {len(blueprint.sections)} != knowledge points "
                    f"{len(self.knowledge_points)}；不得添加前置/总结填充节"
                )
                self._blueprint_errors.append(detail)
                self.quality_notes.append(f"blueprint_section_budget:attempt{attempt}:{detail}")
                if attempt < 2:
                    user += (
                        "\n\n上次蓝图超出轻量生成预算：\n"
                        f"- {detail}\n"
                        "请修正后重新输出完整蓝图 JSON。"
                    )
                continue
            # kp 覆盖校验（与 benchmark 同源的标题归属逻辑）：每个输入 kp 必须有小节标题归属，
            # 防止 LLM 把多个 kp 合并成一节（成稿按小节标题匹配知识点时合并的 kp 归属为空）。
            uncovered = self._blueprint_kp_coverage(blueprint)
            if uncovered:
                detail = (
                    f"以下知识点未被任何小节标题覆盖：{'、'.join(uncovered)}，"
                    "请为每个知识点设独立小节且标题含其名称关键词"
                )
                self._blueprint_errors.append(detail)
                self.quality_notes.append(f"blueprint_invalid:attempt{attempt}:{detail}")
                if attempt < 2:
                    self.quality_notes.append(f"blueprint_retry:{detail}")
                    user += (
                        "\n\n上次蓝图校验未通过：\n"
                        f"- {detail}\n"
                        "请修正后重新输出完整蓝图 JSON。"
                    )
                continue
            if self._research_budget() == "lean" and len(blueprint.figures) > LEAN_MAX_FIGURES:
                original_count = len(blueprint.figures)
                selected = _evenly_spaced_indexes(original_count, LEAN_MAX_FIGURES)
                blueprint.figures = [
                    figure for index, figure in enumerate(blueprint.figures) if index in selected
                ]
                self.quality_notes.append(
                    f"blueprint_figures_trimmed:{original_count}/{LEAN_MAX_FIGURES}"
                )
            self.blueprint = blueprint
            self.blueprint_dict = asdict(blueprint)
            self.notes.write("blueprint", json.dumps(self.blueprint_dict, ensure_ascii=False, indent=2))
            self._decompose_todos()
            return blueprint
        return None

    def _blueprint_kp_coverage(self, blueprint: Blueprint) -> List[str]:
        """返回未被任何小节标题覆盖的 kp 名单。

        把蓝图 section titles 合成伪 markdown（``## {title}`` + 占位正文），复用
        benchmark 的 ``split_sections_by_kp`` 归属逻辑：前置/总结类 section 标题不含
        kp 名称关键词，自然不会顶替 kp 归属。
        """

        pseudo = "\n\n".join(f"## {sec.title}\n\n占位" for sec in blueprint.sections)
        return unmatched_kp_titles(split_sections_by_kp(pseudo, self.knowledge_points))

    @staticmethod
    def _section_covers_point(section: SectionSpec, point: str) -> bool:
        pseudo = f"## {section.title}\n\n正文"
        return bool(split_sections_by_kp(pseudo, [point]).get(point))

    def _section_for_point(self, point: str) -> Optional[SectionSpec]:
        bp = self.blueprint
        if bp is None:
            return None
        return next((sec for sec in bp.sections if self._section_covers_point(sec, point)), None)

    def _align_extension_blueprint(self, blueprint: Blueprint) -> None:
        """Make controlled extension tags and high-school connection intent structural."""

        for topic in self.extension_topics:
            section = next((sec for sec in blueprint.sections if topic in sec.title), None)
            if section is None:
                continue
            tag = f"[拓展:{topic}]"
            if tag not in section.title:
                section.title = f"{tag} {section.title}"
            if not any("[高中连接]" in point for point in section.key_points):
                section.key_points.append(
                    "[高中连接] 从高中知识推导，并说明对高中解题、实验或材料分析的具体帮助"
                )

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
            acceptance="frontier 与预筛命中的引用薄弱小节逐条核查，无 unsupported 断言",
        ))
        self._add_todo(TodoItem(
            id="revision", type="revision", deps=["audit"],
            acceptance="无 unsupported 断言、无未填占位符进终稿",
        ))
        if self._requires_learning_contract():
            self._add_todo(TodoItem(
                id="learning_contract", type="learning_contract", deps=["revision"],
                acceptance="整篇含学习目标、前置知识、带步骤例题、分层自测及逐题评分点",
            ))

    async def _backbone(self) -> Optional[str]:
        self._mark("backbone", "in_progress")
        prompt = _render_prompt(BACKBONE_PROMPT_ID, _FALLBACK_BACKBONE_PROMPT)
        user = (
            f"主题: {self.ctx.topic}\n学科: {self.ctx.subject}\n"
            f"全局输出要求: {self.ctx.requirements or '（无）'}\n\n"
            f"## 蓝图（JSON）\n{json.dumps(self.blueprint_dict, ensure_ascii=False)[:NOTE_PAYLOAD_LIMIT]}"
        )
        for attempt in (1, 2):
            backbone = self._sanitize_backbone(await self._llm_stage("backbone", prompt, user))
            backbone = self._align_backbone_headings(backbone)
            backbone = self._repair_backbone_placeholder_counts(backbone)
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
        """Remove bogus headings and de-tokenize explanatory marker examples."""

        text = _BOGUS_PLACEHOLDER_HEADING_RE.sub("", str(backbone or ""))

        def _replace_example(match: re.Match[str]) -> str:
            return "正文填充标记" if "FILL:" in match.group(0).upper() else "配图标记"

        return _BACKBONE_EXAMPLE_TOKEN_RE.sub(_replace_example, text)

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
        expected = {
            *(f"[[FILL:{sec.id}]]" for sec in bp.sections),
            *(f"[[FIG:{fig.n}]]" for fig in bp.figures),
        }
        unknown = sorted({token for token in _BACKBONE_PLACEHOLDER_RE.findall(backbone) if token not in expected})
        if unknown:
            problems.append("主干含未知占位符（不得作为说明文字或额外正文位置）：" + "、".join(unknown))
        return problems

    @staticmethod
    def _keep_one_backbone_token(text: str, token: str) -> str:
        """Keep one occurrence, preferring a placeholder on its own line."""

        matches = list(re.finditer(re.escape(token), text))
        if len(matches) <= 1:
            return text

        def _standalone(match: "re.Match[str]") -> bool:
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end < 0:
                line_end = len(text)
            return text[line_start:line_end].strip() == token

        keep = next((match for match in matches if _standalone(match)), matches[0])
        return re.sub(re.escape(token), lambda match: token if match.start() == keep.start() else "", text)

    def _repair_backbone_placeholder_counts(self, backbone: str) -> str:
        """Repair only mechanically unambiguous duplicate/missing figure tokens.

        Missing section fills still fail hard because inventing their placement
        could change the document structure. Duplicate tokens are safe to
        collapse, and a missing optional figure token has an unambiguous anchor:
        the fill placeholder for the figure's declared blueprint section.
        """

        bp = self.blueprint
        assert bp is not None
        text = str(backbone or "")

        expected_tokens = [f"[[FILL:{section.id}]]" for section in bp.sections]
        expected_tokens.extend(f"[[FIG:{figure.n}]]" for figure in bp.figures)
        for token in expected_tokens:
            count = text.count(token)
            if count <= 1:
                continue
            text = self._keep_one_backbone_token(text, token)
            note = f"backbone_placeholder_deduplicated:{token}:{count}->1"
            if note not in self.quality_notes:
                self.quality_notes.append(note)

        # Reverse insertion preserves blueprint order when several figures share
        # one section because every marker is inserted immediately after the same anchor.
        for figure in reversed(bp.figures):
            token = f"[[FIG:{figure.n}]]"
            if token in text:
                continue
            anchor = f"[[FILL:{figure.sec_id}]]"
            anchor_at = text.find(anchor)
            if anchor_at < 0:
                continue
            insert_at = anchor_at + len(anchor)
            text = text[:insert_at] + f"\n\n{token}" + text[insert_at:]
            note = f"backbone_figure_placeholder_inserted:{figure.n}:{figure.sec_id}"
            if note not in self.quality_notes:
                self.quality_notes.append(note)
        return text

    def _align_backbone_headings(self, backbone: str) -> str:
        """Insert blueprint titles before markers whose learner-visible KP heading is absent."""

        text = str(backbone or "")
        missing = unmatched_kp_titles(split_sections_by_kp(text, self.knowledge_points))
        for point in missing:
            section = self._section_for_point(point)
            if section is None:
                continue
            marker = f"[[FILL:{section.id}]]"
            if marker not in text:
                continue
            text = text.replace(marker, f"## {section.title}\n\n{marker}", 1)
            note = f"backbone_heading_inserted:{section.id}:{point}"
            if note not in self.quality_notes:
                self.quality_notes.append(note)
        return text

    async def _fill_and_figures(self) -> None:
        bp = self.blueprint
        assert bp is not None
        runner = FillRunner(
            self.llm,
            max_retries=1 if self._research_budget() == "lean" else 2,
            on_event=self.emit,
        )
        fill_sem = asyncio.Semaphore(_fill_concurrency())
        fig_sem = asyncio.Semaphore(FIG_CONCURRENCY)

        async def _fill_one(sec: SectionSpec) -> None:
            tid = f"fill:{sec.id}"
            self._mark(tid, "in_progress")
            min_questions, min_examples = self._section_learning_quotas(sec)
            async with fill_sem:
                try:
                    result: Optional[FillResult] = await runner.fill(
                        sec,
                        backbone_excerpt=self._backbone_excerpt(sec.id),
                        research_slice=self._research_slice_for_section(sec),
                        terminology=bp.terminology,
                        global_requirements=self._global_fill_requirements(),
                        required_markers=self._required_markers_for_section(sec),
                        min_questions=min_questions,
                        min_examples=min_examples,
                    )
                except Exception as exc:  # noqa: BLE001 — LLM/httpx 栈错误不能经 gather 炸掉整本书，降级为作者补写
                    self.quality_notes.append(f"fill_error:{sec.id}:{type(exc).__name__}:{exc}")
                    result = None
            item = self.todos.get(tid)
            if result is not None:
                item.retries = max(0, result.attempts - 1)
                if not result.needs_author_rewrite:
                    self.sections[sec.id] = result.text
                    self._fill_issues.pop(sec.id, None)
                    self._mark(tid, "done")
                    return
            issues = list(result.missing) if result is not None else ["填充调用异常"]
            self._fill_issues[sec.id] = issues
            # 子代理交不出或抛异常：作者用同一 fill prompt 亲自补写（计一次 retry，兜底保证没有交不出的节）。
            item.retries += 1
            try:
                issue_text = "\n".join(f"- {issue}" for issue in issues)
                async with fill_sem:
                    text = await self._author_fill(
                        sec,
                        note=(
                            "填充子代理未通过验收，请作者亲自撰写本节正文。"
                            f"\n上次填充未通过原因：\n{issue_text}"
                        ),
                    )
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
            # 失败先降级为表格替代（保信息与图表计数）；降级不可得再移除 [[FIG:n]] 行。
            if await self._figure_table_fallback(fig):
                self.quality_notes.append(f"figure_fallback_table:{fig.n}:{out.get('status')}")
                self._mark(tid, "done", "table_fallback")
                return
            self.backbone = self._strip_fig(self.backbone, fig.n)
            self.quality_notes.append(f"figure_failed:{fig.n}:{out.get('status')}")
            self._mark(tid, "waived", "figure_failed_stripped")

        await asyncio.gather(
            *[_fill_one(sec) for sec in bp.sections],
            *[_fig_one(fig) for fig in bp.figures],
        )

    def _required_markers_for_section(self, section: SectionSpec) -> List[str]:
        """本节必须逐字出现的短标记。

        只允许括号式短标签：长句结论做逐字校验会因 LaTeX/措辞改写永远失败，
        三次重试后整本书 assemble_failed（真实缺陷：一个硬编码数学结论杀死整次交付）。
        具体内容要求由 blueprint key_points 与比较语义校验承担。
        """

        markers = ["[高中连接]"] if any(topic in section.title for topic in self.extension_topics) else []
        level = self._section_required_level(section)
        if level:
            markers.append(f"[{level}]")
        return markers

    def _section_required_level(self, section: SectionSpec) -> str:
        """学习闭环层级配额的确定性轮转分配：把「全书须覆盖基础/应用/迁移」前移到逐节。"""

        if not self._requires_learning_contract() or self.blueprint is None:
            return ""
        min_questions, _ = self._section_learning_quotas(section)
        if min_questions <= 0:
            return ""
        levels = [str(level) for level in self._learning_requirements().required_levels if str(level)]
        if not levels:
            return ""
        index = next(
            (i for i, spec in enumerate(self.blueprint.sections) if spec.id == section.id),
            -1,
        )
        if index < 0:
            return ""
        return levels[index % len(levels)]

    def _section_learning_quotas(self, section: SectionSpec) -> Tuple[int, int]:
        """逐节学习闭环最低配额 (min_questions, min_examples)。

        把全书 min_practice_questions/min_worked_examples 精确分配到各节并设单节上限；
        缺口在填充时立即重试（G3 检查前移），验收后的整书补齐仅兜底余量。
        未请求练习闭环时为 (0, 0)，不改变现有行为。
        """

        if not self._requires_learning_contract() or self.blueprint is None or not self.blueprint.sections:
            return (0, 0)
        requirements = self._learning_requirements()
        count = len(self.blueprint.sections)
        index = next(
            (i for i, spec in enumerate(self.blueprint.sections) if spec.id == section.id),
            -1,
        )
        if index < 0:
            return (0, 0)
        question_quotas = _distribute_section_quota(
            requirements.min_practice_questions,
            count,
            SECTION_QUESTION_QUOTA_CAP,
        )
        example_quotas = _distribute_section_quota(
            requirements.min_worked_examples,
            count,
            SECTION_EXAMPLE_QUOTA_CAP,
        )
        return (question_quotas[index], example_quotas[index])

    def _backbone_excerpt(self, sec_id: str, *, span: int = EXCERPT_SPAN) -> str:
        marker = f"[[FILL:{sec_id}]]"
        idx = self.backbone.find(marker)
        if idx < 0:
            return ""
        half = span // 2
        return self.backbone[max(0, idx - half): idx + len(marker) + half]

    async def _author_fill(self, sec: SectionSpec, *, note: str = "", stage: str = "author_fill") -> str:
        prompt = _render_prompt(FILL_PROMPT_ID, _FALLBACK_SYSTEM_PROMPT)
        required_markers = self._required_markers_for_section(sec)
        research_slice = self._research_slice_for_section(sec)
        min_questions, min_examples = self._section_learning_quotas(sec)
        payload = FillRunner._build_user_payload(
            sec,
            self._backbone_excerpt(sec.id),
            research_slice,
            self.blueprint.terminology,
            global_requirements=self._global_fill_requirements(),
            required_markers=required_markers,
            min_questions=min_questions,
            min_examples=min_examples,
        )
        user = f"{payload}\n\n{note}" if note else payload
        text = normalize_fill_output(await self._llm_stage(stage, prompt, user, sec_id=sec.id))
        text, example_tag_inserted = restore_missing_example_tag(text)
        if example_tag_inserted:
            self.quality_notes.append(f"author_fill_example_tag_inserted:{sec.id}")
        allowed_citations = source_ids_in_slice(research_slice)
        text, citation_remaps = remap_out_of_scope_citations(text, allowed_citations)
        if citation_remaps:
            detail = ",".join(f"{old}->{new}" for old, new in citation_remaps.items())
            self.quality_notes.append(f"author_fill_citations_remapped:{sec.id}:{detail}")
        missing = FillRunner._validate(
            text,
            min(sec.target_chars * 0.5, 200.0),
            allowed_citations,
            required_markers,
            section_spec=sec,
            min_questions=min_questions,
            min_examples=min_examples,
        )
        if missing:
            self._fill_issues[sec.id] = list(missing)
            self.quality_notes.append(
                f"author_fill_invalid:{sec.id}:" + "|".join(missing)
            )
            return ""
        self._fill_issues.pop(sec.id, None)
        return text

    @staticmethod
    def _strip_fig(backbone: str, n: int) -> str:
        marker = f"[[FIG:{n}]]"
        if marker not in backbone:
            return backbone
        return "\n".join(ln for ln in backbone.splitlines() if marker not in ln)

    @staticmethod
    def _extract_markdown_table(raw: str) -> str:
        """从 LLM 产出提取纯 Markdown 表格；无合法表格或混入占位符/URL 时返回空串。"""

        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if "[[" in text or "http://" in text or "https://" in text:
            return ""
        table_lines = [line.rstrip() for line in text.splitlines() if line.strip().startswith("|")]
        if len(table_lines) < 3:
            return ""
        separator = table_lines[1].strip()
        if not re.fullmatch(r"[\s|:-]+", separator) or "---" not in separator.replace(" ", ""):
            return ""
        return "\n".join(table_lines)

    async def _figure_table_fallback(self, fig: Any) -> bool:
        """配图渲染失败时降级为表格而非直接删除。

        直接剥离 [[FIG:n]] 会同时丢掉信息和 A1 的图表计数；把配图意图改写成
        Markdown 表格保住两者。改写失败（LLM 异常/产出不是纯表格）返回 False，
        走既有剥离路径。
        """

        token = f"[[FIG:{fig.n}]]"
        if token not in self.backbone:
            return False
        section = None
        if self.blueprint is not None:
            section = next((spec for spec in self.blueprint.sections if spec.id == fig.sec_id), None)
        prompt = _render_prompt(FIGURE_TABLE_PROMPT_ID, _FALLBACK_FIGURE_TABLE_PROMPT)
        user_parts = [f"配图意图: {fig.intent}", f"图注: {fig.caption or '（无）'}"]
        if section is not None:
            user_parts.append(f"小节标题: {section.title}")
            user_parts.append(f"小节要点: {'；'.join(section.key_points)}")
        try:
            raw = await self._llm_stage(
                "figure_fallback", prompt, "\n".join(user_parts), sec_id=str(fig.sec_id),
            )
        except Exception:  # noqa: BLE001 — 降级本身失败不升级为任务失败，回退到剥离路径
            return False
        table = self._extract_markdown_table(raw)
        if not table:
            return False
        caption = f"*图 {fig.n}（表格替代）{'：' + fig.caption if fig.caption else ''}*"
        self.backbone = self.backbone.replace(token, f"{table}\n\n{caption}", 1)
        return True

    def _normalize_learning_tags(self, sections: Dict[str, str]) -> Dict[str, str]:
        """Normalize independently authored section labels in blueprint order."""

        bp = self.blueprint
        assert bp is not None
        ordered_ids = [section.id for section in bp.sections if section.id in sections]
        normalized_bodies = renumber_learning_tags_by_section([sections[section_id] for section_id in ordered_ids])
        normalized = dict(sections)
        normalized.update(dict(zip(ordered_ids, normalized_bodies)))
        return normalized

    async def _assemble_with_revise(self) -> Optional[str]:
        # 书目直接使用任务级来源登记表（含 [^n] 编号），与 fill 内联引用一一对应。
        self.references = [dict(entry) for entry in self.source_registry]
        self.sections = self._normalize_learning_tags(self.sections)
        failure: AssemblyError
        try:
            return assemble(self.backbone, self.sections, self.figures, self.references)
        except AssemblyError as exc:
            failure = exc
            self._last_assembly_error = self._assembly_error_detail(exc)
            self.quality_notes.append(f"assemble_failed:{exc}")
        # REVISE 一次：按结构化错误修复实际失败原因；仍失败才置任务 failed。
        revised = False
        fill_repairs: List[tuple[str, SectionSpec]] = []
        if failure.code == "missing_fragments":
            for key in failure.missing:
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
                fill_repairs.append((key, spec))

            repair_sem = asyncio.Semaphore(FILL_CONCURRENCY)

            async def _repair_missing(key: str, spec: SectionSpec) -> tuple[str, str, str]:
                issues = self._fill_issues.get(key) or []
                issue_text = "\n".join(f"- {issue}" for issue in issues)
                note = f"汇编缺少小节 {key} 的正文，请作者补写。"
                if issue_text:
                    note += f"\n上次填充未通过原因：\n{issue_text}"
                try:
                    async with repair_sem:
                        text = await self._author_fill(spec, note=note)
                    return key, text, ""
                except Exception as fill_exc:  # noqa: BLE001 — 补写异常转成结构化失败，不炸掉整本书
                    return key, "", f"{type(fill_exc).__name__}:{fill_exc}"

            repairs = await asyncio.gather(*[_repair_missing(key, spec) for key, spec in fill_repairs])
            for key, text, error in repairs:
                if error:
                    self.quality_notes.append(f"author_fill_error:{key}:{error}")
                if text:
                    self.sections[key] = text
                    revised = True
        elif failure.code == "fallback_leak":
            if has_fallback_note(self.backbone):
                cleaned = strip_fallback_notes(self.backbone)
                revised = cleaned != self.backbone
                self.backbone = cleaned
                if revised:
                    self.notes.write("backbone", self.backbone)
                    self.quality_notes.append("fallback_note_stripped:backbone")
            leaky_sections = [
                sec_id for sec_id, body in self.sections.items() if has_fallback_note(body)
            ]
            for sec_id in leaky_sections:
                spec = next((s for s in self.blueprint.sections if s.id == sec_id), None)
                if spec is not None:
                    try:
                        text = await self._author_fill(
                            spec,
                            note="本节含机器兜底说明，禁止交付。请从头重写为正常教材正文。",
                            stage="assembly_repair",
                        )
                    except Exception as fill_exc:  # noqa: BLE001 — 失败留在结构化终态
                        self.quality_notes.append(
                            f"assembly_repair_error:{sec_id}:{type(fill_exc).__name__}:{fill_exc}"
                        )
                        text = ""
                    if text:
                        self.sections[sec_id] = text
                        revised = True
        if not revised:
            return None
        self.sections = self._normalize_learning_tags(self.sections)
        try:
            document = assemble(self.backbone, self.sections, self.figures, self.references)
        except AssemblyError as exc:
            self._last_assembly_error = self._assembly_error_detail(exc)
            self.quality_notes.append(f"assemble_failed_after_revise:{exc}")
            return None
        self._last_assembly_error = ""
        return document

    @staticmethod
    def _assembly_error_detail(exc: AssemblyError) -> str:
        parts = [f"{exc.code}: {exc}"]
        if exc.fragment:
            parts.append(f"fragment={exc.fragment}")
        if exc.missing:
            parts.append("missing=" + ",".join(exc.missing))
        return "; ".join(parts)

    @staticmethod
    def _uncited_factual_paragraphs(text: str) -> int:
        """无内联引用的长散文段落数（确定性审计预筛信号）。

        只统计正文段落：跳过标题/引用块/表格/图片/列表/公式块与代码围栏；
        段落达到 AUDIT_PRESCREEN_MIN_PARAGRAPH_CHARS 且不含 [^n] 才计数。
        """

        prose = _FENCED_CODE_BLOCK_RE.sub("", str(text or ""))
        skip_prefixes = ("#", ">", "|", "!", "-", "*", "$$")
        count = 0
        for block in re.split(r"\n\s*\n", prose):
            block = block.strip()
            if not block or block.startswith(skip_prefixes):
                continue
            if len(block) < AUDIT_PRESCREEN_MIN_PARAGRAPH_CHARS:
                continue
            if "[^" in block:
                continue
            count += 1
        return count

    def _audit_targets(self) -> List[SectionSpec]:
        """审计对象：frontier 小节全审 + 预筛命中的普通小节（有限额）。

        原先只审 frontier，普通小节的无据断言完全逃过 G1；预筛用无引用长段落
        计数做确定性过滤，只把最可疑的小节送进 LLM 审计，控制调用量。
        """

        bp = self.blueprint
        assert bp is not None
        targets = [sec for sec in bp.sections if sec.frontier]
        flagged: List[Tuple[int, SectionSpec]] = []
        for sec in bp.sections:
            if sec.frontier:
                continue
            body = self.sections.get(sec.id) or ""
            if not body.strip():
                continue
            # 该节没有任何编号来源时，LLM 审计没有判定依据，预筛跳过。
            if not source_ids_in_slice(self._research_slice_for_section(sec)):
                continue
            uncited = self._uncited_factual_paragraphs(body)
            if uncited >= AUDIT_PRESCREEN_MIN_UNCITED:
                flagged.append((uncited, sec))
        if flagged:
            flagged.sort(key=lambda item: (-item[0], item[1].id))
            limit = AUDIT_EXTRA_LIMIT_LEAN if self._research_budget() == "lean" else AUDIT_EXTRA_LIMIT
            extras = [sec for _count, sec in flagged[:limit]]
            self.quality_notes.append("audit_prescreen_flagged:" + ",".join(sec.id for sec in extras))
            targets.extend(extras)
        return targets

    async def _audit_and_revise(self, document: str) -> Optional[str]:
        bp = self.blueprint
        assert bp is not None
        self._mark("audit", "in_progress")
        prompt = _render_prompt(AUDIT_PROMPT_ID, _FALLBACK_AUDIT_PROMPT)
        unsupported: Dict[str, List[Dict[str, Any]]] = {}
        audit_errors: List[str] = []
        for sec in self._audit_targets():
            research_text = self._research_slice_for_section(sec)
            user = (
                f"## 小节正文\n{self.sections.get(sec.id, '')[:NOTE_PAYLOAD_LIMIT]}\n\n"
                f"## 研究笔记切片\n{research_text[:NOTE_PAYLOAD_LIMIT]}"
            )
            try:
                raw = await self._llm_stage("audit", prompt, user, sec_id=sec.id)
            except Exception as exc:  # noqa: BLE001 — 保留上一份已汇编文档并显式降级
                detail = f"audit_error:{sec.id}:{type(exc).__name__}:{exc}"
                self.quality_notes.append(detail)
                audit_errors.append(detail)
                continue
            try:
                data = _extract_json(raw)
                claims = data.get("claims") if isinstance(data, dict) else []
            except ValueError as exc:
                detail = f"audit_unparseable:{sec.id}:{exc}"
                self.quality_notes.append(detail)
                audit_errors.append(detail)
                claims = []
            for claim in claims if isinstance(claims, list) else []:
                if isinstance(claim, dict) and claim.get("verdict") == "unsupported":
                    unsupported.setdefault(sec.id, []).append(claim)
        self.unsupported_claims = [claim for items in unsupported.values() for claim in items]
        if audit_errors:
            self._mark("audit", "failed", f"errors={len(audit_errors)}")
        else:
            self._mark("audit", "done", f"unsupported={len(self.unsupported_claims)}")

        self._mark("revision", "in_progress")
        if not unsupported:
            self._mark("revision", "waived", "no_unsupported_claims")
            return document
        # REVISE 是事务式的：所有目标小节均成功并重新汇编后才提交；否则回退 document。
        self.revision_attempts += 1
        candidate_sections = dict(self.sections)
        revision_errors: List[str] = []
        for sec_id, claims in unsupported.items():
            spec = next((s for s in bp.sections if s.id == sec_id), None)
            if spec is None:
                revision_errors.append(f"missing_section_spec:{sec_id}")
                continue
            fixes = "\n".join(f"- {c.get('text')}: {c.get('fix')}" for c in claims)
            try:
                text = await self._author_fill(
                    spec,
                    note=f"以下断言无研究笔记支持，请修订（改写、降级为推断措辞或删除）：\n{fixes}",
                    stage="revision",
                )
            except Exception as exc:  # noqa: BLE001 — 回退上一份已汇编文档
                detail = f"revision_error:{sec_id}:{type(exc).__name__}:{exc}"
                self.quality_notes.append(detail)
                revision_errors.append(detail)
                continue
            if text:
                candidate_sections[sec_id] = text
            else:
                revision_errors.append(f"revision_empty:{sec_id}")
        if revision_errors:
            self.quality_notes.append("revision_rolled_back:" + "|".join(revision_errors))
            self._mark("revision", "failed", "author_revision_incomplete")
            return document
        try:
            candidate_sections = self._normalize_learning_tags(candidate_sections)
            candidate = assemble(self.backbone, candidate_sections, self.figures, self.references)
        except AssemblyError as exc:
            self._last_assembly_error = self._assembly_error_detail(exc)
            self.quality_notes.append(f"assemble_failed_after_audit_revise:{exc}")
            self.quality_notes.append("revision_rolled_back:assembly_failed")
            self._mark("revision", "failed", self._last_assembly_error)
            return document
        self.sections = candidate_sections
        self._last_assembly_error = ""
        self._emit("text_delta", {"content": candidate})
        self._mark("revision", "done", f"revised_sections={len(unsupported)}")
        return candidate

    async def _ensure_learning_contract(self, document: str) -> str:
        if not self._requires_learning_contract():
            return document

        requirements = self._learning_requirements()
        initial = inspect_learning_contract(document, requirements)
        self._mark("learning_contract", "in_progress")
        if initial["passed"]:
            self._mark("learning_contract", "done", "existing_document_passed")
            return document

        prompt = _render_prompt(LEARNING_REPAIR_PROMPT_ID, _FALLBACK_LEARNING_REPAIR_PROMPT)
        ex_start = self._next_tag_id(document, "EX")
        q_start = self._next_tag_id(document, "Q")
        example_needed = max(0, requirements.min_worked_examples - int(initial["worked_examples"]))
        question_needed = max(0, requirements.min_practice_questions - int(initial["question_count"]))
        paired_needed = max(0, requirements.min_answered_questions - int(initial["paired_count"]))
        required_levels = list(requirements.required_levels) or ["基础", "应用", "迁移"]
        missing_levels = [level for level in required_levels if level not in initial["level_hits"]]
        if not initial["rubric_ok"]:
            paired_needed = max(1, paired_needed)
        new_question_count = max(question_needed, paired_needed, len(missing_levels))
        ex_ids = list(range(ex_start, ex_start + example_needed))
        q_ids = list(range(q_start, q_start + new_question_count))
        level_seed = missing_levels or required_levels
        levels = [level_seed[index % len(level_seed)] for index in range(len(q_ids))]
        outline = "\n".join(
            line for line in document.splitlines() if re.match(r"^#{1,3}\s+", line)
        )[:NOTE_PAYLOAD_LIMIT]
        missing = list(initial["missing"])

        for attempt in (1, 2):
            self.learning_repair_attempts = attempt
            user = (
                f"主题: {self.ctx.topic}\n学科: {self.ctx.subject}\n"
                f"知识点: {'、'.join(self.knowledge_points)}\n"
                f"当前缺口: {'；'.join(missing)}\n\n"
                "必须使用以下全局唯一编号，不得改号或漏号：\n"
                f"- 例题: {', '.join(f'[EX{n}]' for n in ex_ids) or '无需新增'}\n"
                f"- 自测与答案: {', '.join(f'[Q{n}]/[A{n}]' for n in q_ids) or '无需新增'}\n"
                f"- {len(q_ids)}题层级依次为: {', '.join(f'[{level}]' for level in levels)}\n\n"
                "片段必须依次包含二级标题“学习目标（补全）”“前置知识（补全）”“带步骤例题（补全）”"
                "“全书自测题（补全）”“答案与评分点（补全）”。\n"
                f"学习目标用至少{requirements.min_objectives}条列表；"
                "每个例题显式写“步骤”；每个答案显式写“评分点”。\n\n"
                f"## 现有教材目录\n{outline}"
            )
            try:
                raw = await self._llm_stage("learning_repair", prompt, user)
            except Exception as exc:  # noqa: BLE001 — 原成稿仍可降级交付
                detail = f"learning_repair_error:{type(exc).__name__}:{exc}"
                self.quality_notes.append(detail)
                missing = [detail]
                continue
            appendix = self._clean_learning_appendix(raw)
            if not appendix:
                missing = ["补全片段为空或含禁止内容"]
                self.quality_notes.append(f"learning_repair_invalid:{attempt}:{missing[0]}")
                continue
            candidate = self._insert_before_references(document, appendix)
            inspection = inspect_learning_contract(candidate, requirements)
            if inspection["passed"]:
                self.quality_notes.append(f"learning_contract_repaired:attempt={attempt}")
                self._mark("learning_contract", "done", f"repaired_attempt={attempt}")
                self._emit("text_delta", {"content": candidate})
                return candidate
            missing = list(inspection["missing"])
            self.quality_notes.append(
                f"learning_repair_invalid:{attempt}:" + "|".join(missing)
            )

        self.quality_notes.append("learning_contract_unmet:" + "|".join(missing))
        self._mark("learning_contract", "failed", "；".join(missing))
        return document

    @staticmethod
    def _next_tag_id(markdown: str, prefix: str) -> int:
        ids = [
            int(value)
            for value in re.findall(rf"\[{re.escape(prefix)}(\d+)\]", markdown, re.IGNORECASE)
        ]
        return max(ids, default=0) + 1

    @staticmethod
    def _clean_learning_appendix(raw: str) -> str:
        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        forbidden = ("```", "[[", "http://", "https://", "## 参考文献")
        footnote_definition = re.search(r"^\s*\[\^[^\]]+\]:", text, re.MULTILINE)
        if (
            not text
            or text.startswith("# ")
            or any(token in text for token in forbidden)
            or footnote_definition
        ):
            return ""
        return text

    @staticmethod
    def _insert_before_references(document: str, appendix: str) -> str:
        index = document.find("\n## 参考文献\n")
        if index < 0:
            index = document.rfind("\n---\n\n")
        if index < 0:
            index = len(document)
        prefix = document[:index].rstrip()
        suffix = document[index:].lstrip()
        return f"{prefix}\n\n{appendix.strip()}\n\n{suffix}".rstrip() + "\n"

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
        # author 专用验收门决定交付终态：占位符残留硬失败，其余未清零契约显式降级。
        learning_requirements = self._learning_requirements() if self._requires_learning_contract() else None
        report = evaluate_author_acceptance(
            todos=self.todos,
            markdown=document,
            blueprint=bp,
            learning_requirements=learning_requirements,
            knowledge_points=self.knowledge_points,
            min_knowledge_sections=self.min_knowledge_sections,
            extension_topics=self.extension_topics,
        )
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
            "learning_repair_attempts": self.learning_repair_attempts,
            "stage_timings": dict(self.stage_timings),
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
