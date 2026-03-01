"""教案智能体 V2 - 流式生成教案（支持 Markdown 和 PDF 下载）。

本模块实现了一个多阶段的智能教案生成系统，采用分布式子智能体架构来处理复杂的教学内容创作任务。

=== 核心流程 ===

阶段 1 - 规划（Planning）:
    - 接收用户输入的课程主题、学科、学段等参数
    - 调用 LLM 将主题拆分为多个可独立研究的知识点
    - 对拆分结果进行审阅和优化，确保覆盖面和粒度合理

阶段 2 - 研究（Research）:
    - 为每个知识点启动独立的子智能体
    - 子智能体可并发执行（并发数由 LESSON_PLAN_V2_SUBAGENT_CONCURRENCY 控制）
    - 每个子智能体负责：搜索相关资料、提取关键信息、整理成结构化笔记
    - 研究结果会被缓存以避免重复工作

阶段 3 - 撰写（Writing）:
    - 汇总所有子智能体的研究成果
    - 调用 LLM 生成结构化的教案 JSON（包含目标、环节、活动等）
    - 强调原创性：LLM 被要求用自己的话重新组织内容，不得照搬原文

阶段 4 - 导出（Export）:
    - JSON -> Markdown: 将结构化数据转换为可读的 Markdown 格式
    - Markdown -> LaTeX: 使用 LLM 转换为 ElegantBook 模板的 LaTeX 源码
    - LaTeX -> PDF: 调用 xelatex 编译生成最终的 PDF 文件
    - 所有生成的文件都会发布到 .local/media/generated/ 目录供下载

=== 技术特性 ===

流式输出:
    - 支持 SSE（Server-Sent Events）实时推送生成进度
    - 界面不显示全文内容，仅在完成后提供 md/pdf 下载链接

容错机制:
    - LLM 请求失败会自动重试（重试次数由 LESSON_PLAN_LLM_RETRIES 控制）
    - 多次失败后中断并报错，尽量减少静默兜底行为
    - 支持 strict_llm 模式，在该模式下任何 LLM 错误都会立即失败

配置项:
    - LESSON_PLAN_MODEL: 使用的 LLM 模型名称
    - LESSON_PLAN_API_KEY / MOONSHOT_API_KEY: API 密钥
    - LESSON_PLAN_LATEX_TIMEOUT_S: LaTeX 编译超时时间（秒）
    - LESSON_PLAN_V2_MAX_TOKENS: 单次生成的最大 token 数

=== 依赖 ===

外部:
    - xelatex: 用于 LaTeX 到 PDF 的编译（需安装 TeX Live 或类似发行版）
    - ElegantBook: LaTeX 文档类（需安装对应的 .cls 文件）

内部:
    - backend.core.settings: 配置常量
    - backend.core.llm_client: LLM 调用封装
    - backend.core.llm_console: 调试日志输出
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from backend.core.settings import (
    API_TIMEOUT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_MODEL,
    LESSON_PLAN_PROVIDER,
    LESSON_PLAN_TEMPERATURE,
    LESSON_PLAN_V2_SUBAGENT_CONCURRENCY,
    MOONSHOT_API_KEY,
    MOONSHOT_BASE_URL,
)
from backend.core import llm_console
from backend.core.llm_client import (
    cap_max_tokens_for_messages,
    get_llm_api_key_override,
    get_moonshot_api_key_override,
    is_llm_configured,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = (REPO_ROOT / ".local" / "media" / "generated").resolve()
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """你是一位资深教育内容设计专家，擅长编写教案。

核心原则：
1. 所有内容必须用自己的话重新组织和表达，严禁照搬任何来源的原文
2. 可以参考资料获取事实和灵感，但必须经过消化吸收后重新撰写
3. 教案应当清晰、实用、以学生为中心

输出要求：
- 输出结构化 JSON，包含以下字段：
  - title: 课程标题
  - objectives: 教学目标数组，每项含 description 和 type (knowledge/skill/attitude)
  - sections: 教学环节数组，每项含 title, duration_minutes, content, activities, resources
  - summary: 课程小结
