"""Lesson Plan Agent V2 - streaming lesson plan generation (Markdown + PDF downloads).

Flow:
1) Plan: split knowledge points -> review
2) SubAgent: research each knowledge point
3) Write: generate structured lesson plan JSON (原创撰写)
4) Export: JSON -> Markdown -> (LLM) ElegantBook LaTeX -> PDF

Notes:
- UI 不在页面展示全文，只提供 md/pdf 下载链接。
- LLM 请求失败会自动重试；多次失败则中断并报错（尽量减少兜底）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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
    if not LESSON_PLAN_API_KEY:
        if raise_on_fail:
            raise RuntimeError("llm_not_configured")
        return ""

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

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    if reasoning and str(LESSON_PLAN_PROVIDER or "").lower() == "openrouter":
        payload["reasoning"] = dict(reasoning)

    headers = {"Authorization": f"Bearer {LESSON_PLAN_API_KEY}", "Content-Type": "application/json"}
    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    timeout_s = float(API_TIMEOUT or 120)
    last_error: str = ""
    max_retry = _max_retries()

    for attempt in range(max_retry):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
                resp = await client.post(
                    f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions",
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
                await asyncio.sleep(wait_s)
                continue

            resp.raise_for_status()
            data = resp.json()
            try:
                return str(data["choices"][0]["message"]["content"] or "")
            except Exception:
                last_error = "invalid_response"
                if attempt < (max_retry - 1):
                    await asyncio.sleep(min(3.0, 0.4 + random.random() * 0.8))
                    continue
                if raise_on_fail:
                    raise RuntimeError(f"llm_invalid_response model={model}")
                return ""
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            api_msg = _resp_error(exc.response)
            last_error = f"http_status_{status}"
            if status in {400, 422} and "reasoning" in payload and attempt == 0:
                # Some providers/models reject unknown fields. Retry once without `reasoning`.
                try:
                    payload.pop("reasoning", None)
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                continue
            if status in retry_statuses and attempt < (max_retry - 1):
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            if raise_on_fail:
                raise RuntimeError(
                    f"llm_request_failed status={status} model={model} provider={LESSON_PLAN_PROVIDER} msg={api_msg or last_error}"
                )
            return ""
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            last_error = str(exc)
            if attempt < (max_retry - 1):
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={model} err={last_error}")
            return ""
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
            if attempt < (max_retry - 1):
                await asyncio.sleep(min(8.0, (2**attempt) * 0.9 + random.random() * 0.6))
                continue
            if raise_on_fail:
                raise RuntimeError(f"llm_request_failed model={model} err={last_error}")
            return ""

    if raise_on_fail:
        raise RuntimeError(f"llm_request_failed model={model} err={last_error or 'unknown'}")
    return ""


async def _split_knowledge_points(
    topic: str, subject: str, *, min_points: int = 3, max_points: int = 8
) -> List[str]:
    """Split topic into sub-knowledge points (LLM only; fail fast on repeated failures)."""

    model = str(os.getenv("LESSON_PLAN_SPLIT_MODEL") or LESSON_PLAN_MODEL).strip() or LESSON_PLAN_MODEL
    reasoning = {"effort": "medium", "exclude": True} if "deepseek" in (model or "").lower() else None

    prompt = {
        "topic": topic,
        "subject": subject,
        "requirements": [
            "请把 topic 拆分为若干个可用于教学的子知识点（短语级关键词）。",
            f"数量：{min_points}~{max_points} 个。",
            "去重：合并同义/重复项；避免过泛（如“概念”“性质”单独出现）。",
            "只输出严格 JSON：{\"knowledge_points\": [...]}（不要 Markdown，不要解释）。",
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
            max_tokens=600,
            reasoning=reasoning,
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
    reasoning = {"effort": "medium", "exclude": True} if "deepseek" in (model or "").lower() else None

    prompt = {
        "knowledge_point": kp,
        "subject": subject,
        "topic": topic,
        "requirements": [
            "请输出严格 JSON（不要 Markdown，不要解释）。",
            "字段：teaching_points/common_misconceptions/suggested_activities/key_examples（都为字符串数组）。",
            "每条尽量具体、可直接用于课堂设计；避免空话套话。",
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
            max_tokens=900,
            reasoning=reasoning,
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
    reasoning = {"effort": "medium", "exclude": True} if "deepseek" in (model or "").lower() else None

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
            max_tokens=700,
            reasoning=reasoning,
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
    reasoning = {"effort": "medium", "exclude": True} if "deepseek" in (model or "").lower() else None

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
            "重要写作要求：",
            "1) 所有教案内容必须用你自己的话撰写，严禁照搬任何来源原文",
            "2) 课程环节要可执行：教师活动/学生活动/资源/板书要点要具体",
            "3) 教案应覆盖所有知识点（可分配到不同环节）",
            "4) 不要输出参考文献/URL 列表字段",
            "",
            "只输出严格 JSON（不要 Markdown 代码块，不要多余文字）。",
            "输出字段：",
            "{\"title\":...,\"objectives\":[{\"description\":...,\"type\":\"knowledge|skill|attitude\"}],"
            "\"sections\":[{\"title\":...,\"duration_minutes\":...,\"content\":...,\"activities\":[...],\"resources\":[...]}],"
            "\"summary\":...}",
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
            max_tokens=int(LESSON_PLAN_MAX_TOKENS or 2000),
            reasoning=reasoning,
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
    reasoning = {"effort": "medium", "exclude": True} if "deepseek" in (model or "").lower() else None

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
            max_tokens=3800,
            reasoning=reasoning,
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
    reasoning = {"effort": "medium", "exclude": True} if "deepseek" in (model or "").lower() else None

    reqs = [
        "请对下面 LaTeX 进行修订，使其可以稳定编译且排版合理。",
        "只输出 LaTeX 源码，不要代码块，不要解释。",
        "重点：补齐/修正未闭合括号、环境、特殊字符转义；避免未定义命令；避免重复 \\documentclass。",
        "不要输出参考文献/URL 列表。",
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
            max_tokens=3800,
            reasoning=reasoning,
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

    if not LESSON_PLAN_API_KEY:
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
        research_results: List[Dict[str, Any]] = []
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
            t0 = time.monotonic()
            res = await _research_knowledge_point(kp, subject, topic)
            research_results.append(res)
            yield _agent_event(
                'tool_result',
                {
                    'step_id': step_id,
                    'name': 'research_knowledge_point',
                    'title': f'研究知识点：{kp}',
                    'success': True,
                    'elapsed_ms': int((time.monotonic() - t0) * 1000),
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

