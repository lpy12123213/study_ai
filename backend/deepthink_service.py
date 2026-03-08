from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Sequence, Tuple

import httpx

from backend.core import llm_console
from backend.core.settings import settings
from backend.deepthink.prompts import (
    EVALUATOR_SYSTEM_PROMPT_TEMPLATE,
    GENERATOR_SYSTEM_PROMPT_TEMPLATE,
    SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE,
)
from backend.deepthink.tot_engine import ThoughtNode, ToTEngine


def _infer_provider_for_model(model: str) -> str:
    m = (model or "").strip()
    if not m:
        return settings.chat_provider
    if m.startswith("accounts/"):
        return "fireworks"
    if "/" in m:
        return "openrouter"
    return settings.chat_provider


def _resolve_chat_endpoint(model: str) -> Tuple[str, str, str]:
    if getattr(settings, "llm_provider_pinned", False):
        provider = str(settings.chat_provider or "").strip().lower() or "openai_compat"
        return (
            provider,
            (settings.chat_base_url or "").rstrip("/"),
            (settings.chat_api_key or "").strip(),
        )

    provider = _infer_provider_for_model(model)
    if provider == "fireworks":
        return (
            "fireworks",
            (settings.fireworks_base_url or "").rstrip("/"),
            (settings.fireworks_api_key or "").strip(),
        )
    return (
        "openrouter",
        (settings.openrouter_base_url or "").rstrip("/"),
        (settings.openrouter_api_key or "").strip(),
    )


