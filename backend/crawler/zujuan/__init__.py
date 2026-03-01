"""Zujuan crawler package.

This package hosts the zujuan.xkw.com crawler implementation, split by concerns:
- cookies/session bootstrap
- HTTP/API client
- parsing and quality scoring
- blueprint composition helpers

`backend/crawler/zujuan_crawler.py` remains as a compatibility wrapper.
"""

from __future__ import annotations

from backend.crawler.zujuan.client import ZujuanCrawler

__all__ = ["ZujuanCrawler"]

