"""
Probe /zujuan-api/question/list parameter semantics (visitor mode).

This script is intentionally low-volume: it runs a small set of requests and
prints a compact table so you can spot changes after site updates.

As of 2026-02-08, /zujuan-api/question/list is one of the most stable
visitor-accessible data sources (JSON + HTML fragment).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Iterable

import requests


BASE = "https://zujuan.xkw.com"

# Stable sample config (as of 2026-02-08). Adjust if you crawl another subject.
SAMPLE_BANK_ID = 11
SAMPLE_COURSE_ID = 27

# chapter(zj) root: https://zujuan.xkw.com/gzsx/zj135303/
SAMPLE_ZJ_ROOT = 135303

# a leaf-ish knowledge(zsd) id used in docs (may change over time).
SAMPLE_ZSD_LEAF = 28102
SAMPLE_ZSD_SIBLING_A = 28100
SAMPLE_ZSD_SIBLING_B = 28101


RE_QID = re.compile(r'questionid="(\d+)"')
RE_FORMULA_HASH = re.compile(r"/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg)", re.I)


def looks_like_js_challenge(text: str) -> bool:
    t = (text or "").lower()
    return (
        "<body onload=\"check()\">" in t
        or "alicfw_gfver" in t
        or "aliyun_waf_aa" in t
        or "acw_sc__v2" in t
    )


def short(s: str, n: int = 80) -> str:
    s = (s or "").replace("\r", "").replace("\n", "\\n")
    return s[:n]


@dataclass
class ProbeResult:
    label: str
    status: int
    content_type: str
    ok_json: bool
    code: str | None
    total: int | None
    qids: int
    formula_hashes: int
    note: str = ""


def post_question_list(
    session: requests.Session,
    *,
    label: str,
    data: dict | list[tuple[str, str]],
    referer: str | None,
    sleep_s: float = 0.4,
) -> ProbeResult:
    # Be polite and avoid burst requests.
    if sleep_s:
        time.sleep(sleep_s)

    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    if referer:
        headers["Referer"] = referer

    r = session.post(
        f"{BASE}/zujuan-api/question/list",
        headers=headers,
        data=data,
        timeout=30,
        allow_redirects=False,
    )
    ct = (r.headers.get("Content-Type") or "").lower()

    ok_json = False
    code = None
    total = None
    html = ""
    note = ""

    if "json" in ct:
        try:
            payload = r.json()
            ok_json = True
            code = str(payload.get("code"))
            total = (payload.get("data") or {}).get("total")
            try:
                total = int(total) if total is not None else None
            except Exception:
                note = f"total_non_int={total!r}"
                total = None
            html = (payload.get("data") or {}).get("html") or ""
        except Exception:
            note = f"json_parse_fail body_prefix={short(r.text)}"
    else:
        # Sometimes a 200 response is actually HTML (login/challenge page).
        body = r.text or ""
        if looks_like_js_challenge(body):
            note = f"js_challenge body_prefix={short(body)}"
        elif "login.css" in body.lower() or "login-popup.css" in body.lower():
            note = f"login_page body_prefix={short(body)}"
        else:
            note = f"non_json ct={ct} body_prefix={short(body)}"

    qids = len(set(RE_QID.findall(html)))
    formula_hashes = len(set(m.group(1).lower() for m in RE_FORMULA_HASH.finditer(html)))
    return ProbeResult(
        label=label,
        status=r.status_code,
        content_type=ct,
        ok_json=ok_json,
        code=code,
        total=total,
        qids=qids,
        formula_hashes=formula_hashes,
        note=note,
    )


def print_table(rows: Iterable[ProbeResult]):
    rows = list(rows)
    # Simple fixed columns (avoid external deps).
    print(
        "label\tstatus\tct\tjson\tcode\ttotal\tqids\tformula_hashes\tnote",
        flush=True,
    )
    for r in rows:
        print(
            f"{r.label}\t{r.status}\t{r.content_type.split(';')[0]}\t"
            f"{1 if r.ok_json else 0}\t{r.code}\t{r.total}\t{r.qids}\t{r.formula_hashes}\t{r.note}",
            flush=True,
        )


def main():
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    rows: list[ProbeResult] = []

    # 1) pageName strictness / referer mismatch
    base_data = {
        "bankId": str(SAMPLE_BANK_ID),
        "courseId": str(SAMPLE_COURSE_ID),
        "categoryId": str(SAMPLE_ZJ_ROOT),
        "provinceId": "-1",
        "orderBy": "2",
        "quesType": "0",
        "quesDiff": "0",
        "quesYear": "0",
        "curPage": "1",
    }

    rows.append(
        post_question_list(
            s,
            label="zj_ok",
            data={**base_data, "pageName": "zhangjie"},
            referer=f"{BASE}/gzsx/zj{SAMPLE_ZJ_ROOT}/",
        )
    )
    rows.append(
        post_question_list(
            s,
            label="zj_alias",
            data={**base_data, "pageName": "zj"},
            referer=f"{BASE}/gzsx/zj{SAMPLE_ZJ_ROOT}/",
        )
    )
    rows.append(
        post_question_list(
            s,
            label="page_wrong",
            data={**base_data, "pageName": "not_a_page"},
            referer=f"{BASE}/gzsx/zj{SAMPLE_ZJ_ROOT}/",
        )
    )
    rows.append(
        post_question_list(
            s,
            label="ref_mismatch",
            data={**base_data, "pageName": "zhangjie"},
            referer=f"{BASE}/gzsx/zsd27925/",
        )
    )
    rows.append(
        post_question_list(
            s,
            label="no_referer",
            data={**base_data, "pageName": "zhangjie"},
            referer=None,
        )
    )

    # 2) Advanced filters that we can validate without needing extra endpoints.
    # Use a smaller shard (zsd leaf) to make total deltas more obvious.
    leaf_data = {
        "pageName": "zsd",
        "bankId": str(SAMPLE_BANK_ID),
        "courseId": str(SAMPLE_COURSE_ID),
        "categoryId": str(SAMPLE_ZSD_LEAF),
        "provinceId": "-1",
        "orderBy": "2",
        "quesType": "0",
        "quesDiff": "0",
        "quesYear": "0",
        "curPage": "1",
    }
    leaf_ref = f"{BASE}/gzsx/zsd{SAMPLE_ZSD_LEAF}/"

    rows.append(post_question_list(s, label="zsd_leaf_base", data=leaf_data, referer=leaf_ref))
    for attr_id in (1, 2, 3, 4, 5):
        rows.append(
            post_question_list(
                s,
                label=f"attr_{attr_id}",
                data={**leaf_data, "quesAttributeId": str(attr_id)},
                referer=leaf_ref,
            )
        )
    for grade_id in (10, 11, 12):
        rows.append(
            post_question_list(
                s,
                label=f"grade_{grade_id}",
                data={**leaf_data, "learngrade": str(grade_id)},
                referer=leaf_ref,
            )
        )
    for term in (1, 2):
        rows.append(
            post_question_list(
                s,
                label=f"term_{term}",
                data={**leaf_data, "term": str(term)},
                referer=leaf_ref,
            )
        )

    # paperTypeId / paperTypeIds (paper source type)
    for pt in (6, 2, 9):
        rows.append(
            post_question_list(
                s,
                label=f"paperTypeId_{pt}",
                data={**leaf_data, "paperTypeId": str(pt)},
                referer=leaf_ref,
            )
        )

    # paperTypeIds: repeated key vs [] key
    pt_repeat: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("paperTypeIds", "6"),
        ("paperTypeIds", "2"),
    ]
    rows.append(post_question_list(s, label="paperTypeIds_repeat", data=pt_repeat, referer=leaf_ref))
    pt_bracket: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("paperTypeIds[]", "6"),
        ("paperTypeIds[]", "2"),
    ]
    rows.append(post_question_list(s, label="paperTypeIds_bracket", data=pt_bracket, referer=leaf_ref))

    # quesDiff (single) and quesDiffs (multi)
    rows.append(
        post_question_list(
            s,
            label="diff_single_2",
            data={**leaf_data, "quesDiff": "2"},
            referer=leaf_ref,
        )
    )
    diff_repeat: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("quesDiffs", "1"),
        ("quesDiffs", "2"),
    ]
    rows.append(post_question_list(s, label="diffs_repeat", data=diff_repeat, referer=leaf_ref))
    diff_bracket: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("quesDiffs[]", "1"),
        ("quesDiffs[]", "2"),
    ]
    rows.append(post_question_list(s, label="diffs_bracket", data=diff_bracket, referer=leaf_ref))

    # categoryIds multi-select: in this probe, naive categoryIds does NOT change total (likely ignored).
    cat_repeat: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("categoryIds", str(SAMPLE_ZSD_SIBLING_A)),
        ("categoryIds", str(SAMPLE_ZSD_SIBLING_B)),
    ]
    rows.append(post_question_list(s, label="categoryIds_repeat", data=cat_repeat, referer=leaf_ref))

    # 3) Multi-select serialization: quesTypes (repeat key vs [] key).
    # Choose a combination that should reduce total if honored.
    rows.append(
        post_question_list(
            s,
            label="type_single_2701",
            data={**leaf_data, "quesType": "2701"},
            referer=leaf_ref,
        )
    )
    # repeated key: quesTypes=2701&quesTypes=2702
    multi_repeat: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("quesTypes", "2701"),
        ("quesTypes", "2702"),
    ]
    rows.append(
        post_question_list(
            s,
            label="types_repeat",
            data=multi_repeat,
            referer=leaf_ref,
        )
    )
    # bracket key: quesTypes[]=2701&quesTypes[]=2702
    multi_bracket: list[tuple[str, str]] = list(leaf_data.items()) + [
        ("quesTypes[]", "2701"),
        ("quesTypes[]", "2702"),
    ]
    rows.append(
        post_question_list(
            s,
            label="types_bracket",
            data=multi_bracket,
            referer=leaf_ref,
        )
    )

    print_table(rows)

    # Also dump the JSON rows for later diffing (optional).
    out = [r.__dict__ for r in rows]
    print("\njson:", json.dumps(out, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
