"""
知乎内容抓取与 Markdown 转换（用于 MCP 工具）。

参考实现：
- https://github.com/chenluda/zhihu-download

本项目适配点：
- 使用 httpx.AsyncClient（异步）
- 不落盘：直接返回 Markdown 文本与结构化元信息
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


class ZhihuFetchError(RuntimeError):
    """Base class for Zhihu fetch errors."""


class ZhihuCookiesRequired(ZhihuFetchError):
    """Raised when Zhihu requires cookies to access the page."""


class ZhihuNotFound(ZhihuFetchError):
    """Raised when the page does not exist."""


def _extract_date_yyyymmdd(text: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", text or "")
    if not match:
        return ""
    return match.group().replace("-", "")


def _ts_to_yyyymmdd(ts: Any) -> str:
    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts_int <= 0:
        return ""
    # Zhihu 常见字段是秒级时间戳
    try:
        dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        return dt.strftime("%Y%m%d")
    except (OSError, OverflowError, ValueError):
        return ""


def _normalize_zhihu_link(href: str) -> str:
    raw = (href or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        if parsed.netloc.lower() == "link.zhihu.com":
            qs = parse_qs(parsed.query)
            target = qs.get("target", [""])[0]
            return unquote(target) if target else raw
        return raw
    except ValueError:
        return raw


def _pick_first(soup: BeautifulSoup, selectors: List[str]):
    for sel in selectors:
        el = soup.select_one(sel)
        if el is not None:
            return el
    return None


def _extract_author(soup: BeautifulSoup) -> str:
    # 文章/回答常见结构：div.AuthorInfo meta[itemprop=name]
    try:
        author_info = soup.select_one("div.AuthorInfo")
        if author_info is not None:
            meta = author_info.find("meta", attrs={"itemprop": "name"})
            if meta and meta.get("content"):
                return str(meta.get("content")).strip()
    except (AttributeError, TypeError):
        logger.warning("zhihu_author_parse_failed", exc_info=True)

    # 兜底：找可能的作者名节点
    candidates = [
        "a.AuthorInfo-name",
        "span.AuthorInfo-name",
        "meta[name='author']",
    ]
    for sel in candidates:
        el = soup.select_one(sel)
        if el is None:
            continue
        if el.name == "meta" and el.get("content"):
            return str(el.get("content")).strip()
        txt = el.get_text(strip=True)
        if txt:
            return txt
    return ""


def _detect_common_errors(soup: BeautifulSoup) -> None:
    text = soup.get_text(" ", strip=True)
    if not text:
        return

    # zhihu-download 的经验判断
    if "有问题，就会有答案打开知乎App在「我的页」右上角打开扫一扫其他扫码方式" in text:
        raise ZhihuCookiesRequired("cookies_required")
    if "你似乎来到了没有知识存在的荒原" in text:
        raise ZhihuNotFound("page_not_found")


def _extract_title(soup: BeautifulSoup, *, fallback_prefix: str = "") -> str:
    title_el = soup.select_one("h1.Post-Title") or soup.select_one("h1.QuestionHeader-title") or soup.select_one("h1")
    if title_el is not None:
        title = title_el.get_text(strip=True)
        if title:
            return title

    if soup.title and soup.title.string:
        raw = soup.title.string.strip()
        if raw:
            # 常见：`xxx - 知乎`
            raw = re.sub(r"\s*-\s*知乎\s*$", "", raw)
            return raw

    return fallback_prefix or "Untitled"


def _prepare_content_for_markdown(content_el) -> Tuple[str, List[str], List[str]]:
    """
    返回： (html_str, inline_formulas, block_formulas)
    """
    # 去掉 style
    for style_tag in list(content_el.find_all("style")):
        style_tag.decompose()

    # 处理图片：优先使用 data-actualsrc / data-original / data-src
    for img in list(content_el.find_all("img")):
        attrs = img.attrs or {}
        src = (attrs.get("src") or "").strip()
        if src.startswith("data:image/") or not src:
            for k in ("data-actualsrc", "data-original", "data-src", "data-default-watermark-src", "data-original-src"):
                v = (attrs.get(k) or "").strip()
                if v:
                    src = v
                    break
        if src:
            img["src"] = src

    # 处理链接：把 link.zhihu.com 还原为真实 URL，让 markdownify 自己转成 Markdown 链接
    for a in list(content_el.find_all("a")):
        href = a.get("href")
        if not href:
            continue
        normalized = _normalize_zhihu_link(href)
        if normalized:
            a["href"] = normalized
        # 如果没有可见文本，补一个
        if not a.get_text(strip=True):
            a.string = normalized or href

    # 数学公式：用占位符保留位置，markdownify 后再替换
    inline_formulas: List[str] = []
    block_formulas: List[str] = []
    for span in list(content_el.select("span.ztext-math")):
        latex = (span.get("data-tex") or "").strip()
        if not latex:
            continue
        if "\\tag" in latex:
            block_formulas.append(latex)
            span.replace_with("\n\n@@MATH_BLOCK@@\n\n")
        else:
            inline_formulas.append(latex)
            span.replace_with("@@MATH_INLINE@@")

    html_str = content_el.decode_contents().strip()
    return html_str, inline_formulas, block_formulas


def _replace_math_placeholders(markdown_text: str, inline_formulas: List[str], block_formulas: List[str]) -> str:
    text = markdown_text or ""

    for formula in inline_formulas:
        if "$" in formula:
            repl = formula
        else:
            repl = f"${formula}$"
        text = text.replace("@@MATH_INLINE@@", repl, 1)

    for formula in block_formulas:
        if "$" in formula:
            repl = formula
        else:
            repl = f"$${formula}$$"
        text = text.replace("@@MATH_BLOCK@@", repl, 1)

    return text


@dataclass(frozen=True)
class ZhihuFetchResult:
    success: bool
    type: str
    url: str
    title: str = ""
    author: str = ""
    date: str = ""
    content_markdown: str = ""
    items: Optional[List[Dict[str, Any]]] = None
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "success": self.success,
            "type": self.type,
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "date": self.date,
            "content_markdown": self.content_markdown,
        }
        if self.items is not None:
            data["items"] = self.items
        if self.error:
            data["error"] = self.error
        return data


class ZhihuFetcher:
    def __init__(
        self,
        *,
        cookies: str = "",
        timeout_seconds: int = 30,
        user_agent: str = _UA,
    ) -> None:
        self._cookies = (cookies or "").strip()
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent

    def _build_headers(self, cookies: str) -> Dict[str, str]:
        headers = {
            "User-Agent": self._user_agent,
            "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
        }
        ck = (cookies or "").strip()
        if ck:
            headers["Cookie"] = ck
        return headers

    async def fetch(self, url: str, *, cookies: str = "") -> ZhihuFetchResult:
        target_url = (url or "").strip()
        if not target_url:
            return ZhihuFetchResult(success=False, type="unknown", url=url or "", error="missing_url")

        parsed = urlparse(target_url)
        path = parsed.path or ""

        try:
            if "column" in path or "/column/" in path:
                return await self._list_column(target_url, cookies=cookies)
            if "answer" in path:
                return await self._fetch_answer(target_url, cookies=cookies)
            if "zhuanlan.zhihu.com" in (parsed.netloc or "") or "/p/" in path:
                return await self._fetch_article(target_url, cookies=cookies)
            # 兜底：按文章尝试
            return await self._fetch_article(target_url, cookies=cookies)
        except ZhihuCookiesRequired:
            return ZhihuFetchResult(success=False, type="unknown", url=target_url, error="cookies_required")
        except ZhihuNotFound:
            return ZhihuFetchResult(success=False, type="unknown", url=target_url, error="page_not_found")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            return ZhihuFetchResult(
                success=False,
                type="unknown",
                url=target_url,
                error=f"http_status_{status}",
            )
        except httpx.RequestError:
            return ZhihuFetchResult(success=False, type="unknown", url=target_url, error="network_error")
        except Exception:
            logger.warning("zhihu_fetch_unknown_failed", extra={"url": target_url}, exc_info=True)
            return ZhihuFetchResult(success=False, type="unknown", url=target_url, error="unknown_error")

    async def _get_html(self, url: str, *, cookies: str = "") -> str:
        ck = (cookies or "").strip() or self._cookies
        headers = self._build_headers(ck)
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text

    async def _fetch_article(self, url: str, *, cookies: str = "") -> ZhihuFetchResult:
        html = await self._get_html(url, cookies=cookies)
        soup = BeautifulSoup(html, "lxml")
        _detect_common_errors(soup)

        title = _extract_title(soup)
        author = _extract_author(soup)
        # 日期：优先 ContentItem-time
        date = ""
        time_el = _pick_first(soup, ["div.ContentItem-time", "span.ContentItem-time", "div.Post-NormalSub"])
        if time_el is not None:
            date = _extract_date_yyyymmdd(time_el.get_text(" ", strip=True))

        content_el = _pick_first(
            soup,
            [
                "div.Post-RichTextContainer",
                "div.Post-RichText",
                "div.RichText",
                "article",
            ],
        )
        if content_el is None:
            return ZhihuFetchResult(
                success=True,
                type="article",
                url=url,
                title=title,
                author=author,
                date=date,
                content_markdown="",
            )

        html_str, inline_formulas, block_formulas = _prepare_content_for_markdown(content_el)
        content_md = md(html_str)
        content_md = _replace_math_placeholders(content_md, inline_formulas, block_formulas).strip()

        return ZhihuFetchResult(
            success=True,
            type="article",
            url=url,
            title=title,
            author=author,
            date=date,
            content_markdown=content_md,
        )

    async def _fetch_answer(self, url: str, *, cookies: str = "") -> ZhihuFetchResult:
        html = await self._get_html(url, cookies=cookies)
        soup = BeautifulSoup(html, "lxml")
        _detect_common_errors(soup)

        title = _extract_title(soup)
        author = _extract_author(soup)
        date = ""
        time_el = _pick_first(soup, ["div.ContentItem-time", "span.ContentItem-time"])
        if time_el is not None:
            date = _extract_date_yyyymmdd(time_el.get_text(" ", strip=True))

        content_el = _pick_first(
            soup,
            [
                "div.RichContent-inner",
                "div.RichText",
                "article",
            ],
        )
        if content_el is None:
            return ZhihuFetchResult(
                success=True,
                type="answer",
                url=url,
                title=title,
                author=author,
                date=date,
                content_markdown="",
            )

        html_str, inline_formulas, block_formulas = _prepare_content_for_markdown(content_el)
        content_md = md(html_str)
        content_md = _replace_math_placeholders(content_md, inline_formulas, block_formulas).strip()

        return ZhihuFetchResult(
            success=True,
            type="answer",
            url=url,
            title=title,
            author=author,
            date=date,
            content_markdown=content_md,
        )

    async def _list_column(self, url: str, *, cookies: str = "") -> ZhihuFetchResult:
        target_url = (url or "").strip()
        parsed = urlparse(target_url)
        slug = (parsed.path or "").rstrip("/").split("/")[-1]
        if not slug:
            return ZhihuFetchResult(success=False, type="column", url=target_url, error="invalid_column_url")

        ck = (cookies or "").strip() or self._cookies
        headers = self._build_headers(ck)
        timeout = httpx.Timeout(self._timeout_seconds)

        # 尝试获取专栏标题（页面 title）
        title = ""
        try:
            html = await self._get_html(target_url, cookies=cookies)
            soup = BeautifulSoup(html, "lxml")
            _detect_common_errors(soup)
            title = _extract_title(soup, fallback_prefix=slug)
        except (ZhihuFetchError, httpx.HTTPError, ValueError, TypeError):
            title = slug

        api_base = f"https://www.zhihu.com/api/v4/columns/{slug}/items"
        items: List[Dict[str, Any]] = []
        offset = 0
        limit = 10

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            for _ in range(5):  # 防止返回过多；最多拉 50 条
                resp = await client.get(api_base, params={"limit": limit, "offset": offset})
                resp.raise_for_status()
                data_raw = resp.json()
                data = data_raw if isinstance(data_raw, dict) else {}
                chunk = data.get("data") if isinstance(data.get("data"), list) else []
                for it in chunk:
                    if not isinstance(it, dict):
                        continue
                    it_type = str(it.get("type") or "").strip() or "unknown"
                    it_id = str(it.get("id") or "").strip()

                    # title 字段可能不存在；对 answer 取 question.title
                    it_title = str(it.get("title") or "").strip()
                    if not it_title and isinstance(it.get("question"), dict):
                        it_title = str(it["question"].get("title") or "").strip()

                    it_author = (
                        str(it.get("author", {}).get("name") or "").strip()
                        if isinstance(it.get("author"), dict)
                        else ""
                    )
                    it_date = _ts_to_yyyymmdd(it.get("created_time") or it.get("updated_time") or "")

                    it_url = ""
                    if it_type == "article" and it_id:
                        it_url = f"https://zhuanlan.zhihu.com/p/{it_id}"
                    elif it_type == "answer" and it_id and isinstance(it.get("question"), dict):
                        qid = str(it["question"].get("id") or "").strip()
                        if qid:
                            it_url = f"https://www.zhihu.com/question/{qid}/answer/{it_id}"
                    elif it_type == "zvideo" and it_id:
                        it_url = f"https://www.zhihu.com/zvideo/{it_id}"

                    items.append(
                        {
                            "type": it_type,
                            "id": it_id,
                            "title": it_title,
                            "author": it_author,
                            "date": it_date,
                            "url": it_url,
                        }
                    )

                paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
                if paging.get("is_end") is True or not chunk:
                    break
                offset += limit

        # 同时给一份 Markdown 列表，方便 LLM 直接引用
        md_lines = [f"# {title}", "", f"专栏：{target_url}", ""]
        for idx, it in enumerate(items, start=1):
            t = (it.get("title") or "").strip() or "(无标题)"
            u = (it.get("url") or "").strip()
            if u:
                md_lines.append(f"{idx}. [{t}]({u})")
            else:
                md_lines.append(f"{idx}. {t}")
        content_markdown = "\n".join(md_lines).strip()

        return ZhihuFetchResult(
            success=True,
            type="column",
            url=target_url,
            title=title,
            items=items,
            content_markdown=content_markdown,
        )
