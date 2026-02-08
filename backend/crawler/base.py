"""Base classes and utilities for crawlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import httpx


@dataclass
class CrawlerConfig:
    """Configuration for a crawler."""
    base_url: str
    timeout: float = 30.0
    max_retries: int = 3
    headers: Optional[Dict[str, str]] = None
    cookies: Optional[Dict[str, str]] = None


@dataclass
class SearchResult:
    """A single search result."""
    id: str
    title: str
    content: str
    url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class QuestionData:
    """Parsed question data."""
    id: str
    stem: str
    answer: Optional[str] = None
    analysis: Optional[str] = None
    question_type: Optional[str] = None
    difficulty: Optional[float] = None
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseCrawler(ABC):
    """Base class for all crawlers."""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self) -> None:
        """Start the crawler and initialize HTTP client."""
        self._client = httpx.AsyncClient(
            timeout=self.config.timeout,
            headers=self.config.headers,
            cookies=self.config.cookies,
        )

    async def close(self) -> None:
        """Close the crawler and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client."""
        if not self._client:
            raise RuntimeError("Crawler not started. Call start() first.")
        return self._client

    @abstractmethod
    async def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 20,
        **kwargs,
    ) -> List[SearchResult]:
        """Search for questions."""
        pass

    @abstractmethod
    async def get_detail(self, question_id: str) -> Optional[QuestionData]:
        """Get detailed question data."""
        pass

    async def get_multiple_details(
        self,
        question_ids: List[str],
    ) -> List[QuestionData]:
        """Get details for multiple questions."""
        results = []
        for qid in question_ids:
            detail = await self.get_detail(qid)
            if detail:
                results.append(detail)
        return results
