from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from backend.core.logging_utils import get_logger
from backend.core.settings import load_project_dotenv

logger = get_logger(__name__)

load_project_dotenv(override=False)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CSRF_TOKEN_PATTERN = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', re.IGNORECASE)

_ANTIBOT_COOKIE_KEYS = {"aliyungf_tc", "acw_tc", "acw_sc__v2"}
_ALICFW_COOKIE_KEYS = {"alicfw", "alicfw_gfver"}
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ANTIBOT_CACHE_FILE = str(_PROJECT_ROOT / ".local" / "cache" / "zujuan_antibot_cookies.json")
_ANTIBOT_CACHE_FILE_LEGACY = str(_PROJECT_ROOT / ".cache" / "zujuan_antibot_cookies.json")
_ANTIBOT_CACHE_TTL_SECONDS = 6 * 60 * 60

# Login cookie cache is optional (best-effort) and stored locally only.
_LOGIN_CACHE_FILE = str(_PROJECT_ROOT / ".local" / "cache" / "zujuan_login_session.json")
_LOGIN_CACHE_TTL_SECONDS = 4 * 60 * 60


@dataclass(frozen=True)
class CookieFileHeader:
    header: str
    cookie_names: list[str]
    expired_cookie_names: list[str]

    @property
    def cookie_count(self) -> int:
        return len(self.cookie_names)

    @property
    def all_cookie_rows_expired(self) -> bool:
        return bool(self.cookie_names) and len(self.expired_cookie_names) >= len(self.cookie_names)


class ZujuanCookieFileError(RuntimeError):
    def __init__(
        self,
        *,
        error: str,
        message: str,
        path: str | Path,
        instructions: list[str],
        cookie_count: int = 0,
        expired_cookie_names: Optional[list[str]] = None,
    ) -> None:
        super().__init__(message)
        self.error = str(error or "").strip() or "zujuan_cookie_file_error"
        self.payload = {
            "success": False,
            "error": self.error,
            "message": message,
            "instructions": instructions,
            "cookie_file": {
                "variable": "ZUJUAN_COOKIE_FILE",
                "path": str(path),
                "cookie_count": int(cookie_count or 0),
                "expired_cookie_count": len(expired_cookie_names or []),
            },
        }


def resolve_cookie_file_path(path: str | Path) -> Path:
    source = Path(str(path or "").strip()).expanduser()
    if not source.is_absolute():
        source = _REPO_ROOT / source
    return source.resolve(strict=False)


def build_cookie_header_from_netscape_file(
    path: str | Path,
    *,
    include_expired: bool = True,
    now: datetime | None = None,
) -> CookieFileHeader:
    """Build a raw Cookie header from a Netscape/curl visitor-cookie file."""

    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"cookie file not found: {source}")

    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    pairs: list[str] = []
    names: list[str] = []
    expired_names: list[str] = []

    for raw_line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#"):
            continue

        fields = line.split("\t", 6)
        if len(fields) != 7:
            continue

        _domain, _include_subdomains, _path, _secure, expires, name, value = fields
        if not name:
            continue

        is_expired = False
        try:
            expires_ts = int(expires)
            is_expired = expires_ts > 0 and expires_ts < now_ts
        except ValueError:
            pass

        if is_expired:
            expired_names.append(name)
            if not include_expired:
                continue

        names.append(name)
        pairs.append(f"{name}={value}")

    return CookieFileHeader(
        header="; ".join(pairs),
        cookie_names=names,
        expired_cookie_names=expired_names,
    )


def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies


def build_cookie_string(cookies: Dict[str, str]) -> str:
    return "; ".join([f"{k}={v}" for k, v in cookies.items() if k and v])


def get_playwright_login_user_data_dir(*, explicit_dir: str = "") -> Path:
    explicit = str(explicit_dir or os.getenv("ZUJUAN_USER_DATA_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()

    default_dir = _PROJECT_ROOT / ".local" / "playwright" / "zujuan_user_data"
    legacy_dirs = (
        _PROJECT_ROOT / ".local" / "playwright" / "zujuan",
        _PROJECT_ROOT / ".playwright_zujuan_user_data",
    )

    if default_dir.exists():
        return default_dir

    for legacy_dir in legacy_dirs:
        if legacy_dir.exists():
            return legacy_dir

    return default_dir


async def get_cookies_with_playwright() -> str:
    """Use Playwright to fetch a basic (anti-bot) cookie jar without logging in."""

    try:
        import concurrent.futures

        from playwright.sync_api import sync_playwright

        def _sync_get_cookies() -> str:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                page.goto("https://zujuan.xkw.com/", timeout=20000)
                page.wait_for_timeout(1000)  # keep it short; only need cookie bootstrap

                cookies = context.cookies()
                browser.close()
                return "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, _sync_get_cookies)
    except Exception as exc:
        logger.warning("playwright cookie bootstrap failed", extra={"error": str(exc)}, exc_info=True)
        return ""


def load_env_login() -> Dict[str, Any]:
    """Load login cookies from env vars.

    `.env` is loaded centrally by `backend.core.settings.load_project_dotenv`.
    """

    user_id = (os.getenv("ZUJUAN_USER_ID") or "").strip() or None
    csrf_token = (os.getenv("ZUJUAN_CSRF_TOKEN") or "").strip() or None
    cookies = (os.getenv("ZUJUAN_COOKIES") or "").strip()

    if user_id or csrf_token or cookies:
        return {
            "cookies": cookies,
            "user_id": user_id,
            "csrf_token": csrf_token,
            "is_logged_in": bool(user_id or cookies),
            "source": "env",
        }

    return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False, "source": "none"}


def _load_cookie_cache(path: str, *, ttl_s: int) -> str:
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookie_str = str(data.get("cookies") or "").strip()
        ts = float(data.get("ts") or 0.0)
        if not cookie_str:
            return ""
        if ts and ttl_s and (time.time() - ts) > float(ttl_s):
            return ""
        return cookie_str
    except Exception:
        logger.warning("zujuan_cookie_cache_load_failed", extra={"path": path}, exc_info=True)
        return ""


def _save_cookie_cache(path: str, *, cookies: str) -> None:
    try:
        cookie_str = str(cookies or "").strip()
        if not cookie_str:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookie_str, "ts": time.time()}, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        logger.warning("zujuan_cookie_cache_save_failed", extra={"path": path}, exc_info=True)
        return


