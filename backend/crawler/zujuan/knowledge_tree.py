from __future__ import annotations

import re
from typing import Any, Dict, List

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


async def get_knowledge_tree(self) -> Dict[str, Any]:
    """
    从组卷网抓取当前学科的知识点树（zsd 侧栏导航）。

    返回格式::

        {
            "success": True,
            "subject": "高中数学",
            "nodes": [
                {
                    "id": "zsd-27925",
                    "label": "高中数学知识点",
                    "type": "root",
                    "children": [
                        {
                            "id": "zsd-131011",
                            "label": "函数与导数",
                            "type": "chapter",
                            "children": [
                                {"id": "zsd-131012", "label": "函数概念", "type": "knowledge_point", "selectable": True, "children": []},
                                ...
                            ]
                        },
                        ...
                    ]
                }
            ]
        }
    """
    cache_key = f"knowledge_tree:{getattr(self, 'subject', '')}:{getattr(self, 'bank_id', 0)}"
    cached = self._cache_get(cache_key)
    if isinstance(cached, dict) and cached.get("success"):
        return cached

    if not self.client:
        return {"success": False, "error": "client_not_initialized", "nodes": []}

    await self._ensure_bank_meta_loaded()
    course_id_py = str(getattr(self, "course_id_py", "") or "").strip()
    category_id = str(getattr(self, "category_id", "") or "").strip()
    subject = str(getattr(self, "subject", "") or "").strip()

    if not course_id_py:
        return {"success": False, "error": "missing_course_id_py", "nodes": []}

    # Fetch the sidebar HTML from the knowledge point listing page.
    url = f"{self.base_url}/{course_id_py}/zsd0/"
    try:
        resp = await self.client.get(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Referer": f"{self.base_url}/{course_id_py}/",
            },
            follow_redirects=True,
            timeout=20.0,
        )
        html_text = resp.text or ""
    except Exception as exc:
        logger.warning("zujuan_knowledge_tree_fetch_failed", extra={"url": url, "error": str(exc)})
        return {"success": False, "error": str(exc), "nodes": []}

    if not html_text or len(html_text) < 200:
        return {"success": False, "error": "empty_response", "nodes": []}

    # Parse the sidebar tree.
    nodes = parse_knowledge_sidebar(self, html_text, course_id_py, category_id, subject)
    if not nodes:
        return {"success": False, "error": "parse_failed_or_empty", "nodes": []}

    result = {"success": True, "subject": subject, "nodes": nodes}
    self._cache_set(cache_key, result, ttl=60 * 60)  # 1 hour cache
    return result


