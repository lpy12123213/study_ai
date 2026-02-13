from __future__ import annotations

import json
import asyncio
import os
import random
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, PlanStep, StepResult, agent_event
from backend.crawler_manager import get_crawler
from backend.core.settings import (
    API_TIMEOUT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_TEMPERATURE,
    LESSON_PLAN_PROVIDER,
    MAIN_MODEL_MAX_TOKENS,
    MAIN_MODEL_TEMPERATURE,
    MOONSHOT_API_KEY,
    MOONSHOT_BASE_URL,
)
from backend.core import llm_console


_emit_event_var: ContextVar[Optional[Callable[[Dict[str, Any]], Awaitable[None]]]] = ContextVar(
    "agent_emit_event",
    default=None,
)

_PDF_URL_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)


def _looks_like_pdf_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    try:
        path = (urlparse(u).path or "").lower()
        if path.endswith(".pdf"):
            return True
    except Exception:
        pass
    return bool(_PDF_URL_RE.search(u))


def _clip_text(text: str, *, max_chars: int) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if max_chars <= 0:
        return ""
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _compact_snippet(text: str, *, max_chars: int = 400) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    # Collapse all whitespace (including newlines) into a single line to avoid polluting Markdown bullets.
    compact = re.sub(r"\s+", " ", raw.replace("\u00a0", " ")).strip()
    return _clip_text(compact, max_chars=max_chars)


