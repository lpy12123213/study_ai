from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Dict, List, Optional

import httpx

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.generation.question_library.diagram_utils import (
    render_asy_to_url,
    render_chemistry_to_url,
    render_circuit_to_url,
    render_graphviz_to_url,
    render_schematic_to_url,
    render_svg_to_url,
    render_tikz_to_url,
)
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes
from backend.shared.diagrams.static_render import (
    asy_tools_missing_hint,
    tikz_tools_missing_hint,
)
from backend.shared.project_paths import resolve_repo_root

logger = get_logger(__name__)

_REPO_ROOT = resolve_repo_root()
_GENERATED_DIR = (_REPO_ROOT / ".local" / "media" / "generated").resolve()


def _tikz_missing_hint() -> str:
    # Backwards compatible name: used in error payloads.
    return tikz_tools_missing_hint()


def _asy_missing_hint() -> str:
    return asy_tools_missing_hint()


def _resolve_kp(args: Dict[str, Any], ctx: CompressedContext) -> str:
    kp = str(args.get("knowledge_point") or "").strip()
    if not kp:
        kps = args.get("knowledge_points")
        if isinstance(kps, list) and kps:
            kp = str(kps[0] or "").strip()
    if not kp:
        kp = str(ctx.current_task or "").strip()
    return kp


def _store_diagram(ctx: CompressedContext, kp: str, diagram: Dict[str, Any]) -> None:
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
        filename = str(diagram.get("filename") or "").strip()
        if filename and not any(isinstance(d, dict) and str(d.get("filename") or "").strip() == filename for d in dlist):
            dlist.append(diagram)
        kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
        blob["items"] = [x for x in items if isinstance(x, dict)]
        ctx.working_memory["diagrams"] = blob
    except Exception:
        logger.warning("diagram_store_working_memory_failed", exc_info=True)