- content 字段中的文字必须是你自己撰写的，不得复制粘贴来源原文
- 不要输出“参考文献/References/URL 列表”字段（系统会另行处理下载与排版）"""


def _lpv2_infinite_max_tokens() -> int:
    raw = (os.getenv("LESSON_PLAN_V2_MAX_TOKENS") or "").strip()
    try:
        v = int(raw) if raw else 0
    except Exception:
        v = 0
    # "Infinite" (requested): use a very large number so generation isn't artificially truncated.
    return v if v > 0 else 200000


def _agent_event(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"event": kind, "data": data}


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _clean_points(items: List[Any], *, max_points: int) -> List[str]:
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


async def _call_llm_text(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    reasoning: Optional[Dict[str, Any]] = None,
    raise_on_fail: bool = True,
    retries: Optional[int] = None,
) -> str:
    provider = str(LESSON_PLAN_PROVIDER or "").strip().lower() or "openrouter"
    base_url = str(LESSON_PLAN_BASE_URL or "").strip().rstrip("/")
    api_key = str(get_llm_api_key_override() or LESSON_PLAN_API_KEY or "").strip()

    normalized_model = str(model or "").strip()
    model_lower = normalized_model.lower()
    moonshot_key = str(get_moonshot_api_key_override() or MOONSHOT_API_KEY or "").strip()
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

    req_id_base = f"lpv2-{uuid.uuid4().hex[:8]}"

    def _elapsed_s(start_ts: float) -> float:
        if not start_ts:
            return 0.0
        try:
            return max(0.0, time.time() - float(start_ts))
        except Exception:
            return 0.0

    def _max_retries() -> int:
        raw = str(retries if retries is not None else os.getenv("LESSON_PLAN_LLM_RETRIES") or os.getenv("AGENT_LLM_RETRIES") or "6").strip()
        try:
            v = int(raw)
        except Exception:
            v = 6
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
        msg = msg.replace("\n", " ").strip() if msg else ""
        return msg[:260]

    def _parse_context_len_error(msg: str) -> int:
        s = str(msg or "")
        if not s:
            return 0
        m1 = re.search(r"maximum context length is\s+(\d+)\s+tokens", s, flags=re.IGNORECASE)
        if not m1:
            return 0
        try:
            return int(m1.group(1))
        except Exception:
            return 0

    def _parse_input_tokens_error(msg: str) -> int:
        s = str(msg or "")
        if not s:
            return 0
        m2 = re.search(r"\((\d+)\s+of\s+text\s+input,\s*(\d+)\s+in\s+the\s+output\)", s, flags=re.IGNORECASE)
        if not m2:
            return 0
        try:
            return int(m2.group(1))
        except Exception:
            return 0

    def _estimate_text_tokens(text: str) -> int:
        t = str(text or "")
        if not t:
            return 0
        cjk = 0
        for ch in t:
            o = ord(ch)
            if (
                0x4E00 <= o <= 0x9FFF
                or 0x3400 <= o <= 0x4DBF
                or 0x3040 <= o <= 0x30FF
                or 0xAC00 <= o <= 0xD7AF
            ):
                cjk += 1
        ratio = float(cjk) / float(len(t) or 1)
        if ratio >= 0.25:
            return int(math.ceil(len(t) / 1.6))
        return int(math.ceil(len(t) / 4.0))

    def _estimate_messages_tokens(messages_in: List[Dict[str, str]]) -> int:
        total = 0
        for m in messages_in or []:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            content = str(m.get("content") or "")
            total += 6
            total += _estimate_text_tokens(role)
            total += _estimate_text_tokens(content)
        return int(total)

    requested_max_tokens = int(max_tokens)
    payload_max_tokens = cap_max_tokens_for_messages(
        messages=messages,
        model=normalized_model,
        requested_max_tokens=requested_max_tokens,
    )
    adjusted_for_ctx = payload_max_tokens != requested_max_tokens

    payload: Dict[str, Any] = {
        "model": normalized_model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(payload_max_tokens),
        "stream": False,
    }
    if provider == "moonshot" and normalized_model.lower().startswith("kimi-"):
        payload["temperature"] = 1.0
    if reasoning and provider == "openrouter":
        payload["reasoning"] = dict(reasoning)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    timeout_s = float(API_TIMEOUT or 120)
    last_error: str = ""
    max_retry = _max_retries()

    for attempt in range(max_retry):
        req_id = f"{req_id_base}-{attempt + 1}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=provider,
            model=normalized_model,
            stream=False,
            temperature=float(payload.get("temperature") or 0.0),
            max_tokens=int(payload.get("max_tokens") or 0),
            base_url=base_url,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if resp.status_code in retry_statuses and attempt < (max_retry - 1):
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
                content = str(data["choices"][0]["message"]["content"] or "")
                finish_reason = ""
                usage: Dict[str, Any] = {}
                try:
                    choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                    finish_reason = str(choice0.get("finish_reason") or "")
                except Exception:
                    finish_reason = ""
                if isinstance(data, dict) and isinstance(data.get("usage"), dict):
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
                return content
            except Exception:
                last_error = "invalid_response"
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                if attempt < (max_retry - 1):
                    await asyncio.sleep(min(3.0, 0.4 + random.random() * 0.8))
                    continue
                if raise_on_fail:
                    raise RuntimeError(f"llm_invalid_response model={normalized_model}")
                return ""
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            api_msg = _resp_error(exc.response)
            last_error = f"http_status_{status}"
            if status in {400, 422}:
                if provider == "openrouter":
                    limit = _parse_context_len_error(api_msg)
                    if limit > 0:
                        reserve_raw = str(os.getenv("MODEL_CONTEXT_RESERVE_TOKENS") or "").strip()
                        try:
                            reserve = int(reserve_raw) if reserve_raw else 1024
                        except Exception:
                            reserve = 1024
                        reserve = max(128, min(reserve, 8192))
                        in_t = _parse_input_tokens_error(api_msg)
                        if in_t <= 0:
                            in_t = _estimate_messages_tokens(messages)
                        allowed = int(limit - int(in_t) - reserve)
                        if allowed > 0:
                            try:
                                cur = int(payload.get("max_tokens") or 0)
                            except Exception:
                                cur = 0
                            if cur > allowed:
                                payload["max_tokens"] = int(allowed)
                                adjusted_for_ctx = True
                                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=api_msg or last_error)
                                await asyncio.sleep(0.2)
                                continue

                if "reasoning" in payload and attempt == 0:
                    try:
                        payload.pop("reasoning", None)
                    except Exception:
                        pass
                    llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                    await asyncio.sleep(0.2)
                    continue
            if status in retry_statuses and attempt < (max_retry - 1):
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
            if attempt < (max_retry - 1):
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
            return ""
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
            if attempt < (max_retry - 1):
                llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            llm_console.log_end(req_id=req_id, elapsed_s=_elapsed_s(start_ts), error=last_error)
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error}")
            return ""

    if raise_on_fail:
        raise RuntimeError(f"llm_request_failed model={normalized_model} err={last_error or 'unknown'}")
    return ""


async def _split_knowledge_points(
    topic: str, subject: str, *, min_points: int = 3, max_points: int = 8
) -> List[str]:
    """Split topic into sub-knowledge points (LLM only; fail fast on repeated failures)."""

    model = str(os.getenv("LESSON_PLAN_SPLIT_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "topic": topic,
        "subject": subject,
        "requirements": [
            "请把 topic 拆分为若干个可用于教学的子知识点（短语级关键词）。",
            f"数量要求：{min_points}~{max_points} 个，尽量覆盖该主题的核心内容。",
            "粒度要求：每个知识点应具体到可独立讲解的程度，避免过于宽泛（如单独的「概念」「性质」「应用」）。",
            "去重要求：合并语义相近或重复的知识点，确保列表中无冗余项。",
            "排序要求：按照教学逻辑顺序排列，从基础概念到进阶应用。",
            "命名要求：每个知识点用简洁的短语表达（5~20字），便于后续生成教研素材。",
            "输出格式：只输出严格 JSON，格式为 {\"knowledge_points\": [\"知识点1\", \"知识点2\", ...]}",
            "注意：不要输出 Markdown 代码块，不要添加任何解释性文字。",
        ],
    }

    last_err = ""
    for _ in range(3):
        text = await _call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
            max_tokens=2400,
            raise_on_fail=True,
        )
        obj = _extract_json_obj(text)
        points = _clean_points(list(obj.get("knowledge_points") or []), max_points=max_points)
        if len(points) >= min_points:
            return points[:max_points]
        last_err = f"too_few_points got={len(points)} min={min_points}"

    raise RuntimeError(f"llm_split_failed: {last_err or 'unknown'} model={model}")


async def _research_knowledge_point(kp: str, subject: str, topic: str) -> Dict[str, Any]:
    """Research a single knowledge point (LLM only)."""

    model = str(os.getenv("LESSON_PLAN_RESEARCH_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "knowledge_point": kp,
        "subject": subject,
        "topic": topic,
        "requirements": [
            "请针对该知识点进行深度教研分析，输出严格 JSON（不要 Markdown 代码块，不要解释性文字）。",
            "teaching_points（教学要点）：列出 3~6 个核心教学要点，每条应具体说明『教什么』和『怎么教』，避免泛泛而谈。",
            "common_misconceptions（常见误区）：列出 2~4 个学生容易出现的错误理解或典型错误，并简要说明正确认知。",
            "suggested_activities（建议活动）：列出 2~4 个可在课堂实施的教学活动，包括活动形式、时长建议、预期效果。",
            "key_examples（关键例题/案例）：列出 2~4 个典型例题或生活案例，要求具体、可直接用于课堂讲解或练习。",
            "所有字段均为字符串数组，每条内容应详实、可操作，便于直接融入教案设计。",
        ],
        "output_schema": {
            "teaching_points": ["string"],
            "common_misconceptions": ["string"],
            "suggested_activities": ["string"],
            "key_examples": ["string"],
        },
    }

    last_err = ""
    for _ in range(2):
        text = await _call_llm_text(
            messages=[
                {"role": "system", "content": "你是资深教研员，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.3,
            max_tokens=2600,
            raise_on_fail=True,
        )
        obj = _extract_json_obj(text)
        if obj:
            return {"knowledge_point": kp, "research": obj}
        last_err = "invalid_json"

    raise RuntimeError(f"llm_research_failed: {last_err or 'unknown'} model={model}")


async def _review_knowledge_points(
    topic: str,
    subject: str,
    points: List[str],
    *,
    min_points: int,
    max_points: int,
) -> List[str]:
    model = str(os.getenv("LESSON_PLAN_KP_REVIEW_MODEL") or os.getenv("LESSON_PLAN_SPLIT_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt = {
        "topic": topic,
        "subject": subject,
        "knowledge_points": points,
        "requirements": [
            "请审核并微调上述知识点列表，使其更适合『逐点生成教研素材 + 组装成教案』。",
            f"数量要求：{min_points}~{max_points} 个；尽量不超过 {max_points} 个。",
            "去重：合并重复/同义项；避免过泛。",
            "补全：如明显缺失关键子主题，可补充 1~3 个，但不要发散到无关内容。",
            "只输出严格 JSON：{\"knowledge_points\": [...], \"note\": \"...\"}（不要 Markdown，不要多余文字）。",
        ],
    }

    last_err = ""
    for _ in range(3):
        text = await _call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的教研员，输出必须是JSON。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
            max_tokens=2400,
            raise_on_fail=True,
        )
        obj = _extract_json_obj(text)
        revised = obj.get("knowledge_points")
        if isinstance(revised, list):
            cleaned = _clean_points(list(revised), max_points=max_points)
            if len(cleaned) >= min_points:
                return cleaned[:max_points]
            last_err = f"too_few_points got={len(cleaned)} min={min_points}"
        else:
            last_err = "invalid_json"

    raise RuntimeError(f"llm_review_failed: {last_err or 'unknown'} model={model}")


async def _generate_lesson_plan_json(
    *,
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int,
    objectives: Optional[List[str]],
    teaching_style: Optional[str],
    student_level: Optional[str],
    additional_requirements: Optional[str],
    knowledge_points: List[str],
    research_context: List[Dict[str, Any]],
) -> Dict[str, Any]:
    model = str(os.getenv("LESSON_PLAN_WRITER_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    prompt_parts = [
        f"请为以下课程编写一份 {duration_minutes} 分钟的教案（结构化 JSON）：",
        f"- 学科：{subject}",
        f"- 年级：{grade}",
        f"- 课题：{topic}",
        f"- 知识点拆分：{', '.join(knowledge_points)}",
    ]
    if objectives:
        cleaned = [str(x) for x in (objectives or []) if str(x).strip()]
        if cleaned:
            prompt_parts.append(f"- 教学目标（用户提供）：{', '.join(cleaned)}")
    if teaching_style:
        prompt_parts.append(f"- 教学风格：{teaching_style}")
    if student_level:
        prompt_parts.append(f"- 学生水平：{student_level}")
    if additional_requirements:
        prompt_parts.append(f"- 额外要求：{additional_requirements}")

    if research_context:
        prompt_parts.append("")
        prompt_parts.append("以下是各知识点的教研资料（仅供参考，请用自己的话重新组织）：")
        prompt_parts.append(json.dumps(research_context, ensure_ascii=False, indent=2))

    prompt_parts.extend(
        [
            "",
            "=== 写作要求 ===",
            "",
            "【原创性要求】",
            "1. 所有教案内容必须用你自己的话撰写，严禁照搬任何来源原文",
            "2. 可以参考教研资料获取灵感和事实，但必须经过消化吸收后重新组织语言",
            "3. 避免使用模板化、套话式的表述，内容应具体、有针对性",
            "",
            "【教学目标要求】",
            "1. 目标数量：3~6个，覆盖知识、技能、情感态度三个维度",
            "2. 每个目标必须具体、可测量、可操作",
            "3. 使用行为动词描述（如：掌握、理解、运用、分析、评价等）",
            "4. 目标应与知识点紧密对应，避免空泛表述",
            "",
            "【教学环节要求】",
            "1. 环节划分：建议包含导入、新授、练习、小结等基本环节",
            "2. 时间分配：每个环节标注具体时长，总时长应等于课时时长",
            "3. 内容详实：",
            "   - content字段：详细描述该环节的教学内容、讲解要点、板书设计",
            "   - 教师活动：具体说明教师在该环节做什么、说什么、如何引导",
            "   - 学生活动：具体说明学生在该环节做什么、如何参与、预期反馈",
            "4. activities字段：列出2~4个具体可执行的教学活动，包括：",
            "   - 活动名称和形式（如：小组讨论、角色扮演、动手实验等）",
            "   - 活动时长建议",
            "   - 活动步骤或操作要点",
            "5. resources字段：列出该环节所需的教学资源，如：",
            "   - 教具、学具、多媒体素材",
            "   - 练习题、案例材料",
            "   - 板书设计要点",
            "",
            "【课程小结要求】",
            "1. 概括本节课的核心知识点和重点难点",
            "2. 点明学生应掌握的关键技能或方法",
            "3. 可包含课后作业建议或延伸学习方向",
            "",
            "【格式要求】",
            "1. 只输出严格JSON格式，不要Markdown代码块，不要多余解释文字",
            "2. 不要输出参考文献/URL列表字段",
            "3. 确保JSON格式正确，可被直接解析",
            "",
            "输出JSON结构：",
            "{",
            "  \"title\": \"课程标题\",",
            "  \"objectives\": [",
            "    {\"description\": \"具体目标描述\", \"type\": \"knowledge|skill|attitude\"}",
            "  ],",
            "  \"sections\": [",
            "    {",
            "      \"title\": \"环节名称\",",
            "      \"duration_minutes\": 数字,",
            "      \"content\": \"详细教学内容，包括讲解要点、教师活动、学生活动等\",",
            "      \"activities\": [\"具体活动1\", \"具体活动2\"],",
            "      \"resources\": [\"所需资源1\", \"所需资源2\"]",
            "    }",
            "  ],",
            "  \"summary\": \"课程小结内容\"",
            "}",
        ]
    )

    user_prompt = "\n".join(prompt_parts)

    last_err = ""
    for _ in range(3):
        text = await _call_llm_text(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            temperature=float(LESSON_PLAN_TEMPERATURE or 0.7),
            max_tokens=_lpv2_infinite_max_tokens(),
            raise_on_fail=True,
        )
        obj = _extract_json_obj(text)
        if obj.get("title") and isinstance(obj.get("sections"), list):
            obj.pop("references", None)
            return obj
        last_err = "invalid_json"

    raise RuntimeError(f"llm_generate_failed: {last_err or 'unknown'} model={model}")


def _lesson_plan_to_markdown(
    plan: Dict[str, Any],
    *,
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int,
    knowledge_points: List[str],
) -> str:
    title = str(plan.get("title") or topic or "教案").strip() or "教案"

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 学科：{subject or '（未填写）'}")
    lines.append(f"- 年级：{grade or '（未填写）'}")
    lines.append(f"- 课题：{topic or title}")
    lines.append(f"- 课时：{int(duration_minutes)} 分钟")
    if knowledge_points:
        kp_txt = "、".join([kp for kp in knowledge_points if str(kp).strip()])
        if kp_txt:
            lines.append(f"- 知识点：{kp_txt}")
    lines.append("")

    lines.append("## 教学目标")
    lines.append("")
    objectives = plan.get("objectives")
    if isinstance(objectives, list) and objectives:
        for obj in objectives[:12]:
            if not isinstance(obj, dict):
                continue
            desc = str(obj.get("description") or "").strip()
            if desc:
                lines.append(f"- {desc}")
    else:
        lines.append("- （未生成教学目标）")
    lines.append("")

    lines.append("## 教学过程")
    lines.append("")
    sections = plan.get("sections")
    if isinstance(sections, list) and sections:
        for sec in sections[:20]:
            if not isinstance(sec, dict):
                continue
            st = str(sec.get("title") or "").strip() or "教学环节"
            dm = sec.get("duration_minutes")
            try:
                dm_i = int(dm)
            except Exception:
                dm_i = 0
            lines.append(f"### {st}{f'（{dm_i}分钟）' if dm_i else ''}")
            lines.append("")

            content = str(sec.get("content") or "").strip()
            if content:
                lines.append(content)
                lines.append("")

            acts = sec.get("activities")
            if isinstance(acts, list) and any(str(x or "").strip() for x in acts):
                lines.append("活动：")
                for a in acts[:12]:
                    s = str(a or "").strip()
                    if s:
                        lines.append(f"- {s}")
                lines.append("")

            res = sec.get("resources")
            if isinstance(res, list) and any(str(x or "").strip() for x in res):
                lines.append("资源：")
                for r in res[:12]:
                    s = str(r or "").strip()
                    if s:
                        lines.append(f"- {s}")
                lines.append("")
    else:
        lines.append("（未生成教学过程）")
        lines.append("")

    summary = str(plan.get("summary") or "").strip()
    if summary:
        lines.append("## 小结")
        lines.append("")
        lines.append(summary)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _publish_generated_bytes(data: bytes, *, ext: str) -> Dict[str, Any]:
    ext = (ext or "").strip().lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    sha = hashlib.sha256(data).hexdigest()
    filename = f"{sha}{ext}"
    url = f"/api/media/generated/{filename}"

    out_path = (GENERATED_DIR / filename).resolve()
    if not out_path.exists():
        out_path.write_bytes(data)

    return {"url": url, "filename": filename, "sha256": sha, "bytes": len(data)}


def _publish_generated_text(text: str, *, ext: str) -> Dict[str, Any]:
    t = (text or "")
    if not t.endswith("\n"):
        t += "\n"
    return _publish_generated_bytes(t.encode("utf-8"), ext=ext)


async def _convert_markdown_to_latex(*, markdown: str, title: str, subject: str) -> str:
    model = str(os.getenv("LESSON_PLAN_LATEX_MODEL") or os.getenv("STUDY_MATERIALS_LATEX_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    safe_title = title.replace("{", "\\{").replace("}", "\\}")
    template = (
        r"\documentclass[lang=cn]{elegantbook}" "\n"
        r"\usepackage{amsmath,amssymb}" "\n"
        r"\usepackage{graphicx}" "\n"
        r"\usepackage{hyperref}" "\n"
        r"\usepackage{booktabs,longtable}" "\n"
        r"\usepackage{xcolor}" "\n"
        r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}" "\n"
        r"\title{" + safe_title + r"}" "\n"
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
        "subject": subject,
        "template": template,
        "requirements": [
            "请把下面 Markdown 转为 LaTeX，使用 ElegantBook 模板。",
            "只输出 LaTeX 源码，不要 Markdown 代码块，不要额外解释。",
            "必须保留模板结构，仅替换 <BODY> 部分（不要改动 documentclass/preamble）。",
            "正文用 LaTeX 结构：标题层级 #/##/###/#### 映射为 \\section/\\subsection/\\subsubsection/\\paragraph。",
            "保留数学公式 $...$ 与 $$...$$，确保括号与环境闭合。",
            "列表用 itemize/enumerate；代码块用 verbatim；表格必要时可简化。",
            "不要输出“参考文献/外部链接/URL 列表”。",
        ],
        "markdown": markdown,
    }

    raw = (
        await _call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的 LaTeX 排版助手，输出必须是可编译的 LaTeX。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
            max_tokens=_lpv2_infinite_max_tokens(),
            raise_on_fail=True,
        )
    ).strip()
    if not raw:
        raise RuntimeError("llm_empty_response")

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

    return template.replace("<BODY>", body).strip() + "\n"


async def _refine_latex(*, latex: str, topic: str, subject: str, compile_error: str = "") -> str:
    model = str(os.getenv("LESSON_PLAN_LATEX_MODEL") or os.getenv("STUDY_MATERIALS_LATEX_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL

    reqs = [
        "请对下面 LaTeX 进行修订，使其可以稳定编译且排版合理。",
        "只输出 LaTeX 源码，不要代码块，不要解释。",
        "重点检查并修正以下问题：",
        "1. 补齐/修正未闭合的括号、花括号、方括号",
        "2. 检查并修正未闭合的环境（如 \\begin{...} 必须有对应的 \\end{...}）",
        "3. 特殊字符转义：确保 &, %, $, #, _, {, }, ~, ^ 等字符正确转义",
        "4. 避免使用未定义的命令或宏",
        "5. 避免重复的 \\documentclass 声明",
        "6. 确保数学公式中的括号配对正确",
        "7. 检查表格环境中的列数与实际内容是否匹配",
        "8. 确保中文内容使用正确的字体和编码设置",
        "不要输出参考文献/URL 列表。",
        "不要添加任何注释或说明文字。",
    ]
    if compile_error:
        reqs.append(f"编译错误信息（可能截断）：{compile_error[-1200:]}")

    prompt = {"topic": topic, "subject": subject, "requirements": reqs, "latex": latex}
    refined = (
        await _call_llm_text(
            messages=[
                {"role": "system", "content": "你是严谨的 LaTeX 修订助手，输出必须可编译。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            model=model,
            temperature=0.2,
            max_tokens=_lpv2_infinite_max_tokens(),
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

    return refined.strip() + "\n"


def _compile_latex_to_pdf(*, latex: str) -> Dict[str, Any]:
    build_dir = (REPO_ROOT / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    tex_path = build_dir / "main.tex"
    tex_path.write_text((latex or "").strip() + "\n", encoding="utf-8")

    cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
    timeout_s = float(os.getenv("LESSON_PLAN_LATEX_TIMEOUT_S") or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or 600)
    timeout_s = max(30.0, min(timeout_s, 60.0 * 20.0))

    proc = None
    try:
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

    return _publish_generated_bytes(pdf_path.read_bytes(), ext=".pdf")



async def generate_lesson_plan_stream(
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    teaching_style: Optional[str] = None,
    student_level: Optional[str] = None,
    additional_requirements: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Generate a lesson plan and export Markdown/PDF (streaming tool events)."""

    if not is_llm_configured():
        yield _agent_event('error', {'message': 'llm_not_configured'})
        return

    subject = (subject or '').strip()
    grade = (grade or '').strip()
    topic = (topic or '').strip()
    try:
        duration_minutes = int(duration_minutes or 45)
    except Exception:
        duration_minutes = 45
    duration_minutes = max(20, min(duration_minutes, 180))

    try:
        # ── Phase 1: Plan ─────────────────────────────────────────────
        yield _agent_event('thinking', {'content': f'分析教学需求：{subject} {grade}《{topic}》…'})

        split_step_id = f"split_knowledge_points-{uuid.uuid4().hex[:8]}"
        yield _agent_event(
            'tool_call',
            {
                'step_id': split_step_id,
                'name': 'split_knowledge_points',
                'title': '拆分知识点',
                'arguments': {'topic': topic, 'subject': subject, 'min_points': 3, 'max_points': 10},
            },
        )
        t0 = time.monotonic()
        knowledge_points = await _split_knowledge_points(topic, subject, min_points=3, max_points=10)
        yield _agent_event(
            'tool_result',
            {
                'step_id': split_step_id,
                'name': 'split_knowledge_points',
                'title': '拆分知识点',
                'success': True,
                'elapsed_ms': int((time.monotonic() - t0) * 1000),
                'output': {'knowledge_points': knowledge_points, 'count': len(knowledge_points)},
            },
        )

        review_step_id = f"review_knowledge_points-{uuid.uuid4().hex[:8]}"
        yield _agent_event(
            'tool_call',
            {
                'step_id': review_step_id,
                'name': 'review_knowledge_points',
                'title': '审核知识点列表',
                'arguments': {'topic': topic, 'subject': subject, 'knowledge_points': knowledge_points},
            },
        )
        t0 = time.monotonic()
        knowledge_points = await _review_knowledge_points(topic, subject, knowledge_points, min_points=3, max_points=10)
        yield _agent_event(
            'tool_result',
            {
                'step_id': review_step_id,
                'name': 'review_knowledge_points',
                'title': '审核知识点列表',
                'success': True,
                'elapsed_ms': int((time.monotonic() - t0) * 1000),
                'output': {'knowledge_points': knowledge_points, 'count': len(knowledge_points), 'source': 'review_llm'},
            },
        )

        # ── Phase 2: SubAgent research per knowledge point ────────────
        research_results: List[Dict[str, Any]] = [{} for _ in range(len(knowledge_points))]

        try:
            conc_raw = int(LESSON_PLAN_V2_SUBAGENT_CONCURRENCY or 0)
        except Exception:
            conc_raw = 0
        conc = max(1, min(conc_raw if conc_raw > 0 else 3, 20))
        sem = asyncio.Semaphore(conc)

        async def _run_one(*, i: int, kp: str, step_id: str) -> Dict[str, Any]:
            async with sem:
                t0 = time.monotonic()
                res = await _research_knowledge_point(kp, subject, topic)
                return {
                    "index": i,
                    "knowledge_point": kp,
                    "step_id": step_id,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                    "result": res,
                }

        tasks: List[asyncio.Task] = []
        for i, kp in enumerate(knowledge_points):
            yield _agent_event(
                'subagent_start',
                {
                    'knowledge_point': kp,
                    'index': i,
                    'total': len(knowledge_points),
                    'content': f'SubAgent 启动：研究知识点「{kp}」',
                },
            )

            step_id = f"research_knowledge_point-{uuid.uuid4().hex[:8]}"
            yield _agent_event(
                'tool_call',
                {
                    'step_id': step_id,
                    'name': 'research_knowledge_point',
                    'title': f'研究知识点：{kp}',
                    'arguments': {'knowledge_point': kp, 'subject': subject, 'topic': topic},
                },
            )
            tasks.append(asyncio.create_task(_run_one(i=i, kp=kp, step_id=step_id)))

        try:
            for fut in asyncio.as_completed(tasks):
                r = await fut
                i = int(r.get("index") or 0)
                kp = str(r.get("knowledge_point") or "")
                step_id = str(r.get("step_id") or "")
                elapsed_ms = int(r.get("elapsed_ms") or 0)
                res = r.get("result") if isinstance(r.get("result"), dict) else {}
                if 0 <= i < len(research_results):
                    research_results[i] = res

                yield _agent_event(
                    'tool_result',
                    {
                        'step_id': step_id,
                        'name': 'research_knowledge_point',
                        'title': f'研究知识点：{kp}',
                        'success': True,
                        'elapsed_ms': elapsed_ms,
                        'output': {'knowledge_point': kp, 'has_research': bool(res.get('research'))},
                    },
                )

                yield _agent_event(
                    'subagent_end',
                    {
                        'knowledge_point': kp,
                        'index': i,
                        'total': len(knowledge_points),
                        'content': f'SubAgent 完成：「{kp}」资料收集完毕',
                    },
                )
        except Exception:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        # ── Phase 3: Generate lesson plan JSON ────────────────────────
        yield _agent_event('thinking', {'content': '根据收集的资料，撰写教案正文（原创撰写）…'})

        research_context: List[Dict[str, Any]] = []
        for r in research_results:
            kp = str(r.get('knowledge_point') or '').strip()
            blob = r.get('research') if isinstance(r.get('research'), dict) else {}
            if kp and blob:
                research_context.append({'knowledge_point': kp, **blob})

        gen_step_id = f"generate_lesson_plan-{uuid.uuid4().hex[:8]}"
        yield _agent_event(
            'tool_call',
            {
                'step_id': gen_step_id,
                'name': 'generate_lesson_plan',
                'title': '生成教案',
                'arguments': {
                    'subject': subject,
                    'grade': grade,
                    'topic': topic,
                    'duration_minutes': duration_minutes,
                    'knowledge_points': knowledge_points,
                },
            },
        )
        t0 = time.monotonic()
        plan = await _generate_lesson_plan_json(
            subject=subject,
            grade=grade,
            topic=topic,
            duration_minutes=duration_minutes,
            objectives=objectives,
            teaching_style=teaching_style,
            student_level=student_level,
            additional_requirements=additional_requirements,
            knowledge_points=knowledge_points,
            research_context=research_context,
        )
        yield _agent_event(
            'tool_result',
            {
                'step_id': gen_step_id,
                'name': 'generate_lesson_plan',
                'title': '生成教案',
                'success': True,
                'elapsed_ms': int((time.monotonic() - t0) * 1000),
                'output': {'title': str(plan.get('title') or ''), 'sections': len(plan.get('sections') or [])},
            },
        )

        # ── Phase 4: Export Markdown/PDF ──────────────────────────────
        assemble_id = f"assemble_study_archive-{uuid.uuid4().hex[:8]}"
        yield _agent_event(
            'tool_call',
            {
                'step_id': assemble_id,
                'name': 'assemble_study_archive',
                'title': '组装 Markdown',
                'arguments': {'topic': topic, 'subject': subject},
            },
        )
        t0 = time.monotonic()
        md = _lesson_plan_to_markdown(
            plan,
            subject=subject,
            grade=grade,
            topic=topic,
            duration_minutes=duration_minutes,
            knowledge_points=knowledge_points,
        )
        yield _agent_event(
            'tool_result',
            {
                'step_id': assemble_id,
                'name': 'assemble_study_archive',
                'title': '组装 Markdown',
                'success': True,
                'elapsed_ms': int((time.monotonic() - t0) * 1000),
                'output': {'markdown_chars': len(md)},
            },
        )

        title = str(plan.get('title') or topic or '教案').strip() or '教案'

        export_md_id = f"export_study_markdown-{uuid.uuid4().hex[:8]}"
        yield _agent_event(
            'tool_call',
            {
                'step_id': export_md_id,
                'name': 'export_study_markdown',
                'title': '导出 Markdown',
                'arguments': {'topic': topic, 'subject': subject},
            },
        )
        t0 = time.monotonic()
        md_pub = _publish_generated_text(md, ext='.md')
        yield _agent_event(
            'tool_result',
            {
                'step_id': export_md_id,
                'name': 'export_study_markdown',
                'title': '导出 Markdown',
                'success': True,
                'elapsed_ms': int((time.monotonic() - t0) * 1000),
                'output': {'md_url': md_pub['url'], 'filename': md_pub['filename'], 'bytes': md_pub['bytes']},
            },
        )

        convert_id = f"convert_markdown_to_latex-{uuid.uuid4().hex[:8]}"
        yield _agent_event(
            'tool_call',
            {
                'step_id': convert_id,
                'name': 'convert_markdown_to_latex',
                'title': 'Markdown ? LaTeX',
                'arguments': {'topic': topic, 'subject': subject},
            },
        )
        t0 = time.monotonic()
        tex = await _convert_markdown_to_latex(markdown=md, title=title, subject=subject)
        tex_pub = _publish_generated_text(tex, ext='.tex')
        yield _agent_event(
            'tool_result',
            {
                'step_id': convert_id,
                'name': 'convert_markdown_to_latex',
                'title': 'Markdown ? LaTeX',
                'success': True,
                'elapsed_ms': int((time.monotonic() - t0) * 1000),
                'output': {'tex_url': tex_pub['url'], 'filename': tex_pub['filename'], 'bytes': tex_pub['bytes']},
            },
        )

        tex_current = tex
        pdf_pub: Dict[str, Any] = {}
        last_compile_err = ''
        for attempt in range(3):
            refine_id = f"refine_latex-{uuid.uuid4().hex[:8]}"
            yield _agent_event(
                'tool_call',
                {
                    'step_id': refine_id,
                    'name': 'refine_latex',
                    'title': f'修订 LaTeX（第{attempt + 1}轮）',
                    'arguments': {'topic': topic, 'subject': subject},
                },
            )
            t0 = time.monotonic()
            tex_current = await _refine_latex(latex=tex_current, topic=topic, subject=subject, compile_error=last_compile_err)
            tex_pub2 = _publish_generated_text(tex_current, ext='.tex')
            yield _agent_event(
                'tool_result',
                {
                    'step_id': refine_id,
                    'name': 'refine_latex',
                    'title': f'修订 LaTeX（第{attempt + 1}轮）',
                    'success': True,
                    'elapsed_ms': int((time.monotonic() - t0) * 1000),
                    'output': {'tex_url': tex_pub2['url'], 'filename': tex_pub2['filename'], 'bytes': tex_pub2['bytes']},
                },
            )

            compile_id = f"compile_latex_to_pdf-{uuid.uuid4().hex[:8]}"
            yield _agent_event(
                'tool_call',
                {
                    'step_id': compile_id,
                    'name': 'compile_latex_to_pdf',
                    'title': f'编译 PDF（第{attempt + 1}轮）',
                    'arguments': {'topic': topic},
                },
            )
            t0 = time.monotonic()
            try:
                pdf_pub = _compile_latex_to_pdf(latex=tex_current)
                yield _agent_event(
                    'tool_result',
                    {
                        'step_id': compile_id,
                        'name': 'compile_latex_to_pdf',
                        'title': f'编译 PDF（第{attempt + 1}轮）',
                        'success': True,
                        'elapsed_ms': int((time.monotonic() - t0) * 1000),
                        'output': {'pdf_url': pdf_pub['url'], 'filename': pdf_pub['filename'], 'bytes': pdf_pub['bytes']},
                    },
                )
                break
            except Exception as exc:
                last_compile_err = str(exc)
                yield _agent_event(
                    'tool_result',
                    {
                        'step_id': compile_id,
                        'name': 'compile_latex_to_pdf',
                        'title': f'编译 PDF（第{attempt + 1}轮）',
                        'success': False,
                        'elapsed_ms': int((time.monotonic() - t0) * 1000),
                        'error': last_compile_err,
                    },
                )
                if attempt >= 2:
                    raise

        if not pdf_pub:
            raise RuntimeError(f"pdf_missing: {last_compile_err or 'unknown'}")

        yield _agent_event(
            'done',
            {
                'material': {
                    'topic': topic,
                    'title': title,
                    'subject': subject,
                    'grade': grade,
                    'duration_minutes': duration_minutes,
                    'md_url': md_pub['url'],
                    'md_filename': md_pub['filename'],
                    'pdf_url': pdf_pub['url'],
                    'pdf_filename': pdf_pub['filename'],
                }
            },
        )
    except Exception as exc:
        yield _agent_event('error', {'message': str(exc)})