def _strip_evidence_markers(text: str) -> str:
    """Remove common inline evidence markers like `[[1]]` that some providers include."""

    raw = (text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\[\[\s*\d+\s*\]\]", "", raw)
    raw = re.sub(r"\(\[\[\s*\d+\s*\]\]\)", "", raw)
    # Collapse excessive whitespace after removals.
    # IMPORTANT: keep newlines (Markdown structure), only collapse horizontal spaces/tabs.
    raw = re.sub(r"[ \t]{2,}", " ", raw).strip()
    return raw


_UI_NOISE_EXACT = {
    "播报",
    "编辑",
    "登录",
    "注册",
    "目录",
    "导航",
    "首页",
    "帮助",
    "反馈",
    "免责声明",
    "隐私",
    "用户协议",
    "关于我们",
    "联系我们",
    "加入我们",
    "企业推广",
    "广告",
    "推广",
    "分享",
    "收藏",
}

_UI_NOISE_SUBSTRINGS = (
    "©",
    "版权所有",
    "版权",
    "ICP备",
    "备案",
    "Baidu",
    "Sogou",
    "百度",
    "搜狗",
)


def _is_ui_noise_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True

    if s in _UI_NOISE_EXACT and len(s) <= 8:
        return True

    if any(token in s for token in ("免责声明", "隐私", "用户协议")) and len(s) <= 50:
        return True

    lower = s.lower()
    if ("baidu" in lower or "sogou" in lower) and any(x in s for x in ("©", "版权", "版权所有")):
        return True

    if any(sub in s for sub in _UI_NOISE_SUBSTRINGS) and len(s) <= 60:
        return True

    if re.fullmatch(r"©?\s*\d{4}.*", s) and len(s) <= 80:
        return True

    return False


def _remove_ui_noise(text: str, *, max_lines: int = 400) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    lines: List[str] = []
    last = ""
    for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = (ln or "").strip()
        if _is_ui_noise_line(s):
            continue
        if s == last:
            continue
        last = s
        lines.append(s)
        if len(lines) >= max_lines:
            break
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _sanitize_explanation_markdown(markdown: str, *, knowledge_point: str) -> str:
    """Normalize generated Markdown so it fits under `### 核心讲解`.

    The LLM sometimes outputs:
    - top-level headings (`# ...`) which break the final archive structure
    - a duplicated "参考资料/外部链接" block (we render sources separately)
    - raw URLs or evidence markers like `[[1]]`
    """

    text = (markdown or "").strip()
    if not text:
        return ""

    text = _strip_evidence_markers(text)

    # If the model inserted a references section, truncate it (the archive already lists sources).
    ref_pat = re.compile(r"(?im)^(#{1,6}\s*)?(参考资料|参考文献|外部链接|references)\b.*$")
    m = ref_pat.search(text)
    if m:
        text = text[: m.start()].rstrip()

    # Replace markdown links with titles, then drop remaining raw URLs.
    text = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)

    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def _norm_title(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"自学讲解|自学|讲解|概念", "", s)
        s = re.sub(r"[\s:：—\-–·•,，。！？()（）《》“”\"'’]+", "", s)
        return s

    kp_norm = _norm_title(knowledge_point)
    first_non_empty = next((i for i, ln in enumerate(raw_lines) if (ln or "").strip()), None)
    if first_non_empty is not None and kp_norm:
        m0 = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", raw_lines[first_non_empty] or "")
        if m0:
            title = _norm_title(m0.group(2) or "")
            if title and (kp_norm in title or title in kp_norm):
                raw_lines[first_non_empty] = ""

    out_lines: List[str] = []
    for ln in raw_lines:
        s = ln.rstrip()
        # Explanation is rendered under a level-3 heading, so we keep headings at level>=4.
        m_h = re.match(r"^(\s*)(#{1,6})(\s+)(.*)$", s)
        if m_h:
            indent, hashes, space, rest = m_h.groups()
            lvl = len(hashes)
            lvl = lvl if lvl >= 4 else 4
            lvl = 6 if lvl > 6 else lvl
            s = f"{indent}{'#' * lvl}{space}{rest}".rstrip()
        out_lines.append(s)

    cleaned = "\n".join(out_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _has_unclosed_code_fence(text: str) -> bool:
    raw = text or ""
    return raw.count("```") % 2 == 1


def _has_unbalanced_inline_math(text: str) -> bool:
    raw = text or ""
    count = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "$":
            if i + 1 < len(raw) and raw[i + 1] == "$":
                i += 2
                continue
            count += 1
        i += 1
    return count % 2 == 1


def _looks_truncated_markdown(text: str) -> bool:
    raw = (text or "").rstrip()
    if not raw:
        return False
    if _has_unclosed_code_fence(raw):
        return True
    if raw.count("$$") % 2 == 1:
        return True
    if _has_unbalanced_inline_math(raw):
        return True
    last = raw[-1]
    if last in {"-", "—", "(", "（", "[", "{", "=", "+", "*", "/", "\\", "$"}:
        return True
    return False


def _trim_overlap(prefix: str, addition: str, *, max_check: int = 480) -> str:
    if not prefix or not addition:
        return addition
    p = prefix[-max_check:]
    a = addition[:max_check]
    max_k = min(len(p), len(a))
    for k in range(max_k, 24, -1):
        if p.endswith(a[:k]):
            return addition[k:]
    return addition


def _repair_incomplete_markdown(text: str) -> str:
    raw = (text or "").rstrip()
    if not raw:
        return ""
    if _has_unclosed_code_fence(raw):
        raw = raw + "\n```"
    if raw.count("$$") % 2 == 1:
        raw = raw + "\n$$"
    if _has_unbalanced_inline_math(raw):
        raw = raw + "$"
    return raw


def _postprocess_web_search_result(result: Dict[str, Any], *, max_snippet_chars: int = 400) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(result or {})

    # Metaso /ask snippets sometimes contain evidence markers like [[1]]; strip them early so the
    # downstream LLM won't copy them into the final study material.
    for k in ("title", "snippet", "text"):
        if isinstance(out.get(k), str) and out.get(k):
            out[k] = _strip_evidence_markers(str(out.get(k) or ""))

    url = str(out.get("url") or out.get("link") or "").strip()
    if url and not str(out.get("url") or "").strip():
        out["url"] = url

    if _looks_like_pdf_url(url):
        # Avoid injecting garbled "PDF text" into the archive (common for math formulas).
        out["content_type_hint"] = "application/pdf"
        out["snippet"] = "[PDF课件]（为避免公式/符号乱码，已省略正文抽取；建议打开链接查看）"
        out["text"] = ""
        return out

    text = _remove_ui_noise(str(out.get("text") or ""))
    snippet = _remove_ui_noise(str(out.get("snippet") or ""))

    if not snippet and text:
        out["snippet"] = _compact_snippet(text, max_chars=max_snippet_chars)
    elif snippet:
        out["snippet"] = _compact_snippet(snippet, max_chars=max_snippet_chars)

    # Keep the original `text` (if any) but also normalize excessive whitespace.
    if text:
        out["text"] = _clip_text(text, max_chars=8000)
    return out


class Executor:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(default)
        s = str(value).strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off"}:
            return False
        return bool(default)

    def _strict_llm(self, ctx: CompressedContext, args: Optional[Dict[str, Any]] = None) -> bool:
        v: Any = None
        if isinstance(args, dict) and "strict_llm" in args:
            v = args.get("strict_llm")
        else:
            study_opts = ctx.working_memory.get("study_options")
            study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
            v = study_opts.get("strict_llm")
        if v is None:
            v = os.getenv("STUDY_MATERIALS_STRICT_LLM")
        # Default to True (user request: reduce fallbacks, fail fast on LLM errors).
        return self._coerce_bool(v, default=True)

    async def execute_step(
        self,
        step: PlanStep,
        *,
        context: CompressedContext,
        emit_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> StepResult:
        tool = (step.tool or "").strip()
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return StepResult(step_id=step.id, tool=tool, success=False, error=f"Unknown tool: {tool}")

        timeout_s = float(os.getenv("STUDY_MATERIALS_STEP_TIMEOUT_S") or os.getenv("AGENT_STEP_TIMEOUT_S") or "240")
        timeout_s = max(30.0, min(timeout_s, 60.0 * 30.0))  # clamp to [30s, 30m]

        token = _emit_event_var.set(emit_event)
        try:
            output = await asyncio.wait_for(handler(step.arguments or {}, context), timeout=timeout_s)
            return StepResult(step_id=step.id, tool=tool, success=True, output=output)
        except asyncio.TimeoutError:
            return StepResult(
                step_id=step.id,
                tool=tool,
                success=False,
                error=f"Tool timeout after {int(timeout_s)}s: {tool}",
            )
        except Exception as exc:  # pragma: no cover (best-effort safety)
            return StepResult(step_id=step.id, tool=tool, success=False, error=str(exc))
        finally:
            try:
                _emit_event_var.reset(token)
            except Exception:
                pass

    async def _call_llm_text(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
        reasoning: Optional[Dict[str, Any]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
    ) -> str:
        provider = str(LESSON_PLAN_PROVIDER or "").strip().lower() or "openrouter"
        base_url = str(LESSON_PLAN_BASE_URL or "").strip().rstrip("/")
        api_key = str(LESSON_PLAN_API_KEY or "").strip()

        normalized_model = str(model or "").strip()
        model_lower = normalized_model.lower()
        moonshot_key = str(MOONSHOT_API_KEY or "").strip()
        moonshot_base_url = str(MOONSHOT_BASE_URL or "").strip().rstrip("/")

        if provider == "moonshot" or (
            provider == "openrouter"
            and moonshot_key
            and (model_lower.startswith("moonshotai/") or model_lower.startswith("kimi-") or model_lower.startswith("moonshot-"))
        ):
            provider = "moonshot"
            api_key = moonshot_key or api_key
            base_url = moonshot_base_url or base_url
            if "/" in normalized_model:
                normalized_model = normalized_model.split("/")[-1]

        if not api_key:
            if raise_on_fail:
                raise RuntimeError("llm_not_configured")
            return ""

        req_id_base = f"exec-text-{uuid.uuid4().hex[:8]}"

        def _elapsed_s(start_ts: float) -> float:
            if not start_ts:
                return 0.0
            try:
                return max(0.0, time.time() - float(start_ts))
            except Exception:
                return 0.0

        def _truthy(raw: str) -> bool:
            s = (raw or "").strip().lower()
            return s in {"1", "true", "yes", "y", "on"}

        def _default_reasoning_cfg() -> Optional[Dict[str, Any]]:
            # Default to enabled (requested: always use "thinking mode" unless explicitly disabled).
            enabled_raw = (
                os.getenv("STUDY_MATERIALS_THINKING_MODE")
                or os.getenv("STUDY_MATERIALS_REASONING")
                or "1"
            )
            if (enabled_raw or "").strip().lower() in {"0", "false", "no", "off"}:
                return None

            effort_raw = (
                os.getenv("STUDY_MATERIALS_THINKING_EFFORT")
                or os.getenv("STUDY_MATERIALS_REASONING_EFFORT")
                or "xhigh"
            )
            effort = (effort_raw or "").strip().lower().replace("-", "").replace("_", "")
            if effort in {"max", "maximum", "highest"}:
                effort = "xhigh"
            allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
            if effort not in allowed:
                effort = "xhigh"

            exclude_raw = os.getenv("STUDY_MATERIALS_REASONING_EXCLUDE") or "0"
            exclude = _truthy(exclude_raw)
            return {"effort": effort, "exclude": exclude}

        default_reasoning = _default_reasoning_cfg()
        if reasoning is None:
            # No call-site override: use env defaults.
            reasoning = default_reasoning
        else:
            # Call-site override should win.
            if default_reasoning is None:
                reasoning = dict(reasoning)
            else:
                merged = dict(default_reasoning)
                merged.update(dict(reasoning))
                reasoning = merged

        stream_reasoning = _truthy(os.getenv("STUDY_MATERIALS_STREAM_REASONING") or os.getenv("AGENT_STREAM_REASONING") or "1")

        async def _emit_thinking_delta(text: str) -> None:
            cb = _emit_event_var.get()
            if cb is None:
                return
            t = str(text or "")
            if not t:
                return
            # Keep each event small to avoid blowing up the in-memory SSE backlog.
            max_chars = int(os.getenv("STUDY_MATERIALS_REASONING_EVENT_MAX_CHARS") or "1200")
            if max_chars <= 0:
                await cb(agent_event("thinking", {"content": t, "delta": True}))
                return
            for i in range(0, len(t), max_chars):
                chunk = t[i : i + max_chars]
                if chunk:
                    await cb(agent_event("thinking", {"content": chunk, "delta": True}))

        def _max_retries() -> int:
            raw = str(
                retries
                if retries is not None
                else os.getenv("STUDY_MATERIALS_LLM_RETRIES")
                or os.getenv("LESSON_PLAN_LLM_RETRIES")
                or os.getenv("AGENT_LLM_RETRIES")
                or "3"
            ).strip()
            try:
                v = int(raw)
            except Exception:
                v = 3
            return max(1, min(v, 10))

        def _resp_error(resp: Optional[httpx.Response]) -> str:
            if resp is None:
                return ""
            msg = ""
            try:
                data = resp.json()
                if isinstance(data, dict):
                    err = data.get("error")
                    if isinstance(err, dict):
                        msg = str(err.get("message") or err.get("detail") or err.get("error") or "").strip()
                    elif isinstance(err, str):
                        msg = err.strip()
                    if not msg:
                        msg = str(data.get("message") or data.get("detail") or "").strip()
            except Exception:
                msg = ""
            if not msg:
                try:
                    msg = str(resp.text or "").strip()
                except Exception:
                    msg = ""
            if msg:
                msg = msg.replace("\n", " ").strip()
            return msg[:260]

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        effective_temperature = float(temperature)
        if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
            # Moonshot kimi models reject temperatures other than 1.0 (HTTP 400).
            effective_temperature = 1.0
        payload: Dict[str, Any] = {
            "model": normalized_model,
            "messages": messages,
            "temperature": effective_temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if isinstance(response_format, dict) and response_format:
            payload["response_format"] = dict(response_format)
        is_openrouter = provider == "openrouter"
        if stream_reasoning and provider in {"openrouter", "moonshot"}:
            payload["stream"] = True

        if reasoning and is_openrouter:
            # OpenRouter supports the `reasoning` field for some models. We keep it optional and
            # best-effort: if the provider/model rejects it, we'll retry without it.
            payload["reasoning"] = dict(reasoning)

        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        timeout_s = float(API_TIMEOUT or 120)
        last_error: str = ""
        max_retries = _max_retries()
        dropped_reasoning = False
        dropped_response_format = False

        # When streaming, emit reasoning deltas in batches (avoid spamming SSE events).
        reasoning_emit_chars = int(os.getenv("STUDY_MATERIALS_REASONING_EMIT_CHARS") or "240")
        if reasoning_emit_chars <= 0:
            reasoning_emit_chars = 240
        reasoning_emit_interval_s = float(os.getenv("STUDY_MATERIALS_REASONING_EMIT_INTERVAL_S") or "0.25")
        reasoning_emit_interval_s = max(0.05, min(reasoning_emit_interval_s, 2.0))

        for attempt in range(max_retries):
            req_id = f"{req_id_base}-{attempt + 1}"
            start_ts = llm_console.log_start(
                req_id=req_id,
                provider=provider,
                model=normalized_model,
                stream=bool(payload.get("stream")),
                temperature=float(payload.get("temperature") or 0.0),
                max_tokens=int(payload.get("max_tokens") or 0),
                base_url=base_url,
            )
            try:
                async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
                    url = f"{base_url}/chat/completions"

                    if bool(payload.get("stream")):
                        async with client.stream("POST", url, headers=headers, json=payload) as resp:
                            if resp.status_code in retry_statuses and attempt < (max_retries - 1):
                                retry_after = (resp.headers.get("retry-after") or "").strip()
                                wait_s = 0.0
                                try:
                                    wait_s = float(retry_after) if retry_after else 0.0
                                except ValueError:
                                    wait_s = 0.0
                                if wait_s <= 0:
                                    wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                                last_error = f"http_status_{resp.status_code}"
                                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                                await asyncio.sleep(wait_s)
                                continue

                            if resp.status_code != 200:
                                try:
                                    await resp.aread()
                                except Exception:
                                    pass
                            resp.raise_for_status()

                            content_parts: List[str] = []
                            reasoning_buf = ""
                            finish_reason = ""
                            usage: Dict[str, Any] = {}
                            loop = asyncio.get_running_loop()
                            last_emit_t = loop.time()

                            async for line in resp.aiter_lines():
                                if not line:
                                    continue
                                if line.startswith(":"):
                                    continue
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if not data:
                                    continue
                                if data == "[DONE]":
                                    break

                                try:
                                    obj = json.loads(data)
                                except Exception:
                                    continue

                                choices = obj.get("choices")
                                if not isinstance(choices, list) or not choices:
                                    continue
                                choice0 = choices[0] if isinstance(choices[0], dict) else {}
                                delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}

                                # Reasoning tokens: OpenRouter may emit them in multiple delta fields.
                                # IMPORTANT: do NOT concatenate multiple fields, or tokens may be duplicated.
                                r_chunk = ""
                                details = delta.get("reasoning_details")
                                if isinstance(details, list) and details:
                                    text_parts: List[str] = []
                                    summary_parts: List[str] = []
                                    for it in details:
                                        if not isinstance(it, dict):
                                            continue
                                        if isinstance(it.get("text"), str) and it.get("text"):
                                            text_parts.append(str(it.get("text") or ""))
                                        elif isinstance(it.get("summary"), str) and it.get("summary"):
                                            summary_parts.append(str(it.get("summary") or ""))
                                    if text_parts:
                                        r_chunk = "".join(text_parts)
                                    elif summary_parts:
                                        r_chunk = "".join(summary_parts)
                                elif isinstance(delta.get("reasoning_content"), str):
                                    r_chunk = str(delta.get("reasoning_content") or "")
                                elif isinstance(delta.get("reasoning"), str):
                                    r_chunk = str(delta.get("reasoning") or "")

                                if r_chunk:
                                    reasoning_buf += r_chunk
                                    now_t = loop.time()
                                    if len(reasoning_buf) >= reasoning_emit_chars or (now_t - last_emit_t) >= reasoning_emit_interval_s:
                                        await _emit_thinking_delta(reasoning_buf)
                                        llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)
                                        reasoning_buf = ""
                                        last_emit_t = now_t

                                c_chunk = delta.get("content")
                                if isinstance(c_chunk, str) and c_chunk:
                                    content_parts.append(c_chunk)
                                    llm_console.log_delta(req_id=req_id, channel="content", text=c_chunk)

                                fr_chunk = choice0.get("finish_reason")
                                if isinstance(fr_chunk, str) and fr_chunk:
                                    finish_reason = fr_chunk

                                if isinstance(obj.get("usage"), dict):
                                    usage = dict(obj.get("usage") or {})

                            if reasoning_buf:
                                await _emit_thinking_delta(reasoning_buf)
                                llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)

                            content_text = "".join(content_parts)
                            llm_console.log_end(
                                req_id=req_id,
                                elapsed_s=_elapsed_s(start_ts),
                                finish_reason=finish_reason,
                                usage=usage,
                                content_chars=len(content_text),
                            )
                            return content_text

                    resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code in retry_statuses and attempt < (max_retries - 1):
                    retry_after = (resp.headers.get("retry-after") or "").strip()
                    wait_s = 0.0
                    try:
                        wait_s = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        wait_s = 0.0
                    if wait_s <= 0:
                        wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                    last_error = f"http_status_{resp.status_code}"
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(wait_s)
                    continue

                resp.raise_for_status()
                data = resp.json()
                try:
                    # Best-effort: if the provider returns reasoning in non-stream mode, surface it once.
                    if stream_reasoning:
                        try:
                            msg = data.get("choices", [{}])[0].get("message", {}) if isinstance(data, dict) else {}
                            reasoning_text = ""
                            if isinstance(msg, dict):
                                if isinstance(msg.get("reasoning"), str):
                                    reasoning_text = str(msg.get("reasoning") or "")
                                elif isinstance(msg.get("reasoning_content"), str):
                                    reasoning_text = str(msg.get("reasoning_content") or "")
                            if reasoning_text:
                                await _emit_thinking_delta(reasoning_text)
                                llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_text)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            pass
                    content_text = str(data["choices"][0]["message"]["content"] or "")
                    finish_reason = ""
                    usage: Dict[str, Any] = {}
                    try:
                        choices = data.get("choices")
                        first = choices[0] if isinstance(choices, list) and choices else {}
                        if isinstance(first, dict):
                            finish_reason = str(first.get("finish_reason") or "")
                    except Exception:
                        finish_reason = ""
                    if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                        usage = dict(data.get("usage") or {})
                    if content_text:
                        llm_console.log_delta(req_id=req_id, channel="content", text=content_text)
                    llm_console.log_end(
                        req_id=req_id,
                        elapsed_s=_elapsed_s(start_ts),
                        finish_reason=finish_reason,
                        usage=usage,
                        content_chars=len(content_text),
                    )
                    return content_text
                except asyncio.CancelledError:
                    raise
                except Exception:
                    last_error = "invalid_response"
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    if attempt < (max_retries - 1):
                        await asyncio.sleep(min(3.0, 0.4 + random.random() * 0.8))
                        continue
                    if raise_on_fail:
                        raise RuntimeError(f"llm_invalid_response model={normalized_model}")
                    return ""
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                api_msg = _resp_error(exc.response)
                last_error = f"http_status_{status}"
                if status in {400, 422}:
                    if provider == "moonshot":
                        msg_l = (api_msg or "").lower()
                        try:
                            current_t = float(payload.get("temperature") or 0.0)
                        except Exception:
                            current_t = 0.0
                        if ("temperature" in msg_l and "only 1" in msg_l) and current_t != 1.0:
                            try:
                                payload["temperature"] = 1.0
                            except Exception:
                                pass
                            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
                            await asyncio.sleep(0.2)
                            continue
                    # Some models/providers reject unknown fields. Retry after dropping them (once each).
                    if (not dropped_response_format) and ("response_format" in payload):
                        try:
                            payload.pop("response_format", None)
                        except Exception:
                            pass
                        dropped_response_format = True
                        llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                        await asyncio.sleep(0.2)
                        continue
                    if (not dropped_reasoning) and ("reasoning" in payload):
                        try:
                            payload.pop("reasoning", None)
                        except Exception:
                            pass
                        dropped_reasoning = True
                        llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                        await asyncio.sleep(0.2)
                        continue
                if status in retry_statuses and attempt < (max_retries - 1):
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
                if raise_on_fail:
                    raise RuntimeError(
                        f"llm_request_failed status={status} model={normalized_model} provider={provider} msg={api_msg or last_error}"
                    )
                return ""
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_error = str(exc)
                if attempt < (max_retries - 1):
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if raise_on_fail:
                    raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
                return ""
            except Exception as exc:  # pragma: no cover (best-effort)
                last_error = str(exc)
                if attempt < (max_retries - 1):
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if raise_on_fail:
                    raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
                return ""

        # Best-effort: never raise; return empty so callers can fall back.
        if last_error:
            try:
                print(f"[llm] request failed after retries: {last_error}", flush=True)
            except Exception:
                pass
        if raise_on_fail:
            raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error or 'unknown'}")
        return ""

    async def _call_llm_response(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
        reasoning: Optional[Dict[str, Any]] = None,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        provider = str(LESSON_PLAN_PROVIDER or "").strip().lower() or "openrouter"
        base_url = str(LESSON_PLAN_BASE_URL or "").strip().rstrip("/")
        api_key = str(LESSON_PLAN_API_KEY or "").strip()

        normalized_model = str(model or "").strip()
        model_lower = normalized_model.lower()
        moonshot_key = str(MOONSHOT_API_KEY or "").strip()
        moonshot_base_url = str(MOONSHOT_BASE_URL or "").strip().rstrip("/")

        if provider == "moonshot" or (
            provider == "openrouter"
            and moonshot_key
            and (model_lower.startswith("moonshotai/") or model_lower.startswith("kimi-") or model_lower.startswith("moonshot-"))
        ):
            provider = "moonshot"
            api_key = moonshot_key or api_key
            base_url = moonshot_base_url or base_url
            if "/" in normalized_model:
                normalized_model = normalized_model.split("/")[-1]

        if not api_key:
            if raise_on_fail:
                raise RuntimeError("llm_not_configured")
            return {"content": "", "finish_reason": "", "usage": {}}

        req_id_base = f"exec-resp-{uuid.uuid4().hex[:8]}"

        def _elapsed_s(start_ts: float) -> float:
            if not start_ts:
                return 0.0
            try:
                return max(0.0, time.time() - float(start_ts))
            except Exception:
                return 0.0

        def _truthy(raw: str) -> bool:
            s = (raw or "").strip().lower()
            return s in {"1", "true", "yes", "y", "on"}

        def _default_reasoning_cfg() -> Optional[Dict[str, Any]]:
            # Default to enabled (requested: always use "thinking mode" unless explicitly disabled).
            enabled_raw = (
                os.getenv("STUDY_MATERIALS_THINKING_MODE")
                or os.getenv("STUDY_MATERIALS_REASONING")
                or "1"
            )
            if (enabled_raw or "").strip().lower() in {"0", "false", "no", "off"}:
                return None

            effort_raw = (
                os.getenv("STUDY_MATERIALS_THINKING_EFFORT")
                or os.getenv("STUDY_MATERIALS_REASONING_EFFORT")
                or "xhigh"
            )
            effort = (effort_raw or "").strip().lower().replace("-", "").replace("_", "")
            if effort in {"max", "maximum", "highest"}:
                effort = "xhigh"
            allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
            if effort not in allowed:
                effort = "xhigh"

            exclude_raw = os.getenv("STUDY_MATERIALS_REASONING_EXCLUDE") or "0"
            exclude = _truthy(exclude_raw)
            return {"effort": effort, "exclude": exclude}

        default_reasoning = _default_reasoning_cfg()
        if reasoning is None:
            reasoning = default_reasoning
        else:
            # Call-site override should win.
            if default_reasoning is None:
                reasoning = dict(reasoning)
            else:
                merged = dict(default_reasoning)
                merged.update(dict(reasoning))
                reasoning = merged

        stream_reasoning = _truthy(
            os.getenv("STUDY_MATERIALS_STREAM_REASONING") or os.getenv("AGENT_STREAM_REASONING") or "1"
        )

        async def _emit_thinking_delta(text: str) -> None:
            cb = _emit_event_var.get()
            if cb is None:
                return
            t = str(text or "")
            if not t:
                return
            # Keep each event small to avoid blowing up the in-memory SSE backlog.
            max_chars = int(os.getenv("STUDY_MATERIALS_REASONING_EVENT_MAX_CHARS") or "1200")
            if max_chars <= 0:
                await cb(agent_event("thinking", {"content": t, "delta": True}))
                return
            for i in range(0, len(t), max_chars):
                chunk = t[i : i + max_chars]
                if chunk:
                    await cb(agent_event("thinking", {"content": chunk, "delta": True}))

        def _max_retries() -> int:
            raw = str(
                retries
                if retries is not None
                else os.getenv("STUDY_MATERIALS_LLM_RETRIES")
                or os.getenv("LESSON_PLAN_LLM_RETRIES")
                or os.getenv("AGENT_LLM_RETRIES")
                or "3"
            ).strip()
            try:
                v = int(raw)
            except Exception:
                v = 3
            return max(1, min(v, 10))

        def _resp_error(resp: Optional[httpx.Response]) -> str:
            if resp is None:
                return ""
            msg = ""
            try:
                data = resp.json()
                if isinstance(data, dict):
                    err = data.get("error")
                    if isinstance(err, dict):
                        msg = str(err.get("message") or err.get("detail") or err.get("error") or "").strip()
                    elif isinstance(err, str):
                        msg = err.strip()
                    if not msg:
                        msg = str(data.get("message") or data.get("detail") or "").strip()
            except Exception:
                msg = ""
            if not msg:
                try:
                    msg = str(resp.text or "").strip()
                except Exception:
                    msg = ""
            if msg:
                msg = msg.replace("\n", " ").strip()
            return msg[:260]

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        effective_temperature = float(temperature)
        if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
            effective_temperature = 1.0
        payload: Dict[str, Any] = {
            "model": normalized_model,
            "messages": messages,
            "temperature": effective_temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        is_openrouter = provider == "openrouter"
        if stream_reasoning and provider in {"openrouter", "moonshot"}:
            payload["stream"] = True
        if reasoning and is_openrouter:
            payload["reasoning"] = dict(reasoning)

        retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
        timeout_s = float(API_TIMEOUT or 120)
        last_error: str = ""
        max_retries = _max_retries()
        dropped_reasoning = False

        # When streaming, emit reasoning deltas in batches (avoid spamming SSE events).
        reasoning_emit_chars = int(os.getenv("STUDY_MATERIALS_REASONING_EMIT_CHARS") or "240")
        if reasoning_emit_chars <= 0:
            reasoning_emit_chars = 240
        reasoning_emit_interval_s = float(os.getenv("STUDY_MATERIALS_REASONING_EMIT_INTERVAL_S") or "0.25")
        reasoning_emit_interval_s = max(0.05, min(reasoning_emit_interval_s, 2.0))

        for attempt in range(max_retries):
            req_id = f"{req_id_base}-{attempt + 1}"
            start_ts = llm_console.log_start(
                req_id=req_id,
                provider=provider,
                model=normalized_model,
                stream=bool(payload.get("stream")),
                temperature=float(payload.get("temperature") or 0.0),
                max_tokens=int(payload.get("max_tokens") or 0),
                base_url=base_url,
            )
            try:
                async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
                    url = f"{base_url}/chat/completions"

                    if bool(payload.get("stream")):
                        async with client.stream("POST", url, headers=headers, json=payload) as resp:
                            if resp.status_code in retry_statuses and attempt < (max_retries - 1):
                                retry_after = (resp.headers.get("retry-after") or "").strip()
                                wait_s = 0.0
                                try:
                                    wait_s = float(retry_after) if retry_after else 0.0
                                except ValueError:
                                    wait_s = 0.0
                                if wait_s <= 0:
                                    wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                                last_error = f"http_status_{resp.status_code}"
                                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                                await asyncio.sleep(wait_s)
                                continue

                            if resp.status_code != 200:
                                try:
                                    await resp.aread()
                                except Exception:
                                    pass
                            resp.raise_for_status()

                            content_parts: List[str] = []
                            reasoning_buf = ""
                            finish_reason = ""
                            usage: Dict[str, Any] = {}
                            loop = asyncio.get_running_loop()
                            last_emit_t = loop.time()

                            async for line in resp.aiter_lines():
                                if not line:
                                    continue
                                if line.startswith(":"):
                                    continue
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if not data:
                                    continue
                                if data == "[DONE]":
                                    break

                                try:
                                    obj = json.loads(data)
                                except Exception:
                                    continue

                                choices = obj.get("choices")
                                if not isinstance(choices, list) or not choices:
                                    continue
                                choice0 = choices[0] if isinstance(choices[0], dict) else {}
                                delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}

                                r_chunk = ""
                                details = delta.get("reasoning_details")
                                if isinstance(details, list) and details:
                                    text_parts: List[str] = []
                                    summary_parts: List[str] = []
                                    for it in details:
                                        if not isinstance(it, dict):
                                            continue
                                        if isinstance(it.get("text"), str) and it.get("text"):
                                            text_parts.append(str(it.get("text") or ""))
                                        elif isinstance(it.get("summary"), str) and it.get("summary"):
                                            summary_parts.append(str(it.get("summary") or ""))
                                    if text_parts:
                                        r_chunk = "".join(text_parts)
                                    elif summary_parts:
                                        r_chunk = "".join(summary_parts)
                                elif isinstance(delta.get("reasoning_content"), str):
                                    r_chunk = str(delta.get("reasoning_content") or "")
                                elif isinstance(delta.get("reasoning"), str):
                                    r_chunk = str(delta.get("reasoning") or "")

                                if r_chunk:
                                    reasoning_buf += r_chunk
                                    now_t = loop.time()
                                    if len(reasoning_buf) >= reasoning_emit_chars or (now_t - last_emit_t) >= reasoning_emit_interval_s:
                                        await _emit_thinking_delta(reasoning_buf)
                                        llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)
                                        reasoning_buf = ""
                                        last_emit_t = now_t

                                c_chunk = delta.get("content")
                                if isinstance(c_chunk, str) and c_chunk:
                                    content_parts.append(c_chunk)
                                    llm_console.log_delta(req_id=req_id, channel="content", text=c_chunk)

                                fr_chunk = choice0.get("finish_reason")
                                if isinstance(fr_chunk, str) and fr_chunk:
                                    finish_reason = fr_chunk

                                if isinstance(obj.get("usage"), dict):
                                    usage = dict(obj.get("usage") or {})

                            if reasoning_buf:
                                await _emit_thinking_delta(reasoning_buf)
                                llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_buf)

                            content_text = "".join(content_parts)
                            llm_console.log_end(
                                req_id=req_id,
                                elapsed_s=_elapsed_s(start_ts),
                                finish_reason=finish_reason,
                                usage=usage,
                                content_chars=len(content_text),
                            )
                            return {"content": content_text, "finish_reason": finish_reason, "usage": usage}

                    resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code in retry_statuses and attempt < (max_retries - 1):
                    retry_after = (resp.headers.get("retry-after") or "").strip()
                    wait_s = 0.0
                    try:
                        wait_s = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        wait_s = 0.0
                    if wait_s <= 0:
                        wait_s = min(8.0, (2**attempt) * 0.9 + random.random() * 0.6)
                    last_error = f"http_status_{resp.status_code}"
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(wait_s)
                    continue

                resp.raise_for_status()
                data = resp.json()

                # Best-effort: if the provider returns reasoning in non-stream mode, surface it once.
                if stream_reasoning:
                    try:
                        msg = data.get("choices", [{}])[0].get("message", {}) if isinstance(data, dict) else {}
                        reasoning_text = ""
                        if isinstance(msg, dict):
                            if isinstance(msg.get("reasoning"), str):
                                reasoning_text = str(msg.get("reasoning") or "")
                            elif isinstance(msg.get("reasoning_content"), str):
                                reasoning_text = str(msg.get("reasoning_content") or "")
                        if reasoning_text:
                            await _emit_thinking_delta(reasoning_text)
                            llm_console.log_delta(req_id=req_id, channel="reasoning", text=reasoning_text)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass

                content = ""
                finish_reason = ""
                usage: Dict[str, Any] = {}
                try:
                    choices = data.get("choices")
                    first = choices[0] if isinstance(choices, list) and choices else {}
                    if isinstance(first, dict):
                        msg = first.get("message") if isinstance(first.get("message"), dict) else {}
                        content = str((msg or {}).get("content") or "")
                        finish_reason = str(first.get("finish_reason") or "")
                except Exception:
                    content = ""
                    finish_reason = ""
                if isinstance(data.get("usage"), dict):
                    usage = dict(data.get("usage") or {})
                if content:
                    llm_console.log_delta(req_id=req_id, channel="content", text=content)
                llm_console.log_end(
                    req_id=req_id,
                    elapsed_s=_elapsed_s(start_ts),
                    finish_reason=finish_reason,
                    usage=usage,
                    content_chars=len(content),
                )
                return {"content": content, "finish_reason": finish_reason, "usage": usage}
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                api_msg = _resp_error(exc.response)
                last_error = f"http_status_{status}"
                if status in {400, 422} and (not dropped_reasoning) and ("reasoning" in payload):
                    try:
                        payload.pop("reasoning", None)
                        payload["stream"] = False
                    except Exception:
                        pass
                    dropped_reasoning = True
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue
                if status in {400, 422} and provider == "moonshot":
                    msg_l = (api_msg or "").lower()
                    try:
                        current_t = float(payload.get("temperature") or 0.0)
                    except Exception:
                        current_t = 0.0
                    if ("temperature" in msg_l and "only 1" in msg_l) and current_t != 1.0:
                        try:
                            payload["temperature"] = 1.0
                        except Exception:
                            pass
                        llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
                        await asyncio.sleep(0.2)
                        continue
                if status in retry_statuses and attempt < (max_retries - 1):
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
                if raise_on_fail:
                    raise RuntimeError(
                        f"llm_request_failed status={status} model={normalized_model} provider={provider} msg={api_msg or last_error}"
                    )
                return {"content": "", "finish_reason": "", "usage": {}}
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_error = str(exc)
                if attempt < (max_retries - 1):
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if raise_on_fail:
                    raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
                return {"content": "", "finish_reason": "", "usage": {}}
            except Exception as exc:  # pragma: no cover (best-effort)
                last_error = str(exc)
                if attempt < (max_retries - 1):
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                    continue
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if raise_on_fail:
                    raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
                return {"content": "", "finish_reason": "", "usage": {}}

        if last_error:
            try:
                print(f"[llm] request failed after retries: {last_error}", flush=True)
            except Exception:
                pass
        if raise_on_fail:
            raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error or 'unknown'}")
        return {"content": "", "finish_reason": "", "usage": {}}

    async def _call_llm_markdown_with_continuation(
        self,
        *,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = LESSON_PLAN_TEMPERATURE,
        max_tokens: int = LESSON_PLAN_MAX_TOKENS,
        reasoning: Optional[Dict[str, Any]] = None,
        continuation_context: Optional[Dict[str, Any]] = None,
        max_continuations: int = 2,
        raise_on_fail: bool = False,
        retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        res = await self._call_llm_response(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            raise_on_fail=raise_on_fail,
            retries=retries,
        )
        content = str(res.get("content") or "").strip()
        finish_reason = str(res.get("finish_reason") or "").strip().lower()
        usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
        conts = 0

        def _is_truncated(text: str, fr: str, usage_obj: Any) -> bool:
            if (fr or "").strip().lower() == "length":
                return True
            if _looks_truncated_markdown(text):
                return True
            if isinstance(usage_obj, dict):
                try:
                    ct = int(usage_obj.get("completion_tokens") or 0)
                except Exception:
                    ct = 0
                if ct and max_tokens and ct >= int(max_tokens * 0.95):
                    return True
            return False

        try:
            max_continuations = int(max_continuations or 0)
        except Exception:
            max_continuations = 0
        max_continuations = max(0, min(max_continuations, 5))

        ctx_obj = dict(continuation_context) if isinstance(continuation_context, dict) else {}
        while conts < max_continuations and content and _is_truncated(content, finish_reason, usage):
            tail = content[-1600:]
            payload = dict(ctx_obj)
            payload["existing_markdown_tail"] = tail
            payload["instructions"] = (
                "上一次输出疑似被截断。请严格从 existing_markdown_tail 的末尾继续补全。\n"
                "仅输出需要追加的 Markdown，不要重复前文。\n"
                "若最后一行是未完成的句子/公式/列表，请先把该行补完再继续。\n"
                "小节标题从 #### 开始，禁止输出 #/##/###。\n"
                "不输出参考资料/外部链接，不输出任何 URL；不输出 [[1]] 等证据标记。\n"
                "数学公式：行内 $...$，独立行 $$...$$。\n"
            )
            cont_res = await self._call_llm_response(
                messages=[
                    {
                        "role": "system",
                        "content": "你是严谨的 Markdown 续写助手，只输出需要追加的内容，不要重复前文。",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                raise_on_fail=raise_on_fail,
                retries=retries,
            )
            addition = str(cont_res.get("content") or "").strip()
            finish_reason = str(cont_res.get("finish_reason") or "").strip().lower()
            usage = cont_res.get("usage") if isinstance(cont_res.get("usage"), dict) else {}
            if not addition:
                break
            addition = _trim_overlap(content, addition)
            if not addition.strip():
                break
            if not content.endswith("\n") and (
                addition.startswith("####")
                or addition.startswith("- ")
                or addition.startswith("* ")
                or addition.startswith(">")
                or addition.startswith("```")
            ):
                content = content + "\n"
            content = (content + addition).rstrip()
            conts += 1

        if content and _looks_truncated_markdown(content):
            content = _repair_incomplete_markdown(content)

        return {
            "content": content,
            "finish_reason": finish_reason,
            "usage": usage,
            "continuations": conts,
        }

    def _extract_json_obj(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}
        # Strip markdown code fences.
        if raw.startswith("```"):
            stripped = raw.strip()
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1 :]
            if stripped.endswith("```"):
                stripped = stripped[: -3]
            raw = stripped.strip()
        # Fast path: whole string is JSON.
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass

        # Robust path: find the last valid JSON object in the string.
        try:
            decoder = json.JSONDecoder()
            starts = [i for i, ch in enumerate(raw) if ch == "{"]
            for i in reversed(starts):
                try:
                    obj, end = decoder.raw_decode(raw[i:])
                except Exception:
                    continue
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
        return {}

    def _pick_questions(self, questions: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        cleaned: List[Tuple[int, Dict[str, Any]]] = []
        for q in questions:
            stem = str(q.get("stem") or "")
            if not stem or len(stem) < 8:
                continue
            # Prefer fewer images and reasonable length.
            penalty = 0
            penalty += stem.count("[图片:") * 50
            penalty += max(0, len(stem) - 500) // 20
            cleaned.append((penalty, q))
        cleaned.sort(key=lambda x: x[0])
        return [q for _, q in cleaned[: max(1, limit)]]

    async def _tool_split_knowledge_points(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将主题拆分为多个可检索的子知识点。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)
        min_points = int(args.get("min_points") or 3)
        max_points = int(args.get("max_points") or 8)
        min_points = max(1, min(min_points, 10))
        max_points = max(min_points, min(max_points, 15))

        def _clean_points(items: List[Any]) -> List[str]:
            out: List[str] = []
            seen: set[str] = set()
            for it in items or []:
                s = str(it or "").strip()
                s = re.sub(r"\s+", " ", s)
                s = s.strip(" -—·•\t\r\n")
                if not s:
                    continue
                if len(s) > 60:
                    s = s[:60].rstrip() + "…"
                if s in seen:
                    continue
                seen.add(s)
                out.append(s)
                if len(out) >= max_points:
                    break
            return out

        def _extract_wiki_headings(content: str) -> List[str]:
            if not content:
                return []
            # Wikipedia plaintext headings often look like: "== 标题 ==" or "=== 标题 ==="
            headings = re.findall(r"^==+\s*(.+?)\s*==+\s*$", content, flags=re.MULTILINE)
            cleaned: List[str] = []
            stop_exact = {
                "参见",
                "参考文献",
                "外部链接",
                "注释",
                "延伸阅读",
                "参考资料",
                "脚注",
            }
            stop_contains = ["参考", "链接", "注释"]
            for h in headings:
                s = str(h or "").strip()
                s = re.sub(r"\s+", " ", s)
                s = re.sub(r"[（(].*?[）)]", "", s).strip()
                if not s:
                    continue
                if s in stop_exact:
                    continue
                if any(x in s for x in stop_contains):
                    continue
                if len(s) < 2 or len(s) > 24:
                    continue
                cleaned.append(s)
            return cleaned

        async def _split_from_wikipedia() -> List[str]:
            """Best-effort: use Wikipedia page structure to derive sub-knowledge points."""
            try:
                from backend.mcp.wikipedia_search import wikipedia_search as _wiki
            except Exception:
                return []

            q = topic
            # Provide a small disambiguation hint for math topics.
            if subject and "数学" in subject and "数学" not in q:
                q = f"{q} 数学"
            try:
                res = await _wiki(
                    query=q,
                    lang="zh",
                    sentences=2,
                    auto_suggest=True,
                    search_results=5,
                    max_content_length=5000,
                )
            except Exception:
                return []

            if not isinstance(res, dict) or not res.get("success"):
                return []

            content = str(res.get("content") or "")
            headings = _extract_wiki_headings(content)
            hits = res.get("search_hits") if isinstance(res.get("search_hits"), list) else []
            hits = [str(x or "").strip() for x in hits if str(x or "").strip()]

            generic_headings = {"概述", "定义", "性质", "定理", "方法", "应用", "相关概念", "基本概念"}
            candidates: List[str] = []
            for h in headings:
                if h in generic_headings:
                    candidates.append(f"{topic} {h}")
                else:
                    candidates.append(h)
            # Prefer a few related search hits (often include key terms).
            candidates.extend(hits[:8])
            return _clean_points(candidates)

        def _split_by_templates() -> List[str]:
            """Domain heuristics for common topics when no LLM is configured."""
            t = topic
            cands: List[str] = []

            # Projective geometry (射影几何 / 射影)
            if "射影" in t:
                cands.extend(
                    [
                        "射影空间",
                        "齐次坐标",
                        "射影变换",
                        "交比（射影不变量）",
                        "对偶原理",
                        "德萨格定理",
                        "帕普斯定理",
                        "消失点与透视投影",
                        "圆锥曲线的射影性质",
                    ]
                )

            # Generic math fallbacks (still searchable)
            if ("数学" in subject) or ("几何" in t) or ("代数" in t) or ("函数" in t):
                cands.extend(
                    [
                        f"{t} 基本概念",
                        f"{t} 典型性质",
                        f"{t} 常见题型",
                        f"{t} 易错点",
                    ]
                )
            return _clean_points(cands)

        # LLM-powered split when configured.
        if LESSON_PLAN_API_KEY or MOONSHOT_API_KEY:
            prompt = {
                "topic": topic,
                "subject": subject,
                "instructions": (
                    "请把 topic 拆分为若干个可用于检索的子知识点（短语级关键词）。\n"
                    f"- 数量：{min_points} 到 {max_points} 个\n"
                    "- 每个子知识点尽量具体、互不重复\n"
                    "- 仅输出严格 JSON（不要 Markdown、不要代码块）\n"
                    '- JSON 格式：{"knowledge_points": ["...", "..."]}\n'
                ),
            }
            text = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=self.config.planner_model,
                temperature=0.2,
                max_tokens=2400,
                response_format={"type": "json_object"},
                raise_on_fail=strict_llm,
            )
            obj = self._extract_json_obj(text)
            points = _clean_points(list(obj.get("knowledge_points") or []))
            if len(points) >= min_points:
                return {
                    "topic": topic,
                    "subject": subject,
                    "knowledge_points": points,
                    "source": "llm",
                }
            if strict_llm:
                raise RuntimeError(
                    f"llm_split_failed: got={len(points)} min_points={min_points} model={self.config.planner_model}"
                )
        elif strict_llm:
            raise RuntimeError("llm_not_configured")

        # Heuristic fallback: split by punctuation if user provided a list.
        raw = re.split(r"[\n,，;；、/|]+", topic)
        points = _clean_points([x for x in raw if str(x).strip()])

        # If still too few points (single concept), try Wikipedia headings + templates.
        if len(points) < min_points:
            wiki_points = await _split_from_wikipedia()
            points = _clean_points(points + wiki_points)

        if len(points) < min_points:
            tpl_points = _split_by_templates()
            points = _clean_points(points + tpl_points)

        if not points and topic:
            points = [topic]

        # Ensure at least min_points when possible (pad with safe variants).
        if topic and len(points) < min_points:
            pads = [topic]
            pads.extend([f"{topic} 基本概念", f"{topic} 常见题型", f"{topic} 典型例题"])
            points = _clean_points(points + pads)

        return {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points or ([topic] if topic else []),
            "source": "heuristic+",
            "note": "未配置拆分模型或拆分不足，使用 Wikipedia 结构 + 规则模板增强拆分。",
        }

    async def _tool_review_knowledge_points(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """审核并微调知识点列表（去重/补全/粒度调整）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)

        min_points = int(args.get("min_points") or 2)
        max_points = int(args.get("max_points") or 8)
        min_points = max(1, min(min_points, 10))
        max_points = max(min_points, min(max_points, 15))

        def _clean_points(items: List[Any]) -> List[str]:
            out: List[str] = []
            seen: set[str] = set()
            for it in items or []:
                s = str(it or "").strip()
                s = re.sub(r"\s+", " ", s)
                s = s.strip(" -—·•\t\r\n")
                if not s:
                    continue
                if len(s) > 60:
                    s = s[:60].rstrip() + "…"
                if s in seen:
                    continue
                seen.add(s)
                out.append(s)
                if len(out) >= max_points:
                    break
            return out

        provided = args.get("knowledge_points")
        points: List[str] = []
        if isinstance(provided, list):
            points = _clean_points(list(provided))

        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
                points = _clean_points(list(split_res.get("knowledge_points") or []))

        original = list(points)

        source = "heuristic"
        note = ""

        if strict_llm and not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")

        if (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) and points:
            model = str(os.getenv("STUDY_MATERIALS_KP_REVIEW_MODEL") or self.config.planner_model or "").strip()
            if not model:
                model = self.config.planner_model

            prompt = {
                "topic": topic,
                "subject": subject,
                "knowledge_points": points,
                "requirements": [
                    f"请审核并微调上述知识点列表，使其更适合『逐点检索 + 逐点生成自学讲解』。",
                    f"数量要求：{min_points}~{max_points} 个；尽量不超过 {max_points} 个。",
                    "去重：合并重复/同义项；避免过泛（如“概念”“性质”单独出现）。",
                    "补全：如明显缺失关键子主题，可补充 1~3 个，但不要发散到无关内容。",
                    "粒度：短语级关键词，便于搜索与组织讲解；尽量保持原有顺序逻辑。",
                    "只输出严格 JSON：{\"knowledge_points\": [...], \"note\": \"...\"}（不要 Markdown，不要多余文字）。",
                ],
            }
            last_err = ""
            for attempt in range(3):
                text = await self._call_llm_text(
                    messages=[
                        {"role": "system", "content": "你是严谨的教研员，输出必须是JSON。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    model=model,
                    temperature=0.2,
                    max_tokens=2400,
                    response_format={"type": "json_object"},
                    raise_on_fail=strict_llm,
                )
                obj = self._extract_json_obj(text)
                revised = obj.get("knowledge_points")
                if isinstance(revised, list):
                    cleaned = _clean_points(list(revised))
                    if len(cleaned) >= min_points:
                        points = cleaned[:max_points]
                        source = "llm"
                        note = str(obj.get("note") or "").strip()
                        break
                    last_err = f"too_few_points got={len(cleaned)} min={min_points}"
                    if strict_llm and attempt < 2:
                        continue
                else:
                    last_err = "invalid_json"
                    if strict_llm and attempt < 2:
                        continue

                # Non-strict mode: accept heuristic fallback after one attempt.
                break

            if strict_llm and source != "llm":
                raise RuntimeError(f"llm_review_failed: {last_err or 'unknown'} model={model}")

        if topic and len(points) < min_points:
            pads = [
                topic,
                f"{topic} 基本概念",
                f"{topic} 常见题型",
                f"{topic} 典型例题",
                f"{topic} 易错点",
            ]
            points = _clean_points(points + pads)

        points = points[:max_points] if points else ([topic] if topic else [])

        out = {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points,
            "source": f"review_{source}",
        }
        if note:
            out["note"] = note

        removed = [x for x in original if x not in points]
        added = [x for x in points if x not in original]
        if removed or added:
            out["changes"] = {"removed": removed[:10], "added": added[:10]}

        # Make the reviewed list the canonical list for downstream foreach execution.
        try:
            ctx.working_memory["split_knowledge_points"] = {
                "topic": topic,
                "subject": subject,
                "knowledge_points": points,
                "source": f"review_{source}",
                "note": note,
            }
        except Exception:
            pass

        return out

    async def _tool_web_search_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """网络搜索知识点：Metaso 优先（可返回 summary 报告型文本）。

        - 默认使用 Metaso 直接 API（无需额外 MCP 进程）。
        - 若 Metaso 未配置，则回退到 Exa / BigModel（兼容旧配置）。
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        limit = int(args.get("limit") or 5)
        # Allow more per-knowledge-point calls when the user enables deeper presets; keep a safe upper bound.
        limit = max(1, min(limit, 25))
        query_hint = str(args.get("query_hint") or "").strip()
        scope = str(args.get("scope") or "webpage").strip() or "webpage"
        include_summary = bool(args.get("include_summary", True))
        text_max_length = int(args.get("text_max_length") or 2600)
        text_max_length = max(200, min(text_max_length, 8000))
        strict_llm = self._strict_llm(ctx, args)
        if strict_llm and not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")

        # Study preset helps SubAgent choose better sub-questions and prompt style.
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(args.get("preset") or study_opts.get("preset") or os.getenv("STUDY_MATERIALS_PRESET") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = ""

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.metaso_search import metaso_ask, metaso_search

        def _env_truthy(name: str, default: bool = False) -> bool:
            raw = (os.getenv(name) or "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "y", "on"}

        def _clamp_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
            try:
                n = int(value)
            except Exception:
                n = default
            return max(min_value, min(max_value, n))

        def _clean_metaso_answer(text: str) -> str:
            """Best-effort cleanup for Metaso /ask answers.

            Metaso often returns answers with:
            - blockquote prefixes (already handled in metaso_ask)
            - evidence markers like [[1]]
            - meta narration: "我需要/用户/证据/搜索到的资料..."
            """

            raw = (text or "").strip()
            if not raw:
                return ""

            # Drop simple evidence markers.
            raw = re.sub(r"\[\[\s*\d+\s*\]\]", "", raw)
            raw = re.sub(r"\(\[\[\s*\d+\s*\]\]\)", "", raw)
            # Keep newlines (Metaso answers are often structured); only collapse horizontal spaces/tabs.
            raw = re.sub(r"[ \t]{2,}", " ", raw).strip()

            meta_tokens = (
                "用户",
                "证据",
                "资料",
                "搜索到",
                "我需要",
                "我将",
                "让我",
                "Let's",
                "the user",
                "evidence",
            )
            content_markers = ("定义", "直观", "关键", "误区", "方法", "结论", "应用", "例", "注意")

            lines = [ln.rstrip() for ln in raw.splitlines()]
            out: List[str] = []
            started = False
            for ln in lines:
                s = (ln or "").strip()
                if not s:
                    continue

                # Skip leading meta narration before the first useful marker appears.
                if not started:
                    if any(tok in s for tok in content_markers):
                        started = True
                    elif any(tok in s for tok in meta_tokens) and len(s) <= 140:
                        continue
                    elif s.startswith(("好的", "Okay", "首先")) and len(s) <= 80:
                        continue

                # Skip in-body meta sentences that are short and clearly process narration.
                if any(tok in s for tok in meta_tokens) and len(s) <= 120:
                    continue

                out.append(s)

            cleaned = "\n".join(out).strip()
            # Avoid returning empty if our heuristic was too aggressive.
            return cleaned or raw

        async def _decompose_sub_questions(*, knowledge_point: str, base_query: str) -> List[str]:
            """Use the LLM (DeepSeek v3.2) to refine a broad knowledge point into smaller askable questions."""

            # Allow overriding the "thinking" model separately (some providers expose a thinking variant).
            thinking_model = str(
                os.getenv("STUDY_MATERIALS_THINKING_MODEL")
                or self.config.planner_model
                or self.config.summarizer_model
            ).strip()

            sub_n = _clamp_int(
                args.get("sub_questions"),
                default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_SUBQUERIES") or 4, default=4, min_value=2, max_value=25),
                min_value=2,
                max_value=25,
            )

            # If LLM isn't configured, fall back to a deterministic template split (non-strict only).
            if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                if strict_llm:
                    raise RuntimeError("llm_not_configured")
                tpl = [
                    f"{knowledge_point} 的定义与符号约定是什么？适用条件是什么？",
                    f"{knowledge_point} 的直观理解/几何意义是什么？",
                    f"{knowledge_point} 有哪些关键结论/性质？每条结论的使用前提是什么？",
                    f"{knowledge_point} 常见误区有哪些？各给一个反例或纠错点。",
                    f"{knowledge_point} 常用方法/步骤是什么？",
                    f"{knowledge_point} 有哪些等价表述/充分必要条件？容易混淆的相近概念是什么？",
                    f"{knowledge_point} 的边界情况/反例/不适用场景有哪些？",
                    f"{knowledge_point} 的推导/证明思路（非细节）应该怎样组织？",
                ]
                # Research presets: encourage deeper angles.
                if preset in {"deep", "research"}:
                    return tpl[:sub_n]
                return tpl[:sub_n]

            prompt = {
                "subject": subject,
                "knowledge_point": knowledge_point,
                "base_query": base_query,
                "query_hint": query_hint,
                "requirements": [
                    f"请将知识点拆成 {sub_n} 个适合向『联网问答 API』提问的子问题（每个子问题一句话）。",
                    "子问题要覆盖：定义/直观理解/关键结论与条件/常见误区/方法步骤（可合并，但要覆盖）。",
                    "尽量包含：等价表述/充分必要条件、边界情况/反例、不适用条件、与相近概念的区别（若适用）。"
                    if preset in {"deep", "research"}
                    else "（可选）如存在等价表述/边界情况/反例，也可作为子问题的一部分。",
                    "尽量包含：推导/证明思路的“骨架”（若适用）。" if preset in {"deep", "research"} else "（可选）需要时可补充推导/证明思路。",
                    "子问题要足够具体，避免泛泛而谈；每个子问题尽量能检索到不同角度的资料。",
                    "只输出严格 JSON，不要输出任何解释性文字。",
                ],
                "output_schema": {"sub_questions": ["string"]},
            }

            last_err = ""
            for attempt in range(3):
                text = await self._call_llm_text(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是严谨的知识探索助手（面向自学资料）。"
                                "请先在心里思考如何拆分问题，再只输出 JSON。"
                            ),
                        },
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    model=thinking_model,
                    temperature=0.2,
                    max_tokens=1600,
                    response_format={"type": "json_object"},
                    raise_on_fail=strict_llm,
                )
                obj = self._extract_json_obj(text)
                items = obj.get("sub_questions")
                if isinstance(items, list):
                    out = []
                    for it in items:
                        s = str(it or "").strip()
                        s = re.sub(r"\s+", " ", s)
                        if not s:
                            continue
                        if len(s) > 120:
                            s = s[:120].rstrip() + "…"
                        out.append(s)
                    # Ensure we always return something usable.
                    if len(out) >= 2:
                        return out[:sub_n]
                    last_err = f"too_few_items got={len(out)}"
                    if strict_llm and attempt < 2:
                        continue
                else:
                    last_err = "invalid_json"
                    if strict_llm and attempt < 2:
                        continue
                break

            if strict_llm:
                raise RuntimeError(f"llm_decompose_failed: {last_err or 'unknown'} model={thinking_model}")

            # LLM failed to follow schema; use templates as fallback.
            tpl = [
                f"{knowledge_point} 的定义与符号约定是什么？适用条件是什么？",
                f"{knowledge_point} 的直观理解/几何意义是什么？",
                f"{knowledge_point} 的关键结论/性质有哪些？每条结论的使用前提是什么？",
                f"{knowledge_point} 常见误区有哪些？各给一个反例或纠错点。",
                f"{knowledge_point} 常用方法/步骤是什么？",
                f"{knowledge_point} 的等价表述/充分必要条件有哪些？",
                f"{knowledge_point} 的边界情况/反例/不适用场景有哪些？",
                f"{knowledge_point} 的推导/证明思路（非细节）如何组织？",
            ]
            return tpl[:sub_n]

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            # Check if Exa Answer should be used (new default)
            use_exa_answer = _env_truthy("STUDY_MATERIALS_USE_EXA_ANSWER", True)
            exa_answer_mode = str(args.get("search_mode") or os.getenv("STUDY_MATERIALS_SEARCH_MODE") or "").strip().lower()
            if exa_answer_mode == "metaso":
                use_exa_answer = False
            elif exa_answer_mode == "exa":
                use_exa_answer = True

            # 0) Exa Answer API (preferred when configured)
            if use_exa_answer:
                try:
                    from backend.mcp.exa_web_search import exa_answer, EXA_API_KEY

                    if EXA_API_KEY:
                        # Decompose into sub-questions for better coverage
                        decompose = args.get("decompose")
                        if decompose is None:
                            decompose = _env_truthy("STUDY_MATERIALS_WEB_DECOMPOSE", True)
                        decompose = bool(decompose)

                        sub_questions = [base_query]
                        if decompose:
                            sub_questions = await _decompose_sub_questions(knowledge_point=point, base_query=base_query)

                        # Ask Exa for each sub-question
                        sub_conc = _clamp_int(
                            args.get("sub_concurrency"),
                            default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_CONCURRENCY") or 2, default=2, min_value=1, max_value=4),
                            min_value=1,
                            max_value=4,
                        )
                        sub_sem = asyncio.Semaphore(sub_conc)

                        async def _exa_ask_one(sub_q: str) -> Dict[str, Any]:
                            async with sub_sem:
                                return await exa_answer(
                                    query=sub_q,
                                    num_results=min(5, limit),
                                    include_text=True,
                                    text_max_length=min(1500, text_max_length),
                                )

                        exa_calls = await asyncio.gather(*[_exa_ask_one(q) for q in sub_questions])

                        cleaned_results: List[Dict[str, Any]] = []
                        summary_parts: List[str] = []
                        errors: List[str] = []
                        queries: List[str] = []

                        for sub_q, res in zip(sub_questions, exa_calls):
                            queries.append(sub_q)

                            if not isinstance(res, dict) or not res.get("success"):
                                err = str(res.get("error") or "exa answer failed").strip() if isinstance(res, dict) else "exa answer failed"
                                errors.append(f"{sub_q}: {err}")
                                continue

                            ans = _strip_evidence_markers(str(res.get("answer") or "").strip())
                            if ans:
                                summary_parts.append(f"【{sub_q}】\n{_clip_text(ans, max_chars=900)}")

                            for c in (res.get("citations") or []):
                                if not isinstance(c, dict):
                                    continue
                                cleaned_results.append(_postprocess_web_search_result({
                                    "title": c.get("title", ""),
                                    "url": c.get("url", ""),
                                    "snippet": c.get("text", ""),
                                    "published_date": c.get("published_date"),
                                }))

                        # Deduplicate results by URL
                        keep_sources = _clamp_int(
                            args.get("keep_sources"),
                            default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_KEEP_SOURCES") or limit, default=limit, min_value=3, max_value=15),
                            min_value=3,
                            max_value=15,
                        )
                        deduped: List[Dict[str, Any]] = []
                        seen_urls: set[str] = set()
                        for r in cleaned_results:
                            url_value = str(r.get("url") or "").strip()
                            key = url_value or json.dumps(r, ensure_ascii=False, sort_keys=True)
                            if key in seen_urls:
                                continue
                            seen_urls.add(key)
                            deduped.append(r)
                            if len(deduped) >= keep_sources:
                                break

                        summary_value = "\n\n".join(summary_parts).strip()

                        # If we got useful results, return them
                        if summary_value or deduped:
                            return {
                                "knowledge_point": point,
                                "base_query": base_query,
                                "query": base_query,
                                "queries": queries[:12],
                                "provider": "exa-answer+decompose" if decompose else "exa-answer",
                                "scope": scope,
                                "include_summary": True,
                                "summary": summary_value or "(Exa Answer 未返回摘要)",
                                "results": deduped,
                                "sub_questions": sub_questions,
                                "errors": errors[:6],
                            }

                        # If Exa failed completely, fall through to Metaso
                        if errors:
                            print(f"[web_search] Exa Answer failed for {point}, falling back to Metaso: {errors[:2]}", flush=True)
                except Exception as exc:
                    print(f"[web_search] Exa Answer exception for {point}, falling back to Metaso: {exc}", flush=True)

            metaso_mode = str(args.get("metaso_mode") or os.getenv("STUDY_MATERIALS_METASO_MODE") or "ask").strip().lower()
            if metaso_mode not in {"ask", "search"}:
                metaso_mode = "ask"

            # 1) Metaso（fallback when Exa not configured or failed）
            metaso: Dict[str, Any]
            if metaso_mode == "ask":
                # Sub-agent behavior: decompose the knowledge point into smaller questions, then ask.
                decompose = args.get("decompose")
                if decompose is None:
                    decompose = _env_truthy("STUDY_MATERIALS_WEB_DECOMPOSE", True)
                decompose = bool(decompose)

                # How many sources to keep overall (not per sub-question)
                keep_sources = _clamp_int(
                    args.get("keep_sources"),
                    default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_KEEP_SOURCES") or limit, default=limit, min_value=3, max_value=15),
                    min_value=3,
                    max_value=15,
                )

                # Per-sub-question size: keep small because we ask multiple times.
                sub_size = _clamp_int(
                    args.get("sub_size"),
                    default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_SIZE") or min(5, limit), default=min(5, limit), min_value=2, max_value=10),
                    min_value=2,
                    max_value=10,
                )

                metaso_format = str(args.get("metaso_format") or os.getenv("METASO_ASK_FORMAT") or "simple")
                metaso_model = str(args.get("metaso_model") or os.getenv("METASO_ASK_MODEL") or "")

                sub_questions = [base_query]
                if decompose:
                    sub_questions = await _decompose_sub_questions(knowledge_point=point, base_query=base_query)

                # Ask Metaso for each sub-question; cap concurrency to avoid rate-limits.
                sub_conc = _clamp_int(
                    args.get("sub_concurrency"),
                    default=_clamp_int(os.getenv("STUDY_MATERIALS_WEB_SUBQUERY_CONCURRENCY") or 2, default=2, min_value=1, max_value=3),
                    min_value=1,
                    max_value=3,
                )
                sub_sem = asyncio.Semaphore(sub_conc)

                async def _ask_one(sub_q: str) -> Dict[str, Any]:
                    # Important: we treat Metaso as *retrieval + research notes* here, not the final writer.
                    # If we ask Metaso to write long paragraphs, downstream LLMs tend to copy them verbatim.
                    prompt_lines = [
                        "你是自学资料的研究助理。请输出“可用于写教材的研究笔记”，而不是直接写教材正文。",
                        "输出要求：",
                        "1) 中文；分小节输出：定义/符号约定、直观理解、关键结论(含适用条件)、常见误区(含纠正要点或反例提示)、常用方法/解题套路、关键词/同义词(可含英文/符号)。",
                        "2) 尽量用要点列表；避免长段落；单条建议 ≤ 40 字。",
                        "3) 不要输出网址/链接；不要输出 [[1]] 这类证据标记；不要输出过程性叙述(如“根据搜索/证据/资料”).",
                        "4) 不确定处请标注“可能/待核实”，不要编造。",
                        "5)（研究型）尽量写清：适用条件/边界情况/反例提示；如存在等价表述/充分必要条件请指出。"
                        if preset in {"deep", "research"}
                        else "5) 尽量写清适用条件与限制条件。",
                        "6)（研究型）若适用，请补充 3~8 行推导/证明骨架（不是完整证明）。"
                        if preset == "research"
                        else "",
                        f"知识点：{base_query}",
                        f"子问题：{sub_q}",
                    ]
                    if query_hint:
                        prompt_lines.append(f"关注要点（关键词）：{query_hint}")
                    metaso_q = "\n".join(prompt_lines).strip()

                    async with sub_sem:
                        return await metaso_ask(
                            query=metaso_q,
                            scope=scope,
                            size=sub_size,
                            format=metaso_format,
                            model=metaso_model,
                        )

                metaso_calls = await asyncio.gather(*[_ask_one(q) for q in sub_questions])

                cleaned_results: List[Dict[str, Any]] = []
                summary_parts: List[str] = []
                errors: List[str] = []
                queries: List[str] = []

                for sub_q, res in zip(sub_questions, metaso_calls):
                    # Track queries for observability/merging.
                    queries.append(sub_q)

                    if not isinstance(res, dict) or not res.get("success"):
                        err = str(res.get("error") or "metaso ask failed").strip() if isinstance(res, dict) else "metaso ask failed"
                        errors.append(f"{sub_q}: {err}")
                        continue

                    ans = _clean_metaso_answer(str(res.get("answer") or "").strip())
                    if ans:
                        # Keep each block compact; downstream will still do its own LLM writing.
                        summary_parts.append(f"【{sub_q}】\n{_clip_text(ans, max_chars=900)}")

                    for r in (res.get("results") or []):
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_postprocess_web_search_result(r))

                # Deduplicate results by URL and keep bounded.
                deduped: List[Dict[str, Any]] = []
                seen_urls: set[str] = set()
                for r in cleaned_results:
                    url_value = str(r.get("url") or "").strip()
                    key = url_value or json.dumps(r, ensure_ascii=False, sort_keys=True)
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    deduped.append(r)
                    if len(deduped) >= keep_sources:
                        break

                summary_value = "\n\n".join(summary_parts).strip()
                if not summary_value and errors:
                    summary_value = "（Metaso /ask 未返回可用内容：" + "; ".join(errors[:2]) + "）"

                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": base_query,
                    "queries": queries[:12],
                    "provider": "metaso-ask+decompose" if decompose else "metaso-ask",
                    "scope": scope,
                    "include_summary": True,
                    "summary": summary_value,
                    "results": deduped,
                    "sub_questions": sub_questions,
                    "errors": errors[:6],
                }

            # metaso_mode == "search"
            metaso = await metaso_search(query=query, scope=scope, include_summary=include_summary, size=limit)

            if isinstance(metaso, dict) and metaso.get("success"):
                cleaned_results: List[Dict[str, Any]] = []
                for r in (metaso.get("results") or []):
                    if not isinstance(r, dict):
                        continue
                    cleaned_results.append(_postprocess_web_search_result(r))
                cleaned_results = cleaned_results[: max(1, limit)]

                summary_value = str(metaso.get("summary") or "").strip()

                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "metaso",
                    "scope": scope,
                    "include_summary": include_summary,
                    "summary": summary_value,
                    "results": cleaned_results,
                }

            # 2) Legacy fallback：Exa -> BigModel MCP broker（best-effort）
            try:
                from backend.mcp.exa_web_search import exa_search
                from backend.mcp.bigmodel_web_search import web_search_with_bigmodel_mcp

                exa = await exa_search(
                    query=query,
                    num_results=limit,
                    use_autoprompt=True,
                    type="neural",
                    include_text=True,
                    text_max_length=text_max_length,
                )
                exa_results = exa.get("results") if isinstance(exa, dict) else []
                if isinstance(exa_results, list) and exa_results:
                    cleaned_results: List[Dict[str, Any]] = []
                    for r in exa_results:
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_postprocess_web_search_result(r))
                    return {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": query,
                        "queries": [query],
                        "provider": "exa",
                        "results": cleaned_results,
                        "autoprompt_string": exa.get("autoprompt_string") if isinstance(exa, dict) else None,
                        "error": str(metaso.get("error") or "").strip() if isinstance(metaso, dict) else "",
                    }

                zhipu = await web_search_with_bigmodel_mcp(query=query, limit=limit)
                if isinstance(zhipu, dict) and zhipu.get("success") and zhipu.get("results"):
                    cleaned_results = []
                    for r in (zhipu.get("results") or []):
                        if not isinstance(r, dict):
                            continue
                        cleaned_results.append(_postprocess_web_search_result(r))
                    return {
                        "knowledge_point": point,
                        "base_query": base_query,
                        "query": query,
                        "queries": [query],
                        "provider": str(zhipu.get("provider") or "zhipu-bigmodel-mcp-web-search"),
                        "results": cleaned_results,
                        "error": str(metaso.get("error") or "").strip() if isinstance(metaso, dict) else "",
                    }

                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "results": [],
                    "error": str(metaso.get("error") or "web search failed").strip()
                    if isinstance(metaso, dict)
                    else "web search failed",
                }
            except Exception as exc:  # pragma: no cover
                return {
                    "knowledge_point": point,
                    "base_query": base_query,
                    "query": query,
                    "queries": [query],
                    "provider": "none",
                    "results": [],
                    "error": str(exc) or "web search failed",
                }

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "query": point,
                        "provider": "none",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "limit": limit,
            "query_hint": query_hint,
            "scope": scope,
            "include_summary": include_summary,
            "text_max_length": text_max_length,
            "items": items,
        }

    async def _tool_github_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """GitHub 搜索：为每个知识点检索可能的高质量笔记/资料仓库。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        sort = str(args.get("sort") or "stars").strip() or "stars"
        order = str(args.get("order") or "desc").strip() or "desc"
        include_readme = bool(args.get("include_readme", False))
        readme_limit = int(args.get("readme_limit") or (2 if include_readme else 0))
        readme_limit = max(0, min(readme_limit, 3))
        readme_max_chars = int(args.get("readme_max_chars") or 3000)
        readme_max_chars = max(200, min(readme_max_chars, 10000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        existing_by_kp: Dict[str, Dict[str, Any]] = {}
        try:
            prev_blob = ctx.working_memory.get("github_search")
            if isinstance(prev_blob, dict) and isinstance(prev_blob.get("items"), list):
                for it in prev_blob.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        existing_by_kp[kp] = it
        except Exception:
            existing_by_kp = {}

        from backend.mcp.github_search import github_fetch_readme, github_search_repositories

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            # Bias toward repositories with documentation.
            gh_query = f"{query} in:readme"

            prev = existing_by_kp.get(point) or {}
            prev_queries = prev.get("queries") if isinstance(prev.get("queries"), list) else []
            prev_results = prev.get("results") if isinstance(prev.get("results"), list) else []
            if (prev.get("query") == gh_query or gh_query in prev_queries) and prev_results:
                # If README enrichment is requested, ensure it already exists for the top few repos.
                if include_readme and readme_limit > 0:
                    need_readme = False
                    for r in prev_results[:readme_limit]:
                        if not isinstance(r, dict):
                            continue
                        if not str(r.get("readme_excerpt") or "").strip():
                            need_readme = True
                            break
                    if not need_readme:
                        cached = dict(prev)
                        cached["success"] = True
                        cached["cache_hit"] = True
                        return cached
                else:
                    cached = dict(prev)
                    cached["success"] = True
                    cached["cache_hit"] = True
                    return cached

            res = await github_search_repositories(gh_query, limit=limit, sort=sort, order=order)
            if not isinstance(res, dict) or not res.get("success"):
                return {
                    "knowledge_point": point,
                    "success": False,
                    "query": gh_query,
                    "provider": "github",
                    "results": [],
                    "error": str((res or {}).get("error") or "github search failed"),
                    "note": str((res or {}).get("note") or ""),
                }

            results = res.get("results") or []
            if include_readme and readme_limit > 0 and isinstance(results, list) and results:
                enriched: List[Dict[str, Any]] = []
                for r in results:
                    enriched.append(r if isinstance(r, dict) else {})
                for r in enriched[:readme_limit]:
                    full_name = str(r.get("full_name") or "").strip()
                    if not full_name:
                        continue
                    rd = await github_fetch_readme(full_name, max_chars=readme_max_chars)
                    if isinstance(rd, dict) and rd.get("success") and rd.get("readme"):
                        r["readme_excerpt"] = str(rd.get("readme") or "")
                results = enriched

            out: Dict[str, Any] = {
                "knowledge_point": point,
                "success": True,
                "query": gh_query,
                "queries": [gh_query],
                "provider": "github",
                "results": results,
                "total_count": res.get("total_count") or 0,
            }
            note = str(res.get("note") or "").strip()
            if note:
                out["note"] = note
            return out

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "success": False,
                        "query": point,
                        "provider": "github",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "limit": limit,
            "query_hint": query_hint,
            "items": items,
        }

    async def _tool_stackexchange_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """StackExchange 搜索：为每个知识点检索高质量问答解释。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        limit = int(args.get("limit") or 5)
        limit = max(1, min(limit, 10))
        query_hint = str(args.get("query_hint") or "").strip()
        site = str(args.get("site") or "math.stackexchange").strip() or "math.stackexchange"
        include_answers = bool(args.get("include_answers", True))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        existing_by_kp: Dict[str, Dict[str, Any]] = {}
        try:
            prev_blob = ctx.working_memory.get("stackexchange_search")
            if isinstance(prev_blob, dict) and isinstance(prev_blob.get("items"), list):
                for it in prev_blob.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        existing_by_kp[kp] = it
        except Exception:
            existing_by_kp = {}

        from backend.mcp.stackexchange_search import stackexchange_search

        async def _search_one(point: str) -> Dict[str, Any]:
            base_query = f"{subject} {point}".strip() if subject and subject not in point else point
            query = base_query
            if query_hint:
                query = f"{query} {query_hint}".strip()

            prev = existing_by_kp.get(point) or {}
            prev_queries = prev.get("queries") if isinstance(prev.get("queries"), list) else []
            prev_results = prev.get("results") if isinstance(prev.get("results"), list) else []
            if (prev.get("query") == query or query in prev_queries) and prev_results:
                cached = dict(prev)
                cached["success"] = True
                cached["cache_hit"] = True
                return cached

            res = await stackexchange_search(
                query=query,
                site=site,
                limit=limit,
                include_answers=include_answers,
                max_question_chars=3200,
                max_answer_chars=3200,
            )
            if not isinstance(res, dict) or not res.get("success"):
                return {
                    "knowledge_point": point,
                    "success": False,
                    "query": query,
                    "site": site,
                    "provider": "stackexchange",
                    "results": [],
                    "error": str((res or {}).get("error") or "stackexchange search failed"),
                }
            return {
                "knowledge_point": point,
                "success": True,
                "query": query,
                "queries": [query],
                "site": site,
                "provider": "stackexchange",
                "results": res.get("results") or [],
            }

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _search_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "knowledge_point": point,
                        "success": False,
                        "query": point,
                        "site": site,
                        "provider": "stackexchange",
                        "results": [],
                        "error": str(exc),
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "site": site,
            "limit": limit,
            "query_hint": query_hint,
            "items": items,
        }

    async def _tool_mediawiki_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """MediaWiki 百科检索（可用于 Wikipedia/Wikibooks/ProofWiki 等 MediaWiki 站点）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        # Base URL building:
        # - if base_url provided: use it directly
        # - else: build from project + lang, e.g. https://zh.wikibooks.org/
        base_url = str(args.get("base_url") or "").strip()
        project = str(args.get("project") or "").strip().lower()
        lang = str(args.get("lang") or "zh").strip() or "zh"

        if not base_url:
            if project in {"wikipedia", "wikibooks", "wikiversity", "wikisource", "wiktionary"}:
                domain = "wikipedia.org" if project == "wikipedia" else f"{project}.org"
                base_url = f"https://{lang}.{domain}/"
            elif project:
                base_url = str(project)

        sentences = int(args.get("sentences") or 5)
        sentences = max(1, min(sentences, 10))
        search_results = int(args.get("search_results") or 5)
        search_results = max(1, min(search_results, 10))
        max_content_length = int(args.get("max_content_length") or 6000)
        max_content_length = max(200, min(max_content_length, 8000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        existing_by_kp: Dict[str, Dict[str, Any]] = {}
        try:
            prev_blob = ctx.working_memory.get("mediawiki_search")
            if isinstance(prev_blob, dict) and isinstance(prev_blob.get("items"), list):
                for it in prev_blob.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        existing_by_kp[kp] = it
        except Exception:
            existing_by_kp = {}

        from backend.mcp.mediawiki_search import mediawiki_search

        async def _lookup_one(point: str) -> Dict[str, Any]:
            query = f"{subject} {point}".strip() if subject and subject not in point else point
            prev = existing_by_kp.get(point) or {}
            prev_query = str(prev.get("query") or "").strip()
            prev_base = str(prev.get("base_url") or "").strip()
            if prev_query == query and prev_base and prev_base == base_url and str(prev.get("content") or prev.get("summary") or "").strip():
                cached = dict(prev)
                cached["success"] = True
                cached["cache_hit"] = True
                return cached
            res = await mediawiki_search(
                query=query,
                base_url=base_url,
                sentences=sentences,
                search_results=search_results,
                max_content_length=max_content_length,
            )
            payload = res if isinstance(res, dict) else {"success": False, "error": "invalid mediawiki response"}
            payload["knowledge_point"] = point
            payload["provider"] = payload.get("provider") or "mediawiki_api"
            return payload

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _lookup_one(point)
                except Exception as exc:  # pragma: no cover
                    return {
                        "success": False,
                        "knowledge_point": point,
                        "query": point,
                        "error": str(exc),
                        "provider": "mediawiki_api",
                        "base_url": base_url,
                    }

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {
            "topic": topic,
            "subject": subject,
            "base_url": base_url,
            "project": project,
            "lang": lang,
            "sentences": sentences,
            "search_results": search_results,
            "max_content_length": max_content_length,
            "items": items,
        }

    async def _tool_browse_web_pages(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Browse and extract readable text from top web-search results for each knowledge point.

        Best-effort "browseuse" behavior:
        - Uses prior `web_search_knowledge` outputs in working_memory to pick URLs
        - Fetches pages via httpx and extracts visible text using BeautifulSoup
        """

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        top_k = int(args.get("top_k") or 2)
        top_k = max(1, min(top_k, 5))
        max_chars = int(args.get("max_chars") or 8000)
        max_chars = max(800, min(max_chars, 30000))
        timeout_s = float(args.get("timeout_s") or 18)
        timeout_s = max(5.0, min(timeout_s, 60.0))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        def _map_by_point(blob: Any) -> Dict[str, Dict[str, Any]]:
            if not isinstance(blob, dict):
                return {}
            items = blob.get("items")
            if isinstance(items, list):
                mapped: Dict[str, Dict[str, Any]] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if kp:
                        mapped[kp] = it
                return mapped
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                return {kp: blob}  # type: ignore[return-value]
            return {}

        web_map = _map_by_point(ctx.working_memory.get("web_search_knowledge"))
        gh_map = _map_by_point(ctx.working_memory.get("github_search"))
        se_map = _map_by_point(ctx.working_memory.get("stackexchange_search"))
        wiki_map = _map_by_point(ctx.working_memory.get("wikipedia_search"))
        mw_map = _map_by_point(ctx.working_memory.get("mediawiki_search"))

        def _extract_urls(results: Any) -> List[str]:
            if not isinstance(results, list):
                return []
            urls: List[str] = []
            seen: set[str] = set()
            for r in results:
                if not isinstance(r, dict):
                    continue
                u = str(r.get("url") or r.get("link") or "").strip()
                if not u or not u.startswith(("http://", "https://")):
                    continue
                key = u.lower()
                if key in seen:
                    continue
                seen.add(key)
                urls.append(u)
                if len(urls) >= max(10, top_k * 3):
                    break
            return urls

        def _normalize_url_for_fetch(u: str) -> str:
            raw = (u or "").strip()
            if not raw:
                return ""
            try:
                parsed = urlparse(raw)
                host = (parsed.netloc or "").lower()
                if host == "link.zhihu.com":
                    qs = parse_qs(parsed.query or "")
                    target = qs.get("target", [""])[0]
                    if target:
                        return unquote(str(target))
                return raw
            except Exception:
                return raw

        def _is_zhihu_url(u: str) -> bool:
            try:
                host = (urlparse(u).netloc or "").lower()
            except Exception:
                return False
            return host == "zhihu.com" or host.endswith(".zhihu.com")

        async def _fetch_one(url: str, *, client: httpx.AsyncClient) -> Dict[str, Any]:
            url = _normalize_url_for_fetch(url) or url

            if _is_zhihu_url(url):
                cookies = (os.getenv("ZHIHU_COOKIES") or "").strip()
                try:
                    from backend.mcp.zhihu_fetcher import ZhihuFetcher
                except Exception as exc:
                    return {"url": url, "success": False, "error": f"zhihu_fetcher not available: {exc}"}

                try:
                    zh_timeout = int(max(5.0, min(float(timeout_s), 60.0)))
                except Exception:
                    zh_timeout = 30

                fetcher = ZhihuFetcher(cookies=cookies, timeout_seconds=zh_timeout)
                res = await fetcher.fetch(url)
                payload = res.to_dict()

                if not bool(payload.get("success")):
                    out: Dict[str, Any] = {
                        "url": url,
                        "success": False,
                        "provider": "zhihu",
                        "error": str(payload.get("error") or "fetch_failed"),
                        "title": str(payload.get("title") or "").strip(),
                        "author": str(payload.get("author") or "").strip(),
                        "date": str(payload.get("date") or "").strip(),
                        "zhihu_type": str(payload.get("type") or "").strip(),
                    }
                    out = {k: v for k, v in out.items() if v not in ("", None)}
                    if out.get("error") == "cookies_required" and not cookies:
                        out["note"] = "需要登录态：请在环境变量或 .env 配置 ZHIHU_COOKIES"
                    return out

                text = str(payload.get("content_markdown") or "").strip()
                if len(text) > max_chars:
                    text = text[: max_chars - 1].rstrip() + "…"

                out = {
                    "url": url,
                    "success": True,
                    "provider": "zhihu",
                    "content_type": "text/markdown",
                    "zhihu_type": str(payload.get("type") or "").strip(),
                    "title": str(payload.get("title") or "").strip(),
                    "author": str(payload.get("author") or "").strip(),
                    "date": str(payload.get("date") or "").strip(),
                    "chars": len(text),
                    "text": text,
                }
                return {k: v for k, v in out.items() if v not in ("", None)}

            # Skip non-HTML-ish resources.
            if url.lower().endswith((".pdf", ".zip", ".rar", ".7z")):
                return {"url": url, "success": False, "error": "unsupported file type"}
            try:
                resp = await client.get(url)
                ct = str(resp.headers.get("content-type") or "").lower()
                if "application/pdf" in ct:
                    return {"url": url, "success": False, "error": "pdf not supported", "content_type": ct}
                html = resp.text or ""
            except Exception as exc:
                return {"url": url, "success": False, "error": str(exc)}

            try:
                from bs4 import BeautifulSoup  # type: ignore
            except Exception as exc:
                return {"url": url, "success": False, "error": f"beautifulsoup4 not available: {exc}"}

            try:
                soup = BeautifulSoup(html, "lxml")
                for tag in soup(
                    [
                        "script",
                        "style",
                        "noscript",
                        "svg",
                        "canvas",
                        "iframe",
                        "form",
                        "input",
                        "button",
                        "textarea",
                        "select",
                        "option",
                    ]
                ):
                    try:
                        tag.decompose()
                    except Exception:
                        pass
                for tag in soup(["header", "footer", "nav", "aside"]):
                    try:
                        tag.decompose()
                    except Exception:
                        pass
                try:
                    for tag in soup.find_all(
                        attrs={"role": re.compile(r"^(navigation|banner|contentinfo|complementary)$", re.I)}
                    ):
                        try:
                            tag.decompose()
                        except Exception:
                            pass
                except Exception:
                    pass

                title = ""
                try:
                    title = str(soup.title.string or "").strip() if soup.title else ""
                except Exception:
                    title = ""

                body = soup.body or soup
                candidates: List[Any] = []

                def _add(node: Any) -> None:
                    if node is None:
                        return
                    if node not in candidates:
                        candidates.append(node)

                _add(body.find("article"))
                _add(body.find("main"))
                _add(body.find(id="mw-content-text"))
                _add(body.find(id="bodyContent"))
                _add(body.find(id="content"))
                _add(body.find(id="main"))
                try:
                    _add(body.find("div", class_=re.compile(r"(content|main|article|post|entry|text|lemma|summary)", re.I)))
                except Exception:
                    pass
                try:
                    _add(body.find("div", id=re.compile(r"(content|main|article|post|entry|text)", re.I)))
                except Exception:
                    pass

                def _len_text(node: Any) -> int:
                    try:
                        return len(node.get_text(" ", strip=True))
                    except Exception:
                        return 0

                root = max(candidates, key=_len_text, default=body)
                extracted = root.get_text("\n", strip=True)
                extracted = _remove_ui_noise(extracted)
                if len(extracted) > max_chars:
                    extracted = extracted[: max_chars - 1].rstrip() + "…"

                return {
                    "url": url,
                    "success": True,
                    "title": title,
                    "content_type": ct,
                    "chars": len(extracted),
                    "text": extracted,
                }
            except Exception as exc:
                return {"url": url, "success": False, "error": f"parse failed: {exc}"}

        concurrency = int(args.get("concurrency") or 2)
        concurrency = max(1, min(concurrency, 4))
        sem = asyncio.Semaphore(concurrency)
        zhihu_sem = asyncio.Semaphore(min(2, concurrency))

        async def _guarded_fetch(url: str, *, client: httpx.AsyncClient) -> Dict[str, Any]:
            normalized = _normalize_url_for_fetch(url) or url
            async with sem:
                if _is_zhihu_url(normalized):
                    async with zhihu_sem:
                        return await _fetch_one(normalized, client=client)
                return await _fetch_one(normalized, client=client)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        items: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=timeout_s, headers=headers, follow_redirects=True) as client:
            for point in points:
                urls: List[str] = []
                seen: set[str] = set()

                def _add_urls(more: List[str]) -> None:
                    for u in more or []:
                        key = (u or "").strip().lower()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        urls.append(u)

                web = web_map.get(point) or {}
                _add_urls(_extract_urls(web.get("results")))

                se = se_map.get(point) or {}
                _add_urls(_extract_urls(se.get("results")))

                gh = gh_map.get(point) or {}
                _add_urls(_extract_urls(gh.get("results")))

                wiki = wiki_map.get(point) or {}
                wiki_url = str(wiki.get("url") or "").strip()
                if wiki_url.startswith(("http://", "https://")):
                    _add_urls([wiki_url])

                mw = mw_map.get(point) or {}
                mw_url = str(mw.get("url") or "").strip()
                if mw_url.startswith(("http://", "https://")):
                    _add_urls([mw_url])

                urls = urls[: max(0, top_k)]

                if not urls:
                    items.append(
                        {
                            "knowledge_point": point,
                            "success": False,
                            "top_k": top_k,
                            "max_chars": max_chars,
                            "pages": [],
                            "error": "no urls from web/github/stackexchange/wiki sources",
                        }
                    )
                    continue

                pages = await asyncio.gather(*[_guarded_fetch(u, client=client) for u in urls])
                ok = [p for p in pages if isinstance(p, dict) and p.get("success")]
                items.append(
                    {
                        "knowledge_point": point,
                        "success": len(ok) > 0,
                        "top_k": top_k,
                        "max_chars": max_chars,
                        "source": "web_search_knowledge",
                        "pages": pages,
                    }
                )

        return {"topic": topic, "subject": subject, "top_k": top_k, "max_chars": max_chars, "items": items}

    async def _tool_wikipedia_search(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Wikipedia 百科检索（按拆分后的知识点批量查询）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        lang = str(args.get("lang") or "zh").strip() or "zh"
        sentences = int(args.get("sentences") or 4)
        sentences = max(1, min(sentences, 10))
        max_content_length = int(args.get("max_content_length") or 2000)
        max_content_length = max(200, min(max_content_length, 8000))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        from backend.mcp.wikipedia_search import wikipedia_search as _wiki

        async def _lookup_one(point: str) -> Dict[str, Any]:
            query = f"{subject} {point}".strip() if subject and subject not in point else point
            res = await _wiki(
                query=query,
                lang=lang,
                sentences=sentences,
                auto_suggest=True,
                search_results=5,
                max_content_length=max_content_length,
            )
            payload = res if isinstance(res, dict) else {"success": False, "error": "invalid wikipedia response"}
            payload = dict(payload)
            payload["knowledge_point"] = point
            payload["query"] = query
            return payload

        concurrency = int(args.get("concurrency") or 3)
        concurrency = max(1, min(concurrency, 5))
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(point: str) -> Dict[str, Any]:
            async with sem:
                try:
                    return await _lookup_one(point)
                except Exception as exc:  # pragma: no cover
                    return {"success": False, "knowledge_point": point, "query": point, "error": str(exc), "provider": "wikipedia"}

        items = await asyncio.gather(*[_guarded(p) for p in points])
        return {"topic": topic, "subject": subject, "lang": lang, "items": items}

    async def _tool_search_questions_by_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """题库检索：按拆分后的知识点批量搜索例题与练习题。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip() or "中等"
        examples_limit = int(args.get("examples_limit") or 1)
        exercises_limit = int(args.get("exercises_limit") or 4)
        examples_limit = max(0, min(examples_limit, 3))
        exercises_limit = max(0, min(exercises_limit, 10))
        max_pages = int(args.get("max_pages") or 2)
        max_pages = max(1, min(max_pages, 3))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        crawler = await get_crawler(subject=subject)
        applied_subject = subject or getattr(crawler, "subject", "")

        items: List[Dict[str, Any]] = []
        for point in points:
            fetch_limit = int(args.get("limit") or 0) or max(18, (examples_limit + exercises_limit) * 4)
            fetch_limit = max(10, min(fetch_limit, 60))
            try:
                res = await crawler.search_by_knowledge(
                    knowledge_point=point,
                    subject=applied_subject,
                    limit=fetch_limit,
                    difficulty=difficulty,
                    max_pages=max_pages,
                    dedup_by_stem=True,
                    min_quality_score=10,
                    with_quality=True,
                    strict_subject=True,
                    require_difficulty=True,
                )
                questions = list(res.get("questions") or []) if isinstance(res, dict) else []
                examples = self._pick_questions(questions, limit=max(1, examples_limit)) if examples_limit else []
                used_ids = {str(q.get("question_id") or "").strip() for q in examples if isinstance(q, dict)}
                remaining = [
                    q
                    for q in questions
                    if isinstance(q, dict) and str(q.get("question_id") or "").strip() and str(q.get("question_id") or "").strip() not in used_ids
                ]
                exercises = self._pick_questions(remaining, limit=max(1, exercises_limit)) if exercises_limit else []
                items.append(
                    {
                        "knowledge_point": point,
                        "success": bool(res.get("success")) if isinstance(res, dict) and "success" in res else True,
                        "difficulty": difficulty,
                        "examples": examples[:examples_limit] if examples_limit else [],
                        "exercises": exercises[:exercises_limit] if exercises_limit else [],
                        "raw_count": len(questions),
                        "provider": "question-bank",
                    }
                )
            except Exception as exc:  # pragma: no cover
                items.append(
                    {
                        "knowledge_point": point,
                        "success": False,
                        "difficulty": difficulty,
                        "examples": [],
                        "exercises": [],
                        "raw_count": 0,
                        "provider": "question-bank",
                        "error": str(exc),
                    }
                )

        return {
            "topic": topic,
            "subject": applied_subject,
            "difficulty": difficulty,
            "examples_limit": examples_limit,
            "exercises_limit": exercises_limit,
            "items": items,
        }

    async def _tool_generate_study_material(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """基于聚合数据，为每个知识点生成讲解与例题解答。"""

        aggregated = ctx.working_memory.get("aggregate_knowledge") or ctx.working_memory.get("aggregated")
        if not isinstance(aggregated, dict):
            aggregated = {}

        topic = str(args.get("topic") or aggregated.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or aggregated.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        sections_in = aggregated.get("items") if isinstance(aggregated.get("items"), list) else []

        # Study-materials options (passed from API -> TaskManager -> AgentCore).
        # Planner already uses these flags; here we also use them to shape writing style/length.
        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        strict_llm = self._strict_llm(ctx, args)
        if strict_llm and not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")
        preset = str(args.get("preset") or study_opts.get("preset") or "standard").strip().lower() or "standard"
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = "standard"
        requirements = str(args.get("requirements") or study_opts.get("requirements") or "").strip()
        if len(requirements) > 600:
            requirements = requirements[:599].rstrip() + "…"

        # Optional: generate only for specified knowledge points (useful when running per-point subagents).
        requested_points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            requested_points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if requested_points:
            requested_set = {p for p in requested_points}
            sections_in = [
                it
                for it in (sections_in or [])
                if isinstance(it, dict) and str(it.get("knowledge_point") or "").strip() in requested_set
            ]

        max_points = int(args.get("max_points") or 8)
        max_points = max(1, min(max_points, 15))
        max_examples = int(args.get("max_examples") or 1)
        max_examples = max(0, min(max_examples, 2))
        max_web_results = int(args.get("max_web_results") or 8)
        max_web_results = max(3, min(max_web_results, 25))
        max_web_pages = int(args.get("max_web_pages") or 2)
        max_web_pages = max(0, min(max_web_pages, 8))
        max_page_chars = int(args.get("max_page_chars") or 3200)
        max_page_chars = max(500, min(max_page_chars, 8000))
        with_diagrams = bool(args.get("with_diagrams", True))
        with_questions = bool(args.get("with_questions", False))
        max_diagrams = int(
            args.get("max_diagrams")
            or (4 if preset == "deep" else 6 if preset == "research" else 3 if preset == "standard" else 1)
        )
        # Upper bound only; the model is still instructed to output 0~1 unless multiple diagrams truly help.
        max_diagrams = max(0, min(max_diagrams, 20))

        sections: List[Dict[str, Any]] = []
        for item in (sections_in or [])[:max_points]:
            if not isinstance(item, dict):
                continue
            kp = str(item.get("knowledge_point") or "").strip()
            if not kp:
                continue

            writer_model = str(
                os.getenv("STUDY_MATERIALS_WRITER_MODEL")
                or self.config.planner_model
                or self.config.summarizer_model
            ).strip()
            writer_reasoning = None
            writer_max_tokens_raw = str(os.getenv("STUDY_MATERIALS_WRITER_MAX_TOKENS") or "").strip()
            try:
                writer_max_tokens = int(writer_max_tokens_raw) if writer_max_tokens_raw else 0
            except Exception:
                writer_max_tokens = 0
            # "Infinite" (requested): use a very large max_tokens so generation isn't artificially truncated.
            if writer_max_tokens <= 0:
                writer_max_tokens = 200000

            wiki = item.get("wikipedia") if isinstance(item.get("wikipedia"), dict) else {}
            mw = item.get("mediawiki") if isinstance(item.get("mediawiki"), dict) else {}
            web = item.get("web_search") if isinstance(item.get("web_search"), dict) else {}
            pages_blob = item.get("web_pages") if isinstance(item.get("web_pages"), dict) else {}
            gh = item.get("github") if isinstance(item.get("github"), dict) else {}
            se = item.get("stackexchange") if isinstance(item.get("stackexchange"), dict) else {}
            q = item.get("questions") if isinstance(item.get("questions"), dict) else {}

            web_provider = str(web.get("provider") or "").strip()
            web_scope = str(web.get("scope") or "").strip()
            web_summary = str(web.get("summary") or "").strip()
            web_results = web.get("results") if isinstance(web.get("results"), list) else []
            web_results = [r for r in web_results if isinstance(r, dict)][:max_web_results]

            web_pages = pages_blob.get("pages") if isinstance(pages_blob.get("pages"), list) else []
            web_pages = [p for p in web_pages if isinstance(p, dict)]
            web_pages = [p for p in web_pages if p.get("success") and str(p.get("text") or "").strip()]
            web_pages = web_pages[:max_web_pages]

            examples = q.get("examples") if isinstance(q.get("examples"), list) else []
            exercises = q.get("exercises") if isinstance(q.get("exercises"), list) else []
            examples = [x for x in examples if isinstance(x, dict)][: max_examples or 0]
            exercises = [x for x in exercises if isinstance(x, dict)][:10]
            if not with_questions:
                examples = []
                exercises = []

            # Explanation (LLM if configured; fallback to Wikipedia summary)
            explanation_md = ""
            explanation_source = "unknown"
            explanation_finish_reason = ""
            explanation_usage: Dict[str, Any] = {}
            explanation_continuations = 0
            if LESSON_PLAN_API_KEY or MOONSHOT_API_KEY:
                def _clip_text(text: str, limit_chars: int) -> str:
                    t = (text or "").strip()
                    if len(t) <= limit_chars:
                        return t
                    return t[: limit_chars - 1].rstrip() + "…"

                template_lines = [
                    "#### 1) 为什么需要它（动机与问题背景）",
                    "  - 这个概念/方法要解决什么问题？没有它会怎样？",
                    "  - 用一句话概括它的核心价值",
                    "#### 2) 定义与核心表述",
                    "  - 给出精确定义（含符号约定）",
                    "  - 用「一句话版本」帮助记忆",
                    "#### 3) 直观理解（类比与图像）",
                    "  - 用日常生活或已学知识做类比，让读者先建立直觉",
                    '  - 描述"脑中的画面"：如果要画一张图，应该画什么？',
                    "  - 解释「为什么是这样」而不仅是「是什么」",
                    "#### 4) 关键结论与性质",
                    "  - 列出最重要的 3~6 条结论（写清适用条件）",
                    "  - 每条结论用**加粗**突出核心表述",
                    "  - 给出「何时用 / 怎么用」的简要提示",
                    "#### 5) 常见误区与易错点",
                    "  - 误区描述 → 为什么会错 → 正确理解 / 反例",
                    "  - 重点标注「看起来对但实际错」的陷阱",
                    "#### 6) 解题/应用思路小结",
                    "  - 遇到相关问题时的思考框架（2~4 步）",
                    "  - 常用技巧或判断依据",
                ]
                if preset in {"deep", "research"}:
                    template_lines.extend(
                        [
                            "#### 7) 推导/证明思路",
                            "  - 给出 3~8 行的证明框架或推导骨架",
                            "  - 标注关键步骤的「为什么这样做」",
                            "#### 8) 联系与拓展",
                            "  - 前置知识：理解本概念需要先掌握什么？",
                            "  - 相邻概念：与哪些概念容易混淆或有紧密联系？",
                            "  - 典型应用场景举例",
                        ]
                    )
                if preset == "research":
                    template_lines.extend(
                        [
                            "#### 9) 关键例子与反例",
                            "  - 用来检验理解的典型例子（不写成练习题）",
                            "  - 边界情况或反例：帮助界定概念的适用范围",
                            "#### 10) 自检清单",
                            "  - 学完后应能回答的 5 个问题（可用作自我检测）",
                        ]
                    )

                length_note = ""
                if preset == "quick":
                    length_note = "篇幅：尽量精炼；每小节 3~6 条要点为主，避免长段落。"
                elif preset in {"deep", "research"}:
                    length_note = (
                        "篇幅：允许更详细；关键结论尽量 ≥ 5 条，误区 ≥ 3 条（若适用）。"
                        if preset == "deep"
                        else "篇幅：研究型；关键结论尽量 ≥ 6 条，误区 ≥ 3 条，补充推导骨架与自检清单。"
                    )

                extra_req = f"\n额外写作要求（来自用户）：{requirements}\n" if requirements else ""

                instructions = (
                    "【任务】为知识点生成一份可直接自学的讲解（Markdown），嵌入到「### 核心讲解」下方。\n"
                    "\n"
                    f"【生成预设】{preset}\n"
                    f"{length_note}\n"
                    f"{extra_req}"
                    "\n"
                    "【写作理念 — 费曼学习法】\n"
                    "1. 先讲「为什么」：概念要解决什么问题？没有它会怎样？\n"
                    "2. 类比先行：用日常生活或已学知识建立直觉，再给严格定义\n"
                    "3. 渐进深入：从最简单情形讲起，逐步添加复杂度\n"
                    "4. 重点突出：关键结论**加粗**，避免淹没在长段落中\n"
                    "5. 误区预警：主动指出初学者易错点，说明「为何会错」和「如何避免」\n"
                    "\n"
                    "【目标读者】自学者。根据 ability_score 调整深度：\n"
                    "  - 0.0~0.3：侧重直观、类比、生活例子，少用抽象符号\n"
                    "  - 0.4~0.6：直觉与严谨并重，给出完整定义但配合解释\n"
                    "  - 0.7~1.0：可更严谨抽象，补充推导细节和边界条件\n"
                    "\n"
                    "【模板结构】（允许微调顺序，但保留核心小节）\n"
                    + "\n".join(template_lines)
                    + "\n\n"
                    "【硬性格式要求】\n"
                    "- 小节标题从 `####` 开始，禁止输出 `#`/`##`/`###`\n"
                    '- 不输出"参考资料/外部链接"段落，不输出任何 URL\n'
                    "- 不输出 `[[1]]` 等证据标记，不写「根据网页/维基」等过程描述\n"
                    "- 数学公式：行内 $...$，独立行 $$...$$\n"
                    "\n"
                    "【内容质量要求】\n"
                    "- 原创综合：严禁照抄任何数据源（包括 MCP 工具返回的搜索摘要、网页正文、维基百科、StackExchange 等）的原文；\n"
                    "  所有来源仅作为「理解素材」，必须先完全消化，再用你自己的语言重新组织和表达\n"
                    "- 禁止搬运：不得将搜索结果、网页抓取内容或 API 返回的文本直接粘贴或仅做微小改动后输出；\n"
                    "  如果发现某段话与来源高度相似，必须彻底改写（换结构、换表述、换例子）\n"
                    "- 多源整合：综合多条来源的共同结论，不按来源逐条复述，不保留来源的行文结构\n"
                    "- 极短引用：如需引用原句，用引号标注且 ≤20 字，并立即用自己的话解释\n"
                    "- 信息不足时：明确标注「推断」或「建议」\n"
                    "- 不输出例题或练习题\n"
                )

                payload = {
                    "topic": topic,
                    "subject": subject,
                    "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                    "ability_score": float(ctx.user_profile.ability_score or 0.5),
                    "knowledge_point": kp,
                    "wikipedia": {
                        "title": wiki.get("title"),
                        "url": wiki.get("url"),
                        "summary": wiki.get("summary"),
                    },
                    "mediawiki": {
                        "title": mw.get("title"),
                        "url": mw.get("url"),
                        "summary": mw.get("summary"),
                        "base_url": mw.get("base_url"),
                    },
                    "web_provider": web_provider,
                    "web_scope": web_scope,
                    "web_summary": web_summary,
                    "web_results": [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "snippet": _clip_text(
                                str(r.get("snippet") or r.get("text") or ""),
                                900 if preset == "research" else 600,
                            ),
                        }
                        for r in web_results
                    ],
                    "web_pages": [
                        {
                            "title": p.get("title"),
                            "url": p.get("url"),
                            "extract": _clip_text(str(p.get("text") or ""), max_page_chars),
                        }
                        for p in web_pages
                    ],
                    "github_repos": [
                        {
                            "full_name": r.get("full_name"),
                            "url": r.get("url"),
                            "description": r.get("description"),
                            "stars": r.get("stars"),
                            "language": r.get("language"),
                            "readme_excerpt": _clip_text(str(r.get("readme_excerpt") or ""), max_page_chars),
                        }
                        for r in (gh.get("results") if isinstance(gh.get("results"), list) else [])[:10]
                        if isinstance(r, dict)
                    ],
                    "stackexchange": [
                        {
                            "title": r.get("title"),
                            "url": r.get("url"),
                            "score": r.get("score"),
                            "tags": r.get("tags"),
                            "question_text": _clip_text(str(r.get("question_text") or ""), max_page_chars),
                            "top_answer_text": _clip_text(str(r.get("top_answer_text") or ""), max_page_chars),
                        }
                        for r in (se.get("results") if isinstance(se.get("results"), list) else [])[:8]
                        if isinstance(r, dict)
                    ],
                    "instructions": instructions,
                }
                cont_limit_raw = str(os.getenv("STUDY_MATERIALS_MAX_CONTINUATIONS") or "20").strip()
                try:
                    cont_limit = int(cont_limit_raw)
                except Exception:
                    cont_limit = 20
                cont_limit = max(0, min(cont_limit, 100))

                md_res = await self._call_llm_markdown_with_continuation(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是一位经验丰富的教育专家，擅长将复杂概念拆解为可自学的清晰讲解。\n"
                                "你遵循「费曼学习法」：如果不能用简单语言解释清楚，说明还没真正理解。\n"
                                "你的目标是让读者「恍然大悟」，而非堆砌信息。\n"
                                "输出必须是 Markdown。\n"
                                "【最高优先级规则】下方 JSON 中的 wikipedia/web_summary/web_results/web_pages/stackexchange 等字段\n"
                                "仅供你理解知识点，绝对禁止将其原文或近似原文搬入输出。你必须完全用自己的话重写。"
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    model=writer_model,
                    temperature=0.25,
                    max_tokens=writer_max_tokens,
                    reasoning=writer_reasoning,
                    continuation_context={"topic": topic, "subject": subject, "knowledge_point": kp, "preset": preset},
                    max_continuations=cont_limit,
                    raise_on_fail=strict_llm,
                )
                explanation_md = str(md_res.get("content") or "").strip()
                explanation_finish_reason = str(md_res.get("finish_reason") or "").strip()
                explanation_usage = md_res.get("usage") if isinstance(md_res.get("usage"), dict) else {}
                try:
                    explanation_continuations = int(md_res.get("continuations") or 0)
                except Exception:
                    explanation_continuations = 0

                if not explanation_md:
                    # Retry with a smaller payload to reduce context length / provider issues.
                    mini_payload = {
                        "topic": topic,
                        "subject": subject,
                        "ability_level": str(ctx.user_profile.ability_level or "unknown"),
                        "ability_score": float(ctx.user_profile.ability_score or 0.5),
                        "knowledge_point": kp,
                        "wikipedia_summary": _clip_text(str(wiki.get("summary") or ""), 800),
                        "mediawiki_summary": _clip_text(str(mw.get("summary") or ""), 800),
                        "web_summary": _clip_text(web_summary, 1400) if web_summary else "",
                        "web_results": [
                            {"title": r.get("title"), "url": r.get("url"), "snippet": _clip_text(str(r.get("snippet") or r.get("text") or ""), 260)}
                            for r in web_results[:5]
                        ],
                        "instructions": instructions,
                        "note": "上一次生成返回为空，请基于以上摘要重试生成讲解（仍需输出 Markdown）。",
                    }
                    mini_res = await self._call_llm_markdown_with_continuation(
                        messages=[
                            {
                                "role": "system",
                                "content": "你是严谨的自学资料编写老师。所有讲解必须为原创改写与综合，严禁直接搬运或拼贴 MCP/搜索/维基等数据源返回的原文；必须完全用自己的话重新组织。输出必须是 Markdown。",
                            },
                            {"role": "user", "content": json.dumps(mini_payload, ensure_ascii=False)},
                        ],
                        model=writer_model,
                        temperature=0.25,
                        max_tokens=writer_max_tokens,
                        reasoning=writer_reasoning,
                        continuation_context={"topic": topic, "subject": subject, "knowledge_point": kp, "preset": preset},
                        max_continuations=cont_limit,
                        raise_on_fail=strict_llm,
                    )
                    explanation_md = str(mini_res.get("content") or "").strip()
                    explanation_finish_reason = str(mini_res.get("finish_reason") or "").strip()
                    explanation_usage = mini_res.get("usage") if isinstance(mini_res.get("usage"), dict) else {}
                    try:
                        explanation_continuations = int(mini_res.get("continuations") or 0)
                    except Exception:
                        explanation_continuations = 0

                if explanation_md:
                    explanation_source = "llm"
            if not explanation_md:
                # If the main writer LLM isn't configured, optionally fall back to Metaso /ask as a "writer".
                # This keeps the pipeline AI-powered even when only METASO_API_KEY is available.
                if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
                    fallback_raw = (os.getenv("STUDY_MATERIALS_METASO_WRITER_FALLBACK") or "1").strip().lower()
                    use_metaso_writer = fallback_raw in {"1", "true", "yes", "y", "on"}
                    if use_metaso_writer:
                        try:
                            from backend.mcp.metaso_search import metaso_ask as _metaso_ask

                            metaso_template_lines = [
                                "#### 1) 为什么需要它（动机与问题背景）",
                                "#### 2) 定义与核心表述",
                                "#### 3) 直观理解（类比与图像）",
                                "#### 4) 关键结论与性质",
                                "#### 5) 常见误区与易错点",
                                "#### 6) 解题/应用思路小结",
                            ]
                            if preset in {"deep", "research"}:
                                metaso_template_lines.extend(
                                    [
                                        "#### 7) 推导/证明思路",
                                        "#### 8) 联系与拓展（前置知识/相邻概念/典型应用）",
                                    ]
                                )
                            if preset == "research":
                                metaso_template_lines.extend(
                                    [
                                        "#### 9) 关键例子与反例",
                                        "#### 10) 自检清单（学完应能回答的 5 个问题）",
                                    ]
                                )

                            metaso_prompt_lines = [
                                f"请为知识点「{kp}」编写可直接自学的讲解（中文 Markdown）。",
                                "",
                                "【写作理念】费曼学习法：先讲为什么需要，再给定义；用类比建立直觉；重点加粗；主动指出误区。",
                                f"【生成预设】{preset}",
                                f"【额外要求】{requirements}" if requirements else "",
                                "",
                                "【硬性格式要求】",
                                "- 小节标题从 #### 开始，禁止 #/##/###",
                                "- 不输出参考资料/外部链接，不输出任何 URL",
                                "- 不输出 [[1]] 等证据标记，不写过程性叙述",
                                "- 严禁照抄 MCP/搜索/维基等数据源返回的原文，必须完全用自己的话重新组织和表达",
                                "- 数学公式：行内 $...$，独立行 $$...$$",
                                "- 不输出例题或练习题",
                                "",
                                "【模板结构】",
                                *metaso_template_lines,
                            ]
                            metaso_prompt = "\n".join([x for x in metaso_prompt_lines if str(x or "").strip()]).strip()

                            fmt = str(os.getenv("METASO_ASK_FORMAT") or "simple").strip() or "simple"
                            model_hint = str(os.getenv("METASO_ASK_MODEL") or "").strip()
                            metaso_res = await _metaso_ask(
                                query=metaso_prompt,
                                scope="webpage",
                                size=6,
                                format=fmt,
                                model=model_hint,
                            )
                            if isinstance(metaso_res, dict) and metaso_res.get("success") and str(metaso_res.get("answer") or "").strip():
                                explanation_md = str(metaso_res.get("answer") or "").strip()
                                explanation_source = "metaso-ask-writer"
                        except Exception:
                            # Best-effort fallback only; never block the pipeline.
                            pass

                # If the main LLM isn't available or returned empty, prefer Metaso /ask summary notes
                # (already AI-generated) over a raw encyclopedia excerpt.
                if not explanation_md:
                    if strict_llm:
                        raise RuntimeError(f"llm_generation_failed: empty_explanation knowledge_point={kp}")
                    if web_summary:
                        explanation_md = web_summary.strip()
                        explanation_source = web_provider or "web_summary"
                    else:
                        wiki_summary = str(wiki.get("summary") or "").strip()
                        if wiki_summary:
                            explanation_md = f"**百科摘要**：{wiki_summary}\n"
                            explanation_source = "wikipedia"
                        else:
                            mw_summary = str(mw.get("summary") or "").strip()
                            if mw_summary:
                                explanation_md = f"**MediaWiki 摘要**：{mw_summary}\n"
                                explanation_source = "mediawiki"
                            else:
                                explanation_md = "（未获取到可靠百科摘要；以下内容以网络检索笔记为主，建议稍后重试生成。）\n"
                                explanation_source = "fallback"

            explanation_md = _sanitize_explanation_markdown(explanation_md, knowledge_point=kp)

            diagram: Dict[str, Any] = {}
            existing_diagrams: List[Dict[str, Any]] = []
            try:
                diagrams_blob = ctx.working_memory.get("diagrams")
                entries: List[Dict[str, Any]] = []
                if isinstance(diagrams_blob, dict):
                    if isinstance(diagrams_blob.get("items"), list):
                        entries = [x for x in (diagrams_blob.get("items") or []) if isinstance(x, dict)]
                    elif isinstance(diagrams_blob.get("sections"), list):
                        entries = [x for x in (diagrams_blob.get("sections") or []) if isinstance(x, dict)]
                for it in entries:
                    kp0 = str(it.get("knowledge_point") or "").strip()
                    if kp0 != kp:
                        continue
                    ds = it.get("diagrams")
                    if isinstance(ds, list):
                        existing_diagrams = [d for d in ds if isinstance(d, dict)]
                    break
            except Exception:
                existing_diagrams = []

            def _store_extra_diagram(diagram_obj: Dict[str, Any]) -> None:
                try:
                    blob = ctx.working_memory.get("diagrams")
                    if not isinstance(blob, dict):
                        blob = {}
                    items = blob.get("items")
                    if not isinstance(items, list):
                        items = []
                    kp_item: Optional[Dict[str, Any]] = None
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        if str(it.get("knowledge_point") or "").strip() == kp:
                            kp_item = it
                            break
                    if kp_item is None:
                        kp_item = {"knowledge_point": kp, "diagrams": []}
                        items.append(kp_item)
                    dlist = kp_item.get("diagrams")
                    if not isinstance(dlist, list):
                        dlist = []
                    filename = str(diagram_obj.get("filename") or "").strip()
                    if filename and any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
                        return
                    dlist.append(diagram_obj)
                    kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-25:]
                    blob["items"] = [x for x in items if isinstance(x, dict)]
                    ctx.working_memory["diagrams"] = blob
                except Exception:
                    return

            need_diagrams = max(0, int(max_diagrams) - len(existing_diagrams))
            if with_diagrams and (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) and need_diagrams > 0:
                try:
                    context_hints = {
                        "topic": topic,
                        "subject": subject,
                        "knowledge_point": kp,
                        "web_summary": _clip_text(web_summary, 1000) if web_summary else "",
                        "wikipedia_summary": _clip_text(str(wiki.get("summary") or ""), 600) if wiki.get("summary") else "",
                        "mediawiki_summary": _clip_text(str(mw.get("summary") or ""), 600) if mw.get("summary") else "",
                    }
                    prompt = f"""你是数学教学绘图助手。请为知识点「{kp}」生成最多 {need_diagrams} 张“示意图”的 SVG 规范（JSON），用于帮助理解概念。

只输出 JSON 对象，不要输出 Markdown、不要输出代码块。

请输出严格 JSON：{{"diagrams":[{{...}},{{...}}]}}，其中 diagrams 是数组；若不需要画图请输出 {{"diagrams":[]}}。

每张图可以使用这些字段（都可选）：
{{"width":560,"height":320,"padding":24,
  "points":{{"A":[80,240],"B":[440,240],"C":[260,90]}},
  "segments":[["A","B"],{{"from":"B","to":"C","extend":false}},{{"from":"A","to":"C","extend":true,"dash":"6,4"}}],
  "circles":[{{"center":"O","through":"A"}}],
  "labels":[{{"point":"A","text":"A","dx":-12,"dy":16}}],
  "texts":[{{"x":280,"y":30,"text":"...","anchor":"middle"}}],
  "caption":"一句中文图注"
}}

要求：
1) 图形要和「{kp}」强相关，尽量简洁，点/线数量少但表达清楚。
2) 坐标范围：x∈[0,width], y∈[0,height]（SVG 坐标，y 向下）。
3) 每张图 points ≤ 12，segments ≤ 16；不要画复杂背景、不要画大段文字。
4) 图的数量不必凑满：只有确实能帮助理解时才输出多张；否则输出 0~1 张即可。

