from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import mimetypes
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.api.auth import require_auth
from backend.core.logging_utils import get_logger
from backend.core.settings import env_int
from backend.core.time_utils import utcnow_naive
from backend.database.repositories.system.generated_files import get_generated_file

router = APIRouter(dependencies=[Depends(require_auth)])
logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = PROJECT_ROOT / ".local" / "media"
GENERATED_DIR = MEDIA_DIR / "generated"


DEFAULT_ALLOWED_DOMAINS = [
    # Main site + static assets for zujuan crawler.
    "zujuan.xkw.com",
    "staticzujuan.xkw.com",
]

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
}

_PROXY_CACHE_STATS = {
    "hits": 0,
    "misses": 0,
    "expired": 0,
    "evicted_files": 0,
    "evicted_bytes": 0,
}

_proxy_http_client: Optional[httpx.AsyncClient] = None
_proxy_http_client_lock = asyncio.Lock()



def reset_proxy_cache_stats() -> None:
    for key in list(_PROXY_CACHE_STATS.keys()):
        _PROXY_CACHE_STATS[key] = 0


def get_proxy_cache_stats() -> dict[str, int]:
    return {key: int(value or 0) for key, value in _PROXY_CACHE_STATS.items()}


def _bump_proxy_cache_stat(key: str, amount: int = 1) -> None:
    if key not in _PROXY_CACHE_STATS:
        return
    _PROXY_CACHE_STATS[key] = int(_PROXY_CACHE_STATS.get(key, 0) or 0) + int(amount or 0)


async def _get_proxy_http_client() -> httpx.AsyncClient:
    global _proxy_http_client
    if _proxy_http_client is not None:
        return _proxy_http_client

    async with _proxy_http_client_lock:
        if _proxy_http_client is not None:
            return _proxy_http_client
        _proxy_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": "ExamPaperAssistant/1.0"},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
        return _proxy_http_client


async def close_proxy_http_client() -> None:
    global _proxy_http_client
    async with _proxy_http_client_lock:
        client = _proxy_http_client
        _proxy_http_client = None
    if client is None:
        return
    try:
        await client.aclose()
    except (RuntimeError, httpx.HTTPError):
        return


def _get_allowed_domains() -> list[str]:
    raw = (os.getenv("MEDIA_PROXY_ALLOWED_DOMAINS") or "").strip()
    if raw == "*":
        return ["*"]

    items = [s.strip().lower() for s in raw.split(",") if s.strip()]
    return items or list(DEFAULT_ALLOWED_DOMAINS)


def _is_allowed_host(host: str) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return False

    allowed = _get_allowed_domains()
    if "*" in allowed:
        return True

    for d in allowed:
        d = (d or "").strip().lower()
        if not d:
            continue
        if host == d or host.endswith(f".{d}"):
            return True
    return False


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    # Fail closed: only allow globally routable addresses.
    return bool(getattr(ip, "is_global", False))


async def _resolve_host_ips(host: str) -> list[ipaddress._BaseAddress]:
    host = (host or "").strip()
    if not host:
        return []

    # If host is already an IP literal, validate directly.
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, RuntimeError):
        return []

    out: list[ipaddress._BaseAddress] = []
    seen: set[str] = set()
    for _, _, _, _, sockaddr in infos:
        try:
            ip_str = str(sockaddr[0])
        except (IndexError, TypeError):
            continue
        if not ip_str or ip_str in seen:
            continue
        seen.add(ip_str)
        try:
            out.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue
    return out


async def _normalize_remote_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("empty_url")
    if url.startswith("//"):
        url = f"https:{url}"

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("invalid_scheme")
    if not parsed.netloc:
        raise ValueError("missing_host")

    if parsed.username or parsed.password:
        raise ValueError("forbidden_userinfo")

    port = parsed.port
    if port is not None and port not in {80, 443}:
        raise ValueError("forbidden_port")

    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("forbidden_host")

    if not _is_allowed_host(host):
        raise ValueError("host_not_allowed")

    ips = await _resolve_host_ips(host)
    if not ips:
        # Cannot validate DNS => do not proxy.
        raise ValueError("dns_resolution_failed")
    for ip in ips:
        if not _is_public_ip(ip):
            raise ValueError("forbidden_ip")

    return url


