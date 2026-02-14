from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from backend.agent.types import CompressedContext


class ExportToolsMixin:
    async def _tool_save_markdown_file(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """保存最终自学档案到 Markdown 文件。"""

        topic = str(args.get("topic") or ctx.current_task).strip() or "study_archive"
        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            # Best-effort: try common keys
            markdown = str(
                ctx.working_memory.get("assemble_study_archive") or ctx.working_memory.get("assemble_markdown") or ""
            ).strip()

        rel_dir = str(args.get("dir") or "study_archives").strip() or "study_archives"

        # Resolve repo root: backend/agent/executor.py -> repo root
        repo_root = Path(__file__).resolve().parents[3]
        out_dir = (repo_root / rel_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize Windows-unfriendly characters in filename.
        safe = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1F]', "_", topic)
        safe = re.sub(r"\\s+", " ", safe).strip()
        safe = safe.strip(". ")
        safe = safe[:80] if len(safe) > 80 else safe
        if not safe:
            safe = "study_archive"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe}_{ts}.md"
        path = out_dir / filename

        try:
            path.write_text(markdown + ("\n" if not markdown.endswith("\n") else ""), encoding="utf-8")
        except Exception as exc:
            return {"success": False, "error": str(exc), "dir": str(out_dir), "filename": filename}

        ctx.working_memory["archive_path"] = str(path)
        return {
            "success": True,
            "path": str(path),
            "dir": str(out_dir),
            "filename": filename,
            "bytes": len((markdown or "").encode("utf-8")),
        }

    async def _tool_export_study_markdown(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """将最终 Markdown 发布为可下载文件（写入 `.local/media/generated/`）。"""

        markdown = args.get("markdown")
        if not isinstance(markdown, str) or not markdown.strip():
            markdown = str(ctx.working_memory.get("markdown") or "").strip()
        if not markdown:
            markdown = str(ctx.working_memory.get("assemble_study_archive") or "").strip()
        if not markdown:
            raise ValueError("markdown_empty")

        data = (markdown + ("\n" if not markdown.endswith("\n") else "")).encode("utf-8")

        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        filename = f"{sha}.md"
        url = f"/api/media/generated/{filename}"

        repo_root = Path(__file__).resolve().parents[3]
        out_dir = (repo_root / ".local" / "media" / "generated").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename

        if not out_path.exists():
            out_path.write_bytes(data)

        try:
            ctx.working_memory["md_url"] = url
            ctx.working_memory["md_filename"] = filename
        except Exception:
            pass

        return {
            "md_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": len(data),
        }

