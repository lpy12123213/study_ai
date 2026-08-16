"""Core diagram-revise logic shared by MCP tools.

Given a previously-rendered diagram filename, ask an LLM to revise its source
according to a natural-language request, then re-render via the matching
backend. Sidecar JSON files (`<filename>.source.json`) written automatically by
`diagram_utils` carry the source code/spec needed for the round-trip.

The function is HTTP-free so MCP `revise_diagram` (and future callers) can
invoke it without spinning up a FastAPI request.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.generation.question_library.diagram_utils import (
    render_asy_to_url,
    render_chemistry_to_url,
    render_circuit_to_url,
    render_graphviz_to_url,
    render_matplotlib_2d_to_url,
    render_matplotlib_3d_to_url,
    render_schematic_to_url,
    render_svg_to_url,
    render_tikz_to_url,
)
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry
from backend.llm.runner import run_json
from backend.media.diagram_source import read_source_sidecar

logger = get_logger(__name__)


_REVISE_SYSTEM_PROMPT = create_default_prompt_registry().render("question.diagram.revise.v1").content


def _build_user_payload(*, kind: str, existing_source: Any, user_request: str) -> str:
    payload = {
        "kind": kind,
        "existing_source": existing_source,
        "user_request": user_request,
        "instructions": (
            "Revise existing_source to satisfy the user_request. Keep everything else identical. "
            "Output only the revised source under the same schema."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


async def _re_render_by_kind(
    *,
    kind: str,
    source: Any,
    user_id: str,
    alt: str,
) -> Dict[str, Any]:
    """Dispatch revised source to the matching renderer."""

    if kind == "tikz":
        code = ""
        preamble = ""
        if isinstance(source, dict):
            code = str(source.get("code") or source.get("tikz") or "").strip()
            preamble = str(source.get("preamble") or "").strip()
        elif isinstance(source, str):
            code = source.strip()
        if not code:
            return {"success": False, "error": "revised_source_missing_code"}
        return await render_tikz_to_url(tikz=code, user_id=user_id, alt=alt, preamble=preamble)

    if kind == "asy":
        code = ""
        if isinstance(source, dict):
            code = str(source.get("code") or source.get("asy") or "").strip()
        elif isinstance(source, str):
            code = source.strip()
        if not code:
            return {"success": False, "error": "revised_source_missing_code"}
        return await render_asy_to_url(asy=code, user_id=user_id, alt=alt)

    if kind == "chemistry":
        expr = ""
        if isinstance(source, dict):
            expr = str(source.get("expression") or source.get("ce_expr") or "").strip()
        elif isinstance(source, str):
            expr = source.strip()
        if not expr:
            return {"success": False, "error": "revised_source_missing_expression"}
        return await render_chemistry_to_url(expression=expr, user_id=user_id, alt=alt)

    if kind == "circuit":
        body = ""
        if isinstance(source, dict):
            body = str(source.get("body") or source.get("code") or "").strip()
        elif isinstance(source, str):
            body = source.strip()
        if not body:
            return {"success": False, "error": "revised_source_missing_body"}
        return await render_circuit_to_url(circuit_code=body, user_id=user_id, alt=alt)

    if kind == "graphviz":
        dot_code = ""
        engine = "dot"
        if isinstance(source, dict):
            dot_code = str(source.get("dot") or source.get("code") or "").strip()
            engine = str(source.get("engine") or "dot").strip().lower() or "dot"
        elif isinstance(source, str):
            dot_code = source.strip()
        if not dot_code:
            return {"success": False, "error": "revised_source_missing_dot"}
        return await render_graphviz_to_url(dot_code=dot_code, user_id=user_id, alt=alt, engine=engine)

    if kind in {"matplotlib_2d", "matplotlib_3d", "svg", "schematic"}:
        spec: Dict[str, Any] = {}
        if isinstance(source, dict):
            spec = dict(source.get("spec") or source)
        if not spec:
            return {"success": False, "error": "revised_source_missing_spec"}
        if kind == "matplotlib_2d":
            return await render_matplotlib_2d_to_url(spec=spec, user_id=user_id, alt=alt)
        if kind == "matplotlib_3d":
            return await render_matplotlib_3d_to_url(spec=spec, user_id=user_id, alt=alt)
        if kind == "svg":
            return await render_svg_to_url(spec=spec, user_id=user_id, alt=alt)
        return await render_schematic_to_url(spec=spec, user_id=user_id, alt=alt)

    return {"success": False, "error": f"unsupported_kind:{kind}"}


def _normalize_filename(filename: str) -> str:
    name = str(filename or "").strip().lstrip("/")
    for prefix in ("api/media/generated/", "/api/media/generated/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


async def revise_diagram_source(
    *,
    filename: str,
    user_request: str,
    user_id: str,
    alt: Optional[str] = None,
) -> Dict[str, Any]:
    """Revise an existing diagram via LLM + re-render in-place.

    Returns a result dict shaped like:
        { success, kind, url, markdown, filename, cached, bytes, error, hint }
    """

    user_id = str(user_id or "").strip()
    if not user_id:
        return {"success": False, "error": "missing_user_id"}

    name = _normalize_filename(filename)
    request = str(user_request or "").strip()
    if not name or not request:
        return {"success": False, "error": "filename_and_request_required"}

    sidecar = read_source_sidecar(name)
    if sidecar is None:
        return {
            "success": False,
            "error": "source_sidecar_missing",
            "hint": "该图未保留源码副本，无法编辑。仅含 sidecar 的图可改。",
        }

    kind = str(sidecar.get("kind") or "").strip().lower()
    existing_source = sidecar.get("source")
    alt_text = str(alt or sidecar.get("alt") or "diagram").strip() or "diagram"

    if not is_llm_configured():
        return {
            "success": False,
            "error": "llm_not_configured",
            "hint": "diagram 修改依赖 LLM，请在 config/model.json 中配置 lesson_plan 路由及供应商密钥。",
        }

    model = str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-4o-mini"
    try:
        verdict = await run_json(
            messages=[
                {"role": "system", "content": _REVISE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_payload(
                        kind=kind, existing_source=existing_source, user_request=request
                    ),
                },
            ],
            model=model,
            temperature=0.2,
            max_tokens=2400,
            response_format={"type": "json_object"},
            default={},
            req_id_prefix="diagram_revise",
            retries=1,
            raise_on_fail=False,
            scope="diagram_revise",
        )
    except Exception as exc:
        logger.warning("diagram_revise_llm_failed", exc_info=True)
        return {"success": False, "error": f"llm_failed: {exc}"}

    if not isinstance(verdict, dict):
        return {"success": False, "error": "llm_invalid_output"}
    if bool(verdict.get("reject")):
        return {
            "success": False,
            "error": "llm_rejected",
            "hint": str(verdict.get("reason") or "modification declined"),
        }

    revised_source = verdict.get("source")
    revised_kind = str(verdict.get("kind") or kind).strip().lower() or kind
    if revised_kind != kind:
        # Don't let the LLM secretly switch backends — keep the original kind.
        revised_kind = kind

    published = await _re_render_by_kind(
        kind=revised_kind,
        source=revised_source,
        user_id=user_id,
        alt=alt_text,
    )
    if not published.get("success"):
        return {
            "success": False,
            "kind": revised_kind,
            "error": str(published.get("error") or "rerender_failed"),
            "hint": str(published.get("hint") or ""),
        }

    return {
        "success": True,
        "kind": revised_kind,
        "url": str(published.get("url") or ""),
        "markdown": str(published.get("markdown") or ""),
        "filename": str(published.get("filename") or ""),
        "cached": bool(published.get("cached")),
        "bytes": int(published.get("bytes") or 0),
    }
