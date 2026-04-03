from __future__ import annotations

from typing import Any, Dict, List, Protocol


class CrawlerInterface(Protocol):
    """
    A minimal interface contract for crawler implementations.

    Consumers must program against this interface rather than a concrete crawler class
    so switching crawler sources only requires implementing this protocol.
    """

    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    async def search_by_keyword(self, keyword: str, **kwargs: Any) -> Dict[str, Any]: ...

    async def batch_get_question_details(self, question_ids: List[str], **kwargs: Any) -> Dict[str, Any]: ...

    async def get_question_detail(self, question_id: str, **kwargs: Any) -> Dict[str, Any]: ...

    async def get_available_filters(self, **kwargs: Any) -> Dict[str, Any]: ...

    async def get_knowledge_tree(self, **kwargs: Any) -> Dict[str, Any]: ...

    async def compose_paper_blueprint(self, **kwargs: Any) -> Dict[str, Any]: ...

    async def export_to_basket(self, **kwargs: Any) -> Dict[str, Any]: ...
