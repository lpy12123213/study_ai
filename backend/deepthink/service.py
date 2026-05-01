from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Sequence

from backend.core.settings import settings
from backend.deepthink.prompts import (
    get_evaluator_system_prompt,
    get_generator_system_prompt,
    get_synthesizer_system_prompt,
)
from backend.deepthink.tot_engine import ThoughtNode, ToTEngine
from backend.llm.client import chat_completion, is_llm_configured


def _strip_code_fences(text: str) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s).lstrip()
    s = re.sub(r"\s*```$", "", s).rstrip()
    return s.strip()


def _extract_first_json_array(text: str) -> Optional[List[Any]]:
    raw = _strip_code_fences(text)
    if not raw:
        return None
    left = raw.find("[")
    right = raw.rfind("]")
    if left < 0 or right <= left:
        return None
    candidate = raw[left : right + 1].strip()
    try:
        data = json.loads(candidate)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _extract_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = _strip_code_fences(text)
    if not raw:
        return None
    left = raw.find("{")
    right = raw.rfind("}")
    if left < 0 or right <= left:
        return None
    candidate = raw[left : right + 1].strip()
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _format_path(path: Sequence[ThoughtNode]) -> str:
    steps: List[str] = []
    for n in path:
        if not n or not getattr(n, "thought", ""):
            continue
        if n.id == "root":
            continue
        steps.append(f"- {n.thought}")
    return "\n".join(steps) if steps else "（暂无）"


def _build_user_content(text: str, image_url: Optional[str]) -> Any:
    content_text = (text or "").strip()
    url = (image_url or "").strip()
    if not url:
        return content_text
    return [
        {"type": "text", "text": content_text},
        {"type": "image_url", "image_url": {"url": url}},
    ]


