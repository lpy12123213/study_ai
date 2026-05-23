"""Authentication utilities for crawlers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

from backend.core.settings import load_project_dotenv

load_project_dotenv(override=False)


@dataclass
class CrawlerCredentials:
    """Credentials for a crawler."""

    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    cookies: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = None


def get_zujuan_credentials() -> CrawlerCredentials:
    """Get credentials for Zujuan crawler."""
    return CrawlerCredentials(
        username=os.getenv("ZUJUAN_USERNAME"),
        password=os.getenv("ZUJUAN_PASSWORD"),
        cookies=_parse_cookies(os.getenv("ZUJUAN_COOKIES")),
    )


def _parse_cookies(cookie_string: Optional[str]) -> Optional[Dict[str, str]]:
    """Parse a cookie string into a dictionary."""
    if not cookie_string:
        return None

    cookies = {}
    for item in cookie_string.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def get_default_headers() -> Dict[str, str]:
    """Get default HTTP headers for crawlers."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
