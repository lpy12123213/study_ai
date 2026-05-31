"""Vision-LLM diagram verification.

Render-then-verify closes the loop on AI-drawn diagrams: after a renderer
produces an SVG/PNG, ask a vision-capable LLM whether the drawing matches the
intended stem/description. Vision is only invoked for raster outputs
(PNG/JPEG/WEBP) — for SVG we inline the XML so a plain LLM can reason about
geometry and labels textually.

Returns a verdict dict the caller can act on:
  {
    "ok": bool,
    "issues": [str, ...],
    "repair_hint": str,
    "confidence": float (0-1),
    "mode": "vision" | "svg_text" | "skipped",
  }
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger
from backend.core.settings import LESSON_PLAN_MODEL
from backend.llm.client import is_llm_configured
from backend.llm.runner import run_json

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GENERATED_DIR = (_REPO_ROOT / ".local" / "media" / "generated").resolve()

_MEDIA_PREFIX = "/api/media/generated/"
_MAX_SVG_INLINE_CHARS = 18_000
_MAX_VISION_BYTES = 4 * 1024 * 1024  # 4MB safety cap


def _resolve_local_file(url: str) -> Optional[Path]:
    """Map a `/api/media/generated/<filename>` URL to its on-disk path.

    Returns None for URLs outside the generated-media namespace (defensive).
    """

    raw = str(url or "").strip()
    if not raw:
        return None
    # Strip query/fragment and the canonical prefix.
    if raw.startswith(_MEDIA_PREFIX):
        filename = raw[len(_MEDIA_PREFIX) :].split("?", 1)[0].split("#", 1)[0]
    elif "/" not in raw and "." in raw:
        # Bare filename like `<sha>.svg`.
        filename = raw
    else:
        return None
    filename = filename.strip().lstrip("/")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    path = (_GENERATED_DIR / filename).resolve()
    try:
        path.relative_to(_GENERATED_DIR)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def _mime_for_suffix(suffix: str) -> str:
    s = (suffix or "").lower()
    if s in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if s == ".png":
        return "image/png"
    if s == ".webp":
        return "image/webp"
    if s == ".gif":
        return "image/gif"
    if s == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _system_prompt() -> str:
    return (
        "<role>You are a strict diagram-quality reviewer for K-12 / college-entrance exam content.</role>\n"
        "<task>Compare the rendered diagram against the intended description (题干/要点)."
        " Decide whether the diagram faithfully represents what the description requires.</task>\n"
        "<focus>\n"
        "  <item>Geometric relations (perpendicular, parallel, congruence) must match the description.</item>\n"
        "  <item>Labels for points, axes, magnitudes must be present and unambiguous.</item>\n"
        "  <item>Quantities (lengths, angles, directions) should be consistent if specified.</item>\n"
        "  <item>Reject decorative content, extraneous elements, missing labels.</item>\n"
        "  <item>Don't penalize minor cosmetic issues unless strictness is high.</item>\n"
        "</focus>\n"
        "<output>Strict JSON only. Schema: {ok: bool, issues: string[], repair_hint: string, confidence: number(0-1)}.</output>"
    )


def _strictness_guidance(strictness: int) -> str:
    s = max(1, min(int(strictness or 3), 5))
    if s <= 2:
        return "Be lenient: only flag clear contradictions with the description."
    if s == 3:
        return "Be balanced: flag clear errors and missing critical labels; ignore cosmetic issues."
    return "Be strict: any inconsistency, missing label, or ambiguous element should make ok=false."


def _build_user_messages_for_vision(
    *,
    description: str,
    image_bytes: bytes,
    mime: str,
    strictness: int,
) -> List[Dict[str, Any]]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Intended description:\n{description.strip()}\n\n"
                        f"Strictness guidance: {_strictness_guidance(strictness)}\n"
                        "Evaluate the attached image and output a strict JSON verdict."
                    ),
                },
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]


def _build_user_messages_for_svg_text(
    *,
    description: str,
    svg_text: str,
    strictness: int,
) -> List[Dict[str, Any]]:
    clipped = svg_text[:_MAX_SVG_INLINE_CHARS]
    return [
        {
            "role": "user",
            "content": (
                f"Intended description:\n{description.strip()}\n\n"
                f"Strictness guidance: {_strictness_guidance(strictness)}\n\n"
                "The diagram is provided as raw SVG markup below. Read it as XML and assess whether the "
                "geometric content (paths, shapes, text labels, coordinates) matches the intended description.\n\n"
                "```svg\n"
                f"{clipped}\n"
                "```\n\n"
                "Output a strict JSON verdict."
            ),
        }
    ]


async def verify_diagram_with_vision(
    *,
    diagram_url: str,
    description: str,
    strictness: int = 3,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify a rendered diagram matches the intended description.

    Returns {ok, issues, repair_hint, confidence, mode}. Never raises — failures
    yield ok=False with an informative issue.
    """

    desc = (description or "").strip()
    if not desc:
        return {"ok": False, "issues": ["empty_description"], "repair_hint": "", "confidence": 0.0, "mode": "skipped"}

    path = _resolve_local_file(diagram_url)
    if path is None:
        return {
            "ok": False,
            "issues": ["url_not_resolvable_to_local_file"],
            "repair_hint": "确保 url 是 /api/media/generated/<filename> 形式且文件仍存在。",
            "confidence": 0.0,
            "mode": "skipped",
        }

    if not is_llm_configured():
        return {
            "ok": False,
            "issues": ["llm_not_configured"],
            "repair_hint": "verify_diagram 需要可用 LLM。请配置 LESSON_PLAN_API_KEY/MOONSHOT_API_KEY/OPENROUTER_API_KEY。",
            "confidence": 0.0,
            "mode": "skipped",
        }

    suffix = path.suffix.lower()
    mime = _mime_for_suffix(suffix)

    try:
        data = path.read_bytes()
    except OSError as exc:
        return {
            "ok": False,
            "issues": [f"read_failed:{exc}"],
            "repair_hint": "",
            "confidence": 0.0,
            "mode": "skipped",
        }

    chosen_model = (model or "").strip() or str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-4o-mini"

    if suffix == ".svg":
        svg_text = data.decode("utf-8", errors="ignore")
        user_msgs = _build_user_messages_for_svg_text(
            description=desc, svg_text=svg_text, strictness=strictness
        )
        mode = "svg_text"
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        if len(data) > _MAX_VISION_BYTES:
            return {
                "ok": False,
                "issues": ["image_too_large_for_vision"],
                "repair_hint": "图片超过 4MB；尝试降低分辨率或使用 SVG 输出。",
                "confidence": 0.0,
                "mode": "skipped",
            }
        user_msgs = _build_user_messages_for_vision(
            description=desc, image_bytes=data, mime=mime, strictness=strictness
        )
        mode = "vision"
    else:
        return {
            "ok": False,
            "issues": [f"unsupported_format:{suffix}"],
            "repair_hint": "",
            "confidence": 0.0,
            "mode": "skipped",
        }

    messages = [
        {"role": "system", "content": _system_prompt()},
        *user_msgs,
    ]

    try:
        verdict = await run_json(
            messages=messages,
            model=chosen_model,
            temperature=0.1,
            max_tokens=600,
            response_format={"type": "json_object"},
            default={},
            req_id_prefix="diagram_verify",
            retries=1,
            raise_on_fail=False,
            scope="diagram_verify",
        )
    except Exception as exc:
        logger.warning("diagram_verify_llm_failed", exc_info=True)
        return {
            "ok": False,
            "issues": [f"llm_call_failed:{exc}"],
            "repair_hint": "",
            "confidence": 0.0,
            "mode": mode,
        }

    if not isinstance(verdict, dict):
        verdict = {}

    issues_raw = verdict.get("issues")
    issues = [str(x).strip() for x in issues_raw if str(x or "").strip()] if isinstance(issues_raw, list) else []

    return {
        "ok": bool(verdict.get("ok")),
        "issues": issues[:8],
        "repair_hint": str(verdict.get("repair_hint") or "").strip(),
        "confidence": max(0.0, min(1.0, float(verdict.get("confidence") or 0.0))),
        "mode": mode,
    }


async def verify_and_maybe_repair_diagram(
    *,
    diagram_url: str,
    description: str,
    strictness: int = 3,
    max_attempts: int = 2,
) -> Dict[str, Any]:
    """Single-pass verify (caller chooses to repair).

    For now this is a thin wrapper over `verify_diagram_with_vision` so callers
    have a stable API surface. A future revision can drive repair loops by
    re-emitting the source via LLM and re-rendering.
    """

    return await verify_diagram_with_vision(
        diagram_url=diagram_url,
        description=description,
        strictness=strictness,
    )