def parse_knowledge_sidebar(self, html_text: str, course_id_py: str, category_id: str, subject: str) -> List[Dict[str, Any]]:
    """Parse the sidebar navigation tree from zujuan HTML into structured nodes."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return []

    soup = BeautifulSoup(html_text, "lxml")

    # 组卷网 sidebar uses <div class="catalog-list"> or <div class="tk-tree">
    # with nested <dl>/<dt>/<dd> or <ul>/<li> structures.
    # Strategy: find the sidebar container and extract the tree.

    RE_ZSD_ID = re.compile(r"/zsd(\d+)(?:/|$)", re.IGNORECASE)

    def _extract_zsd_id(href: str) -> str:
        m = RE_ZSD_ID.search(href or "")
        return f"zsd-{m.group(1)}" if m else ""

    # Try common sidebar selectors used by 组卷网.
    sidebar = (
        soup.select_one("div.catalog-list")
        or soup.select_one("div.tk-tree")
        or soup.select_one("div.tree-list")
        or soup.select_one("div.left-tree")
        or soup.select_one("aside")
        or soup.select_one("div.catalog")
    )

    if sidebar:
        nodes = parse_sidebar_container(self, sidebar, RE_ZSD_ID)
        if nodes:
            return [
                {
                    "id": f"zsd-{category_id}" if category_id else f"{subject}-root",
                    "label": f"{subject}知识点",
                    "type": "root",
                    "children": nodes,
                }
            ]

    # Fallback: scan all <a> tags with zsd links and group by hierarchy.
    all_links: List[Dict[str, Any]] = []
    for a in soup.select("a[href]"):
        href = str(a.get("href") or "")
        zsd_id = _extract_zsd_id(href)
        if not zsd_id:
            continue
        label = a.get_text(strip=True)
        if not label or len(label) > 60:
            continue
        all_links.append({"id": zsd_id, "label": label, "href": href})

    if not all_links:
        return []

    # Deduplicate by id, keep first occurrence.
    seen: set = set()
    unique_links: List[Dict[str, Any]] = []
    for link in all_links:
        if link["id"] not in seen:
            seen.add(link["id"])
            unique_links.append(link)

    # Build a flat list as knowledge_point nodes (no hierarchy available from flat links).
    children = [
        {
            "id": link["id"],
            "label": link["label"],
            "type": "knowledge_point",
            "selectable": True,
            "children": [],
        }
        for link in unique_links
    ]

    return [
        {
            "id": f"zsd-{category_id}" if category_id else f"{subject}-root",
            "label": f"{subject}知识点",
            "type": "root",
            "children": children,
        }
    ]


def parse_sidebar_container(self, container: Any, RE_ZSD_ID) -> List[Dict[str, Any]]:
    """Parse a sidebar container element into tree nodes."""

    def _extract_zsd_id(href: str) -> str:
        m = RE_ZSD_ID.search(href or "")
        return f"zsd-{m.group(1)}" if m else ""

    nodes: List[Dict[str, Any]] = []

    # Pattern 1: <dl><dt>chapter</dt><dd>children</dd></dl>
    for dl in container.select("dl"):
        dt = dl.select_one("dt")
        if not dt:
            continue
        chapter_link = dt.select_one("a[href]")
        chapter_label = dt.get_text(strip=True)
        chapter_id = _extract_zsd_id(str(chapter_link.get("href", "")) if chapter_link else "")
        if not chapter_label:
            continue
        children = []
        for dd in dl.select("dd"):
            for a in dd.select("a[href]"):
                href = str(a.get("href") or "")
                zsd_id = _extract_zsd_id(href)
                label = a.get_text(strip=True)
                if zsd_id and label:
                    children.append(
                        {
                            "id": zsd_id,
                            "label": label,
                            "type": "knowledge_point",
                            "selectable": True,
                            "children": [],
                        }
                    )
        nodes.append(
            {
                "id": chapter_id or f"chapter-{len(nodes)}",
                "label": chapter_label,
                "type": "chapter",
                "children": children,
            }
        )

    if nodes:
        return nodes

    # Pattern 2: nested <ul>/<li> tree
    for ul in container.select("ul"):
        for li in ul.find_all("li", recursive=False):
            a = li.select_one("a[href]")
            if not a:
                continue
            href = str(a.get("href") or "")
            zsd_id = _extract_zsd_id(href)
            label = a.get_text(strip=True)
            if not label:
                continue
            sub_ul = li.select_one("ul")
            children = []
            if sub_ul:
                for sub_li in sub_ul.find_all("li", recursive=False):
                    sub_a = sub_li.select_one("a[href]")
                    if not sub_a:
                        continue
                    sub_href = str(sub_a.get("href") or "")
                    sub_id = _extract_zsd_id(sub_href)
                    sub_label = sub_a.get_text(strip=True)
                    if sub_id and sub_label:
                        # Check for third level
                        sub_sub_ul = sub_li.select_one("ul")
                        grandchildren = []
                        if sub_sub_ul:
                            for gc_li in sub_sub_ul.find_all("li", recursive=False):
                                gc_a = gc_li.select_one("a[href]")
                                if not gc_a:
                                    continue
                                gc_href = str(gc_a.get("href") or "")
                                gc_id = _extract_zsd_id(gc_href)
                                gc_label = gc_a.get_text(strip=True)
                                if gc_id and gc_label:
                                    grandchildren.append(
                                        {
                                            "id": gc_id,
                                            "label": gc_label,
                                            "type": "knowledge_point",
                                            "selectable": True,
                                            "children": [],
                                        }
                                    )
                        children.append(
                            {
                                "id": sub_id,
                                "label": sub_label,
                                "type": "knowledge_point" if not grandchildren else "chapter",
                                "selectable": not grandchildren,
                                "children": grandchildren,
                            }
                        )
            node_type = "chapter" if children else "knowledge_point"
            nodes.append(
                {
                    "id": zsd_id or f"node-{len(nodes)}",
                    "label": label,
                    "type": node_type,
                    "selectable": not children,
                    "children": children,
                }
            )
        break  # Only process the first top-level <ul>

    return nodes

