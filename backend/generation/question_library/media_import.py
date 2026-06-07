from __future__ import annotations

import base64
import io
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional, Sequence

from backend.core.settings import LESSON_PLAN_MODEL, settings
from backend.llm.client import is_llm_configured
from backend.llm.prompts import create_default_prompt_registry
from backend.llm.runner import run_json
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes
from backend.shared.project_paths import resolve_repo_local_dir

SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
SUPPORTED_PDF_MIME = "application/pdf"
SUPPORTED_MIMES = {*SUPPORTED_IMAGE_MIMES, SUPPORTED_PDF_MIME}
IMAGE_SUFFIX_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
PDF_SUFFIXES = {".pdf"}
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_IMAGE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_IMAGE_SIDE = 1800
DEFAULT_MAX_PDF_PAGES = 12
DEFAULT_MAX_IMAGES = 12
DEFAULT_MAX_QUESTIONS = 30


@dataclass(frozen=True)
class MediaFileRef:
    path: Path
    filename: str
    content_type: str


@dataclass(frozen=True)
class ImagePage:
    source_filename: str
    page_number: int
    mime: str
    data: bytes


class MediaImportError(ValueError):
    pass


JsonExtractor = Callable[..., Awaitable[Any]]
MediaPublisher = Callable[..., Awaitable[dict]]


def safe_media_import_task_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return f"ql_media_{uuid.uuid4().hex[:12]}"
    chars = [ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in raw]
    safe = "".join(chars).strip("_-")[:80]
    return safe or f"ql_media_{uuid.uuid4().hex[:12]}"


def media_import_upload_dir(task_id: str) -> Path:
    tid = safe_media_import_task_id(task_id)
    return (resolve_repo_local_dir() / "question_library" / "media_imports" / tid).resolve()


def build_media_question_id(*, now_ts: float | None = None, suffix: str = "") -> str:
    ts = int((time.time() if now_ts is None else float(now_ts)) * 1000)
    tail = str(suffix or uuid.uuid4().hex[:8]).strip()[:12] or uuid.uuid4().hex[:8]
    return f"media_{ts:x}_{tail}"[:50]


def detect_supported_media_type(filename: str, content_type: str = "") -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    ctype = str(content_type or "").split(";", 1)[0].strip().lower()
    if ctype in SUPPORTED_MIMES:
        return ctype
    if suffix in IMAGE_SUFFIX_MIMES:
        return IMAGE_SUFFIX_MIMES[suffix]
    if suffix in PDF_SUFFIXES:
        return SUPPORTED_PDF_MIME
    raise MediaImportError("unsupported_media_type")


def _safe_filename(filename: str, index: int, mime: str) -> str:
    raw_name = Path(str(filename or "")).name.strip()
    stem = Path(raw_name).stem if raw_name else f"upload-{index}"
    suffix = Path(raw_name).suffix.lower()
    if mime == SUPPORTED_PDF_MIME:
        suffix = ".pdf"
    elif mime == "image/png":
        suffix = ".png"
    elif mime == "image/webp":
        suffix = ".webp"
    else:
        suffix = ".jpg"

    safe_stem = "".join(ch if (ch.isalnum() or ch in {"_", "-"}) else "_" for ch in stem).strip("_-")
    safe_stem = (safe_stem or f"upload-{index}")[:48]
    return f"{index:02d}-{safe_stem}{suffix}"


