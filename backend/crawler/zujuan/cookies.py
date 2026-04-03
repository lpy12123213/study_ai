from __future__ import annotations

import asyncio
import json
import os
import re
import time
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
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ANTIBOT_CACHE_FILE = str(_PROJECT_ROOT / ".local" / "cache" / "zujuan_antibot_cookies.json")
_ANTIBOT_CACHE_FILE_LEGACY = str(_PROJECT_ROOT / ".cache" / "zujuan_antibot_cookies.json")
_ANTIBOT_CACHE_TTL_SECONDS = 6 * 60 * 60

# Login cookie cache is optional (best-effort) and stored locally only.
_LOGIN_CACHE_FILE = str(_PROJECT_ROOT / ".local" / "cache" / "zujuan_login_session.json")
_LOGIN_CACHE_TTL_SECONDS = 4 * 60 * 60


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
        logger.warning("playwright cookie bootstrap failed", extra={"error": str(exc)})
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
        return ""


def _save_cookie_cache(path: str, *, cookies: str) -> None:
    try:
        cookie_str = str(cookies or "").strip()
        if not cookie_str:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookie_str, "ts": time.time()}, f, ensure_ascii=False, indent=2)
    except Exception:
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
        logger.warning("fetch csrf token failed", extra={"error": str(exc)})
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
                user_data_dir = os.path.join(os.path.dirname(__file__), ".playwright_data")
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
        logger.warning("login session refresh failed", extra={"error": str(exc)})
        return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False, "source": "error"}


def missing_antibot_keys(cookies: str) -> set[str]:
    return _ANTIBOT_COOKIE_KEYS - set(parse_cookie_string(cookies or "").keys())
