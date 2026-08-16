"""Section fill runner (design doc §6): bounded context + acceptance loop + author fallback.

Each blueprint section is filled by a dedicated sub-LLM call that sees only a *bounded*
context pack: an excerpt of the backbone where the text attaches, a slice of the research
notes, the numbered source registry (``[^n] title url`` lines — the only URL form allowed
in the fill context), the terminology table, and the section spec. The produced text must
pass an acceptance check (length, no bare URLs / reference sections, allocated
[EXn]/[Qn]/[An] quotas, sourced misconception correction, requested comparison semantics,
and at least one resolvable ``[^n]`` marker whenever the section has usable sources);
failed attempts are retried with the missing items appended to the prompt. When retries
are exhausted the section is flagged for author rewrite instead of silently accepting bad content.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

from .blueprint import SectionSpec
from .trace import make_event

FILL_PROMPT_ID = "study.author.fill.v1"

EXCERPT_LIMIT = 1500    # backbone_excerpt 注入上限（字符）
RESEARCH_LIMIT = 4000   # research_slice 注入上限（字符）
PAYLOAD_LIMIT = 12000   # user payload 总量硬上限（字符）

# 产出验收的长度下限：min(target_chars * MIN_TARGET_RATIO, min_chars)。min_chars 作为上限
# 盖帽，避免大 target_chars 的小节对单次填充提出过长要求。
MIN_TARGET_RATIO = 0.5

_FALLBACK_SYSTEM_PROMPT = (
    "你是严谨的自学教材作者。只为指定的某一个小节撰写核心讲解正文，输出 Markdown。\n"
    "必须执行用户载荷中的全局输出要求与本节硬性标记，并写出标记要求的实际说明；"
    "要求：严格遵守给定术语符号表；仅按用户载荷中的“本节学习闭环硬性配额”生成 "
    "[EXn] 带步骤例题、[Qn] 分层自测题、[An] 答案与评分点，未列出或配额为 0 的标签类型不强制生成；"
    "若生成，三类标签各自独立编号、独占加粗行，不得合并书写；"
    "每个 [Qn] 必须标注层级（基础/应用/迁移）；[An] 答案与 [Qn] 一一对应并给出评分点，"
    "禁止用 [EXn] 充当答案标签；"
    "篇幅严格控制在本节规格目标篇幅的 80%~130%，优先删去重复解释，不得用重复题目凑字数；"
    "有来源的易错点必须先写成常见误区再明确驳正，不能只陈述正确结论；"
    "遇到区分/辨析/比较要求时必须同时点名比较双方并写出明确比较语义；"
    "数学公式用 LaTeX；在关键事实句末用 [^n] 标注来源编号，只允许使用给定来源清单里的全书固定编号；"
    "不得把本节来源从 [^1] 重新编号，必须逐字复制清单中实际给出的编号；"
    "正文禁止出现裸 URL、禁止输出参考文献小节或脚注定义；只写该小节正文。"
    "小节正文内只允许使用 ### 与 #### 标题（禁止 # 与 ##：全书标题层级由主干统一管理）；"
    "[EXn]/[Qn]/[An] 题目标签用加粗行（如 **[EX1]**）而非标题。"
)

_URL_RE = re.compile(r"https?://")
# 小节正文只允许 ###/#### 标题：# 与 ## 与骨架的全书层级冲突（真实缺陷：## [EX1] 例题 破坏层级）。
_LOW_LEVEL_HEADING_RE = re.compile(r"^#{1,2}\s", re.M)
# 来源登记表行：- [^n] title url（pipeline 写入 research.md 头部，fill 上下文里唯一允许的 URL 形态）。
_SOURCE_LINE_RE = re.compile(r"^\s*[-*+]\s*\[\^(\d+)\]\s+(?P<title>.+?)\s+(?P<url>https?://\S+)\s*$", re.M)
_SRC_URL_RE = re.compile(r"src:\s*(https?://[^\s|]+)")
_FOOTNOTE_MARK_RE = re.compile(r"\[\^(\d+)\]")
_EXAMPLE_CUE_RE = re.compile(r"(?:例题|示例|典型例|例\s*\d+)")
# 题号标签纪律（真实缺陷：**[EX1] [Q1]** 合并书写、自测题无层级、**[EX1]**（基础）
# 充当答案标签）：编号必须显式（[Q1]/[A1]），[Qn] 必须标注层级（基础/应用/迁移）。
_QUESTION_NUMBER_RE = re.compile(r"\[Q\d")
_ANSWER_NUMBER_RE = re.compile(r"\[A\d")
_QUESTION_LEVEL_RE = re.compile(r"基础|应用|迁移")
# 逐节学习闭环配额（把全书 min_practice_questions/min_worked_examples 摊到每节，
# 缺口在生成时就重试，而不是等验收后靠整书附录补救）。
_QUESTION_ID_RE = re.compile(r"\[Q(\d+)\]", re.IGNORECASE)
_ANSWER_ID_RE = re.compile(r"\[A(\d+)\]", re.IGNORECASE)
_EXAMPLE_ID_RE = re.compile(r"\[EX(\d+)\]", re.IGNORECASE)
_RUBRIC_CUE_RE = re.compile(r"评分点|得分点|采分点|评分标准")
# 解题过程线索：覆盖中文数学的常见写法（"解："、"证明"、"第一步"、"首先"等）。
# 窄词表（仅"步骤/解答/解析/推导"）在真实探针中误杀了半数小节：模型写了完整
# 解题过程但没用这几个字眼，三次重试烧尽后整本书 assemble_failed。
_WORKED_STEP_CUE_RE = re.compile(
    r"步骤|解答|解析|推导|求解|解法|证明|首先|第[一二三①②③123]\s*步|解\s*[:：]"
)
_CORRECTION_CUE_RE = re.compile(r"(?:常见误区|错误(?:在于|的是|地认为)?|不正确|并非|不是|不能|不可|混淆)")
_COMPARISON_REQUEST_RE = re.compile(r"(?:区分|辨析|对比|比较|区别|差异)", re.IGNORECASE)
_COMPARISON_CUE_RE = re.compile(
    r"(?:相比|相较|区别|差异|前者|后者|二者|两者|不能混同|不可混同|vs\.?)",
    re.IGNORECASE,
)
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_DISPLAY_MATH_DELIMITER_RE = re.compile(r"\\\[([\s\S]*?)\\\]")
_INLINE_MATH_DELIMITER_RE = re.compile(r"\\\(([\s\S]*?)\\\)")
_TOP_LEVEL_HEADING_RE = re.compile(r"^#{1,2}(?=\s)", re.MULTILINE)

LlmFunc = Callable[[str, str], Union[str, Awaitable[str]]]
EventSink = Callable[[Dict[str, Any]], None]


def normalize_fill_output(text: str) -> str:
    """Normalize mechanically repairable math/heading syntax outside code fences."""

    raw = str(text or "")

    def _normalize_segment(segment: str) -> str:
        segment = _DISPLAY_MATH_DELIMITER_RE.sub(lambda match: f"$${match.group(1)}$$", segment)
        segment = _INLINE_MATH_DELIMITER_RE.sub(lambda match: f"${match.group(1)}$", segment)
        return _TOP_LEVEL_HEADING_RE.sub("###", segment)

    parts: List[str] = []
    cursor = 0
    for match in _FENCED_CODE_RE.finditer(raw):
        parts.append(_normalize_segment(raw[cursor:match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(_normalize_segment(raw[cursor:]))
    return "".join(parts)


def _parse_source_lines(text: str) -> List[Dict[str, str]]:
    """从研究笔记切片解析来源登记表行（``- [^n] title url``）。"""

    sources: List[Dict[str, str]] = []
    for match in _SOURCE_LINE_RE.finditer(str(text or "")):
        sources.append({"n": match.group(1), "title": match.group("title").strip(), "url": match.group("url")})
    return sources


def source_ids_in_slice(research_slice: str) -> Set[str]:
    """研究笔记切片（按注入上限截断后）里可用的引用编号集合，供产出校验。"""

    return {s["n"] for s in _parse_source_lines(str(research_slice or "")[:RESEARCH_LIMIT])}


def remap_out_of_scope_citations(text: str, allowed_citation_ids: Set[str]) -> Tuple[str, Dict[str, str]]:
    """Remap hallucinated footnote numbers to this section's real source IDs.

    This is intentionally a last-resort, author-level repair rather than part of
    ordinary child-fill acceptance: the child still gets rejected and receives
    the concrete validation error first.  If the author rewrite again emits a
    number outside the bounded source pack, retain the otherwise valid section
    and map each distinct bad number deterministically across the sources that
    were actually supplied to that section.  With no supplied sources, leave
    the text untouched so unsupported citations remain a hard validation error.
    """

    allowed = {str(marker) for marker in allowed_citation_ids if str(marker).isdigit()}
    if not allowed:
        return str(text or ""), {}
    ordered = sorted(allowed, key=int)
    remapped: Dict[str, str] = {}

    def _replace(match: "re.Match[str]") -> str:
        marker = match.group(1)
        if marker in allowed:
            return match.group(0)
        replacement = remapped.setdefault(marker, ordered[len(remapped) % len(ordered)])
        return f"[^{replacement}]"

    return _FOOTNOTE_MARK_RE.sub(_replace, str(text or "")), remapped


def restore_missing_example_tag(text: str) -> Tuple[str, bool]:
    """Restore ``[EX1]`` only when an author draft already has an explicit example cue.

    The author fallback sometimes writes a complete ``例题``/``示例`` block but
    drops only the machine-readable label.  Prefixing that existing block is a
    format repair; if no unmistakable example cue exists, leave the text alone
    so the worked-example requirement remains a hard error.
    """

    raw = str(text or "")
    if "[EX" in raw:
        return raw, False
    match = _EXAMPLE_CUE_RE.search(raw)
    if match is None:
        return raw, False
    line_start = raw.rfind("\n", 0, match.start()) + 1
    return raw[:line_start] + "**[EX1]**\n" + raw[line_start:], True


@dataclass
class FillResult:
    text: str
    needs_author_rewrite: bool
    attempts: int
    missing: Tuple[str, ...] = ()


class FillRunner:
    def __init__(
        self,
        llm_func: LlmFunc,
        *,
        max_retries: int = 2,
        min_chars: int = 200,
        on_event: Optional[EventSink] = None,
    ) -> None:
        self._llm = llm_func
        self.max_retries = max(1, int(max_retries))
        self.min_chars = min_chars
        self._on_event = on_event
        self._system_prompt = self._load_system_prompt()

    @staticmethod
    def _load_system_prompt() -> str:
        """从 prompt 注册表取 fill system prompt；注册表不可用时降级为内置最小指令。"""
        try:
            from backend.llm.prompts import create_default_prompt_registry

            return create_default_prompt_registry().render(FILL_PROMPT_ID).content
        except (ImportError, KeyError, ValueError, RuntimeError):
            return _FALLBACK_SYSTEM_PROMPT

    async def fill(
        self,
        section_spec: SectionSpec,
        backbone_excerpt: str = "",
        research_slice: str = "",
        terminology: Optional[List[Dict[str, str]]] = None,
        *,
        global_requirements: str = "",
        required_markers: Optional[List[str]] = None,
        min_questions: int = 0,
        min_examples: int = 0,
    ) -> FillResult:
        markers = [str(marker).strip() for marker in (required_markers or []) if str(marker).strip()]
        payload = self._build_user_payload(
            section_spec,
            backbone_excerpt or "",
            research_slice or "",
            terminology or [],
            global_requirements=global_requirements,
            required_markers=markers,
            min_questions=min_questions,
            min_examples=min_examples,
        )
        required_chars = min(section_spec.target_chars * MIN_TARGET_RATIO, float(self.min_chars))
        allowed_citations = source_ids_in_slice(research_slice or "")
        missing: List[str] = []
        for attempt in range(1, self.max_retries + 1):
            self._emit(section_spec.id, "start")
            user = payload
            if missing:
                user += "\n\n上次产出未通过验收，请补全/修正以下缺失项：\n" + "\n".join(f"- {m}" for m in missing)
            text = normalize_fill_output(await self._call_llm(user))
            missing = self._validate(
                text,
                required_chars,
                allowed_citations,
                markers,
                section_spec=section_spec,
                min_questions=min_questions,
                min_examples=min_examples,
            )
            if not missing:
                self._emit(section_spec.id, "ok")
                return FillResult(text=text, needs_author_rewrite=False, attempts=attempt)
            self._emit(
                section_spec.id,
                "retry" if attempt < self.max_retries else "failed",
                missing=missing,
            )
        return FillResult(
            text="",
            needs_author_rewrite=True,
            attempts=self.max_retries,
            missing=tuple(missing),
        )

    async def _call_llm(self, user: str) -> str:
        result = self._llm(self._system_prompt, user)
        if inspect.isawaitable(result):
            result = await result
        return str(result or "").strip()

    def _emit(self, sec_id: str, status: str, *, missing: Optional[List[str]] = None) -> None:
        if self._on_event is None:
            return
        data: Dict[str, Any] = {"sec_id": sec_id, "status": status}
        if missing:
            data["missing"] = list(missing)
        self._on_event(make_event(
            "section_fill",
            agent_path=f"fill:{sec_id}",
            data=data,
        ))

    @staticmethod
    def _validate(
        text: str,
        required_chars: float,
        allowed_citation_ids: Optional[Set[str]] = None,
        required_markers: Optional[List[str]] = None,
        *,
        section_spec: Optional[SectionSpec] = None,
        min_questions: int = 0,
        min_examples: int = 0,
    ) -> List[str]:
        """返回缺失项清单；空列表表示验收通过。"""
        missing: List[str] = []
        prose_text = _FENCED_CODE_RE.sub("", text)
        if len(text) < required_chars:
            missing.append(f"长度不足（{len(text)} < {int(required_chars)} 字符）")
        if _URL_RE.search(text):
            missing.append("包含 URL（http:// 或 https://）")
        if _LOW_LEVEL_HEADING_RE.search(prose_text):
            missing.append("包含 # 或 ## 级标题（小节正文只允许 ###/#### 标题，[EXn]/[Qn]/[An] 标签用加粗行）")
        if "[[" in text:
            missing.append("包含 [[ ]] 式引用标记或占位符")
        if "\\(" in prose_text or "\\[" in prose_text:
            missing.append("使用了 \\( 或 \\[ 定界符（LaTeX 定界符请用 $...$ / $$...$$）")
        if min_examples > 0 and "[EX" not in text:
            missing.append("缺少 [EXn] 标签（本节已分配例题配额）")
        if min_questions > 0 and "[Q" not in text:
            missing.append("缺少 [Qn] 标签（本节已分配自测题配额）")
        if min_questions > 0 and "[A" not in text:
            missing.append("缺少 [An] 标签（本节已分配答案配额）")
        question_ids = set(_QUESTION_ID_RE.findall(text))
        answer_ids = set(_ANSWER_ID_RE.findall(text))
        example_ids = set(_EXAMPLE_ID_RE.findall(text))
        if "[Q" in text:
            if not _QUESTION_NUMBER_RE.search(text):
                missing.append("自测题标签必须带编号（[Q1] 形式），且不得与 [EXn] 合并书写")
            if not _QUESTION_LEVEL_RE.search(text):
                missing.append("每个 [Qn] 自测题必须标注层级（基础/应用/迁移）")
        if "[A" in text and not _ANSWER_NUMBER_RE.search(text):
            missing.append("答案标签必须带编号（[A1] 形式），与 [Qn] 一一对应，禁止用 [EXn] 充当答案标签")
        if min_questions > 0:
            if len(question_ids) < min_questions:
                missing.append(
                    f"自测题数量不足（{len(question_ids)}/{min_questions}），请补足带层级的 [Qn] 自测题"
                )
        if question_ids or answer_ids:
            unpaired = sorted(question_ids ^ answer_ids, key=int)
            if unpaired:
                missing.append(
                    "[Qn] 与 [An] 编号必须一一对应，当前不配对的编号: "
                    + "、".join(unpaired)
                )
            if question_ids and not _RUBRIC_CUE_RE.search(text):
                missing.append("每道 [An] 答案必须写明评分点/得分点")
        if min_examples > 0:
            if len(example_ids) < min_examples:
                missing.append(
                    f"带步骤例题数量不足（{len(example_ids)}/{min_examples}），请补足 [EXn] 例题"
                )
        if example_ids and not _WORKED_STEP_CUE_RE.search(text):
            missing.append("[EXn] 例题必须写出显式解答步骤（步骤/解答/推导）")
        for marker in required_markers or []:
            if marker not in text:
                missing.append(f"缺少必需标记 {marker}")
        if section_spec is not None:
            spec_text = " ".join([section_spec.title, section_spec.purpose, *section_spec.key_points])
            if section_spec.misconceptions and not _CORRECTION_CUE_RE.search(text):
                missing.append("有来源易错点但未先复述误区并明确驳正")
            if _COMPARISON_REQUEST_RE.search(spec_text) and not _COMPARISON_CUE_RE.search(text):
                missing.append("本节要求辨析/对比，但正文未同时点名双方并给出明确比较语义")
        # 内联引用编号必须落在该节来源清单内（幻觉编号 → 重试）。
        allowed = allowed_citation_ids or set()
        cited = set(_FOOTNOTE_MARK_RE.findall(text))
        bad = sorted({marker for marker in cited if marker not in allowed}, key=int)
        if bad:
            missing.append("引用来源清单外的编号 " + "、".join(f"[^{m}]" for m in bad) + "（幻觉引用）")
        if allowed and not (cited & allowed):
            missing.append("本节已有来源清单，但关键事实缺少至少一条有效内联引用")
        return missing

    @staticmethod
    def _split_sources(research: str) -> Tuple[List[Dict[str, str]], str]:
        """抽出研究笔记切片里的来源登记表行；已登记来源的 ``src: url`` 改写为 ``src: [^n]``。"""

        sources = _parse_source_lines(research)
        if not sources:
            return [], research
        text = _SOURCE_LINE_RE.sub("", research)
        text = re.sub(r"^##\s*来源登记表\s*$", "", text, flags=re.M)  # 空标题一并移除
        by_url = {s["url"]: s["n"] for s in sources}

        def _rewrite(match: "re.Match[str]") -> str:
            n = by_url.get(match.group(1))
            return f"src: [^{n}]" if n else match.group(0)

        return sources, _SRC_URL_RE.sub(_rewrite, text)

    @staticmethod
    def _build_user_payload(
        section: SectionSpec,
        backbone_excerpt: str,
        research_slice: str,
        terminology: List[Dict[str, str]],
        *,
        global_requirements: str = "",
        required_markers: Optional[List[str]] = None,
        min_questions: int = 0,
        min_examples: int = 0,
    ) -> str:
        """构造有界 user payload；超总量上限时先裁 research_slice，再裁 backbone_excerpt。"""
        excerpt = backbone_excerpt[:EXCERPT_LIMIT]
        sources, research = FillRunner._split_sources(research_slice[:RESEARCH_LIMIT])

        def render(research_text: str, excerpt_text: str) -> str:
            parts = [
                "## 本节规格\n"
                f"- 标题: {section.title}\n"
                f"- 写作目的: {section.purpose}\n"
                f"- 必覆盖要点: {'；'.join(section.key_points)}\n"
                f"- 目标篇幅: 约 {section.target_chars} 字\n"
                f"- 难度: {section.difficulty}",
            ]
            if min_questions > 0 or min_examples > 0:
                quota_lines = []
                if min_examples > 0:
                    quota_lines.append(f"- 至少 {min_examples} 个 [EXn] 例题，且必须写出显式解答步骤")
                if min_questions > 0:
                    quota_lines.append(
                        f"- 至少 {min_questions} 道 [Qn] 自测题（标注层级），"
                        "每道配同号 [An] 答案并写明评分点"
                    )
                parts.append("## 本节学习闭环硬性配额\n" + "\n".join(quota_lines))
            if str(global_requirements or "").strip():
                parts.append(
                    "## 全局输出要求（只执行与本节相关的条款）\n"
                    + str(global_requirements).strip()
                )
            markers = [str(marker).strip() for marker in (required_markers or []) if str(marker).strip()]
            if markers:
                parts.append(
                    "## 本节硬性标记（必须逐字出现在正文并给出实际说明）\n"
                    + "\n".join(f"- {marker}" for marker in markers)
                )
            if section.misconceptions:
                lines = "\n".join(f"- {m['claim']}（出处: {m['source_url']}）" for m in section.misconceptions)
                parts.append(f"## 易错点（仅可使用以下带出处的条目）\n{lines}")
            if terminology:
                lines = "\n".join(f"- {t.get('symbol', '')}: {t.get('meaning', '')}" for t in terminology)
                parts.append(f"## 全书术语符号表（严格遵守）\n{lines}")
            if sources:
                lines = "\n".join(f"- [^{s['n']}] {s['title']} {s['url']}" for s in sources)
                parts.append(
                    "## 本节来源清单（编号是全书固定编号，不得从 [^1] 重新编号；"
                    "关键事实句末以 [^n] 标注来源，必须逐字复制以下实际编号；"
                    f"正文禁止出现裸 URL）\n{lines}"
                )
            parts.append(f"## 衔接段（正文接在此处之后）\n{excerpt_text or '（无）'}")
            parts.append(f"## 研究笔记切片（事实依据，禁止照抄出处链接到正文）\n{research_text.strip() or '（无）'}")
            return "\n\n".join(parts)

        payload = render(research, excerpt)
        if len(payload) > PAYLOAD_LIMIT:
            keep = max(0, len(research) - (len(payload) - PAYLOAD_LIMIT))
            research = research[:keep]
            payload = render(research, excerpt)
        if len(payload) > PAYLOAD_LIMIT:
            keep = max(0, len(excerpt) - (len(payload) - PAYLOAD_LIMIT))
            excerpt = excerpt[:keep]
            payload = render(research, excerpt)
        if len(payload) > PAYLOAD_LIMIT:
            payload = payload[:PAYLOAD_LIMIT]
        return payload