def _chat_headers(provider: str, api_key: str) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        if (settings.review_http_referer or "").strip():
            headers["HTTP-Referer"] = settings.review_http_referer
        if (settings.review_x_title or "").strip():
            headers["X-Title"] = settings.review_x_title
    return headers


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
    async def _call_chat(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        reasoning: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        provider, base_url, api_key = _resolve_chat_endpoint(model)
        if not api_key:
            return {"success": False, "error": f"未配置 {provider} API Key（当前模型: {model}）"}

        req_id = f"deepthink-{uuid.uuid4().hex[:8]}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=provider,
            model=model,
            stream=False,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            base_url=base_url,
        )
        finish_reason = ""
        usage: Dict[str, Any] = {}
        content_chars = 0
        err = ""

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        if provider == "openrouter" and reasoning:
            payload["reasoning"] = reasoning

        try:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers=_chat_headers(provider, api_key),
                json=payload,
            )
            if resp.status_code != 200:
                detail = ""
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        err = data.get("error")
                        if isinstance(err, dict) and isinstance(err.get("message"), str):
                            detail = err["message"]
                        elif isinstance(data.get("message"), str):
                            detail = data["message"]
                except Exception:
                    detail = (resp.text or "").strip()
                suffix = f" - {detail[:240]}" if detail else ""
                err = f"http_status_{resp.status_code}"
                return {"success": False, "error": f"API错误: {resp.status_code}{suffix} (provider={provider})"}

            data = resp.json()
            try:
                choice0 = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
                finish_reason = str(choice0.get("finish_reason") or "")
                msg = choice0.get("message", {}) if isinstance(choice0.get("message"), dict) else {}
                content_text = str(msg.get("content") or "")
            except Exception:
                content_text = ""
                finish_reason = ""

            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                usage = dict(data.get("usage") or {})
            if content_text:
                content_chars = len(content_text)
                llm_console.log_delta(req_id=req_id, channel="content", text=content_text)

            return {"success": True, "data": data, "provider": provider}
        except Exception as exc:
            err = str(exc)
            return {"success": False, "error": f"请求错误: {str(exc)}"}
        finally:
            elapsed_s = 0.0
            try:
                elapsed_s = max(0.0, time.time() - float(start_ts)) if start_ts else 0.0
            except Exception:
                elapsed_s = 0.0
            llm_console.log_end(
                req_id=req_id,
                elapsed_s=elapsed_s,
                finish_reason=finish_reason,
                usage=usage,
                content_chars=content_chars,
                error=err,
            )

    async def _propose(
        self,
        client: httpx.AsyncClient,
        *,
        question: str,
        subject: str,
        image_url: Optional[str],
        path: Sequence[ThoughtNode],
        n: int,
    ) -> List[Dict[str, Any]]:
        system_prompt = GENERATOR_SYSTEM_PROMPT_TEMPLATE.format(subject=subject)
        user_text = f"题目：{question}\n\n已有推理路径：\n{_format_path(path)}\n\n请生成 {n} 个不同的解题下一步。"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _build_user_content(user_text, image_url)},
        ]

        model = settings.deepthink_generator_model
        res = await self._call_chat(
            client,
            model=model,
            messages=messages,
            max_tokens=settings.deepthink_generator_max_tokens,
            temperature=settings.deepthink_generator_temperature,
            reasoning={"effort": settings.deepthink_reasoning_effort, "exclude": True},
        )
        if not res.get("success"):
            return []

        data = res.get("data") or {}
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content") or ""
        parsed = _extract_first_json_array(content)

        out: List[Dict[str, Any]] = []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    out.append(item)
        return out[: max(1, int(n))]

    async def _evaluate(
        self,
        client: httpx.AsyncClient,
        *,
        question: str,
        subject: str,
        image_url: Optional[str],
        path: Sequence[ThoughtNode],
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        system_prompt = EVALUATOR_SYSTEM_PROMPT_TEMPLATE.format(subject=subject)
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
        res = await self._call_chat(
            client,
            model=model,
            messages=messages,
            max_tokens=settings.deepthink_evaluator_max_tokens,
            temperature=settings.deepthink_evaluator_temperature,
            reasoning=None,  # be conservative across providers
        )
        if not res.get("success"):
            return {"score": 0.0, "reasoning": res.get("error") or "评估失败", "issues": ["评估失败"]}

        data = res.get("data") or {}
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content") or ""
        parsed = _extract_first_json_object(content) or {}
        return parsed if isinstance(parsed, dict) else {"score": 0.0, "reasoning": "评估输出解析失败", "issues": []}

    async def _stream_final_answer(
        self,
        client: httpx.AsyncClient,
        *,
        question: str,
        subject: str,
        image_url: Optional[str],
        best_path: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        system_prompt = SYNTHESIZER_SYSTEM_PROMPT_TEMPLATE.format(subject=subject)

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

        model = settings.deepthink_generator_model
        provider, base_url, api_key = _resolve_chat_endpoint(model)
        if not api_key:
            yield {"type": "error", "message": f"未配置 {provider} API Key（DeepThink Generator）"}
            return

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(settings.deepthink_generator_max_tokens),
            "temperature": 0.2,
            "stream": True,
        }
        if provider == "openrouter":
            payload["reasoning"] = {"effort": settings.deepthink_reasoning_effort, "exclude": True}

        req_id = f"deepthink-stream-{uuid.uuid4().hex[:8]}"
        start_ts = llm_console.log_start(
            req_id=req_id,
            provider=provider,
            model=model,
            stream=True,
            temperature=float(payload.get("temperature") or 0.0),
            max_tokens=int(payload.get("max_tokens") or 0),
            base_url=base_url,
        )
        finish_reason = ""
        usage: Dict[str, Any] = {}
        content_chars = 0
        err = ""

        try:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers=_chat_headers(provider, api_key),
                json=payload,
            ) as response:
                if response.status_code != 200:
                    detail = ""
                    try:
                        raw = await response.aread()
                        text = raw.decode("utf-8", errors="ignore")
                        try:
                            data = json.loads(text)
                            if isinstance(data, dict):
                                err = data.get("error")
                                if isinstance(err, dict) and isinstance(err.get("message"), str):
                                    detail = err["message"]
                                elif isinstance(data.get("message"), str):
                                    detail = data["message"]
                        except Exception:
                            detail = text
                    except Exception:
                        detail = ""
                    suffix = f" - {detail[:240]}" if detail else ""
                    yield {"type": "error", "message": f"API错误: {response.status_code}{suffix} (provider={provider})"}
                    err = f"http_status_{response.status_code}"
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choice0 = (chunk.get("choices") or [{}])[0] if isinstance(chunk, dict) else {}
                        delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
                        content = delta.get("content") or ""
                        if content:
                            llm_console.log_delta(req_id=req_id, channel="content", text=str(content))
                            content_chars += len(str(content))
                            yield {"type": "answer_delta", "content": content}

                        fr = choice0.get("finish_reason")
                        if isinstance(fr, str) and fr:
                            finish_reason = fr
                        if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                            usage = dict(chunk.get("usage") or {})
                    except Exception:
                        continue
        except Exception as exc:
            err = str(exc)
            yield {"type": "error", "message": f"流式请求错误: {str(exc)}"}
        finally:
            elapsed_s = 0.0
            try:
                elapsed_s = max(0.0, time.time() - float(start_ts)) if start_ts else 0.0
            except Exception:
                elapsed_s = 0.0
            llm_console.log_end(
                req_id=req_id,
                elapsed_s=elapsed_s,
                finish_reason=finish_reason,
                usage=usage,
                content_chars=content_chars,
                error=err,
            )

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

        gen_provider, _, gen_key = _resolve_chat_endpoint(settings.deepthink_generator_model)
        if not gen_key:
            yield {"type": "error", "message": f"未配置 {gen_provider} API Key（DeepThink Generator）"}
            return

        eval_model = settings.deepthink_evaluator_model.strip() or settings.main_model
        eval_provider, _, eval_key = _resolve_chat_endpoint(eval_model)
        if not eval_key:
            yield {"type": "error", "message": f"未配置 {eval_provider} API Key（DeepThink Evaluator）"}
            return

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
                "generator_model": settings.deepthink_generator_model,
                "evaluator_model": eval_model,
            },
        }

        started = time.monotonic()
        best_path_event: Optional[Dict[str, Any]] = None

        timeout = httpx.Timeout(settings.api_timeout_seconds, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            engine = ToTEngine(
                question=q,
                subject=subj,
                branch_factor=settings.tot_branch_factor,
                beam_width=settings.tot_beam_width,
                max_depth=settings.tot_max_depth,
                prune_threshold=settings.tot_prune_threshold,
                timeout_seconds=settings.tot_timeout_seconds,
                propose_fn=lambda question, subject, path, n: self._propose(
                    client,
                    question=question,
                    subject=subject,
                    image_url=img,
                    path=path,
                    n=n,
                ),
                evaluate_fn=lambda question, subject, path, proposal: self._evaluate(
                    client,
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
                client,
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
