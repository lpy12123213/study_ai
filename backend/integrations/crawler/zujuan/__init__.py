"""Zujuan crawler package.

This package hosts the zujuan.xkw.com crawler implementation, split by concerns:
- cookies/session bootstrap
- HTTP/API client
- parsing and quality scoring
- blueprint composition helpers

The historical monolith `backend/crawler/zujuan_crawler.py` was removed in the
2026-06 migration; `backend/integrations/crawler/zujuan_crawler.py` is the
remaining thin compatibility entry.
"""

from __future__ import annotations

from backend.integrations.crawler.zujuan.client import ZujuanCrawler

__all__ = ["ZujuanCrawler"]
