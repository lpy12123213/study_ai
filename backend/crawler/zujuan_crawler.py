"""Compatibility wrapper for the Zujuan crawler.

The implementation was historically a single huge file (`backend/crawler/zujuan_crawler.py`).
To make maintenance and testing easier, it has been split into the `backend/crawler/zujuan/` package.
"""

from __future__ import annotations

from backend.crawler.zujuan import ZujuanCrawler

__all__ = ["ZujuanCrawler"]

