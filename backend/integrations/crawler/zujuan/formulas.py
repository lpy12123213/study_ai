from __future__ import annotations

import asyncio
import base64
import binascii
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from backend.core.logging_utils import get_logger
from backend.integrations.crawler.zujuan.cookies import load_env_login
from backend.integrations.crawler.zujuan.parsing import FORMULA_HASH_PATTERN, FORMULA_IMG_TAG_PATTERN

logger = get_logger(__name__)


def _ensure_inline_math_wrapped(latex: str) -> str:
    """Ensure LaTeX is wrapped in an inline-math delimiter.

    We normalize crawler output so frontend renderers can reliably detect math.
    """

    value = (latex or "").strip()
    if not value:
        return ""

    if value.startswith("\\(") and value.endswith("\\)"):
        return value
    if value.startswith("\\[") and value.endswith("\\]"):
        return value
    if value.startswith("$$") and value.endswith("$$") and len(value) >= 4:
        return value
    if value.startswith("$") and value.endswith("$") and len(value) >= 2:
        return value

    return f"\\({value}\\)"


def build_curl_cmd(crawler: Any, url: str, timeout: int = 30, use_login_cookie: bool = True) -> list:
    cmd = [
        "curl",
        "-s",
        "-H",
        f"User-Agent: {crawler.user_agent}",
        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H",
        "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "-H",
        "Referer: https://zujuan.xkw.com/",
    ]

    cookie_to_use = crawler.cookies
    if use_login_cookie and not cookie_to_use:
        env_session = load_env_login()
        if env_session.get("is_logged_in") and env_session.get("cookies"):
            cookie_to_use = env_session["cookies"]

    if cookie_to_use:
        cmd.extend(["-H", f"Cookie: {cookie_to_use}"])
    cmd.append(url)
    return cmd


def resolve_url(crawler: Any, url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        if value.startswith("/quesimg/Upload/"):
            return f"https://staticzujuan.xkw.com{value}"
        return f"{crawler.base_url.rstrip('/')}{value}"
    return value


def formula_cache_get(crawler: Any, formula_hash: str) -> Optional[str]:
    key = (formula_hash or "").strip().lower()
    if not key:
        return None
    # Backwards-compatible: some tests/config mutate `_formula_cache_max_entries`
    # on the crawler instance. Keep the underlying cache in sync.
    try:
        max_entries = int(getattr(crawler, "_formula_cache_max_entries", 0) or 0)
        if max_entries > 0:
            crawler._formula_cache.max_entries = max_entries
    except (TypeError, ValueError):
        if not getattr(crawler, "_formula_cache_max_entries_invalid_logged", False):
            setattr(crawler, "_formula_cache_max_entries_invalid_logged", True)
            logger.warning(
                "zujuan_formula_cache_max_entries_invalid",
                extra={"value": getattr(crawler, "_formula_cache_max_entries", None)},
                exc_info=True,
            )
    cached = crawler._formula_cache.get(key)
    if cached is None:
        return None
    return str(cached or "")


def formula_cache_set(crawler: Any, formula_hash: str, latex: str) -> None:
    key = (formula_hash or "").strip().lower()
    if not key:
        return
    try:
        max_entries = int(getattr(crawler, "_formula_cache_max_entries", 0) or 0)
        if max_entries > 0:
            crawler._formula_cache.max_entries = max_entries
        crawler._formula_cache.set(key, latex or "")
    except Exception:
        logger.warning("zujuan_formula_cache_set_failed", extra={"hash": key}, exc_info=True)
        return


async def fetch_formula_mathml(crawler: Any, formula_hash: str) -> str:
    formula_hash = (formula_hash or "").strip().lower()
    if not formula_hash or not re.fullmatch(r"[0-9a-f]{32}", formula_hash):
        return ""
    if not crawler.client:
        return ""

    url = f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{formula_hash}.mml"
    async with crawler._formula_http_sem:
        resp = await crawler.client.get(
            url,
            headers={
                "User-Agent": crawler.user_agent,
                "Referer": f"{crawler.base_url.rstrip('/')}/",
            },
        )
    if resp.status_code != 200:
        return ""

    raw = (resp.content or b"").strip()
    if not raw:
        return ""

    try:
        as_text = raw.decode("utf-8", errors="ignore").strip()
    except UnicodeDecodeError:
        as_text = ""
    if as_text.lstrip().startswith("<math"):
        return as_text

    try:
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore").strip()
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return ""

    return decoded if "<math" in decoded else ""


async def mathml_to_latex_via_pandoc(crawler: Any, mathml_xml: str) -> str:
    xml = (mathml_xml or "").strip()
    if not xml:
        return ""

    def _run() -> str:
        try:
            result = subprocess.run(
                ["pandoc", "-f", "html", "-t", "latex"],
                input=xml,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=20,
                check=True,
            )
            return (result.stdout or "").strip()
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return ""

    async with crawler._formula_pandoc_sem:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)


