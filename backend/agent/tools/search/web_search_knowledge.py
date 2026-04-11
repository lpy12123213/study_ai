from __future__ import annotations

"""Public import wrapper for the web-search tool.

We keep the stable import path for call sites/tests, while placing the heavy
implementation in `web_search_knowledge_impl.py` to keep file sizes manageable.
"""

from backend.agent.tools.search.web_search_knowledge_impl import WebSearchKnowledgeToolsMixin

__all__ = ["WebSearchKnowledgeToolsMixin"]

