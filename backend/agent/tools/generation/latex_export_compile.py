from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes
from backend.shared.project_paths import resolve_repo_root

from backend.agent.tools.generation.latex_export_utils import _auto_fix_latex

logger = get_logger(__name__)


class LatexCompileMixin:
    async def _tool_compile_latex_to_pdf(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """编译 LaTeX 为 PDF，并发布为可下载文件。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"

        tex = args.get("latex")
        if not isinstance(tex, str) or not tex.strip():
            tex = str(ctx.working_memory.get("latex_tex") or "").strip()
        if not tex:
            raise ValueError("latex_missing")

        tex = _auto_fix_latex(tex).strip() + "\n"
        try:
            ctx.working_memory["latex_tex"] = tex
        except Exception:
            logger.debug("latex_export_set_working_memory_failed", exc_info=True)

        repo_root = resolve_repo_root()
        gen_dir = (repo_root / ".local" / "media" / "generated").resolve()
        gen_dir.mkdir(parents=True, exist_ok=True)

        build_dir = (repo_root / ".local" / "latex_build" / uuid.uuid4().hex[:12]).resolve()
        build_dir.mkdir(parents=True, exist_ok=True)

        tex_path = build_dir / "main.tex"
        tex_path.write_text(tex, encoding="utf-8")

        # Copy local generated images referenced by includegraphics into build dir.
        try:
            includes = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
        except Exception:
            includes = []
        copied = 0
        missing: List[str] = []
        for inc in includes[:80]:
            name = str(inc or "").strip()
            if not name:
                continue
            # Strip any path prefixes and keep basename only.
            base = Path(name).name
            if not base:
                continue
            src = gen_dir / base
            if not src.exists() or not src.is_file():
                # Try to resolve /api/media/generated/<file>
                if base.startswith("generated") and "/" in name:
                    base2 = name.split("/")[-1]
                    src = gen_dir / base2
                if not src.exists() or not src.is_file():
                    missing.append(base)
                    continue
            dst = build_dir / base
            try:
                if not dst.exists():
                    dst.write_bytes(src.read_bytes())
                copied += 1
            except Exception:
                continue

        # Compile with xelatex directly (avoid latexmk dependency on perl on Windows/MiKTeX).
        import subprocess

        cmd = ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "main.tex"]
        # First-time MiKTeX compilation may be slow (font cache / on-the-fly package install).
        timeout_s = float(os.getenv("STUDY_MATERIALS_LATEX_TIMEOUT_S") or 600)
        timeout_s = max(30.0, min(timeout_s, 60.0 * 20.0))

        proc = None
        try:
            # Two passes to resolve references/TOC reliably.
            for _ in range(2):
                proc = subprocess.run(
                    cmd,
                    cwd=str(build_dir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_s,
                )
                if proc.returncode != 0:
                    break
        except FileNotFoundError as exc:
            hint = (
                "xelatex not found. Install a LaTeX engine (MiKTeX or TeX Live) and make sure `xelatex` is on PATH. "
                "Windows example: `winget install MiKTeX.MiKTeX` (or `choco install miktex`)."
            )
            await self._emit_status(f"PDF 编译已跳过：{hint}")
            return {
                "skipped": True,
                "reason": "latex_engine_not_found",
                "hint": hint,
                "engine": "xelatex",
                "error": str(exc),
            }

        if proc is None or proc.returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            stdout = (getattr(proc, "stdout", "") or "").strip()
            msg = stderr[-2000:] if stderr else stdout[-2000:]
            raise RuntimeError(f"latex_compile_failed: {msg}")

        pdf_path = build_dir / "main.pdf"
        if not pdf_path.exists() or not pdf_path.is_file():
            raise RuntimeError("pdf_missing")

        pdf_bytes = pdf_path.read_bytes()
        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await publish_generated_bytes(
            pdf_bytes,
            user_id=user_id,
            ext=".pdf",
            file_type="pdf",
            mime_type="application/pdf",
            ttl_s=default_generated_media_ttl_s(),
        )
        sha = str(published.get("sha256") or "")
        filename = str(published.get("filename") or "")
        url = str(published.get("url") or "")
        size = int(published.get("bytes") or 0)

        try:
            ctx.working_memory["pdf_url"] = url
            ctx.working_memory["pdf_filename"] = filename
        except Exception:
            logger.debug("latex_export_set_working_memory_failed", exc_info=True)

        return {
            "pdf_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": size,
            "topic": topic,
            "copied_images": copied,
            "missing_images": missing[:20],
            "engine": "xelatex",
        }