def load_antibot_cookie_cache() -> str:
    for candidate in (_ANTIBOT_CACHE_FILE, _ANTIBOT_CACHE_FILE_LEGACY):
        cached = _load_cookie_cache(candidate, ttl_s=_ANTIBOT_CACHE_TTL_SECONDS)
        if cached:
            return cached
    return ""


def save_antibot_cookie_cache(cookie_str: str) -> None:
    _save_cookie_cache(_ANTIBOT_CACHE_FILE, cookies=cookie_str)


async def fetch_csrf_token_from_page(cookies: str) -> Optional[str]:
    if not cookies:
        return None

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Cookie": cookies,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://zujuan.xkw.com/",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get("https://zujuan.xkw.com/", headers=headers)
            if resp.status_code != 200:
                return None
            m = CSRF_TOKEN_PATTERN.search(resp.text)
            if m:
                return m.group(1)
    except Exception as exc:
        logger.warning("fetch csrf token failed", extra={"error": str(exc)}, exc_info=True)
    return None


def _load_login_cookie_cache() -> str:
    return _load_cookie_cache(_LOGIN_CACHE_FILE, ttl_s=_LOGIN_CACHE_TTL_SECONDS)


def _save_login_cookie_cache(cookie_str: str) -> None:
    _save_cookie_cache(_LOGIN_CACHE_FILE, cookies=cookie_str)


async def get_login_session_with_playwright(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Best-effort login cookie refresh using a persistent Playwright profile.

    - If `.env` provides login cookies, we use them unless `force_refresh=True`.
    - Otherwise, we try to reuse an existing `user_data_dir` profile (user may have logged in once manually).
    """

    env_session = load_env_login()
    env_cookies = str(env_session.get("cookies") or "").strip()
    if env_cookies and env_session.get("is_logged_in") and not force_refresh:
        csrf_token = await fetch_csrf_token_from_page(env_cookies)
        if csrf_token:
            env_session["csrf_token"] = csrf_token
        return env_session

    cached_login = _load_login_cookie_cache()
    if cached_login and not force_refresh:
        csrf_token = await fetch_csrf_token_from_page(cached_login)
        return {
            "cookies": cached_login,
            "user_id": None,
            "csrf_token": csrf_token,
            "is_logged_in": True,
            "source": "cache",
        }

    try:
        import concurrent.futures

        from playwright.sync_api import sync_playwright

        def _sync_get_session() -> Dict[str, Any]:
            with sync_playwright() as p:
                user_data_dir = str(get_playwright_login_user_data_dir().resolve())
                os.makedirs(user_data_dir, exist_ok=True)

                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                )
                page = browser.pages[0] if browser.pages else browser.new_page()

                page.goto("https://zujuan.xkw.com/gzsx/", timeout=30000)
                page.wait_for_timeout(2000)

                cookies = browser.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                user_id = None
                for c in cookies:
                    if c.get("name") == "userId":
                        user_id = c.get("value")
                        break

                csrf_token = None
                try:
                    csrf_token = page.evaluate(
                        """
                        () => {
                          const input = document.querySelector('input[name="__RequestVerificationToken"]');
                          return input ? input.value : null;
                        }
                        """
                    )
                except Exception:
                    logger.warning("zujuan_csrf_token_eval_failed", exc_info=True)
                    csrf_token = None

                if not csrf_token:
                    for c in cookies:
                        if c.get("name") == "__RequestVerificationToken":
                            csrf_token = c.get("value")
                            break

                browser.close()
                return {
                    "cookies": cookie_str,
                    "user_id": user_id,
                    "csrf_token": csrf_token,
                    "is_logged_in": user_id is not None,
                    "source": "playwright",
                }

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            session = await loop.run_in_executor(pool, _sync_get_session)

        cookies = str(session.get("cookies") or "").strip()
        if cookies and session.get("is_logged_in"):
            _save_login_cookie_cache(cookies)
        return session
    except Exception as exc:
        logger.warning("login session refresh failed", extra={"error": str(exc)}, exc_info=True)
        return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False, "source": "error"}


def missing_antibot_keys(cookies: str) -> set[str]:
    keys = set(parse_cookie_string(cookies or "").keys())
    missing = {"aliyungf_tc", "acw_tc"} - keys
    if "acw_sc__v2" not in keys and not _ALICFW_COOKIE_KEYS.issubset(keys):
        missing.add("acw_sc__v2")
    return missing