async def get_formula_latex(crawler: Any, formula_hash: str) -> str:
    formula_hash = (formula_hash or "").strip().lower()
    if not formula_hash or not re.fullmatch(r"[0-9a-f]{32}", formula_hash):
        return ""

    cached = formula_cache_get(crawler, formula_hash)
    if cached is not None:
        return cached

    # Persistent cache (DB): survives restarts so repeated crawls don't re-run pandoc/svg conversion.
    try:
        from backend.database.repositories.system.formula_cache import get_formula_latex as db_get_formula_latex
    except ImportError:
        db_get_formula_latex = None  # type: ignore[assignment]

    if db_get_formula_latex is not None:
        try:
            persisted = str(await db_get_formula_latex(formula_hash=formula_hash) or "").strip()
        except Exception:
            logger.warning("zujuan_formula_latex_db_get_failed", extra={"hash": formula_hash}, exc_info=True)
            persisted = ""
        if persisted:
            formula_cache_set(crawler, formula_hash, persisted)
            return persisted

    inflight = crawler._formula_inflight.get(formula_hash)
    if inflight is not None:
        try:
            return await inflight
        except Exception:
            logger.warning("zujuan_formula_inflight_failed", extra={"hash": formula_hash}, exc_info=True)
            return ""

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[str] = loop.create_future()
    crawler._formula_inflight[formula_hash] = fut
    try:
        mathml = await fetch_formula_mathml(crawler, formula_hash)
        latex = ""
        if mathml:
            latex = (await mathml_to_latex_via_pandoc(crawler, mathml)).strip()
        if not latex:
            try:
                from backend.core.svg_utils.svg_to_latex import svg_url_to_latex

                svg_url = f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{formula_hash}.svg"
                async with crawler._formula_http_sem:
                    svg_latex, unknown = await svg_url_to_latex(svg_url, client=crawler.client, use_advanced=True)
                svg_latex = (svg_latex or "").strip()
                if svg_latex:
                    latex = f"\\({svg_latex}\\)"

                if unknown:
                    try:
                        from backend.core.svg_utils.unknown_signatures import record_unknown_signatures

                        record_unknown_signatures(unknown_sigs=unknown, source_url=svg_url, context=None)
                    except Exception:
                        logger.warning("zujuan_record_unknown_signatures_failed", exc_info=True)
            except Exception:
                logger.warning("zujuan_svg_formula_fallback_failed", extra={"hash": formula_hash}, exc_info=True)

        latex = _ensure_inline_math_wrapped(latex)
        formula_cache_set(crawler, formula_hash, latex)
        try:
            from backend.database.repositories.system.formula_cache import (
                upsert_formula_latex as db_upsert_formula_latex,
            )

            if latex:
                await db_upsert_formula_latex(formula_hash=formula_hash, latex=latex)
        except Exception:
            if not getattr(crawler, "_formula_db_upsert_failed_logged", False):
                setattr(crawler, "_formula_db_upsert_failed_logged", True)
                logger.warning(
                    "zujuan_formula_latex_db_upsert_failed",
                    extra={"hash": formula_hash},
                    exc_info=True,
                )
        if not fut.done():
            fut.set_result(latex)
        return latex
    except Exception:
        logger.warning("zujuan_get_formula_latex_failed", extra={"hash": formula_hash}, exc_info=True)
        if not fut.done():
            fut.set_result("")
        return ""
    finally:
        crawler._formula_inflight.pop(formula_hash, None)


async def replace_formulas_with_latex_mml(crawler: Any, html: str) -> Tuple[str, List[str]]:
    raw = html or ""
    hashes = [formula_hash.lower() for (formula_hash, _ext) in FORMULA_HASH_PATTERN.findall(raw)]
    hashes = list(dict.fromkeys(hashes))
    if not hashes:
        return raw, []

    latex_list = await asyncio.gather(
        *[get_formula_latex(crawler, formula_hash) for formula_hash in hashes], return_exceptions=True
    )
    hash_to_latex: Dict[str, str] = {}
    for formula_hash, value in zip(hashes, latex_list):
        if isinstance(value, Exception):
            continue
        if isinstance(value, str) and value.strip():
            hash_to_latex[formula_hash] = value.strip()

    def _repl(match: re.Match) -> str:
        formula_hash = (match.group("hash") or "").lower()
        latex = hash_to_latex.get(formula_hash, "")
        if latex:
            return latex
        return f"[公式:{formula_hash}]"

    replaced = FORMULA_IMG_TAG_PATTERN.sub(_repl, raw)
    return replaced, hashes


