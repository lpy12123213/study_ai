from __future__ import annotations

import asyncio
import html as html_module
import re
import urllib.parse
from typing import Any, Dict, List, Tuple

from backend.core.logging_utils import get_logger
from backend.crawler.zujuan.parsing import FORMULA_HASH_PATTERN, FORMULA_IMG_TAG_PATTERN, IMG_TAG_PATTERN
from backend.crawler.zujuan.utils import _safe_int

logger = get_logger(__name__)


async def parse_questions_from_html(
    self,
    html: str,
    bank_id: int,
    *,
    parse_content: bool = True,
) -> List[Dict[str, Any]]:
    """Parse `question/list` HTML fragments into structured questions.

    - Prefer DOM parsing (BeautifulSoup) over regex splitting.
    - Convert formula images via `{hash}.mml` (MathML base64) -> pandoc -> LaTeX.
    """

    decoded = html_module.unescape(html or "")
    if not decoded.strip():
        return []

    questions: List[Dict[str, Any]] = []
    content_fragments: List[Tuple[int, str]] = []

    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        BeautifulSoup = None  # type: ignore

    if BeautifulSoup is None:
        # Best-effort fallback: keep only basic fields.
        question_blocks = re.split(r'<div class=" tk-quest-item', decoded)
        for block in question_blocks[1:]:
            qid_match = re.search(r'questionid="(\d+)"', block)
            if not qid_match:
                continue
            qid = qid_match.group(1)
            q: Dict[str, Any] = {
                "question_id": qid,
                "bank_id": _safe_int(bank_id, 0) or None,
                "source_url": f"{self.base_url}/{bank_id}q{qid}.html",
                "type": "",
                "difficulty": "",
                "difficulty_value": "",
                "knowledge_points": [],
                "source": "",
                "date": "",
            }
            content_fragments.append((len(questions), block))
            q["_stem_html"] = block
            questions.append(q)

        if content_fragments:
            stem_max_chars = 2500 if parse_content else 650
            await batch_convert_formulas(
                self,
                questions,
                content_fragments,
                convert_formulas=bool(parse_content),
                stem_max_chars=stem_max_chars,
            )
        return questions

    soup = BeautifulSoup(decoded, "lxml")

    RE_PAPER = re.compile(r"/(\d+)p(\d+)\.html", re.IGNORECASE)
    # Tag IDs can appear with multiple URL shapes (courseIdPy routes, /course{courseId}/*, etc.).
    RE_ZSD = re.compile(r"/zsd(\d+)(?:/|$)", re.IGNORECASE)
    RE_JTFF = re.compile(r"/jtff(\d+)(?:/|$)", re.IGNORECASE)
    RE_ZJ = re.compile(r"/(?:zj|zhangjie)(\d+)(?:/|$)", re.IGNORECASE)

    for root in soup.select("div.tk-quest-item[questionid]"):
        qid = str(root.get("questionid") or "").strip()
        if not qid.isdigit():
            continue

        q: Dict[str, Any] = {
            "question_id": qid,
            "type": "",
            "difficulty": "",
            "difficulty_value": "",
            "knowledge_points": [],
            "source": "",
            "date": "",
        }

        root_bank_id = (
            _safe_int(root.get("bankid"), 0) or _safe_int(bank_id, 0) or _safe_int(getattr(self, "bank_id", 0), 0)
        )
        if root_bank_id:
            q["bank_id"] = root_bank_id
        q["source_url"] = f"{self.base_url}/{root_bank_id}q{qid}.html" if root_bank_id else self._question_url(qid)
        q["question_index"] = _safe_int(root.get("questionindex"), 0)

        # Structured meta: addques button carries type/difficulty hints.
        meta: Dict[str, Any] = {}
        add_btn = root.select_one("a.addques[quesid]")
        if add_btn is not None:
            qyid = _safe_int(add_btn.get("qyid"), 0)
            qyname = str(add_btn.get("qyname") or "").strip()
            qdid = _safe_int(add_btn.get("qdid"), 0)
            qdname = str(add_btn.get("qdname") or "").strip()
            if qyid or qyname:
                meta["ques_type"] = {"id": qyid, "name": qyname}
            if qdid or qdname:
                meta["ques_diff"] = {"id": qdid, "name": qdname}
            cat_hint_id = _safe_int(add_btn.get("categoryid") or add_btn.get("categoryId"), 0)
            cat_hint_name = str(add_btn.get("categoryname") or add_btn.get("categoryName") or "").strip()
            if cat_hint_id or cat_hint_name:
                meta["category_hint"] = {"id": cat_hint_id, "name": cat_hint_name}

        info_items = [s.get_text(strip=True) for s in root.select("span.info-cnt") if s.get_text(strip=True)]
        if meta.get("ques_type", {}).get("name"):
            q["type"] = str(meta["ques_type"]["name"]).strip()
        elif info_items:
            q["type"] = info_items[0]

        if meta.get("ques_diff", {}).get("name"):
            q["difficulty"] = str(meta["ques_diff"]["name"]).strip()
        if len(info_items) > 1:
            diff_text = info_items[1]
            diff_match = re.search(r"([\u4e00-\u9fa5]+)\s*(?:\((\d+(?:\.\d+)?)\))?", diff_text)
            if diff_match:
                if not q["difficulty"]:
                    q["difficulty"] = (diff_match.group(1) or "").strip()
                if diff_match.group(2):
                    q["difficulty_value"] = diff_match.group(2)

        if meta:
            q["meta"] = meta

        # knowledge point names shown in the block.
        kps = [a.get_text(strip=True) for a in root.select("a.knowledge-item") if a.get_text(strip=True)]
        q["knowledge_points"] = kps

        # Source paper link + title.
        links: Dict[str, Any] = {}
        src_a = root.select_one("a.ques-src[href]")
        if src_a is not None:
            href = str(src_a.get("href") or "").strip()
            if href:
                links["source_paper_url"] = urllib.parse.urljoin(self.base_url, href)
                m = RE_PAPER.search(href)
                if m:
                    meta = dict(meta)
                    meta["source_paper_id"] = _safe_int(m.group(2), 0)
                    q["meta"] = meta
            q["source"] = src_a.get_text(strip=True)

        detail_a = root.select_one("a.detail[href]")
        if detail_a is not None:
            href = str(detail_a.get("href") or "").strip()
            if href:
                links["detail_url"] = urllib.parse.urljoin(self.base_url, href)

        if links:
            q["links"] = links

        date_span = root.select_one("span.no-bound")
        q["date"] = date_span.get_text(strip=True) if date_span else ""

        # Tags: aligned category IDs referenced by links (docs/zujuan_crawler/docs/12-category-alignment.md).
        zsd_ids: List[int] = []
        jtff_ids: List[int] = []
        zj_ids: List[int] = []
        other_links: List[Dict[str, str]] = []
        for a in root.select("a[href]"):
            href = str(a.get("href") or "")
            m = RE_ZSD.search(href)
            if m:
                zsd_ids.append(_safe_int(m.group(1), 0))
                continue
            m = RE_JTFF.search(href)
            if m:
                jtff_ids.append(_safe_int(m.group(1), 0))
                continue
            m = RE_ZJ.search(href)
            if m:
                zj_ids.append(_safe_int(m.group(1), 0))
                continue
            # Keep unmapped tre* links for later alignment.
            if "tre" in href:
                other_links.append({"href": href, "text": a.get_text(strip=True)})

        tags: Dict[str, Any] = {}
        zsd_ids = [x for x in sorted(set(zsd_ids)) if x]
        jtff_ids = [x for x in sorted(set(jtff_ids)) if x]
        zj_ids = [x for x in sorted(set(zj_ids)) if x]
        if zsd_ids:
            tags["knowledge_zsd_ids"] = zsd_ids
        if jtff_ids:
            tags["method_jtff_ids"] = jtff_ids
        if zj_ids:
            tags["chapter_zj_ids"] = zj_ids
        if other_links:
            tags["other_links"] = other_links
        if tags:
            q["tags"] = tags

        # Content fragment: exam-item__cnt usually contains stem + options.
        content_node = root.select_one("div.exam-item__cnt") or root.select_one("div.qbody")
        if content_node is not None:
            content_html = "".join(str(x) for x in content_node.contents)
        else:
            content_html = str(root)
        q["_stem_html"] = content_html
        content_fragments.append((len(questions), content_html))

        # Formula hashes: keep for downstream filtering/diagnostics.
        formula_hashes = [h.lower() for (h, _ext) in FORMULA_HASH_PATTERN.findall(str(root))]
        formula_hashes = list(dict.fromkeys(formula_hashes))
        q["has_formula"] = bool(formula_hashes)
        q["formula_hashes"] = formula_hashes

        questions.append(q)

    if content_fragments:
        stem_max_chars = 2500 if parse_content else 650
        await batch_convert_formulas(
            self,
            questions,
            content_fragments,
            convert_formulas=bool(parse_content),
            stem_max_chars=stem_max_chars,
        )

    return questions