class DiagramToolsMixin:
    async def _tool_draw_svg_diagram(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        if not spec:
            return {"success": False, "error": "spec 不能为空"}

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_svg_to_url(spec=spec, user_id=user_id, alt=alt)
        if not published.get("success"):
            return published
        return {
            "success": True,
            "media_id": str(published.get("media_id") or ""),
            "filename": str(published.get("filename") or ""),
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "bytes": int(published.get("bytes") or 0),
            "cached": bool(published.get("cached")),
        }

    async def _tool_draw_diagram(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        caption = str(args.get("caption") or spec.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        if not spec:
            return {"success": False, "error": "spec 不能为空", "knowledge_point": kp}

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_schematic_to_url(spec=spec, user_id=user_id, alt=alt)
        if not published.get("success"):
            return {"success": False, "error": str(published.get("error") or "schematic_failed"), "knowledge_point": kp}

        diagram = {
            "knowledge_point": kp,
            "kind": "draw_diagram",
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "filename": str(published.get("filename") or ""),
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram(ctx, kp, diagram)
        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": diagram["filename"],
            "url": diagram["url"],
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": diagram["cached"],
        }

    async def _tool_tikz_to_svg(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        caption = str(args.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        tikz = args.get("tikz")
        if not isinstance(tikz, str) or not tikz.strip():
            tikz = args.get("code")
        if not isinstance(tikz, str) or not tikz.strip():
            tikz = args.get("latex")
        tikz = str(tikz or "").strip()
        if not tikz:
            return {"success": False, "error": "tikz 不能为空", "knowledge_point": kp}

        preamble = args.get("preamble")
        if not isinstance(preamble, str):
            preamble = ""
        preamble = preamble.strip()

        timeout_raw = (
            os.getenv("STUDY_MATERIALS_TIKZ_TIMEOUT_S")
            or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S")
            or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT")
            or "240"
        )
        try:
            timeout_s = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_s = 240.0
        timeout_s = max(10.0, min(timeout_s, 60.0 * 20.0))

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_tikz_to_url(
            tikz=tikz, user_id=user_id, alt=alt, preamble=preamble, timeout_s=timeout_s
        )
        if not published.get("success"):
            out = dict(published)
            out["knowledge_point"] = kp
            out.setdefault("hint", _tikz_missing_hint())
            return out

        diagram = {
            "knowledge_point": kp,
            "kind": "tikz_to_svg",
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "filename": str(published.get("filename") or ""),
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram(ctx, kp, diagram)
        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": diagram["filename"],
            "url": diagram["url"],
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": diagram["cached"],
        }

    async def _tool_asy_to_svg(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        caption = str(args.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        asy = args.get("asy")
        if not isinstance(asy, str) or not asy.strip():
            asy = args.get("asymptote")
        if not isinstance(asy, str) or not asy.strip():
            asy = args.get("code")
        if not isinstance(asy, str) or not asy.strip():
            asy = args.get("text")
        asy = str(asy or "").strip()
        if not asy:
            return {"success": False, "error": "asy 不能为空", "knowledge_point": kp}

        timeout_raw = os.getenv("STUDY_MATERIALS_ASY_TIMEOUT_S") or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or "240"
        try:
            timeout_s = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_s = 240.0
        timeout_s = max(10.0, min(timeout_s, 60.0 * 20.0))

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_asy_to_url(asy=asy, user_id=user_id, alt=alt, timeout_s=timeout_s)
        if not published.get("success"):
            out = dict(published)
            out["knowledge_point"] = kp
            out.setdefault("hint", _asy_missing_hint())
            return out

        diagram = {
            "knowledge_point": kp,
            "kind": "asy_to_svg",
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "filename": str(published.get("filename") or ""),
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram(ctx, kp, diagram)
        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": diagram["filename"],
            "url": diagram["url"],
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": diagram["cached"],
        }

    async def _tool_render_chemistry(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Render a chemistry expression via mhchem → TikZ → SVG."""

        alt = str(args.get("alt") or args.get("title") or "化学方程式").strip() or "化学方程式"
        caption = str(args.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        expression = args.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            expression = args.get("ce")
        if not isinstance(expression, str) or not expression.strip():
            expression = args.get("text")
        expression = str(expression or "").strip()
        if not expression:
            return {"success": False, "error": "expression 不能为空", "knowledge_point": kp}

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_chemistry_to_url(expression=expression, user_id=user_id, alt=alt)
        if not published.get("success"):
            out = dict(published)
            out["knowledge_point"] = kp
            return out

        diagram = {
            "knowledge_point": kp,
            "kind": "chemistry",
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "filename": str(published.get("filename") or ""),
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram(ctx, kp, diagram)
        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": diagram["filename"],
            "url": diagram["url"],
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": diagram["cached"],
        }

    async def _tool_render_circuit(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Render a circuitikz circuit description to SVG."""

        alt = str(args.get("alt") or args.get("title") or "电路图").strip() or "电路图"
        caption = str(args.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        circuit_code = args.get("circuit") or args.get("code") or args.get("circuitikz") or ""
        circuit_code = str(circuit_code or "").strip()
        if not circuit_code:
            return {"success": False, "error": "circuit 不能为空", "knowledge_point": kp}

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_circuit_to_url(circuit_code=circuit_code, user_id=user_id, alt=alt)
        if not published.get("success"):
            out = dict(published)
            out["knowledge_point"] = kp
            return out

        diagram = {
            "knowledge_point": kp,
            "kind": "circuit",
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "filename": str(published.get("filename") or ""),
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "cached": bool(published.get("cached")),
        }
        _store_diagram(ctx, kp, diagram)
        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": diagram["filename"],
            "url": diagram["url"],
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": diagram["cached"],
        }

    async def _tool_render_graphviz(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """Render Graphviz DOT source to SVG via `dot -Tsvg`."""

        alt = str(args.get("alt") or args.get("title") or "流程图").strip() or "流程图"
        caption = str(args.get("caption") or "").strip()
        kp = _resolve_kp(args, ctx)

        dot_code = args.get("dot") or args.get("code") or args.get("graphviz") or ""
        dot_code = str(dot_code or "").strip()
        if not dot_code:
            return {"success": False, "error": "dot 不能为空", "knowledge_point": kp}

        engine = str(args.get("engine") or "dot").strip().lower() or "dot"

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await render_graphviz_to_url(dot_code=dot_code, user_id=user_id, alt=alt, engine=engine)
        if not published.get("success"):
            out = dict(published)
            out["knowledge_point"] = kp
            return out

        diagram = {
            "knowledge_point": kp,
            "kind": "graphviz",
            "url": str(published.get("url") or ""),
            "markdown": str(published.get("markdown") or ""),
            "filename": str(published.get("filename") or ""),
            "media_id": str(published.get("media_id") or ""),
            "caption": caption,
            "engine": engine,
            "cached": bool(published.get("cached")),
        }
        _store_diagram(ctx, kp, diagram)
        return {
            "success": True,
            "knowledge_point": kp,
            "diagram": diagram,
            "media_id": diagram["media_id"],
            "filename": diagram["filename"],
            "url": diagram["url"],
            "markdown": diagram["markdown"],
            "bytes": int(published.get("bytes") or 0),
            "cached": diagram["cached"],
        }

    async def _tool_seedream_generate(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        alt = str(args.get("alt") or args.get("title") or "image").strip() or "image"
        caption = str(args.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = args.get("text")
        prompt = str(prompt or "").strip()
        if not prompt:
            return {"success": False, "error": "prompt 不能为空", "knowledge_point": kp}

        api_key = str(os.getenv("ARK_API_KEY") or os.getenv("ARK_API") or "").strip()
        if not api_key:
            return {"success": False, "error": "ark_api_key_missing", "knowledge_point": kp}

        base_url = str(os.getenv("ARK_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3").strip().rstrip("/")
        endpoint = f"{base_url}/images/generations"

        model = str(
            args.get("model")
            or os.getenv("SEEDREAM_MODEL")
            or os.getenv("ARK_IMAGE_MODEL")
            or os.getenv("ARK_IMAGES_MODEL")
            or ""
        ).strip()
        if not model:
            return {"success": False, "error": "seedream_model_missing", "knowledge_point": kp}

        size = str(
            args.get("size") or os.getenv("SEEDREAM_SIZE") or os.getenv("ARK_IMAGES_SIZE") or "1024x1024"
        ).strip()
        try:
            n = int(args.get("n") or os.getenv("SEEDREAM_N") or 1)
        except (TypeError, ValueError):
            n = 1
        n = max(1, min(n, 4))
        response_format = str(
            args.get("response_format")
            or os.getenv("ARK_IMAGES_RESPONSE_FORMAT")
            or os.getenv("SEEDREAM_RESPONSE_FORMAT")
            or "b64_json"
        ).strip()

        payload: Dict[str, Any] = {"model": model, "prompt": prompt, "n": n, "size": size}
        if response_format:
            payload["response_format"] = response_format

        timeout_raw = (
            os.getenv("SEEDREAM_TIMEOUT_S") or os.getenv("ARK_IMAGES_TIMEOUT_S") or os.getenv("API_TIMEOUT") or "120"
        )
        try:
            timeout_s = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_s = 120.0
        timeout_s = max(10.0, min(timeout_s, 60.0 * 20.0))

        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            follow_redirects=True,
            headers=headers,
        ) as client:
            try:
                resp = await client.post(endpoint, json=payload)
            except httpx.HTTPError as exc:
                return {"success": False, "error": f"seedream_request_failed: {str(exc)}", "knowledge_point": kp}

            if resp.status_code != 200:
                msg = ""
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        err = data.get("error")
                        if isinstance(err, dict):
                            msg = str(err.get("message") or err.get("detail") or "").strip()
                        elif isinstance(err, str):
                            msg = err.strip()
                        if not msg:
                            msg = str(data.get("message") or data.get("detail") or "").strip()
                except ValueError:
                    msg = ""
                if not msg:
                    msg = (resp.text or "").strip().replace("\n", " ")
                msg = msg[:260]
                return {
                    "success": False,
                    "error": f"seedream_http_{resp.status_code}: {msg}",
                    "knowledge_point": kp,
                }

            try:
                obj = resp.json()
            except ValueError:
                obj = {}

            data_list = obj.get("data") if isinstance(obj, dict) else None
            if not isinstance(data_list, list) or not data_list:
                return {"success": False, "error": "seedream_empty_response", "knowledge_point": kp}

            def _guess_ext(b: bytes) -> str:
                if b.startswith(b"\x89PNG\r\n\x1a\n"):
                    return "png"
                if b.startswith(b"\xff\xd8\xff"):
                    return "jpg"
                if b[:6] in {b"GIF87a", b"GIF89a"}:
                    return "gif"
                if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
                    return "webp"
                if b.startswith(b"BM"):
                    return "bmp"
                return "png"

            diagrams: List[Dict[str, Any]] = []
            for it in [x for x in data_list if isinstance(x, dict)][:n]:
                img_bytes = b""
                b64 = it.get("b64_json")
                if isinstance(b64, str) and b64.strip():
                    try:
                        img_bytes = base64.b64decode(b64.strip())
                    except (ValueError, binascii.Error):
                        img_bytes = b""
                if not img_bytes:
                    u = it.get("url")
                    if isinstance(u, str) and u.strip():
                        try:
                            # Avoid leaking Authorization header to third-party hosts.
                            async with httpx.AsyncClient(
                                timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
                                follow_redirects=True,
                            ) as dl:
                                r2 = await dl.get(u.strip())
                                if r2.status_code == 200:
                                    img_bytes = bytes(r2.content or b"")
                        except httpx.HTTPError:
                            img_bytes = b""
                if not img_bytes:
                    continue

                ext = _guess_ext(img_bytes)
                mime = {
                    "png": "image/png",
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "gif": "image/gif",
                    "webp": "image/webp",
                    "bmp": "image/bmp",
                }.get(str(ext or "").strip().lower() or "png", "application/octet-stream")

                user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
                published = await publish_generated_bytes(
                    img_bytes,
                    user_id=user_id,
                    ext=f".{ext}",
                    file_type="image",
                    mime_type=mime,
                    ttl_s=default_generated_media_ttl_s(),
                )
                media_id = str(published.get("sha256") or "")
                filename = str(published.get("filename") or "")
                url = str(published.get("url") or "")
                markdown = f"![{alt}]({url})"
                diagram = {
                    "knowledge_point": kp,
                    "kind": "seedream_generate",
                    "url": url,
                    "markdown": markdown,
                    "filename": filename,
                    "media_id": media_id,
                    "caption": caption,
                    "prompt": prompt,
                }
                diagrams.append(diagram)

            if not diagrams:
                return {"success": False, "error": "seedream_decode_failed", "knowledge_point": kp}

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
                for d in diagrams:
                    fn = str(d.get("filename") or "").strip()
                    if fn and not any(
                        isinstance(x, dict) and str(x.get("filename") or "").strip() == fn for x in dlist
                    ):
                        dlist.append(d)
                kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
                blob["items"] = [x for x in items if isinstance(x, dict)]
                ctx.working_memory["diagrams"] = blob
            except Exception:
                logger.warning("diagram_store_working_memory_failed", exc_info=True)

            first = diagrams[0]
            first_bytes = 0
            try:
                fp = _GENERATED_DIR / str(first.get("filename") or "")
                if fp.exists() and fp.is_file():
                    first_bytes = int(fp.stat().st_size)
            except (OSError, ValueError):
                first_bytes = 0
            return {
                "success": True,
                "knowledge_point": kp,
                "diagram": first,
                "diagrams": diagrams,
                "media_id": str(first.get("media_id") or ""),
                "filename": str(first.get("filename") or ""),
                "url": str(first.get("url") or ""),
                "markdown": str(first.get("markdown") or ""),
                "bytes": first_bytes,
            }