async def fetch_formula_svg(_crawler: Any, png_url: str) -> str:
    svg_url = (png_url or "").strip()
    if not svg_url:
        return ""
    if not svg_url.lower().endswith(".svg"):
        svg_url = re.sub(r"\.(png|gif|jpe?g)(\?.*)?$", ".svg", svg_url, flags=re.IGNORECASE)
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(["curl", "-s", svg_url], capture_output=True, timeout=10),
        )
        svg = result.stdout.decode("utf-8", errors="ignore")
        if svg.startswith("<svg"):
            return svg
    except Exception:
        logger.warning("zujuan_fetch_formula_svg_failed", extra={"url": svg_url}, exc_info=True)
    return ""


async def replace_formulas_with_latex(crawler: Any, html: str) -> str:
    try:
        replaced, _hashes = await replace_formulas_with_latex_mml(crawler, html)
        return replaced
    except Exception:
        logger.warning("zujuan_replace_formulas_mml_failed; fallback", exc_info=True)

    try:
        from backend.core.svg_utils.svg_to_latex import replace_formulas_with_latex as replace_svg_formulas

        result, unknown_sigs = await replace_svg_formulas(html, concurrency=12, use_advanced=True)

        if unknown_sigs:
            try:
                from backend.core.svg_utils.unknown_signatures import record_unknown_signatures

                for svg_url, sigs in unknown_sigs.items():
                    if sigs:
                        record_unknown_signatures(unknown_sigs=sigs, source_url=svg_url, context=None)
            except ImportError:
                pass

        return result
    except ImportError:
        return await replace_formulas_with_svg(crawler, html)
    except Exception as exc:
        logger.warning("mathml to latex failed; fallback to svg", extra={"error": str(exc)}, exc_info=True)
        return await replace_formulas_with_svg(crawler, html)


async def replace_formulas_with_svg(crawler: Any, html: str) -> str:
    raw = html or ""
    hashes = [formula_hash.lower() for (formula_hash, _ext) in FORMULA_HASH_PATTERN.findall(raw)]
    hashes = list(dict.fromkeys(hashes))
    if not hashes:
        return raw

    hashes = hashes[:20]
    svg_list = await asyncio.gather(
        *[
            fetch_formula_svg(crawler, f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{formula_hash}.svg")
            for formula_hash in hashes
        ],
        return_exceptions=True,
    )
    hash_to_svg: Dict[str, str] = {}
    for formula_hash, value in zip(hashes, svg_list):
        if isinstance(value, Exception):
            continue
        if isinstance(value, str) and value.lstrip().startswith("<svg"):
            hash_to_svg[formula_hash] = value

    def _repl(match: re.Match) -> str:
        formula_hash = (match.group("hash") or "").lower()
        svg = hash_to_svg.get(formula_hash, "")
        if svg:
            return f"[公式:{svg}]"
        return f"[公式:{formula_hash}]"

    return FORMULA_IMG_TAG_PATTERN.sub(_repl, raw)


async def replace_formulas_with_inline_svg(crawler: Any, html: str) -> str:
    formula_pattern = r'<img[^>]*src="([^"]+)"[^>]*>'
    matches = re.findall(formula_pattern, html)
    formula_srcs = []
    for src in matches:
        if "/Upload/formula/" not in src:
            continue
        formula_srcs.append(src)

    formula_srcs = list(dict.fromkeys(formula_srcs))
    if not formula_srcs:
        return html

    svg_map = {}
    for src in formula_srcs[:20]:
        resolved = src
        if resolved.startswith("//"):
            resolved = f"https:{resolved}"
        elif resolved.startswith("/"):
            resolved = f"{crawler.base_url.rstrip('/')}{resolved}"
        svg = await fetch_formula_svg(crawler, resolved)
        if svg:
            svg_map[src] = svg

    result = html
    for src, svg in svg_map.items():
        img_pattern = f'<img[^>]*src="{re.escape(src)}"[^>]*>'
        replacement = f'<span class="epa-formula" data-formula-src="{src}">{svg}</span>'
        result = re.sub(img_pattern, replacement, result)

    return result
