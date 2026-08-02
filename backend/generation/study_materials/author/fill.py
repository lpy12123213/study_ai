"""Section fill runner (design doc §6): bounded context + acceptance loop + author fallback.

Each blueprint section is filled by a dedicated sub-LLM call that sees only a *bounded*
context pack: an excerpt of the backbone where the text attaches, a slice of the research
notes, the numbered source registry (``[^n] title url`` lines — the only URL form allowed
in the fill context), the terminology table, and the section spec. The produced text must
pass an acceptance check (length, no bare URLs / reference sections, required
[EXn]/[Qn]/[An] tags, and every inline ``[^n]`` citation marker must resolve to the given
source list — hallucinated ids are retried); failed attempts are retried with the list of
missing items appended to the prompt. When retries are exhausted the section is flagged
for author rewrite instead of silently accepting bad content.
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
    "要求：严格遵守给定术语符号表；必须包含 [EXn] 带步骤例题、[Qn] 分层自测题、[An] 答案与评分点；"
    "三类标签各自独立编号、独占加粗行，不得合并书写；"
    "每个 [Qn] 必须标注层级（基础/应用/迁移）；[An] 答案与 [Qn] 一一对应并给出评分点，"
    "禁止用 [EXn] 充当答案标签；"
    "数学公式用 LaTeX；在关键事实句末用 [^n] 标注来源编号，只允许使用给定来源清单里的编号；"
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
# 题号标签纪律（真实缺陷：**[EX1] [Q1]** 合并书写、自测题无层级、**[EX1]**（基础）
# 充当答案标签）：编号必须显式（[Q1]/[A1]），[Qn] 必须标注层级（基础/应用/迁移）。
_QUESTION_NUMBER_RE = re.compile(r"\[Q\d")
_ANSWER_NUMBER_RE = re.compile(r"\[A\d")
_QUESTION_LEVEL_RE = re.compile(r"基础|应用|迁移")

LlmFunc = Callable[[str, str], Union[str, Awaitable[str]]]
EventSink = Callable[[Dict[str, Any]], None]


def _parse_source_lines(text: str) -> List[Dict[str, str]]:
    """从研究笔记切片解析来源登记表行（``- [^n] title url``）。"""

    sources: List[Dict[str, str]] = []
    for match in _SOURCE_LINE_RE.finditer(str(text or "")):
        sources.append({"n": match.group(1), "title": match.group("title").strip(), "url": match.group("url")})
    return sources


def source_ids_in_slice(research_slice: str) -> Set[str]:
    """研究笔记切片（按注入上限截断后）里可用的引用编号集合，供产出校验。"""

    return {s["n"] for s in _parse_source_lines(str(research_slice or "")[:RESEARCH_LIMIT])}


@dataclass
class FillResult:
    text: str
    needs_author_rewrite: bool
    attempts: int


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
    ) -> FillResult:
        payload = self._build_user_payload(
            section_spec, backbone_excerpt or "", research_slice or "", terminology or []
        )
        required_chars = min(section_spec.target_chars * MIN_TARGET_RATIO, float(self.min_chars))
        allowed_citations = source_ids_in_slice(research_slice or "")
        missing: List[str] = []
        for attempt in range(1, self.max_retries + 1):
            self._emit(section_spec.id, "start")
            user = payload
            if missing:
                user += "\n\n上次产出未通过验收，请补全/修正以下缺失项：\n" + "\n".join(f"- {m}" for m in missing)
            text = await self._call_llm(user)
            missing = self._validate(text, required_chars, allowed_citations)
            if not missing:
                self._emit(section_spec.id, "ok")
                return FillResult(text=text, needs_author_rewrite=False, attempts=attempt)
            self._emit(section_spec.id, "retry" if attempt < self.max_retries else "failed")
        return FillResult(text="", needs_author_rewrite=True, attempts=self.max_retries)

    async def _call_llm(self, user: str) -> str:
        result = self._llm(self._system_prompt, user)
        if inspect.isawaitable(result):
            result = await result
        return str(result or "").strip()

    def _emit(self, sec_id: str, status: str) -> None:
        if self._on_event is None:
            return
        self._on_event(make_event(
            "section_fill",
            agent_path=f"fill:{sec_id}",
            data={"sec_id": sec_id, "status": status},
        ))

    @staticmethod
    def _validate(
        text: str,
        required_chars: float,
        allowed_citation_ids: Optional[Set[str]] = None,
    ) -> List[str]:
        """返回缺失项清单；空列表表示验收通过。"""
        missing: List[str] = []
        if len(text) < required_chars:
            missing.append(f"长度不足（{len(text)} < {int(required_chars)} 字符）")
        if _URL_RE.search(text):
            missing.append("包含 URL（http:// 或 https://）")
        if _LOW_LEVEL_HEADING_RE.search(text):
            missing.append("包含 # 或 ## 级标题（小节正文只允许 ###/#### 标题，[EXn]/[Qn]/[An] 标签用加粗行）")
        if "[[" in text:
            missing.append("包含 [[ ]] 式引用标记或占位符")
        if "\\(" in text or "\\[" in text:
            missing.append("使用了 \\( 或 \\[ 定界符（LaTeX 定界符请用 $...$ / $$...$$）")
        for tag in ("[EX", "[Q", "[A"):
            if tag not in text:
                missing.append(f"缺少 {tag}n] 标签（例题/自测题/答案）")
        if "[Q" in text:
            if not _QUESTION_NUMBER_RE.search(text):
                missing.append("自测题标签必须带编号（[Q1] 形式），且不得与 [EXn] 合并书写")
            if not _QUESTION_LEVEL_RE.search(text):
                missing.append("每个 [Qn] 自测题必须标注层级（基础/应用/迁移）")
        if "[A" in text and not _ANSWER_NUMBER_RE.search(text):
            missing.append("答案标签必须带编号（[A1] 形式），与 [Qn] 一一对应，禁止用 [EXn] 充当答案标签")
        # 内联引用编号必须落在该节来源清单内（幻觉编号 → 重试）。
        allowed = allowed_citation_ids or set()
        bad = sorted({m for m in _FOOTNOTE_MARK_RE.findall(text) if m not in allowed}, key=int)
        if bad:
            missing.append("引用来源清单外的编号 " + "、".join(f"[^{m}]" for m in bad) + "（幻觉引用）")
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
            if section.misconceptions:
                lines = "\n".join(f"- {m['claim']}（出处: {m['source_url']}）" for m in section.misconceptions)
                parts.append(f"## 易错点（仅可使用以下带出处的条目）\n{lines}")
            if terminology:
                lines = "\n".join(f"- {t.get('symbol', '')}: {t.get('meaning', '')}" for t in terminology)
                parts.append(f"## 全书术语符号表（严格遵守）\n{lines}")
            if sources:
                lines = "\n".join(f"- [^{s['n']}] {s['title']} {s['url']}" for s in sources)
                parts.append(
                    "## 本节来源清单（关键事实句末以 [^n] 标注来源，仅可使用以下编号；"
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