可参考信息（可能为空）：
{json.dumps(context_hints, ensure_ascii=False)}
"""

                    raw = (
                        await self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的绘图规范生成器，只输出JSON。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=writer_model,
                            temperature=0.2,
                            max_tokens=1800,
                            response_format={"type": "json_object"},
                        )
                    ).strip()

                    obj = self._extract_json_obj(raw)
                    specs = obj.get("diagrams")
                    specs_list: List[Dict[str, Any]] = []
                    if isinstance(specs, list):
                        specs_list = [s for s in specs if isinstance(s, dict)]
                    elif isinstance(obj, dict) and obj:
                        specs_list = [obj]

                    for spec in specs_list[:need_diagrams]:
                        draw_res = await self._tool_draw_svg_diagram({"spec": spec, "alt": f"{kp} 示意图"}, ctx)
                        if not (isinstance(draw_res, dict) and draw_res.get("success")):
                            continue
                        d_obj = {
                            "knowledge_point": kp,
                            "kind": "draw_svg_diagram",
                            "url": str(draw_res.get("url") or "").strip(),
                            "markdown": str(draw_res.get("markdown") or "").strip(),
                            "filename": str(draw_res.get("filename") or "").strip(),
                            "media_id": str(draw_res.get("media_id") or "").strip(),
                            "caption": str(spec.get("caption") or "").strip(),
                        }
                        _store_extra_diagram(d_obj)
                        if not diagram:
                            diagram = {
                                "url": d_obj.get("url"),
                                "markdown": d_obj.get("markdown"),
                                "filename": d_obj.get("filename"),
                                "media_id": d_obj.get("media_id"),
                                "caption": d_obj.get("caption"),
                            }
                except Exception:
                    diagram = {}

            # Example solutions
            solved_examples: List[Dict[str, Any]] = []
            for ex in examples:
                stem = str(ex.get("stem") or "").strip()
                if not stem:
                    continue
                sol_md = ""
                if LESSON_PLAN_API_KEY or MOONSHOT_API_KEY:
                    prompt = (
                        "请为下面例题写出详细分步解答（Markdown）。\n\n"
                        "要求：\n- 每一步说明在做什么\n- 结论清晰\n\n"
                        f"题目：\n{stem}\n"
                    )
                    sol_md = (
                        await self._call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的解题老师，输出必须是Markdown。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=writer_model,
                            temperature=0.3,
                            max_tokens=4000,
                            reasoning=writer_reasoning,
                        )
                    ).strip()
                if not sol_md:
                    sol_md = "（模型未配置或调用失败，无法生成解答。）"
                solved_examples.append(
                    {
                        "question_id": ex.get("question_id"),
                        "stem": stem,
                        "solution_markdown": sol_md,
                        "difficulty": ex.get("difficulty"),
                        "source": ex.get("source"),
                    }
                )

            # LLM fallback when the question bank returns nothing (avoid empty sections in the final archive).
            # Note: question generation is optional and disabled by default (concept-first).
            default_min_exercises = 2 if with_questions else 0
            try:
                min_exercises = int(args.get("min_exercises") or default_min_exercises)
            except Exception:
                min_exercises = default_min_exercises
            min_exercises = max(0, min(min_exercises, 5))

            have_exercise_stems = {
                str(e.get("stem") or "").strip()
                for e in exercises
                if isinstance(e, dict) and str(e.get("stem") or "").strip()
            }
            need_example = bool(with_questions and max_examples > 0 and not solved_examples)
            need_exercises = bool(with_questions and len(have_exercise_stems) < min_exercises)

            if (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) and (need_example or need_exercises):
                example_count = 1 if need_example else 0
                exercise_count = (min_exercises - len(have_exercise_stems)) if need_exercises else 0
                exercise_count = max(0, min(exercise_count, 5))

                prompt = f"""请为知识点「{kp}」生成练习内容，并严格按 JSON 输出（不要 Markdown 代码块，不要额外解释文字）。