def _pick_extension(url: str, content_type: str) -> str:
    url_path = urlparse(url).path
    suffix = Path(url_path).suffix.lower()
    if suffix and len(suffix) <= 8:
        # Only allow common raster image extensions.
        if suffix in ALLOWED_IMAGE_EXTENSIONS:
            return suffix

    ct = (content_type or "").split(";")[0].strip().lower()
    guessed = mimetypes.guess_extension(ct) if ct else None
    if guessed and guessed.lower() in ALLOWED_IMAGE_EXTENSIONS:
        return guessed.lower()
    return ".bin"


def _find_cached_file(media_id: str) -> Optional[Path]:
    if not MEDIA_DIR.exists():
        return None
    for p in MEDIA_DIR.glob(f"{media_id}.*"):
        if p.is_file():
            return p
    return None


def _is_safe_generated_filename(name: str) -> bool:
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    stem, dot, ext = name.rpartition(".")
    if dot != ".":
        return False
    allowed_ext = ext.lower() in {
        "svg",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "md",
        "tex",
        "pdf",
        "zip",
        "docx",
        "mp4",
        "srt",
        "json",
        "py",
    }
    if not allowed_ext:
        return False

    # Normal generated files are user-scoped 64-character hashes. Historical
    # Gaokao imports use deterministic, registered SVG sidecar names; accept
    # only their two narrow formats. The endpoint still requires a matching
    # generated_files row owned by the current user and resolves under
    # GENERATED_DIR before serving.
    if len(stem) == 64 and all(c in "0123456789abcdef" for c in stem.lower()):
        return True
    if ext.lower() != "svg":
        return False
    if stem.startswith("eol-"):
        digest = stem.removeprefix("eol-")
        return len(digest) == 32 and all(c in "0123456789abcdef" for c in digest.lower())
    if stem.startswith("gaokao-"):
        return len(stem) <= 192 and all(c.isascii() and (c.islower() or c.isdigit() or c == "-") for c in stem)
    return False


def _file_response(path: Path, *, filename: Optional[str] = None) -> FileResponse:
    headers = {"X-Content-Type-Options": "nosniff"}
    if filename:
        return FileResponse(path, filename=filename, headers=headers)
    return FileResponse(path, headers=headers)


@router.get("/media/generated/{filename}")
async def get_generated_media(filename: str, user: dict = Depends(require_auth)) -> FileResponse:
    """Serve locally generated media from `.local/media/generated/`."""

    if not _is_safe_generated_filename(filename):
        raise HTTPException(status_code=400, detail="invalid_filename")

    meta = await get_generated_file(filename=filename)
    if not meta:
        raise HTTPException(status_code=404, detail="not_found")

    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id or str(meta.get("user_id") or "").strip() != user_id:
        # Avoid leaking existence across users.
        raise HTTPException(status_code=404, detail="not_found")

    expires_at = str(meta.get("expires_at") or "").strip()
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if exp_dt.tzinfo is not None:
                exp_dt = exp_dt.astimezone(timezone.utc).replace(tzinfo=None)
            if exp_dt and exp_dt < utcnow_naive():
                raise HTTPException(status_code=410, detail="link_expired")
        except HTTPException:
            raise
        except ValueError:
            # If metadata is malformed, fail closed.
            raise HTTPException(status_code=410, detail="link_expired")

    path = (GENERATED_DIR / filename).resolve()
    try:
        path.relative_to(GENERATED_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="not_found")

    ext = path.suffix.lower().lstrip(".")
    if ext in {"md", "tex", "pdf", "zip", "docx", "srt", "json", "py"}:
        # Force "download" behavior for generated documents (avoid opening raw text/PDF in-app).
        return _file_response(path, filename=filename)
    return _file_response(path)