async def persist_upload_files(
    *,
    task_id: str,
    uploads: Sequence[Any],
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> List[MediaFileRef]:
    refs: List[MediaFileRef] = []
    upload_dir = media_import_upload_dir(task_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    limit = max(1, int(max_file_bytes or DEFAULT_MAX_FILE_BYTES))

    for index, upload in enumerate(uploads or [], start=1):
        filename = str(getattr(upload, "filename", "") or "").strip()
        content_type = str(getattr(upload, "content_type", "") or "").strip()
        mime = detect_supported_media_type(filename, content_type)
        data = await upload.read()
        if not data:
            continue
        if len(data) > limit:
            raise MediaImportError("file_too_large")

        stored_name = _safe_filename(filename, index, mime)
        path = (upload_dir / stored_name).resolve()
        if upload_dir not in path.parents:
            raise MediaImportError("unsafe_upload_path")
        path.write_bytes(data)
        refs.append(MediaFileRef(path=path, filename=filename or stored_name, content_type=mime))

    if not refs:
        raise MediaImportError("no_supported_files")
    return refs


def _join_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(_join_text(item) for item in value if _join_text(item)).strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False).strip()
    return str(value).strip()


def _first_text(obj: dict, keys: Sequence[str]) -> str:
    for key in keys:
        value = _join_text(obj.get(key))
        if value:
            return value
    return ""


def normalize_extracted_questions(payload: Any, *, max_questions: int = DEFAULT_MAX_QUESTIONS) -> List[dict]:
    if isinstance(payload, dict):
        raw_questions = payload.get("questions") or payload.get("items") or []
    else:
        raw_questions = payload
    if not isinstance(raw_questions, list):
        return []

    limit = max(1, min(int(max_questions or DEFAULT_MAX_QUESTIONS), DEFAULT_MAX_QUESTIONS))
    out: List[dict] = []
    for item in raw_questions:
        if not isinstance(item, dict):
            continue
        stem = _first_text(item, ["stem", "question", "content", "题干", "题目", "试题"])
        if not stem:
            continue
        out.append(
            {
                "stem": stem,
                "answer": _first_text(item, ["answer", "solution", "final_answer", "答案", "参考答案"]),
                "analysis": _first_text(item, ["analysis", "explanation", "reasoning", "解析", "解答过程", "详解"]),
            }
        )
        if len(out) >= limit:
            break
    return out


def _normalize_image_for_vision(
    data: bytes,
    *,
    mime: str,
    max_side: int = DEFAULT_MAX_IMAGE_SIDE,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> tuple[str, bytes]:
    if len(data or b"") <= max_bytes:
        return mime, data

    try:
        from PIL import Image
    except ImportError as exc:
        raise MediaImportError("pillow_required_for_large_image") from exc

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if max(image.size or (0, 0)) > max_side:
            image.thumbnail((max_side, max_side))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")

        for quality in (88, 78, 68, 58):
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=quality, optimize=True)
            out = buf.getvalue()
            if len(out) <= max_bytes:
                return "image/jpeg", out
    raise MediaImportError("image_too_large_for_vision")


def _render_pdf_pages(
    ref: MediaFileRef,
    *,
    max_pdf_pages: int,
    max_image_side: int,
    max_image_bytes: int,
) -> List[ImagePage]:
    try:
        import fitz
    except ImportError as exc:
        raise MediaImportError("pymupdf_required_for_pdf_import") from exc

    pages: List[ImagePage] = []
    doc = fitz.open(ref.path)
    try:
        page_count = min(max(0, int(doc.page_count or 0)), max(1, int(max_pdf_pages or DEFAULT_MAX_PDF_PAGES)))
        zoom = 2.0
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            data = pix.tobytes("png")
            mime, normalized = _normalize_image_for_vision(
                data,
                mime="image/png",
                max_side=max_image_side,
                max_bytes=max_image_bytes,
            )
            pages.append(
                ImagePage(
                    source_filename=ref.filename or ref.path.name,
                    page_number=page_index + 1,
                    mime=mime,
                    data=normalized,
                )
            )
    finally:
        doc.close()
    return pages


def load_media_as_image_pages(
    ref: MediaFileRef,
    *,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_image_side: int = DEFAULT_MAX_IMAGE_SIDE,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> List[ImagePage]:
    mime = detect_supported_media_type(ref.filename or ref.path.name, ref.content_type)
    if mime == SUPPORTED_PDF_MIME:
        return _render_pdf_pages(
            ref,
            max_pdf_pages=max_pdf_pages,
            max_image_side=max_image_side,
            max_image_bytes=max_image_bytes,
        )

    data = ref.path.read_bytes()
    out_mime, normalized = _normalize_image_for_vision(
        data,
        mime=mime,
        max_side=max_image_side,
        max_bytes=max_image_bytes,
    )
    return [ImagePage(source_filename=ref.filename or ref.path.name, page_number=1, mime=out_mime, data=normalized)]


def load_all_media_pages(
    files: Sequence[MediaFileRef],
    *,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_images: int = DEFAULT_MAX_IMAGES,
) -> List[ImagePage]:
    limit = max(1, min(int(max_images or DEFAULT_MAX_IMAGES), DEFAULT_MAX_IMAGES))
    pages: List[ImagePage] = []
    for ref in files or []:
        pages.extend(load_media_as_image_pages(ref, max_pdf_pages=max_pdf_pages))
        if len(pages) >= limit:
            return pages[:limit]
    return pages


def _preview_ext_for_mime(mime: str) -> str:
    normalized = str(mime or "").split(";", 1)[0].strip().lower()
    if normalized == "image/png":
        return ".png"
    if normalized == "image/webp":
        return ".webp"
    return ".jpg"


async def publish_media_pages_for_preview(
    pages: Sequence[ImagePage],
    *,
    user_id: str,
    max_diagrams: int = 6,
    publisher: Optional[MediaPublisher] = None,
) -> List[dict]:
    uid = str(user_id or "").strip()
    if not uid:
        raise MediaImportError("missing_user_id")

    limit = max(1, min(int(max_diagrams or 6), 6))
    publish = publisher or publish_generated_bytes
    diagrams: List[dict] = []
    for page in list(pages or [])[:limit]:
        if not isinstance(page, ImagePage) or not page.data:
            continue
        meta = await publish(
            page.data,
            user_id=uid,
            ext=_preview_ext_for_mime(page.mime),
            file_type="question_library_media_import_source",
            mime_type=page.mime,
            ttl_s=default_generated_media_ttl_s(),
        )
        url = str((meta or {}).get("url") or "").strip()
        if not url:
            continue
        source = str(page.source_filename or "upload").strip() or "upload"
        label = f"{source} 第 {int(page.page_number or 1)} 页"
        diagrams.append(
            {
                "kind": "source",
                "url": url,
                "filename": str((meta or {}).get("filename") or "").strip(),
                "media_id": str((meta or {}).get("sha256") or "").strip(),
                "alt": label,
                "caption": f"原始导入：{label}",
                "markdown": f"![{label}]({url})",
            }
        )
    return diagrams


def _data_url(page: ImagePage) -> str:
    b64 = base64.b64encode(page.data).decode("ascii")
    return f"data:{page.mime};base64,{b64}"


def build_media_import_messages(
    *,
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    max_questions: int,
    pages: Sequence[ImagePage],
) -> List[dict]:
    limit = max(1, min(int(max_questions or DEFAULT_MAX_QUESTIONS), DEFAULT_MAX_QUESTIONS))
    system = create_default_prompt_registry().render("question.media_import.extract.v1").content
    page_notes = "\n".join(
        f"- image {idx + 1}: {page.source_filename} page {page.page_number}" for idx, page in enumerate(pages)
    )
    user_text = (
        f"学科：{str(subject or '').strip() or '未指定'}\n"
        f"主题/知识点：{str(topic or '').strip() or '未指定'}\n"
        f"难度：{str(difficulty or '').strip() or '未指定'}\n"
        f"题型：{str(question_type or '').strip() or '未指定'}\n"
        f"最多提取：{limit} 题\n\n"
        f"图片顺序：\n{page_notes}\n\n"
        "输出格式：{\"questions\":[{\"stem\":\"题干\",\"answer\":\"答案\",\"analysis\":\"解析\"}]}"
    )
    content: List[dict] = [{"type": "text", "text": user_text}]
    content.extend({"type": "image_url", "image_url": {"url": _data_url(page)}} for page in pages)
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


async def extract_questions_from_media_pages(
    *,
    pages: Sequence[ImagePage],
    subject: str,
    topic: str,
    difficulty: str,
    question_type: str,
    max_questions: int,
    model: Optional[str] = None,
    extractor: Optional[JsonExtractor] = None,
) -> List[dict]:
    if not pages:
        return []
    if not is_llm_configured(scope="chat"):
        raise MediaImportError("llm_not_configured")

    messages = build_media_import_messages(
        subject=subject,
        topic=topic,
        difficulty=difficulty,
        question_type=question_type,
        max_questions=max_questions,
        pages=pages,
    )
    runner = extractor or run_json
    payload = await runner(
        messages=messages,
        model=(model or "").strip() or str(LESSON_PLAN_MODEL or "").strip() or "openai/gpt-4o-mini",
        temperature=0.1,
        max_tokens=max(1200, min(8000, int(max_questions or 1) * 900)),
        response_format={"type": "json_object"},
        default={"questions": []},
        retries=1,
        raise_on_fail=True,
        timeout_s=float(settings.api_timeout_seconds or 120),
        req_id_prefix="ql_media_import",
        scope="question_library_media_import",
    )
    return normalize_extracted_questions(payload, max_questions=max_questions)
