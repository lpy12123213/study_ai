from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.agent.types import CompressedContext


def _tikz_missing_hint() -> str:
    return (
        "TikZ rendering requires both `xelatex` and `dvisvgm` on PATH. "
        "Install a TeX distribution (MiKTeX/TeX Live) that provides them, or use the Matplotlib fallback "
        "(draw_diagram/plot tools)."
    )


class DiagramToolsMixin:
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

        repo_root = Path(__file__).resolve().parents[3]
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

        repo_root = Path(__file__).resolve().parents[3]
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

    async def _tool_tikz_to_svg(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        alt = str(args.get("alt") or args.get("title") or "diagram").strip() or "diagram"
        caption = str(args.get("caption") or "").strip()

        kp = str(args.get("knowledge_point") or "").strip()
        if not kp:
            kps = args.get("knowledge_points")
            if isinstance(kps, list) and kps:
                kp = str(kps[0] or "").strip()
        if not kp:
            kp = str(ctx.current_task or "").strip()

        tikz = args.get("tikz")
        if not isinstance(tikz, str) or not tikz.strip():
            tikz = args.get("code")
        if not isinstance(tikz, str) or not tikz.strip():
            tikz = args.get("latex")
        tikz = str(tikz or "").strip()
        if not tikz:
            return {"success": False, "error": "tikz 不能为空", "knowledge_point": kp}

        missing_tools: List[str] = []
        if shutil.which("xelatex") is None:
            missing_tools.append("xelatex")
        if shutil.which("dvisvgm") is None:
            missing_tools.append("dvisvgm")
        if missing_tools:
            return {
                "success": False,
                "error": "tikz_tools_missing",
                "missing": missing_tools,
                "hint": _tikz_missing_hint(),
                "knowledge_point": kp,
            }

        if "\\begin{tikzpicture" not in tikz:
            tikz = "\\begin{tikzpicture}\n" + tikz + "\n\\end{tikzpicture}"

        preamble = args.get("preamble")
        if not isinstance(preamble, str):
            preamble = ""
        preamble = preamble.strip()

        tex_lines: List[str] = [
            r"\\documentclass[tikz]{standalone}",
            r"\\usepackage{tikz}",
        ]
        if preamble:
            tex_lines.append(preamble)
        tex_lines.extend([r"\\begin{document}", tikz, r"\\end{document}", ""])
        tex = "\n".join(tex_lines)

        repo_root = Path(__file__).resolve().parents[3]
        gen_dir = (repo_root / ".local" / "media" / "generated").resolve()
        gen_dir.mkdir(parents=True, exist_ok=True)

        build_dir = (repo_root / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
        build_dir.mkdir(parents=True, exist_ok=True)

        tex_path = build_dir / "main.tex"
        tex_path.write_text(tex, encoding="utf-8")

        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        timeout_raw = (
            os.getenv("STUDY_MATERIALS_TIKZ_TIMEOUT_S")
            or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S")
            or os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT")
            or "240"
        )
        try:
            timeout_s = float(timeout_raw)
        except Exception:
            timeout_s = 240.0
        timeout_s = max(30.0, min(timeout_s, 60.0 * 20.0))

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except FileNotFoundError as exc:
            return {
                "success": False,
                "error": f"latex_engine_not_found: {exc}",
                "hint": _tikz_missing_hint(),
                "knowledge_point": kp,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "latex_compile_timeout", "knowledge_point": kp}

        if proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            stdout = (getattr(proc, "stdout", "") or "").strip()
            msg = stderr[-2000:] if stderr else stdout[-2000:]
            return {"success": False, "error": f"latex_compile_failed: {msg}", "knowledge_point": kp}

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.exists() or not pdf_path.is_file():
            return {"success": False, "error": "pdf_missing", "knowledge_point": kp}

        svg_path = build_dir / "main.svg"
        dvisvgm_cmd = [
            "dvisvgm",
            "--pdf",
            "--no-fonts",
            "--exact-bbox",
            "-o",
            str(svg_path.name),
            str(pdf_path.name),
        ]

        try:
            proc2 = subprocess.run(
                dvisvgm_cmd,
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except FileNotFoundError as exc:
            return {
                "success": False,
                "error": f"dvisvgm_not_found: {exc}",
                "hint": _tikz_missing_hint(),
                "knowledge_point": kp,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "dvisvgm_timeout", "knowledge_point": kp}

        if proc2.returncode != 0:
            stderr = (getattr(proc2, "stderr", "") or "").strip()
            stdout = (getattr(proc2, "stdout", "") or "").strip()
            msg = stderr[-2000:] if stderr else stdout[-2000:]
            return {"success": False, "error": f"dvisvgm_failed: {msg}", "knowledge_point": kp}

        if not svg_path.exists() or not svg_path.is_file():
            return {"success": False, "error": "svg_missing", "knowledge_point": kp}

        svg_bytes = svg_path.read_bytes()
        media_id = hashlib.sha256(svg_bytes).hexdigest()
        filename = f"{media_id}.svg"
        out_path = gen_dir / filename
        try:
            if not out_path.exists():
                out_path.write_bytes(svg_bytes)
        except Exception as exc:
            return {"success": False, "error": str(exc), "filename": filename, "knowledge_point": kp}

        url = f"/api/media/generated/{filename}"
        markdown = f"![{alt}]({url})"
        diagram = {
            "knowledge_point": kp,
            "kind": "tikz_to_svg",
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
            "bytes": len(svg_bytes),
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

        size = str(args.get("size") or os.getenv("SEEDREAM_SIZE") or os.getenv("ARK_IMAGES_SIZE") or "1024x1024").strip()
        try:
            n = int(args.get("n") or os.getenv("SEEDREAM_N") or 1)
        except Exception:
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

        timeout_raw = os.getenv("SEEDREAM_TIMEOUT_S") or os.getenv("ARK_IMAGES_TIMEOUT_S") or os.getenv("API_TIMEOUT") or "120"
        try:
            timeout_s = float(timeout_raw)
        except Exception:
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
            except Exception as exc:
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
                except Exception:
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
            except Exception:
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

            repo_root = Path(__file__).resolve().parents[3]
            gen_dir = (repo_root / ".local" / "media" / "generated").resolve()
            gen_dir.mkdir(parents=True, exist_ok=True)

            diagrams: List[Dict[str, Any]] = []
            for it in [x for x in data_list if isinstance(x, dict)][:n]:
                img_bytes = b""
                b64 = it.get("b64_json")
                if isinstance(b64, str) and b64.strip():
                    try:
                        img_bytes = base64.b64decode(b64.strip())
                    except Exception:
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
                        except Exception:
                            img_bytes = b""
                if not img_bytes:
                    continue

                ext = _guess_ext(img_bytes)
                media_id = hashlib.sha256(img_bytes).hexdigest()
                filename = f"{media_id}.{ext}"
                out_path = gen_dir / filename
                try:
                    if not out_path.exists():
                        out_path.write_bytes(img_bytes)
                except Exception:
                    continue

                url = f"/api/media/generated/{filename}"
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
                    if fn and not any(isinstance(x, dict) and str(x.get("filename") or "").strip() == fn for x in dlist):
                        dlist.append(d)
                kp_item["diagrams"] = [d for d in dlist if isinstance(d, dict)][-20:]
                blob["items"] = [x for x in items if isinstance(x, dict)]
                ctx.working_memory["diagrams"] = blob
            except Exception:
                pass

            first = diagrams[0]
            first_bytes = 0
            try:
                fp = gen_dir / str(first.get("filename") or "")
                if fp.exists() and fp.is_file():
                    first_bytes = int(fp.stat().st_size)
            except Exception:
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