def _iter_proxy_cache_files() -> list[Path]:
    if not MEDIA_DIR.exists():
        return []
    out: list[Path] = []
    for p in MEDIA_DIR.iterdir():
        if p.is_dir():
            continue
        out.append(p)
    return out


def _prune_proxy_cache() -> dict[str, int]:
    """
    Best-effort pruning to avoid unbounded disk growth.

    Controls:
    - MEDIA_PROXY_CACHE_TTL_SECONDS (default: 7 days)
    - MEDIA_PROXY_CACHE_MAX_BYTES  (default: 512MB)
    - MEDIA_PROXY_CACHE_MAX_FILES  (default: 5000)
    """

    ttl_s = env_int("MEDIA_PROXY_CACHE_TTL_SECONDS", 7 * 24 * 3600)
    max_bytes = env_int("MEDIA_PROXY_CACHE_MAX_BYTES", 512 * 1024 * 1024)
    max_files = env_int("MEDIA_PROXY_CACHE_MAX_FILES", 5000)

    ttl_s = max(0, min(ttl_s, 365 * 24 * 3600))
    max_bytes = max(1, min(max_bytes, 10 * 1024 * 1024 * 1024))
    max_files = max(1, min(max_files, 200_000))

    stats = {
        "temp_deleted": 0,
        "expired": 0,
        "evicted_files": 0,
        "evicted_bytes": 0,
    }

    files = _iter_proxy_cache_files()
    if not files:
        return stats

    # 1) Delete temp files and expired files.
    survivors: list[tuple[Path, float, int]] = []
    for p in files:
        try:
            if p.name.endswith(".tmp"):
                p.unlink(missing_ok=True)
                stats["temp_deleted"] += 1
                continue
            stat = p.stat()
            mtime = float(stat.st_mtime or 0.0)
            size = int(stat.st_size or 0)
            if ttl_s > 0:
                if (time.time() - mtime) > ttl_s:
                    p.unlink(missing_ok=True)
                    stats["expired"] += 1
                    continue
            survivors.append((p, mtime, size))
        except OSError:
            continue

    if not survivors:
        _bump_proxy_cache_stat("expired", stats["expired"])
        _bump_proxy_cache_stat("evicted_files", stats["evicted_files"])
        _bump_proxy_cache_stat("evicted_bytes", stats["evicted_bytes"])
        return stats

    # 2) Enforce max_files.
    survivors.sort(key=lambda t: (t[1], str(t[0].name)))
    if len(survivors) > max_files:
        for p, _, size in survivors[: max(0, len(survivors) - max_files)]:
            try:
                p.unlink(missing_ok=True)
                stats["evicted_files"] += 1
                stats["evicted_bytes"] += int(size or 0)
            except OSError:
                logger.warning("media_proxy_cache_evict_file_failed", extra={"path": str(p)}, exc_info=True)
        survivors = survivors[-max_files:]

    # 3) Enforce max_bytes.
    total = sum(s for _, _, s in survivors)
    if total <= max_bytes:
        _bump_proxy_cache_stat("expired", stats["expired"])
        _bump_proxy_cache_stat("evicted_files", stats["evicted_files"])
        _bump_proxy_cache_stat("evicted_bytes", stats["evicted_bytes"])
        return stats
    for p, _, s in survivors:
        try:
            p.unlink(missing_ok=True)
            stats["evicted_files"] += 1
            stats["evicted_bytes"] += int(s or 0)
        except OSError:
            logger.warning("media_proxy_cache_evict_bytes_failed", extra={"path": str(p)}, exc_info=True)
        total -= s
        if total <= max_bytes:
            break
    _bump_proxy_cache_stat("expired", stats["expired"])
    _bump_proxy_cache_stat("evicted_files", stats["evicted_files"])
    _bump_proxy_cache_stat("evicted_bytes", stats["evicted_bytes"])
    return stats


