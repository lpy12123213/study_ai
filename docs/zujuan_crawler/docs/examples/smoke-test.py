import base64
import re
import subprocess
from datetime import datetime, timezone

import requests


BASE = "https://zujuan.xkw.com"
STATIC = "https://staticzujuan.xkw.com"

# A stable, visitor-accessible sample (as of 2026-02-08).
SAMPLE_BANK_ID = 11
SAMPLE_COURSE_ID = 27
SAMPLE_ZJ_ROOT = 135303
SAMPLE_ZSD_LEAF = 28102


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def looks_like_js_challenge(text: str) -> bool:
    t = text.lower()
    return (
        "<body onload=\"check()\">" in t
        or "alicfw_gfver" in t
        or "aliyun_waf_aa" in t
        or "acw_sc__v2" in t
    )


def looks_like_login_page(text: str) -> bool:
    t = text.lower()
    return "login.css" in t or "login-popup.css" in t


def short_body(text: str, n: int = 200) -> str:
    s = text.replace("\r", "").replace("\n", "\\n")
    return s[:n]


def ok(label: str):
    print(f"[PASS] {label}")


def fail(label: str, reason: str):
    print(f"[FAIL] {label}: {reason}")


def check_base(session: requests.Session) -> tuple[bool, str | None]:
    label = "GET /zujuan-api/base"
    r = session.get(f"{BASE}/zujuan-api/base", timeout=30, allow_redirects=False)
    ct = (r.headers.get("Content-Type") or "").lower()
    text = r.text if "text" in ct or "javascript" in ct or "plain" in ct else ""

    if r.status_code != 200:
        fail(label, f"status={r.status_code}")
        return False, None
    if looks_like_js_challenge(text):
        fail(label, f"js_challenge body_prefix={short_body(text)}")
        return False, None
    if not r.text.lstrip().startswith("var edu="):
        fail(label, f"unexpected body_prefix={short_body(r.text)}")
        return False, None
    ok(label)
    return True, r.text


def check_base_province(session: requests.Session) -> bool:
    label = "GET /zujuan-api/base-province"
    r = session.get(f"{BASE}/zujuan-api/base-province", timeout=30, allow_redirects=False)
    if r.status_code != 200:
        fail(label, f"status={r.status_code}")
        return False
    if not r.text.lstrip().startswith("var province_list="):
        fail(label, f"unexpected body_prefix={short_body(r.text)}")
        return False
    ok(label)
    return True


def check_cdn_tree(session: requests.Session, cdn_domain: str) -> bool:
    label = "GET cdn tree lk_{bankId}.json"
    url = f"{cdn_domain}/zujuan/tree/lk_{SAMPLE_BANK_ID}.json"
    r = session.get(url, timeout=30, allow_redirects=False)
    if r.status_code != 200:
        fail(label, f"status={r.status_code} url={url}")
        return False
    ct = (r.headers.get("Content-Type") or "").lower()
    if "json" not in ct:
        fail(label, f"unexpected ct={ct} body_prefix={short_body(r.text)}")
        return False
    try:
        data = r.json()
    except Exception:
        fail(label, f"not json body_prefix={short_body(r.text)}")
        return False
    if not isinstance(data, dict) or "children" not in data:
        fail(label, f"unexpected shape type={type(data)} keys={(list(data.keys())[:10] if isinstance(data, dict) else None)}")
        return False
    ok(label)
    return True


def check_paper_list(session: requests.Session) -> bool:
    label = "POST /zujuan-api/paper/list"
    r = session.post(
        f"{BASE}/zujuan-api/paper/list",
        headers={"Referer": f"{BASE}/shijuan/"},
        data={
            "pageName": "shijuan",
            "bankId": str(SAMPLE_BANK_ID),
            "learnGradeId": "0",
            "paperTypeId": "0",
            "schoolId": "0",
            "provinceId": "-1",
            "paperYear": "0",
            "paperLevelId": "0",
            "newCategoryId": "0",
            "isFreshPaper": "0",
            "orderBy": "0",
            "curPage": "1",
        },
        timeout=30,
        allow_redirects=False,
    )
    if r.status_code != 200:
        fail(label, f"status={r.status_code}")
        return False
    try:
        payload = r.json()
    except Exception:
        fail(label, f"not json ct={r.headers.get('Content-Type')} body_prefix={short_body(r.text)}")
        return False
    code = str(payload.get("code"))
    if code not in ("0", "200"):
        fail(label, f"unexpected code={code}")
        return False
    html = ((payload.get("data") or {}).get("html") or "")
    if f"/{SAMPLE_BANK_ID}p" not in html:
        fail(label, "data.html missing /{bankId}p... links")
        return False
    ok(label)
    return True


def check_question_list(session: requests.Session) -> tuple[bool, str | None]:
    label = "POST /zujuan-api/question/list"
    r = session.post(
        f"{BASE}/zujuan-api/question/list",
        headers={"Referer": f"{BASE}/gzsx/zj{SAMPLE_ZJ_ROOT}/"},
        data={
            "pageName": "zhangjie",
            "bankId": str(SAMPLE_BANK_ID),
            "courseId": str(SAMPLE_COURSE_ID),
            "categoryId": str(SAMPLE_ZJ_ROOT),
            "provinceId": "-1",
            "orderBy": "2",
            "quesType": "0",
            "quesDiff": "0",
            "quesYear": "0",
            "curPage": "1",
        },
        timeout=30,
        allow_redirects=False,
    )
    if r.status_code != 200:
        fail(label, f"status={r.status_code}")
        return False, None
    try:
        payload = r.json()
    except Exception:
        fail(label, f"not json ct={r.headers.get('Content-Type')} body_prefix={short_body(r.text)}")
        return False, None
    code = str(payload.get("code"))
    if code not in ("0", "200"):
        fail(label, f"unexpected code={code}")
        return False, None
    html = ((payload.get("data") or {}).get("html") or "")
    if 'questionid="' not in html:
        fail(label, "data.html missing questionid attributes")
        return False, None

    # Extract one formula hash (optional)
    m = re.search(r"/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg)", html, re.I)
    formula_hash = m.group(1).lower() if m else None

    ok(label)
    return True, formula_hash


