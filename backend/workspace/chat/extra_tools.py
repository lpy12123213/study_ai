from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.generation.question_library.diagram_utils import render_matplotlib_2d_to_url
from backend.integrations.mcp.search.service import run_web_search
from backend.integrations.mcp.tools.python_scientific_compute import python_scientific_compute


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _number_pair(value: Any, default: List[float]) -> List[float]:
    if not isinstance(value, list) or len(value) != 2:
        return list(default)
    try:
        left = float(value[0])
        right = float(value[1])
    except (TypeError, ValueError):
        return list(default)
    if left == right:
        return list(default)
    return [left, right]


def _search_markdown(result: Dict[str, Any]) -> str:
    if not result.get("success"):
        return f"Web search unavailable: {result.get('error') or 'unknown error'}"

    query = str(result.get("query") or "").strip()
    provider = str(result.get("provider") or "").strip()
    heading = f"### Web search results{f' for {query}' if query else ''}"
    if provider:
        heading += f" ({provider})"

    lines = [heading]
    answer = str(result.get("answer") or result.get("summary") or "").strip()
    if answer:
        lines.extend(["", answer])

    results = result.get("results") if isinstance(result.get("results"), list) else []
    if not results:
        lines.extend(["", "No matching web results were returned."])
        return "\n".join(lines)

    lines.append("")
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("url") or f"Result {index}").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        published = str(item.get("published_date") or "").strip()
        link = f"[{title}]({url})" if url else title
        suffix = f" - {published}" if published else ""
        lines.append(f"{index}. {link}{suffix}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines).strip()


async def handle_python_scientific_compute(
    arguments: Dict[str, Any],
    *,
    sub_model: Optional[str] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    _ = sub_model, user_id
    code = str(arguments.get("code") or "").strip()
    if not code:
        return {"success": False, "error": "code is required"}
    purpose = str(arguments.get("purpose") or "").strip()
    timeout_seconds = _as_int(arguments.get("timeout_seconds"), 5, minimum=1, maximum=15)
    result = await python_scientific_compute(code=code, purpose=purpose, timeout_seconds=timeout_seconds)
    return dict(result) if isinstance(result, dict) else {"success": False, "error": "invalid compute result"}


async def handle_plot_function(
    arguments: Dict[str, Any],
    *,
    sub_model: Optional[str] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    _ = sub_model
    expr = str(arguments.get("expr") or "").strip()
    if not expr:
        return {"success": False, "error": "expr is required"}

    title = str(arguments.get("title") or "").strip()
    label = str(arguments.get("label") or "").strip()
    alt = str(arguments.get("alt") or "plot").strip() or "plot"
    spec: Dict[str, Any] = {
        "x_range": _number_pair(arguments.get("x_range"), [-5.0, 5.0]),
        "title": title,
        "curves": [{"expr": expr, **({"label": label} if label else {})}],
    }
    if isinstance(arguments.get("y_range"), list):
        y_range = _number_pair(arguments.get("y_range"), [])
        if y_range:
            spec["y_range"] = y_range

    published = await render_matplotlib_2d_to_url(spec=spec, user_id=str(user_id or "").strip(), alt=alt)
    if not isinstance(published, dict):
        return {"success": False, "error": "plot_failed"}
    if not published.get("success"):
        return {
            "success": False,
            "error": str(published.get("error") or "plot_failed"),
            "warnings": published.get("warnings") or [],
        }

    url = str(published.get("url") or "").strip()
    markdown = str(published.get("markdown") or "").strip()
    if not markdown and url:
        markdown = f"![{alt}]({url})"
    return {
        "success": True,
        "url": url,
        "markdown": markdown,
        "filename": str(published.get("filename") or ""),
        "cached": bool(published.get("cached")),
        "bytes": int(published.get("bytes") or 0),
    }


async def handle_web_search(
    arguments: Dict[str, Any],
    *,
    sub_model: Optional[str] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    _ = sub_model, user_id
    result = await run_web_search(
        query=str(arguments.get("query") or "").strip(),
        limit=_as_int(arguments.get("limit"), 5, minimum=1, maximum=10),
        provider=str(arguments.get("provider") or "auto").strip() or "auto",
        mode=str(arguments.get("mode") or "trending").strip() or "trending",
        recency_days=_as_int(arguments.get("recency_days"), 180, minimum=1, maximum=3650),
        model=str(arguments.get("model") or "").strip(),
    )
    out = dict(result) if isinstance(result, dict) else {"success": False, "error": "invalid search result", "results": []}
    out["markdown"] = _search_markdown(out)
    return out