async def batch_convert_formulas(
    self,
    questions: List[Dict[str, Any]],
    question_stems: List[Tuple[int, str]],
    *,
    convert_formulas: bool = True,
    stem_max_chars: int = 2500,
) -> None:
    """
    批量转换题面片段中的公式图片为 LaTeX，并生成可用于下游的纯文本 `stem` 字段。

    公式链路（优先）：
    - `{hash}.mml`（MathML base64 sidecar）→ pandoc → LaTeX
    """
    if not question_stems:
        return

    def _is_fragmented_text(value: str) -> bool:
        if not re.search(r"[\r\n\u2028\u2029]", value or ""):
            return False
        lines = [ln.strip() for ln in re.split(r"\r\n|\r|\n|\u2028|\u2029", value or "") if ln.strip()]
        if len(lines) < 8:
            return False
        short2 = sum(1 for ln in lines if len(ln) <= 2)
        short3 = sum(1 for ln in lines if len(ln) <= 3)
        ratio2 = short2 / max(1, len(lines))
        ratio3 = short3 / max(1, len(lines))
        if len(lines) >= 25:
            return ratio2 >= 0.6 or (ratio3 >= 0.7 and short2 >= 10)
        return ratio2 >= 0.55 or (ratio3 >= 0.7 and short2 >= 6)

    def _defragment_text(value: str) -> str:
        if not _is_fragmented_text(value):
            return value

        parts = re.split(r"\r\n|\r|\n|\u2028|\u2029", value or "")
        out = ""
        pending_paragraph = False
        for ln in parts:
            t = (ln or "").strip()
            if not t:
                pending_paragraph = True
                continue
            if pending_paragraph and out:
                out += "\n\n"
            pending_paragraph = False
            out += t
        return out

    # 1) Collect unique hashes across all fragments.
    all_hashes: List[str] = []
    per_fragment_hashes: Dict[int, List[str]] = {}
    for idx, frag_html in question_stems:
        raw = frag_html or ""
        hashes = [h.lower() for (h, _ext) in FORMULA_HASH_PATTERN.findall(raw)]
        # Prefer pre-extracted hashes from the full question block when available.
        existing_hashes = questions[idx].get("formula_hashes")
        if isinstance(existing_hashes, list):
            for h in existing_hashes:
                hs = str(h or "").strip().lower()
                if hs:
                    hashes.append(hs)
        hashes = list(dict.fromkeys(hashes))
        if hashes:
            per_fragment_hashes[idx] = hashes
            all_hashes.extend(hashes)

    all_hashes = list(dict.fromkeys(all_hashes))

    # 2) Batch convert hashes to LaTeX (mml -> pandoc).
    convert_formulas = bool(convert_formulas)
    try:
        stem_max_chars = int(stem_max_chars or 0)
    except Exception:
        stem_max_chars = 2500
    stem_max_chars = max(120, min(stem_max_chars, 5000))

    hash_to_latex: Dict[str, str] = {}
    if convert_formulas and all_hashes:
        latex_list = await asyncio.gather(
            *[self._get_formula_latex(h) for h in all_hashes],
            return_exceptions=True,
        )
        for h, v in zip(all_hashes, latex_list):
            if isinstance(v, Exception):
                continue
            if isinstance(v, str) and v.strip():
                hash_to_latex[h] = v.strip()

    def _replace_formula_imgs(fragment: str) -> str:
        def _repl(m: re.Match) -> str:
            h = (m.group("hash") or "").lower()
            latex = hash_to_latex.get(h, "")
            if latex:
                return latex
            return f"[公式:{h}]"

        return FORMULA_IMG_TAG_PATTERN.sub(_repl, fragment or "")

    def _replace_other_imgs(fragment: str) -> str:
        def _repl(m: re.Match) -> str:
            src = self._resolve_url(m.group("src"))
            if not src:
                return "[图片]"
            return f"[图片:{src}]"

        return IMG_TAG_PATTERN.sub(_repl, fragment or "")

    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        BeautifulSoup = None  # type: ignore

    def _strip_math_wrappers(value: str) -> str:
        token = str(value or "").strip()
        while True:
            next_token = token
            if next_token.startswith("\\(") and next_token.endswith("\\)") and len(next_token) >= 4:
                next_token = next_token[2:-2].strip()
            elif next_token.startswith("\\[") and next_token.endswith("\\]") and len(next_token) >= 4:
                next_token = next_token[2:-2].strip()
            elif next_token.startswith("$$") and next_token.endswith("$$") and len(next_token) >= 4:
                next_token = next_token[2:-2].strip()
            elif next_token.startswith("$") and next_token.endswith("$") and len(next_token) >= 2:
                next_token = next_token[1:-1].strip()
            if next_token == token:
                return token
            token = next_token

    def _normalize_table_cell(value: str) -> str:
        text = _strip_math_wrappers(html_module.unescape(value or ""))
        text = re.sub(r"\s+", " ", text).strip()
        if text in {"...", "…"}:
            return "\\cdots"
        return text.replace("&", "\\&")

    def _table_to_latex(table: Any) -> str:
        rows: List[List[str]] = []
        for tr in table.select("tr"):
            cells = tr.select("th,td")
            if not cells:
                continue
            row: List[str] = []
            for cell in cells:
                try:
                    for br in cell.select("br"):
                        br.replace_with(" ")
                except Exception:
                    logger.warning("zujuan_table_br_replace_failed", exc_info=True)
                row.append(_normalize_table_cell(cell.get_text("", strip=True)))
            if any(token for token in row):
                rows.append(row)

        if not rows:
            return ""

        width = max(len(row) for row in rows)
        aligned_rows = [row + [""] * (width - len(row)) for row in rows]
        body = " \\\\ ".join([" & ".join(row) for row in aligned_rows])
        return f"\\[\\begin{{array}}{{{'c' * max(2, width)}}}{body}\\end{{array}}\\]"

    for idx, stem_html in question_stems:
        # 3) Replace formulas first, then replace remaining images.
        converted = _replace_formula_imgs(stem_html or "")
        converted = _replace_other_imgs(converted)

        # 4) HTML -> text
        if BeautifulSoup is not None:
            soup = BeautifulSoup(converted, "lxml")
            # Avoid "vertical text" output: some stems wrap every character in inline tags.
            # We manually insert newlines for <br> and common block elements, then extract
            # text with an empty separator so inline spans don't become one-char-per-line.
            try:
                for table in soup.select("table"):
                    latex_table = _table_to_latex(table)
                    if latex_table:
                        table.replace_with(soup.new_string(f"\n{latex_table}\n"))
                for br in soup.select("br"):
                    br.replace_with("\n")
                for block in soup.select("p,div,li,section,ul,ol,hr,h1,h2,h3,h4,h5,h6"):
                    block.append("\n")
            except Exception:
                logger.debug("zujuan_soup_normalize_failed", exc_info=True)
            text = soup.get_text("", strip=False)
        else:
            text = re.sub(r"<[^>]+>", "", converted)

        text = html_module.unescape(text or "")
        text = re.sub(r"[ \t]+", " ", text)
        text = text.replace("\u00a0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = _defragment_text(text).strip()
        text = re.sub(r"^\d+\s*[.．、]\s*", "", text)

        # Keep within reasonable size to avoid tool payload bloat.
        questions[idx]["stem"] = text[:stem_max_chars]

        frag_hashes = per_fragment_hashes.get(idx) or []
        if frag_hashes and "formula_hashes" not in questions[idx]:
            questions[idx]["formula_hashes"] = frag_hashes
        if frag_hashes and "has_formula" not in questions[idx]:
            questions[idx]["has_formula"] = True

        if "_stem_html" in questions[idx]:
            del questions[idx]["_stem_html"]
        # Ensure we never leak HTML fragments in results (MCP/tool payload bloat).
        for k in ("raw_html_fragment", "latex_html_fragment"):
            if k in questions[idx]:
                del questions[idx][k]