@router.get("/media/proxy")
async def proxy_media(
    url: str = Query(..., min_length=1, max_length=2000),
    user: dict = Depends(require_auth),
) -> FileResponse:
    """
    Fetch a remote media URL and cache it on disk for stable rendering.

    - Requires an authenticated user (router-level + explicit dep for clarity).
    - Returns a cached file if available.
    - Downloads and stores into `.local/media/` otherwise.
    """
    if not str((user or {}).get("user_id") or "").strip():
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    try:
        normalized = await _normalize_remote_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    media_id = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    cached = _find_cached_file(media_id)
    if cached:
        try:
            os.utime(cached, None)
        except OSError:
            logger.warning("media_proxy_cache_touch_failed", extra={"path": str(cached)}, exc_info=True)
        _bump_proxy_cache_stat("hits")
        return _file_response(cached)

    _bump_proxy_cache_stat("misses")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    _prune_proxy_cache()

    try:
        max_bytes = int(os.getenv("MEDIA_PROXY_MAX_BYTES") or str(10 * 1024 * 1024))
    except (TypeError, ValueError):
        max_bytes = 10 * 1024 * 1024
    max_bytes = max(256 * 1024, min(max_bytes, 200 * 1024 * 1024))

    client = await _get_proxy_http_client()
    current = normalized
    for _ in range(6):
        try:
            async with client.stream("GET", current) as resp:
                if resp.status_code in {301, 302, 303, 307, 308}:
                    loc = (resp.headers.get("location") or "").strip()
                    if not loc:
                        raise HTTPException(status_code=502, detail="redirect_missing_location")
                    try:
                        next_url = urljoin(current, loc)
                        current = await _normalize_remote_url(next_url)
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))
                    continue

                if resp.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"fetch_failed_status: {resp.status_code}")

                content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if content_type in {"image/svg+xml"}:
                    raise HTTPException(status_code=415, detail="svg_not_allowed")

                url_suffix = Path(urlparse(current).path or "").suffix.lower()
                if content_type:
                    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
                        # Some sites return `application/octet-stream` for images; allow only if URL suffix is safe.
                        if url_suffix not in ALLOWED_IMAGE_EXTENSIONS:
                            raise HTTPException(status_code=415, detail="unsupported_media_type")
                else:
                    if url_suffix not in ALLOWED_IMAGE_EXTENSIONS:
                        raise HTTPException(status_code=415, detail="unsupported_media_type")

                content_len = resp.headers.get("content-length") or ""
                try:
                    if content_len.strip() and int(content_len) > max_bytes:
                        raise HTTPException(status_code=413, detail="media_too_large")
                except ValueError:
                    pass

                ext = _pick_extension(current, content_type)
                if ext == ".bin":
                    raise HTTPException(status_code=415, detail="unsupported_media_type")

                out_path = MEDIA_DIR / f"{media_id}{ext}"
                tmp_path = MEDIA_DIR / f"{media_id}{ext}.tmp"

                total = 0
                try:
                    with tmp_path.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > max_bytes:
                                raise HTTPException(status_code=413, detail="media_too_large")
                            f.write(chunk)
                    tmp_path.replace(out_path)
                except HTTPException:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("media_proxy_tmp_cleanup_failed", extra={"path": str(tmp_path)}, exc_info=True)
                    raise
                except (OSError, RuntimeError, httpx.HTTPError) as exc:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("media_proxy_tmp_cleanup_failed", extra={"path": str(tmp_path)}, exc_info=True)
                    logger.exception(
                        "media_proxy_fetch_failed",
                        extra={"url": current, "media_id": media_id},
                    )
                    raise HTTPException(status_code=502, detail="fetch_failed") from exc

                _prune_proxy_cache()
                return _file_response(out_path)
        except HTTPException:
            raise
        except (RuntimeError, httpx.HTTPError) as exc:
            logger.exception(
                "media_proxy_fetch_failed",
                extra={"url": current, "media_id": media_id},
            )
            raise HTTPException(status_code=502, detail="fetch_failed") from exc

    raise HTTPException(status_code=400, detail="too_many_redirects")
