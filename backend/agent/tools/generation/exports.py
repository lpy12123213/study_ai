from __future__ import annotations

from typing import Any, Dict

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.generation.study_materials.archive_storage import (
    resolve_study_archives_dir,
    safe_study_archive_filename,
)
from backend.media.generated import default_generated_media_ttl_s, publish_generated_text

logger = get_logger(__name__)


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

        out_dir = resolve_study_archives_dir(str(args.get("dir") or "study_archives"))
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = safe_study_archive_filename(topic)
        path = out_dir / filename

        try:
            path.write_text(markdown + ("\n" if not markdown.endswith("\n") else ""), encoding="utf-8")
        except OSError as exc:
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

        user_id = str(getattr(ctx.user_profile, "user_id", "") or "").strip() or "anonymous"
        published = await publish_generated_text(
            markdown,
            user_id=user_id,
            ext=".md",
            file_type="md",
            mime_type="text/markdown; charset=utf-8",
            ttl_s=default_generated_media_ttl_s(),
        )
        url = str(published.get("url") or "")
        filename = str(published.get("filename") or "")
        sha = str(published.get("sha256") or "")
        size = int(published.get("bytes") or 0)

        try:
            ctx.working_memory["md_url"] = url
            ctx.working_memory["md_filename"] = filename
        except Exception:
            logger.exception("export_store_working_memory_failed")

        return {
            "md_url": url,
            "filename": filename,
            "sha256": sha,
            "bytes": size,
        }
