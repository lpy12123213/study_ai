from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from backend.generation.knowledge_video.models import GeneratedVideoPackage, KnowledgeVideoRequest
from backend.llm.client import chat_completion_text


def _json_from_text(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("invalid_llm_json")
        obj = json.loads(raw[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("invalid_llm_json")
    return obj


def _clip(text: str, *, max_chars: int) -> str:
    s = str(text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip()


def parse_generated_package(text: str) -> GeneratedVideoPackage:
    obj = _json_from_text(text)
    code = str(obj.get("code") or "").strip()
    scene_name = str(obj.get("scene_name") or obj.get("sceneName") or "KnowledgeVideoScene").strip()
    subtitles = obj.get("subtitles") if isinstance(obj.get("subtitles"), list) else []
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    if not code:
        raise ValueError("missing_code")
    return GeneratedVideoPackage(
        code=code,
        scene_name=scene_name or "KnowledgeVideoScene",
        subtitles=[x for x in subtitles if isinstance(x, dict)],
        metadata=dict(metadata),
    )


async def generate_manim_package(
    *,
    request: KnowledgeVideoRequest,
    previous_code: str = "",
    render_error: str = "",
) -> GeneratedVideoPackage:
    model = str(os.getenv("KNOWLEDGE_VIDEO_MODEL") or os.getenv("STUDY_MATERIALS_WRITER_MODEL") or os.getenv("SUB_MODEL") or "").strip()
    max_tokens = int(os.getenv("KNOWLEDGE_VIDEO_MAX_TOKENS") or "8000")
    temp = float(os.getenv("KNOWLEDGE_VIDEO_TEMPERATURE") or "0.3")

    repair = ""
    if previous_code or render_error:
        repair = (
            "\n这是一次修复请求。请保留同一个 scene_name，返回完整可运行代码，不要只返回 diff。\n"
            f"上次错误日志：\n{_clip(render_error, max_chars=3000)}\n"
            f"上次代码：\n{_clip(previous_code, max_chars=12000)}\n"
        )

    source = _clip(request.source_markdown, max_chars=12000)
    messages: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是 Manim Community 代码生成器。只返回 JSON 对象，不要 Markdown。"
                "JSON 字段必须包含 code、scene_name、subtitles、metadata。"
                "code 必须是完整 Python 源码，直接使用 Manim 生成一个单 Scene 知识讲解动画。"
                "代码会在无网络、非 root、资源受限的 Docker 沙盒中运行；可自由使用 Manim 和 Python 表达教学内容。"
                "默认 scene_name 使用 KnowledgeVideoScene。字幕 subtitles 为数组，每项包含 start/end/text 秒级时间。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"主题：{request.topic}\n"
                f"学科：{request.subject or '未指定'}\n"
                f"目标时长：{request.duration_seconds} 秒\n"
                f"风格：{request.style or 'clean'}\n"
                f"额外要求：{request.requirements or '无'}\n"
                f"参考材料：\n{source or '无'}\n"
                f"{repair}"
            ),
        },
    ]

    text = await chat_completion_text(
        messages=messages,
        model=model,
        temperature=temp,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        raise_on_fail=True,
        retries=3,
        timeout_s=float(os.getenv("KNOWLEDGE_VIDEO_LLM_TIMEOUT_S") or "180"),
        req_id_prefix="knowledge-video",
        scope="lesson_plan",
    )
    return parse_generated_package(text)