需要生成：
- 例题数量：{example_count}（例题需包含详细解答）
- 练习题数量：{exercise_count}（只给题干，不要答案）

JSON 格式必须是：
{{
  "example": {{"stem": "...", "solution_markdown": "..."}},
  "exercises": [{{"stem": "..."}}, {{"stem": "..."}}]
}}

要求：
1) 题目必须与知识点强相关，避免过于宽泛。
2) 数学公式使用 LaTeX：行内用 $...$，独立行用 $$...$$。
3) solution_markdown 必须是 Markdown，包含分步推导与最后结论。
4) stem/solution_markdown 均不要包含外部链接。
5) 如果某项数量为 0，请返回对应为空对象/空数组（例如 example 可以为 {{}}，exercises 可以为 []）。
"""

                raw = (
                    await self._call_llm_text(
                        messages=[
                            {
                                "role": "system",
                                "content": "你是严谨的数学出题与解题老师。你只输出严格 JSON，不输出任何额外文字。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        model=writer_model,
                        temperature=0.3,
                        max_tokens=5000,
                        response_format={"type": "json_object"},
                    )
                ).strip()

                obj = self._extract_json_obj(raw)
                if need_example and isinstance(obj.get("example"), dict):
                    gen_ex = obj.get("example") or {}
                    stem = str(gen_ex.get("stem") or "").strip()
                    sol = str(gen_ex.get("solution_markdown") or "").strip()
                    if stem:
                        solved_examples.append(
                            {
                                "question_id": None,
                                "stem": stem,
                                "solution_markdown": sol or "（未生成到解答内容）",
                                "difficulty": None,
                                "source": "llm-generated",
                            }
                        )

                if need_exercises and isinstance(obj.get("exercises"), list):
                    for item in obj.get("exercises") or []:
                        stem = ""
                        if isinstance(item, dict):
                            stem = str(item.get("stem") or "").strip()
                        else:
                            stem = str(item or "").strip()
                        if not stem or stem in have_exercise_stems:
                            continue
                        exercises.append({"stem": stem, "source": "llm-generated"})
                        have_exercise_stems.add(stem)
                        if len(have_exercise_stems) >= min_exercises:
                            break

            sections.append(
                {
                    "knowledge_point": kp,
                    "explanation_markdown": explanation_md,
                    "explanation_source": explanation_source,
                    "explanation_finish_reason": explanation_finish_reason,
                    "explanation_usage": explanation_usage,
                    "explanation_continuations": explanation_continuations,
                    "wikipedia": wiki,
                    "mediawiki": mw,
                    "web_provider": web_provider,
                    "web_scope": web_scope,
                    "web_summary": web_summary,
                    "diagram": diagram,
                    "web_results": web_results,
                    "web_pages": web_pages,
                    "github": gh,
                    "stackexchange": se,
                    "examples": solved_examples,
                    "exercises": exercises,
                }
            )

        # Note: per-knowledge-point runs are merged by ContextManager.on_step_result (by knowledge_point),
        # so we only return the sections generated in *this* call.
        return {
            "topic": topic,
            "subject": subject,
            "preset": preset,
            "requirements": requirements,
            "sections": sections,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    async def _tool_assemble_study_archive(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将生成内容组装为最终自学档案 Markdown。"""

        material = ctx.working_memory.get("generate_study_material")
        if not isinstance(material, dict):
            material = ctx.working_memory.get("study_material") if isinstance(ctx.working_memory.get("study_material"), dict) else {}

        topic = str(args.get("topic") or material.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or material.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        preset = str(args.get("preset") or material.get("preset") or "").strip().lower()
        if preset and preset not in {"quick", "standard", "deep", "research"}:
            preset = ""
        requirements = str(args.get("requirements") or material.get("requirements") or "").strip()
        if len(requirements) > 160:
            requirements = requirements[:159].rstrip() + "…"
        sections = material.get("sections") if isinstance(material.get("sections"), list) else []

        # Preserve the split order as the final output order (parallel subagents may finish out-of-order).
        split_res = ctx.working_memory.get("split_knowledge_points")
        preferred_order: List[str] = []
        if isinstance(split_res, dict) and isinstance(split_res.get("knowledge_points"), list):
            preferred_order = [
                str(x or "").strip() for x in (split_res.get("knowledge_points") or []) if str(x or "").strip()
            ][:20]

        if preferred_order and sections:
            preferred_set = set(preferred_order)
            by_kp: Dict[str, List[Dict[str, Any]]] = {}
            rest: List[Dict[str, Any]] = []
            for sec in sections:
                if not isinstance(sec, dict):
                    continue
                kp = str(sec.get("knowledge_point") or "").strip()
                if not kp:
                    continue
                if kp in preferred_set:
                    by_kp.setdefault(kp, []).append(sec)
                else:
                    rest.append(sec)

            ordered: List[Dict[str, Any]] = []
            for kp in preferred_order:
                ordered.extend(by_kp.get(kp) or [])
            ordered.extend(rest)
            sections = ordered

        def _link(title: str, url: str) -> str:
            t = (title or "").strip()
            u = (url or "").strip()
            if t and u:
                return f"[{t}]({u})"
            return t or u

        refs_by_kp: Dict[str, List[Dict[str, str]]] = {}
        refs_seen_by_kp: Dict[str, set] = {}

        def _add_ref(*, kp: str, url: str, title: str, source: str) -> None:
            kp_key = (kp or "").strip()
            u = (url or "").strip()
            if not kp_key or not u:
                return
            key = u.split("#")[0].rstrip("/")
            seen = refs_seen_by_kp.setdefault(kp_key, set())
            if key in seen:
                return
            seen.add(key)
            t = (title or "").strip() or u
            s = (source or "").strip() or "web"
            refs_by_kp.setdefault(kp_key, []).append({"url": u, "title": t, "source": s})

        chinese_nums = "一二三四五六七八九十"
        lines: List[str] = []
        lines.append(f"# 自学材料：{topic}")
        meta_lines: List[str] = []
        if subject:
            meta_lines.append(f"> 学科：{subject}")
        if preset:
            meta_lines.append(f"> 生成预设：{preset}")
        if requirements:
            meta_lines.append(f"> 额外要求：{requirements}")
        if meta_lines:
            lines.append("")
            lines.extend(meta_lines)
            lines.append("")

        lines.append("## 使用方式（建议）")
        lines.append("- 先按「知识点目录」顺序学习；每个知识点优先阅读「核心讲解」。")
        lines.append("- 资料来自多轮检索与聚合；建议先读讲解，再按需回查原始材料。")
        lines.append("")

        # Knowledge points list
        lines.append("## 知识点目录")
        kp_list = [
            str(s.get("knowledge_point") or "").strip()
            for s in sections
            if isinstance(s, dict) and str(s.get("knowledge_point") or "").strip()
        ]
        if kp_list:
            for kp in kp_list:
                lines.append(f"- {kp}")
        else:
            lines.append(f"- {topic}")
        lines.append("")

        for idx, sec in enumerate([s for s in sections if isinstance(s, dict)], start=1):
            kp = str(sec.get("knowledge_point") or "").strip()
            if not kp:
                continue
            num = chinese_nums[idx - 1] if 1 <= idx <= len(chinese_nums) else str(idx)
            lines.append(f"## {num}、{kp}")
            lines.append("")

            # 核心讲解（优先展示“AI生成”的部分）
            lines.append("### 核心讲解")
            lines.append("")
            diagram_blob = sec.get("diagram") if isinstance(sec.get("diagram"), dict) else {}
            diagram_md = str(diagram_blob.get("markdown") or "").strip()
            diagram_caption = str(diagram_blob.get("caption") or "").strip()
            diagram_url = str(diagram_blob.get("url") or "").strip()

            diagrams_blob = ctx.working_memory.get("diagrams")
            extra_diagrams: List[Dict[str, Any]] = []
            if isinstance(diagrams_blob, dict):
                entries: List[Dict[str, Any]] = []
                if isinstance(diagrams_blob.get("items"), list):
                    entries = [x for x in (diagrams_blob.get("items") or []) if isinstance(x, dict)]
                elif isinstance(diagrams_blob.get("sections"), list):
                    entries = [x for x in (diagrams_blob.get("sections") or []) if isinstance(x, dict)]
                for it in entries:
                    if str(it.get("knowledge_point") or "").strip() != kp:
                        continue
                    ds = it.get("diagrams")
                    if isinstance(ds, list):
                        extra_diagrams = [d for d in ds if isinstance(d, dict)]
                    break

            extra_urls: set[str] = set()
            for d in extra_diagrams[:8]:
                md = str(d.get("markdown") or "").strip()
                if not md:
                    continue
                u = str(d.get("url") or "").strip()
                if u:
                    extra_urls.add(u)
                cap = str(d.get("caption") or "").strip()
                lines.append(md)
                if cap:
                    lines.append("")
                    lines.append(f"> 图注：{cap}")
                lines.append("")

            if diagram_md and (not diagram_url or diagram_url not in extra_urls):
                lines.append(diagram_md)
                if diagram_caption:
                    lines.append("")
                    lines.append(f"> 图注：{diagram_caption}")
                lines.append("")

            explanation = str(sec.get("explanation_markdown") or "").strip()
            lines.append(explanation or "（讲解为空：可能是模型调用失败或资料不足，建议重试或提供更具体的范围。）")
            explanation_source = str(sec.get("explanation_source") or "").strip()
            if explanation_source and explanation_source != "llm" and not explanation_source.lower().startswith("metaso"):
                lines.append("")
                lines.append(f"> 注：本段讲解未成功使用模型生成（source={explanation_source}），已退回到摘要/兜底内容。若你已配置模型，请稍后重试或更换模型。")
            lines.append("")

            # Collect references; they will be rendered once at the end as a bibliography.
            wiki = sec.get("wikipedia") if isinstance(sec.get("wikipedia"), dict) else {}
            mw = sec.get("mediawiki") if isinstance(sec.get("mediawiki"), dict) else {}
            wiki_title = str(wiki.get("title") or "").strip()
            wiki_url = str(wiki.get("url") or "").strip()
            mw_title = str(mw.get("title") or "").strip()
            mw_url = str(mw.get("url") or "").strip()
            if wiki_url:
                _add_ref(kp=kp, url=wiki_url, title=wiki_title or "词条", source="Wikipedia")
            if mw_url:
                _add_ref(kp=kp, url=mw_url, title=mw_title or "词条", source="MediaWiki")

            web_provider = str(sec.get("web_provider") or "").strip()
            web_source = f"网页检索/{web_provider}" if web_provider else "网页检索"
            web_results = sec.get("web_results") if isinstance(sec.get("web_results"), list) else []
            web_results = [r for r in web_results if isinstance(r, dict)][:8]
            for r in web_results:
                title = str(r.get("title") or "").strip()
                url = str(r.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=title or "网页", source=web_source)

            web_pages = sec.get("web_pages") if isinstance(sec.get("web_pages"), list) else []
            web_pages = [p for p in web_pages if isinstance(p, dict)][:6]
            for p in web_pages:
                title = str(p.get("title") or "").strip()
                url = str(p.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=title or "网页正文", source="网页正文")

            se = sec.get("stackexchange") if isinstance(sec.get("stackexchange"), dict) else {}
            se_results = se.get("results") if isinstance(se.get("results"), list) else []
            se_results = [r for r in se_results if isinstance(r, dict)][:6]
            for r in se_results:
                title = str(r.get("title") or "").strip()
                url = str(r.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=title or "问答", source="StackExchange")

            gh = sec.get("github") if isinstance(sec.get("github"), dict) else {}
            gh_results = gh.get("results") if isinstance(gh.get("results"), list) else []
            gh_results = [r for r in gh_results if isinstance(r, dict)][:6]
            for r in gh_results:
                full_name = str(r.get("full_name") or "").strip()
                url = str(r.get("url") or "").strip()
                if url:
                    _add_ref(kp=kp, url=url, title=full_name or "repo", source="GitHub")

        lines.append("---")
        lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        ctx.working_memory["markdown"] = markdown
        return {
            "topic": topic,
            "subject": subject,
            "knowledge_points": kp_list[:20] if kp_list else ([topic] if topic else []),
            "markdown_chars": len(markdown),
        }

    async def _tool_aggregate_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """聚合：拆分结果 + Web 搜索 + 题库检索（可选：百科/网页正文/问答/GitHub）。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        def _map_by_point(blob: Any) -> Dict[str, Any]:
            if not isinstance(blob, dict):
                return {}
            items = blob.get("items")
            if isinstance(items, list):
                mapped: Dict[str, Any] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    kp = str(it.get("knowledge_point") or "").strip()
                    if not kp:
                        continue
                    mapped[kp] = it
                return mapped
            # Single-result style payload
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                return {kp: blob}
            return {}

        web_map = _map_by_point(ctx.working_memory.get("web_search_knowledge"))
        browse_map = _map_by_point(ctx.working_memory.get("browse_web_pages"))
        wiki_map = _map_by_point(ctx.working_memory.get("wikipedia_search"))
        mw_map = _map_by_point(ctx.working_memory.get("mediawiki_search"))
        gh_map = _map_by_point(ctx.working_memory.get("github_search"))
        se_map = _map_by_point(ctx.working_memory.get("stackexchange_search"))
        q_map = _map_by_point(ctx.working_memory.get("search_questions_by_knowledge"))

        aggregated_items: List[Dict[str, Any]] = []
        for kp in points:
            aggregated_items.append(
                {
                    "knowledge_point": kp,
                    "wikipedia": wiki_map.get(kp) or {},
                    "mediawiki": mw_map.get(kp) or {},
                    "web_search": web_map.get(kp) or {},
                    "web_pages": browse_map.get(kp) or {},
                    "github": gh_map.get(kp) or {},
                    "stackexchange": se_map.get(kp) or {},
                    "questions": q_map.get(kp) or {},
                }
            )

        summary = {
            "topic": topic,
            "subject": subject,
            "knowledge_points": points,
            "items": aggregated_items,
            "counts": {
                "knowledge_points": len(points),
                "web": len([x for x in web_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "pages": len([x for x in browse_map.values() if isinstance(x, dict) and (x.get("pages") or [])]),
                "wiki": len([x for x in wiki_map.values() if isinstance(x, dict) and (x.get("summary") or x.get("content"))]),
                "mediawiki": len([x for x in mw_map.values() if isinstance(x, dict) and (x.get("summary") or x.get("content"))]),
                "github": len([x for x in gh_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "stackexchange": len([x for x in se_map.values() if isinstance(x, dict) and (x.get("results") or [])]),
                "questions": len([x for x in q_map.values() if isinstance(x, dict) and (x.get("questions") or x.get("examples") or x.get("exercises"))]),
            },
        }
        ctx.working_memory["aggregated"] = summary
        return summary

    async def _tool_save_markdown_file(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """保存最终自学档案到 Markdown 文件。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            # Best-effort: try common keys
            markdown = str(ctx.working_memory.get("assemble_study_archive") or ctx.working_memory.get("assemble_markdown") or "").strip()

        rel_dir = str(args.get("dir") or "study_archives").strip() or "study_archives"

        # Resolve repo root: backend/agent/executor.py -> repo root
        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / rel_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize Windows-unfriendly characters in filename.
        safe = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1F]', "_", topic)
        safe = re.sub(r"\\s+", " ", safe).strip()
        safe = safe.strip(". ")
        safe = safe[:80] if len(safe) > 80 else safe
        if not safe:
            safe = "study_archive"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe}_{ts}.md"
        path = out_dir / filename

        try:
            path.write_text(markdown + ("\n" if not markdown.endswith("\n") else ""), encoding="utf-8")
        except Exception as exc:
            return {"success": False, "error": str(exc), "dir": str(out_dir), "filename": filename}

        ctx.working_memory["archive_path"] = str(path)
        return {
            "success": True,
            "path": str(path),
            "dir": str(out_dir),
            "filename": filename,
            "bytes": len((markdown or "").encode("utf-8")),
        }

    async def _tool_export_study_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将最终 Markdown 发布为可下载文件（写入 `.local/media/generated/`）。"""

        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_study_archive") or "").strip()
        if not markdown:
            raise ValueError("markdown_empty")

        data = (markdown + ("\n" if not markdown.endswith("\n") else "")).encode("utf-8")

        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        filename = f"{sha}.md"
        url = f"/api/media/generated/{filename}"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        if not out_path.exists():
            out_path.write_bytes(data)

        try:
            ctx.working_memory["md_url"] = url
            ctx.working_memory["md_filename"] = filename
        except Exception:
            pass

        return {
            "md_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": len(data),
        }

    async def _tool_convert_markdown_to_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """用 LLM 把 Markdown 转成 ElegantBook LaTeX，并发布为可下载 .tex。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)
        # LaTeX export is 100% LLM-dependent; fail fast even if other tools allow fallbacks.
        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")

        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_study_archive") or "").strip()
        if not markdown:
            raise ValueError("markdown_empty")

        model = str(
            os.getenv("STUDY_MATERIALS_LATEX_MODEL")
            or os.getenv("STUDY_MATERIALS_WRITER_MODEL")
            or self.config.planner_model
            or self.config.summarizer_model
        ).strip()
        if not model:
            model = self.config.planner_model or self.config.summarizer_model
        title = f"自学材料：{topic}"
        if subject and subject not in title:
            title = f"{subject}｜{title}"

        template = (
            r"\documentclass[lang=cn]{elegantbook}" "\n"
            r"\usepackage{amsmath,amssymb}" "\n"
            r"\usepackage{graphicx}" "\n"
            r"\usepackage{hyperref}" "\n"
            r"\usepackage{booktabs,longtable}" "\n"
            r"\usepackage{xcolor}" "\n"
            r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}" "\n"
            r"\title{" + title.replace("{", "\\{").replace("}", "\\}") + r"}" "\n"
            r"\author{}" "\n"
            r"\date{\today}" "\n"
            r"\begin{document}" "\n"
            r"\maketitle" "\n\n"
            r"% --- BEGIN_BODY ---" "\n"
            r"<BODY>" "\n"
            r"% --- END_BODY ---" "\n\n"
            r"\end{document}" "\n"
        )

        prompt = {
            "topic": topic,
            "subject": subject,
            "template": template,
            "requirements": [
                "请把下面 Markdown 转为 LaTeX，使用 ElegantBook 模板。",
                "只输出 LaTeX 源码，不要 Markdown 代码块，不要额外解释。",
                "必须保留模板结构，仅替换 <BODY> 部分（不要改动 documentclass/preamble）。",
                "正文用 LaTeX 结构：标题层级 #/##/###/#### 映射为 \\section/\\subsection/\\subsubsection/\\paragraph。",
                "保留数学公式 $...$ 与 $$...$$，确保括号与环境闭合。",
                "列表用 itemize/enumerate；代码块用 verbatim；表格必要时可简化。",
                "图片：只处理 PNG/JPG/JPEG/WebP/GIF/BMP。将 `![](/api/media/generated/xxx.png)` 转为 `\\\\includegraphics[width=0.9\\\\linewidth]{xxx.png}`；遇到 SVG 图片不要插图，改为一句话：`（图略：SVG 见 Markdown 版）`。",
                "不要输出“参考文献/外部链接/URL 列表”。",
            ],
            "markdown": markdown,
        }

        raw = (
            # LaTeX bodies can be long; allow overriding output budget to reduce `finish_reason=length`.
            await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的 LaTeX 排版助手，输出必须是可编译的 LaTeX。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=_clamp_int(os.getenv("STUDY_MATERIALS_LATEX_MAX_TOKENS") or 8000, default=8000, min_value=1200, max_value=20000),
                raise_on_fail=True,
            )
        ).strip()

        if not raw:
            raise RuntimeError("llm_empty_response")

        # Strip code fences if any.
        if raw.startswith("```"):
            first_newline = raw.find("\n")
            if first_newline != -1:
                raw = raw[first_newline + 1 :]
            if raw.endswith("```"):
                raw = raw[: -3]
            raw = raw.strip()

        body = raw
        if "\\begin{document}" in raw:
            body = raw.split("\\begin{document}", 1)[1]
            if "\\end{document}" in body:
                body = body.split("\\end{document}", 1)[0]
        body = body.strip()

        tex = template.replace("<BODY>", body).strip() + "\n"

        tex_bytes = tex.encode("utf-8")
        import hashlib

        sha = hashlib.sha256(tex_bytes).hexdigest()
        filename = f"{sha}.tex"
        url = f"/api/media/generated/{filename}"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        if not out_path.exists():
            out_path.write_bytes(tex_bytes)

        try:
            ctx.working_memory["latex_tex"] = tex
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename
        except Exception:
            pass

        return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": len(tex_bytes), "model": model}

    async def _tool_refine_latex(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """对 LaTeX 做二次修订，尽量减少编译失败与排版问题。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        strict_llm = self._strict_llm(ctx, args)
        # LaTeX refining is LLM-dependent; fail fast to avoid cascading "latex_missing" errors.
        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            raise RuntimeError("llm_not_configured")

        tex = args.get("latex")
        if not isinstance(tex, str) or not tex.strip():
            tex = str(ctx.working_memory.get("latex_tex") or "").strip()
        if not tex:
            raise ValueError("latex_missing")

        compile_error = str(args.get("compile_error") or "").strip()
        if len(compile_error) > 1800:
            compile_error = compile_error[:1799].rstrip() + "…"

        model = str(os.getenv("STUDY_MATERIALS_LATEX_MODEL") or self.config.planner_model or self.config.summarizer_model).strip()
        if not model:
            model = self.config.planner_model or self.config.summarizer_model
        prompt = {
            "topic": topic,
            "subject": subject,
            "requirements": [
                "下面是一份 LaTeX（ElegantBook）。请在不改变整体结构的前提下修订，使其更容易编译且排版更干净。",
                "只输出完整 LaTeX 源码（从 \\documentclass 到 \\end{document}），不要 Markdown 代码块，不要解释。",
                "修复常见问题：未转义的特殊字符（%, _, &, #）、未闭合的环境/括号、错误的图片扩展名（SVG 请改为文字占位而非 includegraphics）。",
                "数学公式保持原意，确保括号闭合。",
                "不要输出参考文献/URL 列表。",
                "如提供 compile_error，请优先修复该错误（缺包/缺文件/语法错误/未闭合环境等）。",
            ],
            "latex": tex,
            "compile_error": compile_error,
        }

        refined = (
            # LaTeX sources can be long; allow overriding output budget to reduce `finish_reason=length`.
            await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的 LaTeX 修订助手，输出必须可编译。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                model=model,
                temperature=0.2,
                max_tokens=_clamp_int(
                    os.getenv("STUDY_MATERIALS_LATEX_REFINE_MAX_TOKENS") or os.getenv("STUDY_MATERIALS_LATEX_MAX_TOKENS") or 8000,
                    default=8000,
                    min_value=1200,
                    max_value=20000,
                ),
                raise_on_fail=True,
            )
        ).strip()

        if not refined:
            raise RuntimeError("llm_empty_response")

        if refined.startswith("```"):
            first_newline = refined.find("\n")
            if first_newline != -1:
                refined = refined[first_newline + 1 :]
            if refined.endswith("```"):
                refined = refined[: -3]
            refined = refined.strip()

        tex_bytes = (refined.strip() + "\n").encode("utf-8")
        import hashlib

        sha = hashlib.sha256(tex_bytes).hexdigest()
        filename = f"{sha}.tex"
        url = f"/api/media/generated/{filename}"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        if not out_path.exists():
            out_path.write_bytes(tex_bytes)

        try:
            ctx.working_memory["latex_tex"] = refined.strip() + "\n"
            ctx.working_memory["tex_url"] = url
            ctx.working_memory["tex_filename"] = filename
        except Exception:
            pass

        return {"tex_url": url, "filename": filename, "sha256": sha, "bytes": len(tex_bytes), "model": model}

    async def _tool_compile_latex_to_pdf(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """编译 LaTeX 为 PDF，并发布为可下载文件。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"

        tex = args.get("latex")
        if not isinstance(tex, str) or not tex.strip():
            tex = str(ctx.working_memory.get("latex_tex") or "").strip()
        if not tex:
            raise ValueError("latex_missing")

        repo_root = Path(__file__).resolve().parents[2]
        gen_dir = (repo_root / ".local" / "media" / "generated").resolve()
        gen_dir.mkdir(parents=True, exist_ok=True)

        build_dir = (repo_root / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
        build_dir.mkdir(parents=True, exist_ok=True)

        tex_path = build_dir / "main.tex"
        tex_path.write_text(tex.strip() + "\n", encoding="utf-8")

        # Copy local generated images referenced by includegraphics into build dir.
        try:
            includes = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
        except Exception:
            includes = []
        copied = 0
        missing: List[str] = []
        for inc in includes[:80]:
            name = str(inc or "").strip()
            if not name:
                continue
            # Strip any path prefixes and keep basename only.
            base = Path(name).name
            if not base:
                continue
            src = gen_dir / base
            if not src.exists() or not src.is_file():
                # Try to resolve /api/media/generated/<file>
                if base.startswith("generated") and "/" in name:
                    base2 = name.split("/")[-1]
                    src = gen_dir / base2
                if not src.exists() or not src.is_file():
                    missing.append(base)
                    continue
            dst = build_dir / base
            try:
                if not dst.exists():
                    dst.write_bytes(src.read_bytes())
                copied += 1
            except Exception:
                continue

        # Compile with xelatex directly (avoid latexmk dependency on perl on Windows/MiKTeX).
        import subprocess

        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        # First-time MiKTeX compilation may be slow (font cache / on-the-fly package install).
        timeout_s = float(os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or 600)
        timeout_s = max(30.0, min(timeout_s, 60.0 * 20.0))

        proc = None
        try:
            # Two passes to resolve references/TOC reliably.
            for _ in range(2):
                proc = subprocess.run(
                    cmd,
                    cwd=str(build_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
                if proc.returncode != 0:
                    break
        except FileNotFoundError as exc:
            raise RuntimeError(f"latex_engine_not_found: {exc}")

        if proc is None or proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            stdout = (getattr(proc, "stdout", "") or "").strip()
            msg = stderr[-2000:] if stderr else stdout[-2000:]
            raise RuntimeError(f"latex_compile_failed: {msg}")

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.exists() or not pdf_path.is_file():
            raise RuntimeError("pdf_missing")

        pdf_bytes = pdf_path.read_bytes()

        import hashlib

        sha = hashlib.sha256(pdf_bytes).hexdigest()
        filename = f"{sha}.pdf"
        url = f"/api/media/generated/{filename}"
        out_path = gen_dir / filename
        if not out_path.exists():
            out_path.write_bytes(pdf_bytes)

        try:
            ctx.working_memory["pdf_url"] = url
            ctx.working_memory["pdf_filename"] = filename
        except Exception:
            pass

        return {
            "pdf_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": len(pdf_bytes),
            "topic": topic,
            "copied_images": copied,
            "missing_images": missing[:20],
            "engine": "xelatex",
        }

    async def _tool_draw_svg_diagram(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Render an SVG diagram and persist it under `.local/media/generated/`.

        Args:
            spec: dict - SVG diagram spec (see `backend/core/svg_diagram.py`)
            alt: str (optional) - used in returned Markdown image tag

        Returns:
            {
              "success": bool,
              "media_id": str,
              "filename": str,
              "url": str,
              "markdown": str,
              "bytes": int
            }
        """

        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        if not spec:
            return {"success": False, "error": "spec 不能为空"}

        from backend.core.svg_diagram import render_svg_diagram

        svg = render_svg_diagram(spec)
        svg_bytes = (svg or "").encode("utf-8")

        import hashlib

        media_id = hashlib.sha256(svg_bytes).hexdigest()
        filename = f"{media_id}.svg"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        try:
            if not out_path.exists():
                out_path.write_bytes(svg_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        return {
            "success": True,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": len(svg_bytes),
        }

    async def _tool_plot_function(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "plot").strip() or "plot"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        from backend.core.plot_tools import render_2d_plot

        try:
            png_bytes = render_2d_plot(spec)
        except Exception as exc:
            return {"success": False, "error": str(exc), "knowledge_point": kp}

        import hashlib

        media_id = hashlib.sha256(png_bytes).hexdigest()
        filename = f"{media_id}.png"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        try:
            if not out_path.exists():
                out_path.write_bytes(png_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename, "knowledge_point": kp}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "plot_function",
            "url": url,
            "markdown": markdown,
            "filename": filename,
            "media_id": media_id,
            "caption": caption,
        }

        try:
            blob = ctx.working_memory.get("diagrams")
            if not isinstance(blob, dict):
                blob = {}
            items = blob.get("items")
            if not isinstance(items, list):
                items = []
            kp_item: Optional[Dict[str, Any]] = None
            for it in items:
                if not isinstance(it, dict):
                    continue
                if str(it.get("knowledge_point") or "").strip() == kp:
                    kp_item = it
                    break
            if kp_item is None:
                kp_item = {"knowledge_point": kp, "diagrams": []}
                items.append(kp_item)
            dlist = kp_item.get("diagrams")
            if not isinstance(dlist, list):
                dlist = []
            if not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
                dlist.append(diagram)
            kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
            blob["items"] = [x for x in items if isinstance(x, dict)]
            ctx.working_memory["diagrams"] = blob
        except Exception:
            pass

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": len(png_bytes),
        }

    async def _tool_plot_3d(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "plot").strip() or "plot"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        from backend.core.plot_tools import render_3d_plot

        try:
            png_bytes = render_3d_plot(spec)
        except Exception as exc:
            return {"success": False, "error": str(exc), "knowledge_point": kp}

        import hashlib

        media_id = hashlib.sha256(png_bytes).hexdigest()
        filename = f"{media_id}.png"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        try:
            if not out_path.exists():
                out_path.write_bytes(png_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename, "knowledge_point": kp}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "plot_3d",
            "url": url,
            "markdown": markdown,
            "filename": filename,
            "media_id": media_id,
            "caption": caption,
        }

        try:
            blob = ctx.working_memory.get("diagrams")
            if not isinstance(blob, dict):
                blob = {}
            items = blob.get("items")
            if not isinstance(items, list):
                items = []
            kp_item: Optional[Dict[str, Any]] = None
            for it in items:
                if not isinstance(it, dict):
                    continue
                if str(it.get("knowledge_point") or "").strip() == kp:
                    kp_item = it
                    break
            if kp_item is None:
                kp_item = {"knowledge_point": kp, "diagrams": []}
                items.append(kp_item)
            dlist = kp_item.get("diagrams")
            if not isinstance(dlist, list):
                dlist = []
            if not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
                dlist.append(diagram)
            kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
            blob["items"] = [x for x in items if isinstance(x, dict)]
            ctx.working_memory["diagrams"] = blob
        except Exception:
            pass

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": len(png_bytes),
        }

    async def _tool_draw_diagram(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        from backend.core.plot_tools import render_schematic

        try:
            png_bytes = render_schematic(spec)
        except Exception as exc:
            return {"success": False, "error": str(exc), "knowledge_point": kp}

        import hashlib

        media_id = hashlib.sha256(png_bytes).hexdigest()
        filename = f"{media_id}.png"

        repo_root = Path(__file__).resolve().parents[2]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        try:
            if not out_path.exists():
                out_path.write_bytes(png_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename, "knowledge_point": kp}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "draw_diagram",
            "url": url,
            "markdown": markdown,
            "filename": filename,
            "media_id": media_id,
            "caption": caption,
        }

        try:
            blob = ctx.working_memory.get("diagrams")
            if not isinstance(blob, dict):
                blob = {}
            items = blob.get("items")
            if not isinstance(items, list):
                items = []
            kp_item: Optional[Dict[str, Any]] = None
            for it in items:
                if not isinstance(it, dict):
                    continue
                if str(it.get("knowledge_point") or "").strip() == kp:
                    kp_item = it
                    break
            if kp_item is None:
                kp_item = {"knowledge_point": kp, "diagrams": []}
                items.append(kp_item)
            dlist = kp_item.get("diagrams")
            if not isinstance(dlist, list):
                dlist = []
            if not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
                dlist.append(diagram)
            kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
            blob["items"] = [x for x in items if isinstance(x, dict)]
            ctx.working_memory["diagrams"] = blob
        except Exception:
            pass

        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": media_id,
            "filename": filename,
            "url": url,
            "markdown": markdown,
            "bytes": len(png_bytes),
        }

    async def _tool_retrieve_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            return {
                "topic": topic,
                "subject": subject,
                "difficulty": difficulty,
                "definition": "",
                "key_points": [],
                "prerequisites": [],
                "common_mistakes": [],
                "methods": [],
                "source": "fallback",
                "note": "未配置模型，知识检索返回为空。",
            }

        prompt = f"""请为“{subject}”的知识点“{topic}”生成可用于自学资料的事实性要点。\n\n要求：\n- 输出严格 JSON（不要 Markdown、不要代码块）\n- 字段：definition(str), key_points(str[]), prerequisites(str[]), common_mistakes(str[]), methods(str[])\n- 难度参考：{difficulty}\n"""
        text = await self._call_llm_text(
            messages=[{"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"}, {"role": "user", "content": prompt}],
            model=self.config.summarizer_model,
            temperature=0.2,
            max_tokens=2600,
            response_format={"type": "json_object"},
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "difficulty": difficulty,
            "definition": str(obj.get("definition") or ""),
            "key_points": list(obj.get("key_points") or []),
            "prerequisites": list(obj.get("prerequisites") or []),
            "common_mistakes": list(obj.get("common_mistakes") or []),
            "methods": list(obj.get("methods") or []),
            "source": "llm",
        }

    async def _tool_search_examples(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 3)
        limit = max(1, min(5, limit))

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(12, limit * 4),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        picked = self._pick_questions(questions, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "examples": picked}

    async def _tool_search_exercises(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 10)
        limit = max(5, min(30, limit))

        used_ids: set[str] = set()
        prev = ctx.working_memory.get("search_examples")
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                qid = str(q.get("question_id") or "").strip()
                if qid:
                    used_ids.add(qid)

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(20, limit * 3),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        filtered = [q for q in questions if str(q.get("question_id") or "").strip() not in used_ids]
        picked = self._pick_questions(filtered, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "exercises": picked}

    async def _tool_analyze_topic(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            return {
                "topic": topic,
                "subject": subject,
                "outline": ["概念与定义", "常用方法", "例题精讲", "分层练习"],
                "confusions": [],
                "source": "fallback",
            }

        prompt = {
            "topic": topic,
            "subject": subject,
            "knowledge": knowledge,
            "required_output": {
                "outline": "string[]",
                "confusions": "string[]",
                "teaching_order": "string[]",
            },
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的教学设计专家，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=2600,
            response_format={"type": "json_object"},
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "outline": list(obj.get("outline") or []),
            "confusions": list(obj.get("confusions") or []),
            "teaching_order": list(obj.get("teaching_order") or []),
            "source": "llm",
        }

    async def _tool_generate_explanation(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}
        analysis = ctx.working_memory.get("analyze_topic") if isinstance(ctx.working_memory.get("analyze_topic"), dict) else {}

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            return (
                f"## 一、知识点讲解：{topic}\n\n"
                "（未配置模型，无法生成详细讲解。你可以先配置 `.env` 中的 `LESSON_PLAN_*` 后重试。）\n"
            )

        prompt = {
            "topic": topic,
            "subject": subject,
            "knowledge": knowledge,
            "analysis": analysis,
            "instructions": "请生成 Markdown 章节：知识点讲解。包含：定义、关键点、常见误区、方法小结。不要输出练习题。",
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的自学资料编写老师，输出必须是Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.4,
            max_tokens=6000,
        )
        return text.strip()

    async def _tool_generate_solutions(self, args: Dict[str, Any], ctx: CompressedContext) -> List[Dict[str, Any]]:
        max_examples = int(args.get("max_examples") or 3)
        max_examples = max(1, min(5, max_examples))

        prev = ctx.working_memory.get("search_examples")
        examples: List[Dict[str, Any]] = []
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                if isinstance(q, dict):
                    examples.append(q)
        examples = examples[:max_examples]

        if not examples:
            return []

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            return [
                {
                    "question_id": q.get("question_id"),
                    "stem": q.get("stem"),
                    "solution_markdown": "（未配置模型，无法生成解答。）",
                }
                for q in examples
            ]

        solutions: List[Dict[str, Any]] = []
        for idx, q in enumerate(examples, start=1):
            stem = str(q.get("stem") or "").strip()
            prompt = f"""请为下面例题写出详细分步解答（Markdown）。\n\n要求：\n- 每一步说明在做什么\n- 如果题干信息不足，请说明需要补充什么\n\n题目：\n{stem}\n"""
            sol = await self._call_llm_text(
                messages=[
                    {"role": "system", "content": "你是严谨的数学解题老师，输出必须是Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.config.planner_model,
                temperature=0.3,
                max_tokens=4000,
            )
            solutions.append(
                {
                    "index": idx,
                    "question_id": q.get("question_id"),
                    "source": q.get("source"),
                    "difficulty": q.get("difficulty"),
                    "stem": stem,
                    "solution_markdown": (sol or "").strip(),
                }
            )
        return solutions

    async def _tool_assemble_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()

        knowledge = ctx.working_memory.get("retrieve_knowledge") if isinstance(ctx.working_memory.get("retrieve_knowledge"), dict) else {}
        explanation = ctx.working_memory.get("generate_explanation")
        solutions = ctx.working_memory.get("generate_solutions")
        exercises = ctx.working_memory.get("search_exercises") if isinstance(ctx.working_memory.get("search_exercises"), dict) else {}

        lines: List[str] = []
        lines.append(f"# 自学材料：{topic}")
        if subject:
            lines.append("")
            lines.append(f"> 学科：{subject}")

        # Knowledge block (structured) + explanation block (markdown)
        definition = str(knowledge.get("definition") or "").strip()
        key_points = knowledge.get("key_points") if isinstance(knowledge.get("key_points"), list) else []
        prereq = knowledge.get("prerequisites") if isinstance(knowledge.get("prerequisites"), list) else []
        mistakes = knowledge.get("common_mistakes") if isinstance(knowledge.get("common_mistakes"), list) else []
        methods = knowledge.get("methods") if isinstance(knowledge.get("methods"), list) else []

        lines.append("")
        lines.append("## 一、知识点讲解")
        lines.append("")
        if definition:
            lines.append("### 1) 定义")
            lines.append("")
            lines.append(definition)
            lines.append("")
        if key_points:
            lines.append("### 2) 关键点")
            lines.append("")
            for x in key_points:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if prereq:
            lines.append("### 3) 前置知识")
            lines.append("")
            for x in prereq:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if mistakes:
            lines.append("### 4) 常见误区")
            lines.append("")
            for x in mistakes:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")
        if methods:
            lines.append("### 5) 方法小结")
            lines.append("")
            for x in methods:
                if isinstance(x, str) and x.strip():
                    lines.append(f"- {x.strip()}")
            lines.append("")

        if isinstance(explanation, str) and explanation.strip():
            lines.append("### 6) 讲解稿")
            lines.append("")
            lines.append(explanation.strip())
            lines.append("")

        # Examples + solutions
        lines.append("## 二、例题精讲（含步骤）")
        lines.append("")
        if isinstance(solutions, list) and solutions:
            for item in solutions:
                stem = str(item.get("stem") or "").strip()
                sol_md = str(item.get("solution_markdown") or "").strip()
                idx = item.get("index") or ""
                lines.append(f"### 例题 {idx}".strip())
                lines.append("")
                if stem:
                    lines.append("**题目**：")
                    lines.append("")
                    lines.append(stem)
                    lines.append("")
                if sol_md:
                    lines.append("**解答**：")
                    lines.append("")
                    lines.append(sol_md)
                    lines.append("")
                else:
                    lines.append("（未生成解答）")
                    lines.append("")
        else:
            examples = ctx.working_memory.get("search_examples")
            if isinstance(examples, dict) and examples.get("examples"):
                for i, q in enumerate(examples.get("examples") or [], start=1):
                    if not isinstance(q, dict):
                        continue
                    lines.append(f"### 例题 {i}")
                    lines.append("")
                    lines.append(str(q.get("stem") or "").strip())
                    lines.append("")
            else:
                lines.append("（未检索到例题）")
                lines.append("")

        # Exercises (no solutions)
        lines.append("## 三、练习题（不含答案）")
        lines.append("")
        ex_list = exercises.get("exercises") if isinstance(exercises.get("exercises"), list) else []
        if ex_list:
            for i, q in enumerate(ex_list, start=1):
                if not isinstance(q, dict):
                    continue
                stem = str(q.get("stem") or "").strip()
                if not stem:
                    continue
                lines.append(f"{i}. {stem}")
                lines.append("")
        else:
            lines.append("（未检索到练习题）")
            lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        ctx.working_memory["markdown"] = markdown
        return markdown

    async def _tool_review_content(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        markdown = str(ctx.working_memory.get("markdown") or "")
        strict_llm = self._strict_llm(ctx, args)

        study_opts = ctx.working_memory.get("study_options")
        study_opts = dict(study_opts) if isinstance(study_opts, dict) else {}
        preset = str(study_opts.get("preset") or "").strip().lower()
        if preset not in {"quick", "standard", "deep", "research"}:
            preset = ""

        # Heuristic checks (source coverage) to encourage deep research iterations.
        # We only fail the review when at least some upstream retrieval worked; otherwise we'd loop
        # endlessly on missing API keys/network constraints.
        heuristic_issues: List[str] = []
        heuristic_suggestions: List[str] = []

        aggregated = ctx.working_memory.get("aggregated") or ctx.working_memory.get("aggregate_knowledge")
        if isinstance(aggregated, dict) and isinstance(aggregated.get("items"), list):
            items = [x for x in (aggregated.get("items") or []) if isinstance(x, dict)]

            def _count_list(obj: Any, key: str) -> int:
                if not isinstance(obj, dict):
                    return 0
                v = obj.get(key)
                return len(v) if isinstance(v, list) else 0

            any_web = any(_count_list(it.get("web_search"), "results") > 0 for it in items)
            any_wiki = any(
                str((it.get("wikipedia") or {}).get("summary") or "").strip()
                or str((it.get("mediawiki") or {}).get("summary") or "").strip()
                for it in items
                if isinstance(it, dict)
            )
            any_stackexchange = any(_count_list(it.get("stackexchange"), "results") > 0 for it in items)

            enforce_sources = any_web or any_wiki or any_stackexchange

            for it in items:
                kp = str(it.get("knowledge_point") or "").strip() or "（未命名知识点）"

                wiki_summary = str((it.get("wikipedia") or {}).get("summary") or "").strip()
                mw_summary = str((it.get("mediawiki") or {}).get("summary") or "").strip()

                web_n = _count_list(it.get("web_search"), "results")
                pages_n = _count_list(it.get("web_pages"), "pages")
                se_n = _count_list(it.get("stackexchange"), "results")
                gh_n = _count_list(it.get("github"), "results")

                min_web = 3
                if preset == "deep":
                    min_web = 4
                elif preset == "research":
                    min_web = 5

                sources_ok = bool(wiki_summary or mw_summary) or web_n >= min_web or pages_n >= 1 or se_n >= 1 or gh_n >= 1
                if enforce_sources and not sources_ok:
                    heuristic_issues.append(
                        f"知识点「{kp}」资料来源不足：网搜结果偏少；建议增加 web_search_knowledge 轮次或调整 query_hint。"
                    )

                if ctx.working_memory.get("search_questions_by_knowledge") is not None:
                    examples_n = _count_list((it.get("questions") or {}), "examples")
                    exercises_n = _count_list((it.get("questions") or {}), "exercises")
                    if examples_n + exercises_n <= 0:
                        heuristic_suggestions.append(
                            f"知识点「{kp}」题库未返回例题/练习题：可提高 max_pages、放宽筛选或换更具体关键词。"
                        )

        if heuristic_issues:
            return {
                "passed": False,
                "issues": heuristic_issues[:8],
                "suggestions": heuristic_suggestions[:8],
                "source": "heuristic",
            }

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY):
            if strict_llm:
                raise RuntimeError("llm_not_configured")
            return {"passed": True, "issues": [], "suggestions": [], "source": "fallback"}

        prompt = f"""请审查下面这份自学资料 Markdown，找出：\n1) 逻辑跳跃/不清晰处\n2) 可能的错误或表述不严谨\n3) 建议改进点（最多5条）\n\n要求：输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n\n主题：{topic}\n\nMarkdown:\n{markdown}\n"""
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=self.config.reflector_model,
            temperature=0.1,
            max_tokens=2600,
            response_format={"type": "json_object"},
            raise_on_fail=strict_llm,
        )
        obj = self._extract_json_obj(text)
        if strict_llm and not obj:
            raise RuntimeError(f"llm_review_failed: invalid_json model={self.config.reflector_model}")
        return {
            "passed": bool(obj.get("passed")) if "passed" in obj else True,
            "issues": list(obj.get("issues") or []),
            "suggestions": list(obj.get("suggestions") or []),
            "source": "llm",
        }

    async def _tool_revise_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> str:
        issues = args.get("issues") or []
        markdown = str(ctx.working_memory.get("markdown") or "")
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_markdown") or "")

        if not (LESSON_PLAN_API_KEY or MOONSHOT_API_KEY) or not markdown:
            return markdown

        prompt = {
            "issues": issues,
            "instructions": "请根据 issues 修订 Markdown，保持结构：讲解→例题→练习题（练习题不含答案）。仅输出修订后的Markdown。",
            "markdown": markdown,
        }
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的自学资料编辑，输出必须是Markdown。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=self.config.planner_model,
            temperature=0.2,
            max_tokens=8000,
        )
        revised = (text or "").strip()
        if revised:
            ctx.working_memory["markdown"] = revised
            return revised
        return markdown
