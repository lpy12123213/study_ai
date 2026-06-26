# Zujuan Visitor Cookie File Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore question crawling when `zujuan.xkw.com` returns a JavaScript challenge page by replaying the user's own Netscape/curl visitor cookie file as an unmodified raw `Cookie` header.

**Architecture:** Keep the public question-library flow unchanged. Add a focused cookie-file parser in the Zujuan integration, load it during crawler initialization through `ZUJUAN_COOKIE_FILE`, and preserve constructor/env-cookie precedence. Continue detecting challenge pages rather than attempting to solve them, and expose configuration guidance when replay is unavailable or stale.

**Tech Stack:** Python 3.13, FastAPI backend, `httpx.AsyncClient`, `unittest`.

---

### Task 1: Parse Netscape visitor cookies into a raw header

**Files:**
- Modify: `backend/integrations/crawler/zujuan/cookies.py`
- Test: `backend/tests/test_zujuan_request_building.py`

- [ ] **Step 1: Write the failing parser test**

Add a test that writes a Netscape cookie file containing a normal row, a `#HttpOnly_` row, an expired row, and a value containing `=`. Assert the parser preserves row order and values in `name=value; ...` form while returning cookie and expired-row counts without exposing values.

- [ ] **Step 2: Run the parser test and verify RED**

Run: `python -m unittest backend.tests.test_zujuan_request_building.TestZujuanCookieFileReplay`

Expected: FAIL because `build_cookie_header_from_netscape_file` does not exist.

- [ ] **Step 3: Implement the parser**

Add a frozen result dataclass and `build_cookie_header_from_netscape_file(path, include_expired=True, now=None)`. Preserve the capture rows exactly enough to create a browser-shaped raw header, including expired rows by default because the verified `zujuancrawl` replay depends on raw-header semantics rather than a normalized CookieJar.

- [ ] **Step 4: Run the parser test and verify GREEN**

Run: `python -m unittest backend.tests.test_zujuan_request_building.TestZujuanCookieFileReplay`

Expected: PASS.

### Task 2: Load the configured cookie file during crawler initialization

**Files:**
- Modify: `backend/integrations/crawler/zujuan/client.py`
- Test: `backend/tests/test_zujuan_request_building.py`

- [ ] **Step 1: Write the failing initialization test**

Configure `ZUJUAN_COOKIE_FILE` with a temporary Netscape file, keep legacy env-cookie and browser-bootstrap toggles disabled, initialize `ZujuanCrawler`, and assert both `crawler.cookies` and the `httpx` client use the raw header.

- [ ] **Step 2: Run the initialization test and verify RED**

Run: `python -m unittest backend.tests.test_zujuan_request_building.TestZujuanCookieFileReplay.test_initialize_loads_configured_visitor_cookie_file`

Expected: FAIL because initialization ignores `ZUJUAN_COOKIE_FILE`.

- [ ] **Step 3: Implement minimal initialization support**

Resolve relative configured paths from the repository root, load only when no explicit constructor or enabled env cookie already exists, log counts rather than cookie values, and continue safely in visitor mode when the configured file cannot be read.

- [ ] **Step 4: Run the initialization test and verify GREEN**

Run: `python -m unittest backend.tests.test_zujuan_request_building.TestZujuanCookieFileReplay.test_initialize_loads_configured_visitor_cookie_file`

Expected: PASS.

### Task 3: Configure and verify the real question-library chain

**Files:**
- Modify: `.env` (ignored local configuration only)
- Modify: `.env.example`
- Modify: `backend/integrations/crawler/zujuan/search.py`
- Test: `backend/tests/test_zujuan_request_building.py`

- [ ] **Step 1: Add a failing guidance assertion**

Extend the blocker-path test to assert JavaScript challenge instructions name `ZUJUAN_COOKIE_FILE` and describe replaying the user's own visitor cookie file rather than requiring account login.

- [ ] **Step 2: Run the guidance test and verify RED**

Run: `python -m unittest backend.tests.test_zujuan_request_building.TestZujuanChallengeGuidance`

Expected: FAIL because current guidance only points to the login script.

- [ ] **Step 3: Update guidance and configuration**

Document `ZUJUAN_COOKIE_FILE` in `.env.example`, update the challenge error guidance, and set the ignored local `.env` path to the existing verified visitor-cookie capture in the sibling `zujuancrawl` workspace. Do not copy or commit cookie values.

- [ ] **Step 4: Run focused regression tests**

Run: `python -m unittest backend.tests.test_zujuan_request_building backend.tests.test_zujuan_client_utils backend.tests.test_question_library_crawl`

Expected: PASS with zero failures.

- [ ] **Step 5: Run low-frequency live verification**

Start a fresh process so `.env` is reloaded, call the same `get_crawler(...).search_by_keyword(...)` path used by the question-library runner with a one-page, small-limit request, and verify `success=true`, a non-zero count, non-empty question IDs, and non-empty stems. Do not print cookie values.

- [ ] **Step 6: Check only touched-file whitespace and diff**

Run: `git diff --check -- backend/integrations/crawler/zujuan/cookies.py backend/integrations/crawler/zujuan/client.py backend/integrations/crawler/zujuan/search.py backend/tests/test_zujuan_request_building.py .env.example docs/superpowers/plans/2026-06-21-zujuan-cookie-file-replay.md`

Expected: no output and exit code 0.
