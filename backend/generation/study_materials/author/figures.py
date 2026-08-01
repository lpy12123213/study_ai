"""Figure codegen + render engine fallback for the author-agent pipeline (design doc §6).

Each figure spec is forged asynchronously: an injectable LLM codegen produces the
diagram source, then render engines are tried along a fallback chain until one
succeeds. Every stage emits a figure_trace event; when all engines fail the
result is a structured failure dict (never an exception) so assembly can degrade
gracefully. Provider functions are injectable for tests; the default codegen and
renderer adapt the prompt registry, the project LLM client, and
backend/shared/diagrams/static_render.py lazily."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from backend.generation.study_materials.author.blueprint import FIGURE_KINDS, FigureSpec
from backend.generation.study_materials.author.trace import make_event

CodegenFunc = Callable[[Dict[str, Any]], Awaitable[str]]
RenderFunc = Callable[[str, str], Awaitable[Dict[str, Any]]]
TraceFunc = Callable[[Dict[str, Any]], None]

DEFAULT_ENGINE_ORDER: Tuple[str, ...] = ("mermaid", "tikz")
_ENGINE_KINDS = FIGURE_KINDS - {"auto"}


def _extract_code(text: str) -> str:
    """Pull the {"code": ...} payload out of the codegen LLM's JSON output."""
    raw = str(text or "").strip()
    if not raw:
        raise RuntimeError("figure codegen returned empty text")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("figure codegen returned non-JSON text") from None
        obj = json.loads(raw[start:end + 1])
    code = str(obj.get("code") or "").strip() if isinstance(obj, dict) else ""
    if not code:
        raise RuntimeError("figure codegen returned no usable code")
    return code


async def default_llm_codegen(spec: Dict[str, Any]) -> str:
    """Default codegen: render figure.spec.v1 as the system prompt, then call the
    project LLM client with the figure spec as a JSON user message.

    Imports are lazy so tests with injected providers never touch the LLM stack."""
    from backend.core.settings import LESSON_PLAN_MODEL
    from backend.llm.client import chat_completion_text, is_llm_configured
    from backend.llm.prompts import create_default_prompt_registry

    if not is_llm_configured():
        raise RuntimeError("llm_not_configured")
    system_prompt = create_default_prompt_registry().render("figure.spec.v1").content
    payload = {
        "intent": spec.get("intent"),
        "kind": spec.get("kind"),
        "content_spec": spec.get("content_spec") or spec.get("sec_id"),
        "caption": spec.get("caption"),
    }
    text = await chat_completion_text(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-5-mini",
        temperature=0.2,
        max_tokens=0,
        req_id_prefix="figure_forge",
    )
    return _extract_code(text)


class FigureForge:
    def __init__(
        self,
        llm_codegen: Optional[CodegenFunc] = default_llm_codegen,
        render_func: Optional[RenderFunc] = None,
        on_trace: Optional[TraceFunc] = None,
        *,
        engine_order: Sequence[str] = DEFAULT_ENGINE_ORDER,
        media_user_id: str = "study-author",
    ) -> None:
        order: List[str] = []
        for engine in engine_order or ():
            eng = str(engine or "").strip().lower()
            if eng not in _ENGINE_KINDS:
                raise ValueError(f"unknown render engine: {engine!r}")
            if eng not in order:
                order.append(eng)
        if not order:
            raise ValueError("engine_order must not be empty")
        self._engine_order = tuple(order)
        # None disables codegen on purpose: generate() then fails fast with ValueError.
        self._llm_codegen = llm_codegen
        self._render = render_func or self._default_render
        self._on_trace = on_trace or (lambda ev: None)
        self._media_user_id = str(media_user_id or "").strip() or "study-author"

    async def generate(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        figure = FigureSpec.from_dict(spec, "figure")  # BlueprintError (a ValueError) on malformed specs
        if self._llm_codegen is None:
            raise ValueError("llm_codegen is required to generate figure code")
        agent_path = f"fig:{figure.n}"

        code = str(await self._llm_codegen(dict(spec))).strip()
        if not code:
            raise RuntimeError("llm_codegen returned empty code")
        self._trace(agent_path, figure.n, "codegen", chars=len(code))

        attempts: List[str] = []
        for engine in self._engine_chain(figure.kind):
            attempts.append(engine)
            self._trace(agent_path, figure.n, "render_attempt", engine=engine)
            try:
                result = await self._render(engine, code)
            except Exception as exc:  # noqa: BLE001 - fall through to the next engine, never raise
                self._trace(agent_path, figure.n, "render_fail", engine=engine, error=str(exc))
                continue
            url = str((result or {}).get("url") or "").strip()
            if not url:
                self._trace(agent_path, figure.n, "render_fail", engine=engine, error="empty_url")
                continue
            self._trace(agent_path, figure.n, "render_ok", engine=engine, url=url)
            return {"url": url, "engine": str(result.get("engine") or engine), "status": "ok"}
        return {"url": None, "status": "failed", "attempts": attempts}

    def _engine_chain(self, kind: str) -> List[str]:
        if kind == "auto":
            return list(self._engine_order)
        return [kind] + [engine for engine in self._engine_order if engine != kind]

    def _trace(self, agent_path: str, figure_id: int, stage: str, **data: Any) -> None:
        payload = {"figure_id": figure_id, "stage": stage}
        payload.update(data)
        self._on_trace(make_event("figure_trace", agent_path=agent_path, data=payload))

    async def _default_render(self, kind: str, code: str) -> Dict[str, Any]:
        """Reuse backend/shared/diagrams/static_render.py where a local renderer exists.

        Only tikz is renderable locally today (xelatex + dvisvgm); other engines
        must be injected via render_func until their renderers land. Imports are
        lazy so tests never touch the toolchain or the media database."""
        if kind == "tikz":
            from backend.shared.diagrams.static_render import render_tikz_to_svg_bytes

            result = await asyncio.to_thread(render_tikz_to_svg_bytes, tikz=code)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or "tikz_render_failed"))
            from backend.media.generated import publish_generated_bytes

            published = await publish_generated_bytes(
                result["svg_bytes"],
                user_id=self._media_user_id,
                ext=".svg",
                file_type="study_figure",
                mime_type="image/svg+xml",
            )
            return {"url": published["url"], "engine": "tikz"}
        raise NotImplementedError(f"no default renderer for engine {kind!r}; inject render_func")
