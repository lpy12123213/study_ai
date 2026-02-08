"""
Probe the formula pipeline:

question/list HTML -> formula hash -> {hash}.mml (Base64 MathML) -> optional pandoc -> LaTeX

This is a regression/coverage script. Keep it low-volume and cache results if
you scale it up in production.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import re
import subprocess
import time
from dataclasses import dataclass

import requests


BASE = "https://zujuan.xkw.com"
STATIC = "https://staticzujuan.xkw.com"


RE_FORMULA_HASH = re.compile(r"/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg)", re.I)
RE_QID = re.compile(r'questionid="(\d+)"')


def has_pandoc() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def mathml_to_latex_pandoc(mathml_xml: str) -> str:
    p = subprocess.run(
        ["pandoc", "-f", "html", "-t", "latex"],
        input=mathml_xml,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        timeout=10,
    )
    return p.stdout.strip()


@dataclass
class MmlResult:
    formula_hash: str
    status: int
    ok_base64: bool
    has_math_tag: bool
    pandoc_ok: bool | None
    note: str = ""


def fetch_question_list_html(
    session: requests.Session,
    *,
    bank_id: int,
    course_id: int,
    page_name: str,
    category_id: int,
    cur_page: int,
    referer: str,
    extra: dict[str, str] | None = None,
    sleep_s: float = 0.4,
) -> tuple[str, int | None]:
    if sleep_s:
        time.sleep(sleep_s)
    data = {
        "pageName": page_name,
        "bankId": str(bank_id),
        "courseId": str(course_id),
        "categoryId": str(category_id),
        "provinceId": "-1",
        "orderBy": "2",
        "quesType": "0",
        "quesDiff": "0",
        "quesYear": "0",
        "curPage": str(cur_page),
    }
    if extra:
        data.update(extra)
    r = session.post(
        f"{BASE}/zujuan-api/question/list",
        headers={
            "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        data=data,
        timeout=30,
        allow_redirects=False,
    )
    payload = r.json()
    html = (payload.get("data") or {}).get("html") or ""
    total = (payload.get("data") or {}).get("total")
    try:
        total = int(total) if total is not None else None
    except Exception:
        total = None
    return html, total


def gather_formula_hashes(
    session: requests.Session,
    *,
    bank_id: int,
    course_id: int,
    page_name: str,
    category_id: int,
    referer: str,
    target_unique: int,
    max_pages: int,
) -> list[str]:
    hashes: set[str] = set()
    cur = 1
    while cur <= max_pages and len(hashes) < target_unique:
        html, _ = fetch_question_list_html(
            session,
            bank_id=bank_id,
            course_id=course_id,
            page_name=page_name,
            category_id=category_id,
            cur_page=cur,
            referer=referer,
        )
        # Stop if page has no questions (end).
        if not RE_QID.search(html):
            break
        for m in RE_FORMULA_HASH.finditer(html):
            hashes.add(m.group(1).lower())
        cur += 1
    return sorted(hashes)


def fetch_mml_and_optional_pandoc(
    session: requests.Session,
    formula_hash: str,
    *,
    do_pandoc: bool,
    sleep_s: float = 0.05,
) -> MmlResult:
    if sleep_s:
        time.sleep(sleep_s)
    url = f"{STATIC}/quesimg/Upload/formula/{formula_hash}.mml"
    r = session.get(url, timeout=30, allow_redirects=False)
    if r.status_code != 200:
        return MmlResult(formula_hash=formula_hash, status=r.status_code, ok_base64=False, has_math_tag=False, pandoc_ok=None, note="mml_http")

    raw = (r.content or b"").strip()
    ok_base64 = True
    has_math_tag = False
    pandoc_ok: bool | None = None
    note = ""
    try:
        mathml_xml = base64.b64decode(raw).decode("utf-8", errors="replace")
        has_math_tag = "<math" in mathml_xml
    except Exception as e:
        ok_base64 = False
        note = f"base64_error:{type(e).__name__}"
        mathml_xml = ""

    if do_pandoc and ok_base64 and has_math_tag:
        try:
            out = mathml_to_latex_pandoc(mathml_xml)
            pandoc_ok = bool(out)
            if not out:
                note = "pandoc_empty"
        except Exception as e:
            pandoc_ok = False
            note = f"pandoc_error:{type(e).__name__}"

    return MmlResult(
        formula_hash=formula_hash,
        status=r.status_code,
        ok_base64=ok_base64,
        has_math_tag=has_math_tag,
        pandoc_ok=pandoc_ok,
        note=note,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank-id", type=int, default=11)
    ap.add_argument("--course-id", type=int, default=27)
    ap.add_argument("--page-name", type=str, default="zsd", help="zsd/zj/jtff")
    ap.add_argument("--category-id", type=int, default=28102)
    ap.add_argument("--referer", type=str, default=f"{BASE}/gzsx/zsd28102/")
    ap.add_argument("--target", type=int, default=100, help="target unique formula hashes")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--sample", type=int, default=100, help="how many hashes to probe (<=target)")
    ap.add_argument("--shuffle", action="store_true", help="randomly sample hashes instead of taking first N")
    ap.add_argument("--no-pandoc", action="store_true", help="skip pandoc conversion even if installed")
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"})

    print("gathering formula hashes...")
    hashes = gather_formula_hashes(
        s,
        bank_id=args.bank_id,
        course_id=args.course_id,
        page_name=args.page_name,
        category_id=args.category_id,
        referer=args.referer,
        target_unique=args.target,
        max_pages=args.max_pages,
    )
    print("unique_hashes", len(hashes))
    if not hashes:
        print("no hashes found; try another shard/categoryId")
        return

    sample_n = min(args.sample, len(hashes))
    if args.shuffle:
        sample = random.sample(hashes, k=sample_n)
    else:
        sample = hashes[:sample_n]

    do_pandoc = (not args.no_pandoc) and has_pandoc()
    print("pandoc", "enabled" if do_pandoc else "disabled")

    results: list[MmlResult] = []
    for h in sample:
        results.append(fetch_mml_and_optional_pandoc(s, h, do_pandoc=do_pandoc))

    # Stats
    ok_http = sum(1 for r in results if r.status == 200)
    ok_base64 = sum(1 for r in results if r.status == 200 and r.ok_base64)
    ok_math = sum(1 for r in results if r.status == 200 and r.ok_base64 and r.has_math_tag)
    pandoc_ok = sum(1 for r in results if r.pandoc_ok is True)
    pandoc_fail = sum(1 for r in results if r.pandoc_ok is False)

    print("\nsummary:")
    print("sample_size", len(results))
    print("mml_http_200", ok_http)
    print("mml_base64_ok", ok_base64)
    print("mml_has_math", ok_math)
    if do_pandoc:
        print("pandoc_ok", pandoc_ok)
        print("pandoc_fail", pandoc_fail)

    # Print a few failures for debugging.
    fails = [r for r in results if not (r.status == 200 and r.ok_base64 and r.has_math_tag)]
    if fails:
        print("\nfail_samples:")
        for r in fails[:10]:
            print(r.formula_hash, "status", r.status, "ok_base64", r.ok_base64, "has_math", r.has_math_tag, "note", r.note)

    # JSON output (truncate on console).
    out = [r.__dict__ for r in results]
    print("\njson_prefix:", json.dumps(out, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()

