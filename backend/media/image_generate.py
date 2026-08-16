"""Volcano ARK Seedream text-to-image generation.

Standalone async function that talks to ARK's `/images/generations` endpoint,
decodes the response (base64 or hosted URL), and publishes the bytes via
`publish_generated_bytes`. Designed to be called from MCP tools without
requiring a CompressedContext.
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Dict, List

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import model_name, model_param, model_param_int, model_provider
from backend.media.generated import default_generated_media_ttl_s, publish_generated_bytes

logger = get_logger(__name__)


_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


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


async def generate_image_via_seedream(
    *,
    prompt: str,
    user_id: str,
    alt: str = "image",
    caption: str = "",
    model: str = "",
    size: str = "",
    n: int = 1,
    response_format: str = "",
    timeout_s: float = 0.0,
) -> Dict[str, Any]:
    """Generate one or more images via ARK Seedream and publish each.

    Returns:
        On success: {"success": True, "images": [{url, markdown, filename, media_id, ...}], "model", "prompt"}
        On failure: {"success": False, "error": "...", "hint": "..."}
    """

    prompt = str(prompt or "").strip()
    if not prompt:
        return {"success": False, "error": "prompt_empty"}

    ark_provider = model_provider("ark")
    api_key = str(ark_provider.api_key or "").strip()
    if not api_key:
        return {
            "success": False,
            "error": "ark_api_key_missing",
            "hint": "需要在 config/model.json 的 providers.ark 中配置 API Key。",
        }

    base_url = str(ark_provider.base_url or "").strip().rstrip("/")
    endpoint = f"{base_url}/images/generations"

    effective_model = str(
        model
        or model_name("image_generation", provider="ark")
        or ""
    ).strip()
    if not effective_model:
        return {
            "success": False,
            "error": "seedream_model_missing",
            "hint": "需要在 config/model.json 的 models.image_generation 中配置模型。",
        }

    effective_size = str(size or model_param("image_size", "1024x1024")).strip()
    try:
        effective_n = int(n or model_param_int("image_count", 1))
    except (TypeError, ValueError):
        effective_n = 1
    effective_n = max(1, min(effective_n, 4))

    effective_response_format = str(
        response_format
        or model_param("image_response_format", "b64_json")
        or "b64_json"
    ).strip()

    payload: Dict[str, Any] = {
        "model": effective_model,
        "prompt": prompt,
        "n": effective_n,
        "size": effective_size,
    }
    if effective_response_format:
        payload["response_format"] = effective_response_format

    if not timeout_s:
        timeout_raw = (
            os.getenv("SEEDREAM_TIMEOUT_S") or os.getenv("ARK_IMAGES_TIMEOUT_S") or os.getenv("API_TIMEOUT") or "120"
        )
        try:
            timeout_s = float(timeout_raw)
        except (TypeError, ValueError):
            timeout_s = 120.0
    timeout_s = max(10.0, min(float(timeout_s), 60.0 * 20.0))

    uid = str(user_id or "").strip() or "anonymous"
    alt_safe = str(alt or "image").strip() or "image"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            resp = await client.post(endpoint, json=payload)
        except httpx.HTTPError as exc:
            return {"success": False, "error": f"seedream_request_failed: {exc}"}

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
            return {"success": False, "error": f"seedream_http_{resp.status_code}: {msg[:260]}"}

        try:
            obj = resp.json()
        except ValueError:
            obj = {}

        data_list = obj.get("data") if isinstance(obj, dict) else None
        if not isinstance(data_list, list) or not data_list:
            return {"success": False, "error": "seedream_empty_response"}

        images: List[Dict[str, Any]] = []
        for it in [x for x in data_list if isinstance(x, dict)][:effective_n]:
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
                        # Don't leak our Authorization header to a third-party host.
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
            mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
            published = await publish_generated_bytes(
                img_bytes,
                user_id=uid,
                ext=f".{ext}",
                file_type="image",
                mime_type=mime,
                ttl_s=default_generated_media_ttl_s(),
            )
            url = str(published.get("url") or "")
            filename = str(published.get("filename") or "")
            images.append(
                {
                    "url": url,
                    "markdown": f"![{alt_safe}]({url})" if url else "",
                    "filename": filename,
                    "media_id": str(published.get("sha256") or ""),
                    "bytes": int(published.get("bytes") or len(img_bytes)),
                    "mime_type": mime,
                    "caption": caption,
                }
            )

        if not images:
            return {"success": False, "error": "seedream_decode_failed"}

        return {
            "success": True,
            "kind": "seedream_generate",
            "model": effective_model,
            "prompt": prompt,
            "size": effective_size,
            "images": images,
        }