def check_question_list_zsd_leaf_for_formula(session: requests.Session) -> str | None:
    label = "POST /zujuan-api/question/list (zsd leaf, for formula)"
    for cur_page in (1, 2, 3):
        r = session.post(
            f"{BASE}/zujuan-api/question/list",
            headers={"Referer": f"{BASE}/gzsx/zsd{SAMPLE_ZSD_LEAF}/"},
            data={
                "pageName": "zsd",
                "bankId": str(SAMPLE_BANK_ID),
                "courseId": str(SAMPLE_COURSE_ID),
                "categoryId": str(SAMPLE_ZSD_LEAF),
                "provinceId": "-1",
                "orderBy": "2",
                "quesType": "0",
                "quesDiff": "0",
                "quesYear": "0",
                "curPage": str(cur_page),
            },
            timeout=30,
            allow_redirects=False,
        )
        if r.status_code != 200:
            fail(label, f"status={r.status_code} curPage={cur_page}")
            return None
        try:
            payload = r.json()
        except Exception:
            fail(label, f"not json ct={r.headers.get('Content-Type')} body_prefix={short_body(r.text)}")
            return None
        code = str(payload.get("code"))
        if code not in ("0", "200"):
            fail(label, f"unexpected code={code}")
            return None
        html = ((payload.get("data") or {}).get("html") or "")
        m = re.search(r"/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg)", html, re.I)
        if m:
            ok(label)
            return m.group(1).lower()

    print(f"[WARN] {label}: no formula hash found in first 3 pages; skipping formula chain")
    return None


def check_child_node(session: requests.Session) -> bool:
    label = "GET /zujuan-api/category/child_node"
    r = session.get(
        f"{BASE}/zujuan-api/category/child_node",
        params={"bankId": SAMPLE_BANK_ID, "type": 0, "categoryId": SAMPLE_ZJ_ROOT, "c2k": "false"},
        headers={"Referer": f"{BASE}/gzsx/zj{SAMPLE_ZJ_ROOT}/"},
        timeout=30,
        allow_redirects=False,
    )
    if r.status_code != 200:
        fail(label, f"status={r.status_code}")
        return False
    try:
        data = r.json()
    except Exception:
        fail(label, f"not json ct={r.headers.get('Content-Type')} body_prefix={short_body(r.text)}")
        return False
    if not isinstance(data, list):
        fail(label, f"expected list got {type(data)}")
        return False
    ok(label)
    return True


def check_formula_chain(session: requests.Session, formula_hash: str) -> bool:
    label = "formula png/mml + optional pandoc"
    png_url = f"{STATIC}/quesimg/Upload/formula/{formula_hash}.png"
    mml_url = f"{STATIC}/quesimg/Upload/formula/{formula_hash}.mml"

    r = session.get(png_url, timeout=30, allow_redirects=False)
    if r.status_code != 200 or "image" not in (r.headers.get("Content-Type") or "").lower():
        fail(label, f"png fetch failed status={r.status_code} ct={r.headers.get('Content-Type')}")
        return False

    r = session.get(mml_url, timeout=30, allow_redirects=False)
    if r.status_code != 200:
        fail(label, f"mml fetch failed status={r.status_code}")
        return False
    raw = (r.content or b"").strip()
    try:
        mathml_xml = base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception as e:
        fail(label, f"mml base64 decode error: {e}")
        return False
    if "<math" not in mathml_xml:
        fail(label, f"mml decoded but missing <math, prefix={mathml_xml[:80]!r}")
        return False

    # pandoc is optional; skip if not available.
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
        p = subprocess.run(
            ["pandoc", "-f", "html", "-t", "latex"],
            input=mathml_xml,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
            timeout=10,
        )
        out = p.stdout.strip()
        if not out:
            fail(label, "pandoc output empty")
            return False
    except FileNotFoundError:
        # pandoc not installed; this is acceptable for a basic crawl.
        pass
    except Exception as e:
        fail(label, f"pandoc convert failed: {e}")
        return False

    ok(label)
    return True


def main():
    print("zujuan smoke test:", now_iso())
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    # Keep this light: a few requests only.
    ok_base, base_text = check_base(s)
    check_base_province(s)
    check_paper_list(s)
    ok_q, formula_hash = check_question_list(s)
    check_child_node(s)

    if ok_base and base_text:
        m = re.search(r"cdn_domain='([^']+)'", base_text)
        if m:
            check_cdn_tree(s, m.group(1))
        else:
            print("[WARN] cdn_domain not found in /zujuan-api/base; skipping cdn tree check")

    if ok_q and not formula_hash:
        # Some pages might not contain formula images; use a known formula-rich shard as fallback.
        formula_hash = check_question_list_zsd_leaf_for_formula(s)

    if ok_q and formula_hash:
        check_formula_chain(s, formula_hash)


if __name__ == "__main__":
    main()