class DeepThinkService:
    async def _call_chat_text(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        reasoning: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        res = await chat_completion(
            messages=messages,  # allow multimodal content
            model=str(model or "").strip(),
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            reasoning=reasoning,
            stream=bool(stream),
            on_content_delta=on_content_delta,
            raise_on_fail=False,
            retries=3,
            timeout_s=float(settings.api_timeout_seconds or 120),
            req_id_prefix="deepthink",
            scope="chat",
        )
        return str(res.content or "")

    async def _propose(
        self,
        *,
        question: str,
        subject: str,
        image_url: Optional[str],
        path: Sequence[ThoughtNode],
        n: int,
    ) -> List[Dict[str, Any]]:
        system_prompt = get_generator_system_prompt(subject)
        user_text = f"题目：{question}\n\n已有推理路径：\n{_format_path(path)}\n\n请生成 {n} 个不同的解题下一步。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_content(user_text, image_url)},
        ]

        model = str(settings.deepthink_generator_model or settings.main_model or "").strip() or "openai/gpt-4o-mini"
        content = await self._call_chat_text(
            model=model,
            messages=messages,
            max_tokens=settings.deepthink_generator_max_tokens,
            temperature=settings.deepthink_generator_temperature,
            reasoning={"effort": settings.deepthink_reasoning_effort, "exclude": True},
        )
        if not content:
            return []
        parsed = _extract_first_json_array(content)

        out: List[Dict[str, Any]] = []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    out.append(item)
        return out[: max(1, int(n))]

    async def _evaluate(
        self,
        *,
        question: str,
        subject: str,
        image_url: Optional[str],
        path: Sequence[ThoughtNode],
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        system_prompt = get_evaluator_system_prompt(subject)
        thought = str(proposal.get("thought") or "").strip()
        reasoning = str(proposal.get("reasoning") or "").strip()
        user_text = (
            f"题目：{question}\n\n"
            f"当前推理路径：\n{_format_path(path)}\n\n"
            f"待评估步骤：{thought}\n"
            f"步骤说明：{reasoning}\n"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_content(user_text, image_url)},
        ]

        model = settings.deepthink_evaluator_model.strip() or settings.main_model
        content = await self._call_chat_text(
            model=model,
            messages=messages,
            max_tokens=settings.deepthink_evaluator_max_tokens,
            temperature=settings.deepthink_evaluator_temperature,
            reasoning=None,  # be conservative across providers
        )
        if not content:
            return {"score": 0.0, "reasoning": "评估失败", "issues": ["评估失败"]}
        parsed = _extract_first_json_object(content) or {}
        return parsed if isinstance(parsed, dict) else {"score": 0.0, "reasoning": "评估输出解析失败", "issues": []}

    async def _stream_final_answer(
        self,
        *,
        question: str,
        subject: str,
        image_url: Optional[str],
        best_path: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        system_prompt = get_synthesizer_system_prompt(subject)

        steps_lines: List[str] = []
        step_idx = 0
        for item in best_path or []:
            thought = str((item or {}).get("thought") or "").strip()
            if not thought or (item or {}).get("nodeId") == "root":
                continue
            step_idx += 1
            steps_lines.append(f"{step_idx}. {thought}")
        steps_text = "\n".join(steps_lines) if steps_lines else "（无）"

        user_text = f"题目：{question}\n\n最优推理路径（按顺序）：\n{steps_text}\n\n请基于该路径写出完整解答。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_content(user_text, image_url)},
        ]

        model = str(settings.deepthink_generator_model or settings.main_model or "").strip() or "openai/gpt-4o-mini"
        if not is_llm_configured(scope="chat"):
            yield {"type": "error", "message": "llm_not_configured"}
            return

        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        error: List[str] = []

        async def on_delta(chunk: str) -> None:
            if chunk:
                await queue.put(chunk)

        async def run_stream() -> None:
            try:
                await chat_completion(
                    messages=messages,
                    model=model,
                    temperature=0.2,
                    max_tokens=int(settings.deepthink_generator_max_tokens),
                    reasoning={"effort": settings.deepthink_reasoning_effort, "exclude": True},
                    stream=True,
                    on_content_delta=on_delta,
                    raise_on_fail=False,
                    retries=3,
                    timeout_s=float(settings.api_timeout_seconds or 120),
                    req_id_prefix="deepthink-answer",
                    scope="chat",
                )
            except Exception as exc:
                error.append(str(exc))
            finally:
                await queue.put(None)

        stream_task = asyncio.create_task(run_stream())
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield {"type": "answer_delta", "content": chunk}
        await stream_task
        if error:
            yield {"type": "error", "message": f"流式请求错误: {error[-1]}"}

    async def solve(
        self,
        *,
        question: str,
        subject: str = "高中数学",
        image_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        q = (question or "").strip()
        if not q:
            yield {"type": "error", "message": "题目不能为空"}
            return

        subj = (subject or "").strip() or "高中数学"
        img = (image_url or "").strip() or None

        if not is_llm_configured(scope="chat"):
            yield {"type": "error", "message": "llm_not_configured"}
            return

        gen_model = str(settings.deepthink_generator_model or settings.main_model or "").strip() or "openai/gpt-4o-mini"
        eval_model_in = str(settings.deepthink_evaluator_model or "").strip() or str(settings.main_model or "").strip()
        eval_model = eval_model_in or gen_model

        yield {
            "type": "search_start",
            "question": q,
            "subject": subj,
            "config": {
                "branch_factor": settings.tot_branch_factor,
                "beam_width": settings.tot_beam_width,
                "max_depth": settings.tot_max_depth,
                "prune_threshold": settings.tot_prune_threshold,
                "timeout": settings.tot_timeout_seconds,
                "generator_model": gen_model,
                "evaluator_model": eval_model,
            },
        }

        started = time.monotonic()
        best_path_event: Optional[Dict[str, Any]] = None

        engine = ToTEngine(
            question=q,
            subject=subj,
            branch_factor=settings.tot_branch_factor,
            beam_width=settings.tot_beam_width,
            max_depth=settings.tot_max_depth,
            prune_threshold=settings.tot_prune_threshold,
            timeout_seconds=settings.tot_timeout_seconds,
            propose_fn=lambda question, subject, path, n: self._propose(
                question=question,
                subject=subject,
                image_url=img,
                path=path,
                n=n,
            ),
            evaluate_fn=lambda question, subject, path, proposal: self._evaluate(
                question=question,
                subject=subject,
                image_url=img,
                path=path,
                proposal=proposal,
            ),
        )

        async for event in engine.search():
            if event.get("type") == "best_path":
                best_path_event = event
            yield event

        best_path = (best_path_event or {}).get("path") if isinstance(best_path_event, dict) else None
        best_path_list = best_path if isinstance(best_path, list) else []

        yield {"type": "answer_start"}
        async for chunk in self._stream_final_answer(
            question=q,
            subject=subj,
            image_url=img,
            best_path=best_path_list,
        ):
            yield chunk

        elapsed = round(time.monotonic() - started, 3)
        yield {
            "type": "done",
            "elapsed": elapsed,
            "bestScore": (best_path_event or {}).get("bestScore", 0.0) if isinstance(best_path_event, dict) else 0.0,
            "bestLeafId": (best_path_event or {}).get("bestLeafId", "") if isinstance(best_path_event, dict) else "",
            "totalNodes": len(engine.nodes),
        }


deepthink_service = DeepThinkService()
