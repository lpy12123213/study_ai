"""
组卷网爬虫（无登录版）
仅返回题号和元数据，不抓取题干/答案。
核心思路：
- 使用公开的 /zujuan-api/search (SSE) 获取推荐的知识点/筛选参数
- 使用 /zujuan-api/question/list POST 拉取题目列表（返回 HTML），从中解析题号
- 使用 curl + Playwright获取的cookie 获取题目详情
- 支持导出题目到组卷网题篮（需要登录）
"""
from __future__ import annotations

import asyncio
import hashlib
import html as html_module
import json
import os
import re
import subprocess
import time
import urllib.parse
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.config import DIFFICULTY_QUERY_MODE
from backend.subjects import (
    DEFAULT_DIFFICULTY,
    DIFFICULTY_LEVELS,
    SUBJECTS,
    normalize_difficulty,
    resolve_subject,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

CSRF_TOKEN_PATTERN = re.compile(
    r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', re.IGNORECASE
)


async def _get_cookies_with_playwright() -> str:
    """使用Playwright访问页面获取cookie（无需登录）"""
    try:
        from playwright.sync_api import sync_playwright
        import concurrent.futures

        def _sync_get_cookies():
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                # 访问任意页面触发cookie生成
                page.goto("https://zujuan.xkw.com/", timeout=20000)
                page.wait_for_timeout(1000)  # 减少等待时间以加快初始化

                # 获取cookies
                cookies = context.cookies()
                browser.close()

                # 转换为cookie字符串
                return "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        # 在线程池中运行同步版本（避免Windows asyncio subprocess问题）
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            cookie_str = await loop.run_in_executor(pool, _sync_get_cookies)
        return cookie_str
    except Exception as e:
        print(f"Playwright获取cookie失败: {e}")
        return ""


def _load_env_login() -> Dict[str, Any]:
    """从 .env 文件加载登录信息"""
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

    if not os.path.exists(env_file):
        return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False}

    try:
        env_data: Dict[str, str] = {}
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if (
                    (value.startswith('"') and value.endswith('"'))
                    or (value.startswith("'") and value.endswith("'"))
                ):
                    value = value[1:-1]
                env_data[key] = value

        user_id = (env_data.get("ZUJUAN_USER_ID") or "").strip() or None
        csrf_token = (env_data.get("ZUJUAN_CSRF_TOKEN") or "").strip() or None
        cookies = env_data.get("ZUJUAN_COOKIES", "") or ""

        return {
            "cookies": cookies,
            "user_id": user_id,
            "csrf_token": csrf_token,
            "is_logged_in": bool(user_id),
        }
    except Exception as e:
        print(f"读取.env失败: {e}")
        return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False}


def _parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies


def _build_cookie_string(cookies: Dict[str, str]) -> str:
    return "; ".join([f"{k}={v}" for k, v in cookies.items() if k and v])


_ANTIBOT_COOKIE_KEYS = {"aliyungf_tc", "acw_tc", "acw_sc__v2"}
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ANTIBOT_CACHE_FILE = str(_PROJECT_ROOT / ".local" / "cache" / "zujuan_antibot_cookies.json")
_ANTIBOT_CACHE_FILE_LEGACY = str(_PROJECT_ROOT / ".cache" / "zujuan_antibot_cookies.json")
_ANTIBOT_CACHE_TTL_SECONDS = 6 * 60 * 60


def _load_antibot_cookie_cache() -> str:
    try:
        for candidate in (_ANTIBOT_CACHE_FILE, _ANTIBOT_CACHE_FILE_LEGACY):
            if not os.path.exists(candidate):
                continue
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookie_str = (data.get("cookies") or "").strip()
            ts = float(data.get("ts") or 0)
            if not cookie_str:
                continue
            if ts and (time.time() - ts) > _ANTIBOT_CACHE_TTL_SECONDS:
                continue
            return cookie_str
        return ""
    except Exception:
        return ""


def _save_antibot_cookie_cache(cookie_str: str) -> None:
    try:
        cookie_str = (cookie_str or "").strip()
        if not cookie_str:
            return
        os.makedirs(os.path.dirname(_ANTIBOT_CACHE_FILE), exist_ok=True)
        with open(_ANTIBOT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookie_str, "ts": time.time()}, f, ensure_ascii=False, indent=2)
    except Exception:
        return


async def _fetch_csrf_token_from_page(cookies: str) -> Optional[str]:
    """
    ä½¿ç”¨å­˜å‚¨çš„ cookie èŽ·å–é¡µé¢ä¸­çš„CSRF token
    ç»„å·ç½‘ APIéœ€è¦ RequestVerification headerï¼Œå€¼æ¥è‡ªé¡µé¢çš„éšè—å­—æ®µ
    """
    if not cookies:
        return None

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Cookie": cookies,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://zujuan.xkw.com/",
    }

    try:
        # 用站点首页获取 CSRF token，避免绑定到某个具体学科入口（如 gzsx）
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get("https://zujuan.xkw.com/", headers=headers)
            if resp.status_code != 200:
                return None

            m = CSRF_TOKEN_PATTERN.search(resp.text)
            if m:
                return m.group(1)
    except Exception as e:
        print(f"èŽ·å–CSRF token å¤±è´¥: {e}")

    return None

    try:
        env_data = {}
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_data[key.strip()] = value.strip()

        user_id = env_data.get("ZUJUAN_USER_ID")
        csrf_token = env_data.get("ZUJUAN_CSRF_TOKEN")
        cookies = env_data.get("ZUJUAN_COOKIES", "")

        return {
            "cookies": cookies,
            "user_id": user_id,
            "csrf_token": csrf_token,
            "is_logged_in": bool(user_id)
        }
    except Exception as e:
        print(f"读取.env失败: {e}")
        return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False}


async def _get_login_session_with_playwright() -> Dict[str, Any]:
    """
    ????????????????cookie??CSRF token???????Playwright
    """
    env_session = _load_env_login()
    if env_session.get("is_logged_in") and env_session.get("cookies"):
        csrf_token = await _fetch_csrf_token_from_page(env_session["cookies"])
        if csrf_token:
            env_session["csrf_token"] = csrf_token
            return env_session
        else:
            # 使用 .env 中已保存的 CSRF token / cookie（即使刷新失败）
            return env_session

    try:
        from playwright.sync_api import sync_playwright
        import concurrent.futures

        def _sync_get_session():
            with sync_playwright() as p:
                user_data_dir = os.path.join(os.path.dirname(__file__), ".playwright_data")
                os.makedirs(user_data_dir, exist_ok=True)

                browser = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                )
                page = browser.pages[0] if browser.pages else browser.new_page()

                page.goto("https://zujuan.xkw.com/gzsx/", timeout=30000)
                page.wait_for_timeout(2000)

                cookies = browser.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                user_id = None
                for c in cookies:
                    if c['name'] == 'userId':
                        user_id = c['value']
                        break

                csrf_token = None
                try:
                    csrf_token = page.evaluate('''
                        () => {
                            const input = document.querySelector('input[name="__RequestVerificationToken"]');
                            return input ? input.value : null;
                        }
                    ''')
                except Exception:
                    csrf_token = None

                if not csrf_token:
                    for c in cookies:
                        if c['name'] == '__RequestVerificationToken':
                            csrf_token = c['value']
                            break

                browser.close()

                return {
                    "cookies": cookie_str,
                    "user_id": user_id,
                    "csrf_token": csrf_token,
                    "is_logged_in": user_id is not None
                }

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            session = await loop.run_in_executor(pool, _sync_get_session)
        return session
    except Exception as e:
        print(f"????????: {e}")
        return {"cookies": "", "user_id": None, "csrf_token": None, "is_logged_in": False}



def _extract_js_var_json(text: str, var_name: str) -> Optional[str]:
    """
    从类似 `var xxx=[...]` / `var xxx={...}` 的 JS 文本中提取出 `xxx` 的 JSON 值。

    说明：/zujuan-api/base 不是纯 JSON，通常会包含 `var edu=[...]` 及其他内容，
    直接用正则截到末尾会导致 json.loads 失败。这里用简单的括号匹配截取完整值。
    """
    marker = f"var {var_name}="
    idx = text.find(marker)
    if idx < 0:
        return None

    start = None
    open_ch = None
    for ch in ("[", "{"):
        pos = text.find(ch, idx + len(marker))
        if pos >= 0 and (start is None or pos < start):
            start = pos
            open_ch = ch

    if start is None or open_ch is None:
        return None

    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
                continue
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == open_ch:
            depth += 1
            continue
        if ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def _parse_base_json(text: str) -> Optional[List[Dict[str, Any]]]:        
    """解析 /zujuan-api/base 中的 `var edu=[...]`。"""
    raw = _extract_js_var_json(text, "edu")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _parse_province_list_json(text: str) -> Optional[List[Dict[str, Any]]]:
    """解析 /zujuan-api/base-province 中的 `var province_list=[...]`。"""
    raw = _extract_js_var_json(text, "province_list")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except Exception:
        return None


PROVINCE_UNLIMITED_ALIASES = {
    "不限",
    "不限地区",
    "不限省份",
    "全国",
    "全國",
    "全部",
    "all",
    "ALL",
}


def _normalize_province_name(name: str) -> str:
    """Normalize province names for matching (e.g. 北京市 -> 北京)."""
    s = re.sub(r"\\s+", "", (name or "").strip())
    if not s:
        return ""
    if s in PROVINCE_UNLIMITED_ALIASES:
        return "不限"
    suffixes = [
        "特别行政区",
        "特别行政區",
        "维吾尔自治区",
        "維吾爾自治區",
        "壮族自治区",
        "壯族自治區",
        "回族自治区",
        "回族自治區",
        "自治区",
        "自治區",
        "省",
        "市",
    ]
    for suffix in suffixes:
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    return s


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if not s:
            return default
        return int(s)
    except Exception:
        return default


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


class ZujuanCrawler:
    """
    题目检索爬虫：使用Playwright自动获取cookie绕过反爬。
    支持多学科配置。
    """

    def __init__(self, cookies: str = "", subject: str = "高中数学"):
        self.base_url = "https://zujuan.xkw.com"
        self.client: Optional[httpx.AsyncClient] = None
        self.user_agent = DEFAULT_USER_AGENT
        self.cookies = cookies  # 用于绕过反爬的cookie
        self.ques_type_map: Dict[str, int] = {}
        self.learn_grade_map: Dict[str, int] = {}
        self.learn_grade_id_to_name: Dict[int, str] = {}
        self.paper_types_by_grade: Dict[int, List[Dict[str, Any]]] = {}
        self.paper_type_map: Dict[str, int] = {}
        self.category_map: Dict[str, str] = {}
        self.textbook_versions: List[Dict[str, str]] = []
        self.textbook_version_map: Dict[str, str] = {}
        self.question_types: List[Dict[str, Any]] = []
        self.provinces: List[Dict[str, Any]] = []
        self.province_name_to_id: Dict[str, int] = {}
        self._base_meta_data: Optional[List[Dict[str, Any]]] = None
        self._bank_meta_loaded_for: Optional[int] = None
        self._cache: "OrderedDict[str, Tuple[float, float, Any]]" = OrderedDict()
        self._cache_max_entries = 256

        # 学科配置
        self.subject = subject
        self._load_subject_config()

    def _load_subject_config(self):
        """加载学科配置"""
        try:
            import sys
            from pathlib import Path
            sys.path.append(str(Path(__file__).parent.parent))
            from backend.subjects import get_subject_config
            config = get_subject_config(self.subject)
            self.bank_id = config["bank_id"]
            self.category_id = config["category_id"]
            self.edu_id = config["edu_id"]
        except Exception:
            # 默认高中数学
            self.bank_id = 11
            self.category_id = "100693"
            self.edu_id = 3

    def set_subject(self, subject: str):
        """切换学科"""
        self.subject = subject
        self._load_subject_config()
        # bankId 变化后，清空与学科绑定的元数据缓存
        self._bank_meta_loaded_for = None
        self.learn_grade_map = {}
        self.learn_grade_id_to_name = {}
        self.paper_types_by_grade = {}
        self.paper_type_map = {}
        self.category_map = {}
        self.textbook_versions = []
        self.textbook_version_map = {}
        self.question_types = []

    def _apply_search_constraints(
        self,
        subject: str,
        edu_level: str,
        difficulty: str,
        require_difficulty: bool,
        strict_subject: bool,
    ) -> Tuple[str, str]:
        resolved_subject = (subject or "").strip() or self.subject
        resolved_subject = resolve_subject(
            resolved_subject,
            edu_level=(edu_level or "").strip(),
            strict=strict_subject,
        )
        if resolved_subject != self.subject:
            self.set_subject(resolved_subject)

        normalized_difficulty = (difficulty or "").strip()
        if require_difficulty and not normalized_difficulty:
            normalized_difficulty = DEFAULT_DIFFICULTY
        if normalized_difficulty:
            normalized_difficulty = normalize_difficulty(normalized_difficulty, strict=True)
        return resolved_subject, normalized_difficulty

    async def initialize(self):
        """初始化 HTTP 客户端，自动获取cookie。"""
        # 已初始化则复用（MCP 模式下避免每次工具调用都做一次网络/浏览器初始化）
        if self.client is not None:
            return

        # 1) 先加载 .env Cookie（通常包含登录态）
        env_session = _load_env_login()
        env_cookies = (env_session.get("cookies") or "").strip()
        is_logged_in = bool(env_session.get("is_logged_in"))

        if env_cookies:
            self.cookies = env_cookies

        env_cookie_dict = _parse_cookie_string(self.cookies)

        # 2) 优先合并缓存的反爬 Cookie（避免每次启动都跑一次 Playwright）
        cached_antibot = _load_antibot_cookie_cache()
        if cached_antibot:
            cached_dict = _parse_cookie_string(cached_antibot)
            cached_dict.update(env_cookie_dict)  # 以 .env Cookie 为准覆盖
            self.cookies = _build_cookie_string(cached_dict)
            env_cookie_dict = cached_dict

        async def cookie_can_access_api(cookie_str: str) -> bool:
            if not cookie_str:
                return False
            try:
                async with httpx.AsyncClient(
                    headers={"User-Agent": self.user_agent, "Cookie": cookie_str},
                    timeout=10.0,
                ) as c:
                    resp = await c.get(f"{self.base_url}/zujuan-api/base")
                return resp.status_code == 200 and _parse_base_json(resp.text) is not None
            except Exception:
                return False

        missing_antibot = _ANTIBOT_COOKIE_KEYS - set(env_cookie_dict.keys())
        if missing_antibot or (self.cookies and not await cookie_can_access_api(self.cookies)):
            # 缺失/过期：用 Playwright 获取最新的反爬 Cookie，再与 .env Cookie 合并
            print("正在使用Playwright刷新反爬cookie...")
            base_cookie_str = await _get_cookies_with_playwright()
            if base_cookie_str:
                _save_antibot_cookie_cache(base_cookie_str)
                base_cookie_dict = _parse_cookie_string(base_cookie_str)
                base_cookie_dict.update(env_cookie_dict)  # 以 .env Cookie 为准覆盖
                self.cookies = _build_cookie_string(base_cookie_dict)
                env_cookie_dict = base_cookie_dict

        # 兜底：如果仍没有 cookie，再用 Playwright 获取
        if not self.cookies:
            print("正在使用Playwright获取cookie...")
            self.cookies = await _get_cookies_with_playwright()
            if self.cookies:
                print(f"Cookie获取成功: {self.cookies[:50]}...")
            else:
                print("Cookie获取失败，部分功能可能受限")
        else:
            missing_antibot = _ANTIBOT_COOKIE_KEYS - set(_parse_cookie_string(self.cookies).keys())
            if is_logged_in:
                print("使用登录Cookie")
            elif env_cookies:
                print("使用.env Cookie")
            else:
                print("使用反爬Cookie" if not missing_antibot else "使用Cookie(可能不完整)")

        client_kwargs = dict(
            headers={
                "User-Agent": self.user_agent,
                "Cookie": self.cookies or "",
            },
            timeout=30.0,
        )
        try:
            self.client = httpx.AsyncClient(http2=True, **client_kwargs)
        except ImportError:
            # http2 需要额外依赖（h2）；缺失时自动降级
            self.client = httpx.AsyncClient(**client_kwargs)
        print("HTTP 客户端初始化完成")

    async def _ensure_base_meta_loaded(self) -> None:
        """确保题型映射已加载（按需加载，避免初始化阻塞导致 MCP 首次调用过慢）。"""
        if self.ques_type_map:
            return
        await self._load_base_meta()

    def _set_provinces_from_list(self, province_list: List[Dict[str, Any]]) -> None:
        provinces: List[Dict[str, Any]] = []
        name_to_id: Dict[str, int] = {}
        seen_ids: set[int] = set()

        for item in province_list or []:
            if not isinstance(item, dict):
                continue

            pid = _safe_int(
                item.get("id")
                or item.get("ID")
                or item.get("Id")
                or item.get("province_id")
                or item.get("provinceId")
                or item.get("ProvinceId")
                or item.get("ProvinceID"),
                0,
            )
            pname = (
                item.get("name")
                or item.get("Name")
                or item.get("province_name")
                or item.get("provinceName")
                or ""
            )
            pname = str(pname).strip()
            if not pname:
                continue

            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            provinces.append({"id": pid, "name": pname})

            raw_key = re.sub(r"\\s+", "", pname)
            norm_key = _normalize_province_name(pname)
            if raw_key:
                name_to_id[raw_key] = pid
            if norm_key:
                name_to_id[norm_key] = pid

        self.provinces = provinces
        self.province_name_to_id = name_to_id

    async def _ensure_province_meta_loaded(self) -> None:
        """Load province list used for `province` name resolution."""
        if self.provinces and self.province_name_to_id:
            return

        cached = self._cache_get("meta:provinces")
        if isinstance(cached, list):
            self._set_provinces_from_list(cached)  # type: ignore[arg-type]
            return

        if not self.client:
            return

        try:
            resp = await self.client.get(f"{self.base_url}/zujuan-api/base-province")
            data = _parse_province_list_json(resp.text)
            if not data:
                return
            self._cache_set("meta:provinces", data, ttl=12 * 60 * 60)
            self._set_provinces_from_list(data)
        except Exception:
            return

    async def _resolve_province_id(self, province: str) -> Optional[int]:
        """Resolve a province name (e.g. 北京/北京市) into province_id.

        Returns:
            - int: resolved province_id (including -1 for "不限")
            - None: cannot resolve (unknown name or meta unavailable)
        """
        raw = (province or "").strip()
        if not raw:
            return None

        raw_compact = re.sub(r"\\s+", "", raw)
        if raw_compact in PROVINCE_UNLIMITED_ALIASES:
            return -1

        # Allow passing numeric ID via `province` to reduce caller friction.
        if raw_compact.isdigit():
            try:
                return int(raw_compact)
            except Exception:
                return None

        norm = _normalize_province_name(raw_compact)
        if norm == "不限":
            return -1

        await self._ensure_province_meta_loaded()
        if not self.province_name_to_id:
            return None

        if raw_compact in self.province_name_to_id:
            return self.province_name_to_id[raw_compact]
        if norm and norm in self.province_name_to_id:
            return self.province_name_to_id[norm]

        # Fuzzy fallback: compare normalized names.
        for p in self.provinces or []:
            pname = (p.get("name") or "").strip()
            if not pname:
                continue
            if _normalize_province_name(pname) == norm:
                return _safe_int(p.get("id"), 0)

        return None

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None
        print("HTTP 客户端已关闭")

    def _cache_get(self, key: str) -> Optional[Any]:
        item = self._cache.get(key)
        if not item:
            return None
        ts, ttl, value = item
        if ttl > 0 and (time.time() - ts) > ttl:
            try:
                del self._cache[key]
            except Exception:
                pass
            return None
        try:
            self._cache.move_to_end(key)
        except Exception:
            pass
        return value

    def _cache_set(self, key: str, value: Any, ttl: float) -> None:
        try:
            self._cache[key] = (time.time(), float(ttl or 0), value)
            self._cache.move_to_end(key)
            while len(self._cache) > int(self._cache_max_entries or 256):
                self._cache.popitem(last=False)
        except Exception:
            return

    def _find_bank_in_base_meta(self, bank_id: int) -> Optional[Dict[str, Any]]:
        bank_id = _safe_int(bank_id, 0)
        if not bank_id or not self._base_meta_data:
            return None
        for edu in self._base_meta_data:
            for bank in edu.get("QuesBankList", []) or []:
                if _safe_int(bank.get("ID"), 0) == bank_id:
                    return bank
        return None

    def _load_bank_meta_from_base(self) -> None:
        bank_id = _safe_int(getattr(self, "bank_id", 0), 0)
        if not bank_id or not self._base_meta_data:
            return
        if self._bank_meta_loaded_for == bank_id:
            return

        self.learn_grade_map = {}
        self.learn_grade_id_to_name = {}
        self.paper_types_by_grade = {}
        self.paper_type_map = {}
        self.category_map = {}
        self.textbook_versions = []
        self.textbook_version_map = {}
        self.question_types = []

        bank = self._find_bank_in_base_meta(bank_id)
        if not bank:
            self._bank_meta_loaded_for = bank_id
            return

        for q in bank.get("QuesTypeList", []) or []:
            name = (q.get("Name") or "").strip()
            qid = _safe_int(q.get("ID"), 0)
            if name and qid:
                self.question_types.append({"id": qid, "name": name})

        for g in bank.get("LearnGradeList", []) or []:
            gid = _safe_int(g.get("ID"), 0)
            gname = (g.get("Name") or "").strip()
            if gid and gname:
                self.learn_grade_map[gname] = gid
                self.learn_grade_id_to_name[gid] = gname

            paper_types = []
            for p in g.get("PaperTypeList", []) or []:
                pid = _safe_int(p.get("ID"), 0)
                pname = (p.get("Name") or "").strip()
                parent_id = _safe_int(p.get("ParentId") or p.get("ParentID"), 0)
                if pid and pname:
                    self.paper_type_map[pname] = pid
                    paper_types.append({"id": pid, "name": pname, "parent_id": parent_id})
            if gid and paper_types:
                self.paper_types_by_grade[gid] = paper_types

        for cat in bank.get("CategoryList", []) or []:
            cid = _safe_int(cat.get("ID"), 0)
            cname = (cat.get("Name") or "").strip()
            if cid and cname:
                self.category_map[cname] = str(cid)
                is_default_like = (
                    cname.endswith("综合库")
                    or _safe_int(cat.get("Type"), 0) == 1
                    or _safe_int(cat.get("knowledgeType"), 0) == 1
                )
                if is_default_like:
                    continue
                # 版本/教材库：常见为 Type=0 且带 qbmId
                if _safe_int(cat.get("qbmId"), 0) > 0 or _safe_int(cat.get("Type"), 0) == 0:
                    self.textbook_versions.append({"id": str(cid), "name": cname})
                    self.textbook_version_map[cname] = str(cid)

        self._bank_meta_loaded_for = bank_id

    async def _load_base_meta(self):
        """加载 /zujuan-api/base，构建题型、年级、版本等元数据缓存。"""
        if not self.client:
            return
        try:
            resp = await self.client.get(f"{self.base_url}/zujuan-api/base")    
            data = _parse_base_json(resp.text)
            if not data:
                return
            self._base_meta_data = data
            # 构建名称 -> ID 映射（简单/常见题型）
            for edu in data:
                for bank in edu.get("QuesBankList", []):
                    for q in bank.get("QuesTypeList", []):
                        name = q.get("Name")
                        if name:
                            self.ques_type_map[name] = q.get("ID", 0)
            self._load_bank_meta_from_base()
        except Exception:
            pass

    async def _ai_search(self, keyword: str) -> Dict[str, Any]:
        """
        调用 /zujuan-api/search SSE，返回推荐的检索参数。
        """
        if not self.client:
            return {"success": False, "error": "client not initialized"}        

        keyword = (keyword or "").strip()
        cache_key = f"sse:{keyword}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, dict) and cached.get("success") and cached.get("payload"):
            return cached

        url = f"{self.base_url}/zujuan-api/search"
        params = {"query": keyword}
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            "User-Agent": self.user_agent,
        }

        try:
            async with self.client.stream("GET", url, params=params, headers=headers) as r:
                end_payload = None
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:") and '"code":200' in line:       
                        try:
                            end_payload = json.loads(line.replace("data:", "").strip())
                            break
                        except Exception:
                            continue
                if not end_payload:
                    return {"success": False, "error": "未获取到搜索结果指引"}  
                result = {"success": True, "payload": end_payload}
                self._cache_set(cache_key, result, ttl=15 * 60)
                return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _ensure_bank_meta_loaded(self) -> None:
        if not self.client:
            return
        if self._base_meta_data is None:
            await self._load_base_meta()
            return
        self._load_bank_meta_from_base()

    def _resolve_textbook_category_id(self, textbook_version: str) -> str:
        version = (textbook_version or "").strip()
        if not version:
            return ""
        numeric = _safe_int(version, 0)
        if numeric > 0:
            return str(numeric)

        # 精确/包含匹配
        for name, cid in self.textbook_version_map.items():
            if version == name:
                return cid
        for name, cid in self.textbook_version_map.items():
            if version in name or name in version:
                return cid

        # 兜底：在全部分类里找
        for name, cid in self.category_map.items():
            if version == name:
                return cid
        for name, cid in self.category_map.items():
            if version in name or name in version:
                return cid
        return ""

    def _resolve_learn_grade_id(self, learn_grade: str, learn_grade_id: int = 0) -> int:
        if _safe_int(learn_grade_id, 0) > 0:
            return _safe_int(learn_grade_id, 0)
        name = (learn_grade or "").strip()
        if not name:
            return 0
        as_int = _safe_int(name, 0)
        if as_int > 0:
            return as_int
        if name in self.learn_grade_map:
            return self.learn_grade_map[name]
        for gname, gid in self.learn_grade_map.items():
            if gname and (name in gname or gname in name):
                return gid
        return 0

    def _normalize_elective_mode(self, elective_mode: str, exclude_elective: bool) -> str:
        """
        elective_mode:
        - include: 不做选修过滤
        - exclude: 排除选修/选必
        - only: 仅保留选修/选必
        """
        raw = (elective_mode or "").strip()
        if raw:
            lowered = raw.lower()
            if lowered in {"include", "all", "any"}:
                return "include"
            if lowered in {"exclude", "no", "without"}:
                return "exclude"
            if lowered in {"only", "require", "must"}:
                return "only"
            # 中文兼容
            if raw in {"不限", "包含", "全部"}:
                return "include"
            if raw in {"排除", "不含", "去除", "排除选修", "不含选修"}:
                return "exclude"
            if raw in {"仅选修", "只选修", "只要选修", "仅选择性必修"}:
                return "only"
        return "exclude" if exclude_elective else "include"

    def _is_question_elective(self, question: Dict[str, Any], markers: List[str]) -> bool:
        if not markers:
            markers = ["选修", "选择性必修", "选必"]
        source = (question.get("source") or "").strip()
        stem = (question.get("stem") or "").strip()
        kps = question.get("knowledge_points") or []
        if isinstance(kps, str):
            kp_text = kps
        elif isinstance(kps, list):
            kp_text = " ".join([str(x) for x in kps if x])
        else:
            kp_text = ""
        haystack = " ".join([source, kp_text, stem])
        return any(m and (m in haystack) for m in markers)

    def _stem_fingerprint(self, stem: str) -> str:
        s = (stem or "").strip().lower()
        if not s:
            return ""
        s = re.sub(r"\s+", "", s)
        # 限制长度避免极端长文本影响性能
        s = s[:1500]
        return hashlib.md5(s.encode("utf-8", errors="ignore")).hexdigest()

    def _quality_score(self, question: Dict[str, Any]) -> Tuple[int, List[str]]:
        stem = (question.get("stem") or "").strip()
        if not stem:
            return 0, ["missing_stem"]

        flags: List[str] = []
        score = 100

        stem_len = len(stem)
        if stem_len < 20:
            flags.append("stem_too_short")
            score -= 70
        elif stem_len < 60:
            flags.append("stem_short")
            score -= 30

        unknown_tokens = len(re.findall(r"\[\?[0-9a-fA-F]{4,}\]", stem))
        if unknown_tokens > 0:
            flags.append(f"unknown_tokens:{unknown_tokens}")
            score -= min(unknown_tokens * 15, 60)

        image_tokens = stem.count("[图片:")
        if image_tokens > 0:
            flags.append(f"has_images:{image_tokens}")
            score -= min(image_tokens * 10, 40)

        if "(需登录查看)" in stem:
            flags.append("login_required_content")
            score -= 30

        score = max(0, min(100, score))
        return score, flags

    def _parse_target_from_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从 SSE payload 中提取 question/list 所需参数。
        示例 payload.data.params: { bank_id, knowledges, ... }
        示例 url: /gzsx/zsd131011/o2  => pageName=zsd, categoryId=131011
        """
        url_path = payload.get("url", "")
        # 常见两类：
        # - /gzsx/zsd131011/o2
        # - /gzyy/zsd0/qt2809o2  (包含 quesType 过滤 qtXXXX)
        m = re.search(
            r"/[a-z]+/(?P<page>zsd|zj|zh|zs)(?P<cat>\d+)(?:/qt(?P<qt>\d+))?/?o(?P<order>\d+)",
            url_path,
        )
        if not m:
            return None
        page_name = m.group("page")
        cat_id = m.group("cat")
        qt_id = m.groupdict().get("qt")
        order_by = m.groupdict().get("order")
        params = payload.get("data", {}).get("params", {})
        bank_id = params.get("bank_id") or params.get("bankId") or 0
        target: Dict[str, Any] = {
            "page_name": page_name,
            "category_id": cat_id,
            "bank_id": bank_id,
        }
        if qt_id:
            target["question_type_id"] = _safe_int(qt_id, 0)
        if order_by:
            target["order_by"] = _safe_int(order_by, 0)
        ques_type_name = (params.get("ques_type") or "").strip()
        if ques_type_name:
            target["question_type_name"] = ques_type_name
        return target

    def _difficulty_code(self, difficulty: str) -> int:
        """
        组卷网 question/list 的 quesDiff 使用站内难度 ID（常见为 1-5）：
        - 1 容易
        - 2 简单
        - 3 一般/适中（≈中等）
        - 4 较难
        - 5 困难
        """
        d = (difficulty or "").strip()
        if not d:
            return 0

        # 精确匹配优先
        exact = {
            "容易": 1,
            "简单": 2,
            "一般": 3,
            "适中": 3,
            "中等": 3,
            "较难": 4,
            "困难": 5,
        }
        if d in exact:
            return exact[d]

        # 宽松匹配（兼容输入中包含“难度：”“中等难度”等）
        if "难" in d:
            # “较难/困难”都当作困难档过滤（更严格可用“较难”）
            return 5
        if "中" in d or "适" in d or "一" in d:
            return 3
        if "易" in d:
            return 1
        if "简" in d:
            return 2
        return 0

    def _difficulty_codes(self, difficulty: str) -> List[int]:
        """
        将三档难度映射为可直接请求的 quesDiff 列表：
        - 简单 -> [1, 2]（容易/简单）
        - 中等 -> [3]
        - 困难 -> [4, 5]（较难/困难）
        """
        d = (difficulty or "").strip()
        if not d:
            return []
        bucket_map = {
            "简单": [1, 2],
            "中等": [3],
            "困难": [4, 5],
        }
        if d in bucket_map:
            return bucket_map[d]

        # 兼容细粒度描述
        exact = {
            "容易": 1,
            "简单": 2,
            "一般": 3,
            "适中": 3,
            "中等": 3,
            "较难": 4,
            "困难": 5,
        }
        if d in exact:
            return [exact[d]]

        code = self._difficulty_code(d)
        return [code] if code else []

    def _use_multi_difficulty_codes(self) -> bool:
        mode = (DIFFICULTY_QUERY_MODE or "multi").strip().lower()
        return mode not in {"single", "strict", "exact", "one"}

    def _difficulty_bucket(self, difficulty_label: str) -> str:
        """把站内难度文案归一到 easy/medium/hard，用于兜底的客户端过滤。"""
        d = (difficulty_label or "").strip()
        if not d:
            return ""
        if d in {"容易", "简单", "较易", "易"}:
            return "easy"
        if d in {"一般", "适中", "中等", "中"}:
            return "medium"
        if d in {"较难", "困难", "难"}:
            return "hard"
        # 部分页面会出现“适中(0.65)”这种形式
        if "较难" in d or "困难" in d or d.endswith("难"):
            return "hard"
        if "一般" in d or "适中" in d or "中等" in d:
            return "medium"
        if "简单" in d or "容易" in d or "较易" in d:
            return "easy"
        return ""

    def _requested_difficulty_buckets(self, requested: str) -> set[str]:
        """
        MCP 的 difficulty 目前是 3 档：简单/中等/困难。
        这里把 3 档映射为可接受的站内难度集合，做兜底过滤。
        """
        d = (requested or "").strip()
        if not d:
            return set()
        if d == "简单":
            return {"容易", "简单", "较易"}
        if d == "中等":
            return {"一般", "适中", "中等"}
        if d == "困难":
            return {"较难", "困难"}
        # 兼容用户/模型输出的其他写法
        bucket = self._difficulty_bucket(d)
        if bucket == "easy":
            return {"容易", "简单", "较易"}
        if bucket == "medium":
            return {"一般", "适中", "中等"}
        if bucket == "hard":
            return {"较难", "困难"}
        return set()

    def _question_url(self, question_id: str) -> str:
        """生成题目链接，使用当前学科的 bank_id"""
        return f"{self.base_url}/{self.bank_id}q{question_id}.html"

    def _question_type_code(self, question_type: str) -> int:
        if not question_type:
            return 0
        return self.ques_type_map.get(question_type.strip(), 0)

    async def _fallback_question_list(
        self,
        keyword: str = "",
        limit: int = 20,
        difficulty: str = "",
        question_type: str = "",
        learn_grade: str = "",
        learn_grade_id: int = 0,
        textbook_version: str = "",
        max_pages: int = 3,
        year: int = 0,
        province: str = "",
        province_id: int = -1,
        paper_type_id: int = 0,
        term: int = 0,
        order_by: int = 2,
        source_contains: str = "",
        stem_contains: str = "",
        knowledge_contains: str = "",
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        difficulty_value_min: Optional[float] = None,
        difficulty_value_max: Optional[float] = None,
        dedup_by_stem: bool = False,
        min_quality_score: int = 0,
        with_quality: bool = True,
    ) -> Dict[str, Any]:
        """
        官方 AI 搜索无法解析意图时的兜底：直接访问 question/list。
        使用当前学科配置的 bankId 和 categoryId。
        """
        limit = _safe_int(limit, 20)
        limit = max(1, min(50, limit))

        max_pages = _safe_int(max_pages, 3)
        max_pages = max(1, min(8, max_pages))

        year = _safe_int(year, 0)
        paper_type_id = _safe_int(paper_type_id, 0)
        term = _safe_int(term, 0)
        order_by = _safe_int(order_by, 2)

        if difficulty_value_min is not None:
            difficulty_value_min = _safe_float(difficulty_value_min)
        if difficulty_value_max is not None:
            difficulty_value_max = _safe_float(difficulty_value_max)

        if question_type and not self.ques_type_map and self.client is not None:
            await self._ensure_base_meta_loaded()
        await self._ensure_bank_meta_loaded()
        page_name = "zsd"
        bank_id = self.bank_id
        category_id = self._resolve_textbook_category_id(textbook_version) or str(self.category_id)
        resolved_learn_grade_id = self._resolve_learn_grade_id(learn_grade, learn_grade_id)
        province_id = _safe_int(province_id, -1)
        province = (province or "").strip()
        if province and province_id in (-1, 0):
            resolved = await self._resolve_province_id(province)
            if resolved is not None:
                province_id = resolved

        all_questions: List[Dict[str, Any]] = []
        debug_pages = []
        for page_idx in range(1, max_pages + 1):
            questions, dbg = await self._fetch_question_list(
                page_name=page_name,
                bank_id=bank_id,
                category_id=category_id,
                cur_page=page_idx,
                difficulty=difficulty,
                question_type=question_type,
                learn_grade_id=resolved_learn_grade_id,
                year=year,
                province_id=province_id,
                paper_type_id=paper_type_id,
                term=term,
                order_by=order_by,
                parse_content=True,
            )
            all_questions.extend(questions)
            debug_pages.append(dbg)
            if len(all_questions) >= limit or (dbg.get("raw_count", 0) == 0):   
                break

        if not all_questions:
            return {
                "success": False,
                "error": "fallback_list_empty",
                "trace": {"method": "fallback", "pages": debug_pages},
            }

        selected_questions: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_stem_fps: set[str] = set()
        min_quality_score = _safe_int(min_quality_score, 0)

        for q in all_questions:
            qid = (q.get("question_id") or "").strip()
            if not qid or qid in seen_ids:
                continue
            seen_ids.add(qid)

            if not self._matches_local_filters(
                q,
                source_contains=source_contains,
                stem_contains=stem_contains,
                knowledge_contains=knowledge_contains,
                elective_mode=elective_mode,
                elective_keywords=elective_keywords,
                exclude_elective=exclude_elective,
                year=year,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
            ):
                continue

            score, flags = self._quality_score(q)
            if with_quality:
                q["quality_score"] = score
                if flags:
                    q["quality_flags"] = flags
            if min_quality_score > 0 and score < min_quality_score:
                continue

            if dedup_by_stem:
                fp = self._stem_fingerprint(q.get("stem") or "")
                if fp and fp in seen_stem_fps:
                    continue
                if fp:
                    seen_stem_fps.add(fp)

            selected_questions.append(q)
            if len(selected_questions) >= limit:
                break

        return {
            "success": True,
            "keyword": keyword,
            "count": len(selected_questions[:limit]),
            "questions": selected_questions[:limit],
            "trace": {
                "method": "fallback",
                "target": {
                    "page_name": page_name,
                    "bank_id": bank_id,
                    "category_id": category_id,
                },
                "filters": {
                    "learn_grade_id": resolved_learn_grade_id,
                    "year": _safe_int(year, 0),
                    "province_id": _safe_int(province_id, -1),
                    "paper_type_id": _safe_int(paper_type_id, 0),
                    "term": _safe_int(term, 0),
                    "order_by": _safe_int(order_by, 2),
                    "source_contains": (source_contains or "").strip(),
                    "stem_contains": (stem_contains or "").strip(),
                    "knowledge_contains": (knowledge_contains or "").strip(),
                    "exclude_elective": bool(exclude_elective),
                    "elective_mode": self._normalize_elective_mode(elective_mode, exclude_elective),
                    "dedup_by_stem": bool(dedup_by_stem),
                    "min_quality_score": min_quality_score,
                    "with_quality": bool(with_quality),
                    "difficulty_value_min": difficulty_value_min,
                    "difficulty_value_max": difficulty_value_max,
                },
                "pages": debug_pages,
            },
        }

    async def _fetch_question_list(
        self,
        page_name: str,
        bank_id: int,
        category_id: str,
        cur_page: int = 1,
        difficulty: str = "",
        question_type: str = "",
        question_type_id: int = 0,
        learn_grade_id: int = 0,
        year: int = 0,
        province_id: int = -1,
        paper_type_id: int = 0,
        term: int = 0,
        order_by: int = 2,
        parse_content: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        调用 /zujuan-api/question/list，解析题目信息。
        返回 (题目列表, 调试信息)
        parse_content=True 时解析完整题目内容，False 时只返回ID
        """
        if not self.client:
            return [], {"error": "client not initialized"}

        use_multi = self._use_multi_difficulty_codes()
        if use_multi:
            difficulty_codes = self._difficulty_codes(difficulty)
        else:
            code = self._difficulty_code(difficulty)
            difficulty_codes = [code] if code else []
        if not difficulty_codes:
            difficulty_codes = [0]

        year = _safe_int(year, 0)
        province_id = _safe_int(province_id, -1)
        paper_type_id = _safe_int(paper_type_id, 0)
        term = _safe_int(term, 0)
        order_by = _safe_int(order_by, 2)
        question_type_id = _safe_int(question_type_id, 0)
        ques_type_code = question_type_id or self._question_type_code(question_type)
        learn_grade_id = _safe_int(learn_grade_id, 0)

        cache_key = (
            f"qlist:{page_name}:{bank_id}:{category_id}:{cur_page}:{difficulty}:"
            f"{ques_type_code}:{year}:{province_id}:{paper_type_id}:{term}:{order_by}:"
            f"{learn_grade_id}:{int(parse_content)}"
        )
        cached = self._cache_get(cache_key)
        if isinstance(cached, tuple) and len(cached) == 2:
            return cached  # type: ignore[return-value]

        seen_ids = set()
        all_questions: List[Dict[str, Any]] = []
        total_raw_count = 0
        sub_requests = []
        errors = []

        for diff_code in difficulty_codes:
            data = {
                "pageName": page_name,
                "bankId": str(bank_id or 0),
                "courseId": "0",
                "categoryId": str(category_id),
                "canCategoryId": "true",
                "categoryIds[0]": "0",
                "quesType": str(ques_type_code),
                "quesDiff": str(diff_code),
                "quesYear": str(year or 0),
                "paperTypeId": str(paper_type_id or 0),
                "scenarioizedTypeId": "0",
                "tagId": "0",
                "provinceId": str(province_id),
                "learngrade": str(learn_grade_id or 0),
                "term": str(term or 0),
                "orderBy": str(order_by or 2),
                "curPage": str(cur_page),
                "quesAttributeId": "0",
                "examMethodId": "0",
                "isFresh": "0",
                "catelogTokpointId": "0",
            }

            resp = await self.client.post(
                f"{self.base_url}/zujuan-api/question/list",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            try:
                resp_json = resp.json()
                html = resp_json.get("data", {}).get("html", "")
            except Exception:
                errors.append({"quesDiff": diff_code, "error": "json_parse_failed", "status": resp.status_code})
                continue

            if not html:
                errors.append({"quesDiff": diff_code, "error": "empty_html", "status": resp.status_code})
                continue

            if not parse_content:
                ids = re.findall(r'questionid="(\d+)"', html)
                total_raw_count += len(ids)
                for qid in ids:
                    if qid not in seen_ids:
                        all_questions.append({"question_id": qid})
                        seen_ids.add(qid)
                sub_requests.append({"quesDiff": diff_code, "raw_count": len(ids), "page": cur_page})
                continue

            questions = await self._parse_questions_from_html(html, bank_id)
            total_raw_count += len(questions)
            for q in questions:
                qid = q.get("question_id")
                if not qid:
                    continue
                if qid not in seen_ids:
                    all_questions.append(q)
                    seen_ids.add(qid)
            sub_requests.append({"quesDiff": diff_code, "raw_count": len(questions), "page": cur_page})

        if not all_questions and errors:
            return [], {
                "error": "question_list_failed",
                "raw_count": 0,
                "page": cur_page,
                "details": errors,
            }

        # 兜底：若站点未按 quesDiff 过滤（偶发），这里再按解析出的难度文案过滤一次
        accepted_labels = self._requested_difficulty_buckets(difficulty)
        if accepted_labels and parse_content:
            all_questions = [
                q for q in all_questions if (q.get("difficulty") or "").strip() in accepted_labels
            ]

        debug_info = {
            "raw_count": total_raw_count,
            "returned_count": len(all_questions),
            "page": cur_page,
            "difficulty_mode": "multi" if use_multi else "single",
            "ques_type_code": ques_type_code,
            "learn_grade_id": learn_grade_id,
            "year": year,
            "province_id": province_id,
            "paper_type_id": paper_type_id,
            "term": term,
            "order_by": order_by,
        }
        if len(sub_requests) > 1:
            debug_info["difficulty_codes"] = difficulty_codes
            debug_info["sub_requests"] = sub_requests
        if errors:
            debug_info["errors"] = errors

        result = (all_questions, debug_info)
        self._cache_set(cache_key, result, ttl=8 * 60 if parse_content else 10 * 60)
        return result

    async def _parse_questions_from_html(self, html: str, bank_id: int) -> List[Dict[str, Any]]:
        """
        从搜索结果 HTML 解析题目信息，将公式转换为 LaTeX
        
        优化：先收集所有公式URL，批量转换，避免每个题目单独请求
        """
        questions = []
        question_stems = []  # 存储(题目索引, 题干HTML)用于批量处理

        # 按题目块分割
        question_blocks = re.split(r'<div class=" tk-quest-item', html)

        for block in question_blocks[1:]:  # 跳过第一个空块
            q = {}

            # 题号
            qid_match = re.search(r'questionid="(\d+)"', block)
            if not qid_match:
                continue
            q["question_id"] = qid_match.group(1)
            q["source_url"] = f"{self.base_url}/{bank_id}q{q['question_id']}.html"

            # 题型和难度 (从 info-cnt 解析)
            info_items = re.findall(r'<span class="info-cnt">\s*([^<]+)\s*</span>', block)
            if info_items:
                # 第一个通常是题型，解码 HTML 实体
                q["type"] = html_module.unescape(info_items[0].strip()) if info_items else ""
                # 第二个通常是难度
                if len(info_items) > 1:
                    diff_text = html_module.unescape(info_items[1].strip())
                    # 解析难度值，如 "适中(0.65)"
                    diff_match = re.search(r'([\u4e00-\u9fa5]+)\s*\(?([\\d.]+)?\)?', diff_text)
                    if diff_match:
                        q["difficulty"] = diff_match.group(1)
                        q["difficulty_value"] = diff_match.group(2) if diff_match.group(2) else ""
                    else:
                        q["difficulty"] = diff_text
                        q["difficulty_value"] = ""

            # 知识点
            kp_matches = re.findall(r'class="knowledge-item"[^>]*>([^<]+)</a>', block)
            q["knowledge_points"] = [html_module.unescape(kp) for kp in kp_matches] if kp_matches else []

            # 来源
            src_match = re.search(r'class="addi-msg ques-src"[^>]*>([^<]+)</a>', block)
            q["source"] = html_module.unescape(src_match.group(1).strip()) if src_match else ""

            # 题干内容 (从 exam-item__cnt 解析)
            stem_match = re.search(r'<div class="exam-item__cnt[^"]*">([\s\S]*?)</div>\s*<div[^>]*class="exam-item__opt"', block)
            if stem_match:
                stem_html = stem_match.group(1)
                question_stems.append((len(questions), stem_html))
                q["_stem_html"] = stem_html  # 临时存储
            else:
                q["stem"] = ""

            # 日期
            date_match = re.search(r'<span class="no-bound"[^>]*>(\d{4}/\d{1,2}/\d{1,2})</span>', block)
            q["date"] = date_match.group(1) if date_match else ""

            questions.append(q)

        # 批量处理所有题干中的公式（大幅提升性能）
        if question_stems:
            # 合并所有题干HTML，一次性提取所有公式URL
            await self._batch_convert_formulas(questions, question_stems)

        return questions

    async def _batch_convert_formulas(self, questions: List[Dict[str, Any]], question_stems: List[Tuple[int, str]]) -> None:
        """
        批量转换所有题目中的公式
        
        优化策略：
        1. 收集所有公式URL
        2. 一次性批量请求并转换
        3. 用转换结果填充题目
        """
        try:
            from utils.svg_to_latex import batch_svg_to_latex, load_signatures
            
            load_signatures()
            
            # 收集所有公式URL
            formula_pattern = r'<img[^>]*src="(https://[^"]+/formula/[^"]+\.png)"[^>]*>'
            all_png_urls = set()
            stem_formula_map = {}  # {题目索引: [png_urls]}
            
            for idx, stem_html in question_stems:
                png_urls = re.findall(formula_pattern, stem_html)
                all_png_urls.update(png_urls)
                stem_formula_map[idx] = png_urls
            
            # 转换为SVG URL并批量获取
            svg_urls = [url.replace('.png', '.svg') for url in all_png_urls]
            
            if svg_urls:
                # 批量转换，提高并发到30
                latex_map = await batch_svg_to_latex(svg_urls, concurrency=30, use_advanced=True)
                
                # 构建 png_url -> latex 的映射
                png_to_latex = {}
                for png_url in all_png_urls:
                    svg_url = png_url.replace('.png', '.svg')
                    if svg_url in latex_map:
                        latex, _ = latex_map[svg_url]
                        if latex:
                            png_to_latex[png_url] = latex
            else:
                png_to_latex = {}
            
            # 用转换结果填充题目
            for idx, stem_html in question_stems:
                # 替换公式
                for png_url in stem_formula_map.get(idx, []):
                    if png_url in png_to_latex:
                        latex = png_to_latex[png_url]
                        # 转义反斜杠
                        latex_escaped = latex.replace('\\', '\\\\')
                        img_pattern = f'<img[^>]*src="{re.escape(png_url)}"[^>]*>'
                        stem_html = re.sub(img_pattern, f'${latex_escaped}$', stem_html)
                
                # 保留普通图片链接
                stem_html = re.sub(
                    r'<img[^>]*src="([^"]+)"[^>]*>',
                    r'[图片:\1]',
                    stem_html
                )
                # 清理HTML标签
                stem_text = re.sub(r'<[^>]+>', '', stem_html)
                stem_text = html_module.unescape(stem_text)
                stem_text = re.sub(r'\s+', ' ', stem_text).strip()
                # 去掉题号前缀
                stem_text = re.sub(r'^\d+\s*[.．、]\s*', '', stem_text)
                
                questions[idx]["stem"] = stem_text[:2000]
                # 删除临时字段
                if "_stem_html" in questions[idx]:
                    del questions[idx]["_stem_html"]
                    
        except ImportError:
            # 回退到串行处理
            for idx, stem_html in question_stems:
                stem_html = await self._replace_formulas_with_latex(stem_html)
                stem_html = re.sub(r'<img[^>]*src="([^"]+)"[^>]*>', r'[图片:\1]', stem_html)
                stem_text = re.sub(r'<[^>]+>', '', stem_html)
                stem_text = html_module.unescape(stem_text)
                stem_text = re.sub(r'\s+', ' ', stem_text).strip()
                stem_text = re.sub(r'^\d+\s*[.．、]\s*', '', stem_text)
                questions[idx]["stem"] = stem_text[:2000]
                if "_stem_html" in questions[idx]:
                    del questions[idx]["_stem_html"]
        except Exception as e:
            print(f"批量公式转换失败，回退到串行: {e}")
            for idx, stem_html in question_stems:
                stem_html = await self._replace_formulas_with_latex(stem_html)
                stem_html = re.sub(r'<img[^>]*src="([^"]+)"[^>]*>', r'[图片:\1]', stem_html)
                stem_text = re.sub(r'<[^>]+>', '', stem_html)
                stem_text = html_module.unescape(stem_text)
                stem_text = re.sub(r'\s+', ' ', stem_text).strip()
                stem_text = re.sub(r'^\d+\s*[.．、]\s*', '', stem_text)
                questions[idx]["stem"] = stem_text[:2000]
                if "_stem_html" in questions[idx]:
                    del questions[idx]["_stem_html"]

    def _matches_local_filters(
        self,
        question: Dict[str, Any],
        *,
        source_contains: str = "",
        stem_contains: str = "",
        knowledge_contains: str = "",
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        year: int = 0,
        difficulty_value_min: Optional[float] = None,
        difficulty_value_max: Optional[float] = None,
    ) -> bool:
        source_contains = (source_contains or "").strip()
        stem_contains = (stem_contains or "").strip()
        knowledge_contains = (knowledge_contains or "").strip()

        if source_contains:
            source = (question.get("source") or "").strip()
            if source_contains.lower() not in source.lower():
                return False

        if stem_contains:
            stem = (question.get("stem") or "").strip()
            if stem_contains.lower() not in stem.lower():
                return False

        if knowledge_contains:
            kps = question.get("knowledge_points") or []
            if isinstance(kps, str):
                kp_text = kps
            elif isinstance(kps, list):
                kp_text = " ".join([str(x) for x in kps if x])
            else:
                kp_text = ""
            if knowledge_contains.lower() not in kp_text.lower():
                return False

        mode = self._normalize_elective_mode(elective_mode, exclude_elective)
        if mode != "include":
            markers = elective_keywords or ["选修", "选择性必修", "选必"]
            is_elective = self._is_question_elective(question, list(markers))
            if mode == "exclude" and is_elective:
                return False
            if mode == "only" and not is_elective:
                return False

        year = _safe_int(year, 0)
        if year > 0:
            date_str = (question.get("date") or "").strip()
            if date_str and "/" in date_str:
                try:
                    date_year = int(date_str.split("/", 1)[0])
                    if date_year != year:
                        return False
                except Exception:
                    pass

        if difficulty_value_min is not None or difficulty_value_max is not None:
            dv = _safe_float(question.get("difficulty_value"))
            if dv is None:
                # 不强制要求每道题都带“难度系数”。
                # 如果题目没有难度系数，则不因该过滤条件被剔除。
                return True
            if difficulty_value_min is not None and dv < difficulty_value_min:  
                return False
            if difficulty_value_max is not None and dv > difficulty_value_max:  
                return False

        return True

    async def search_by_keyword(
        self,
        keyword: str,
        subject: str = "",
        edu_level: str = "",
        limit: int = 20,
        difficulty: str = "",
        question_type: str = "",
        learn_grade: str = "",
        learn_grade_id: int = 0,
        textbook_version: str = "",
        max_pages: int = 2,
        year: int = 0,
        province: str = "",
        province_id: int = -1,
        paper_type_id: int = 0,
        term: int = 0,
        order_by: int = 2,
        source_contains: str = "",
        stem_contains: str = "",
        knowledge_contains: str = "",
        difficulty_value_min: Optional[float] = None,
        difficulty_value_max: Optional[float] = None,
        require_difficulty: bool = False,
        strict_subject: bool = True,
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        dedup_by_stem: bool = False,
        min_quality_score: int = 0,
        with_quality: bool = True,
    ) -> Dict[str, Any]:
        """
        关键词搜索（无需登录）：SSE 得到推荐参数 -> question/list 获取完整题目信息。
        返回的 questions 包含题干、难度、知识点等完整信息。
        """
        try:
            resolved_subject, difficulty = self._apply_search_constraints(
                subject=subject,
                edu_level=edu_level,
                difficulty=difficulty,
                require_difficulty=require_difficulty,
                strict_subject=strict_subject,
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "available_subjects": list(SUBJECTS.keys()),
                "allowed_difficulties": sorted(DIFFICULTY_LEVELS),
            }

        limit = _safe_int(limit, 20)
        limit = max(1, min(50, limit))

        max_pages = _safe_int(max_pages, 2)
        max_pages = max(1, min(8, max_pages))

        if difficulty_value_min is not None:
            difficulty_value_min = _safe_float(difficulty_value_min)
        if difficulty_value_max is not None:
            difficulty_value_max = _safe_float(difficulty_value_max)

        meta_task = None
        if (
            (question_type or "").strip()
            or (learn_grade or "").strip()
            or _safe_int(learn_grade_id, 0) > 0
            or (textbook_version or "").strip()
        ) and self.client is not None:
            # 按需加载题型/年级/教材版本映射，并与 AI 搜索并行以减少等待
            meta_task = asyncio.create_task(self._ensure_bank_meta_loaded())

        province_id = _safe_int(province_id, -1)
        province = (province or "").strip()
        if province and province_id in (-1, 0) and self.client is not None:
            resolved = await self._resolve_province_id(province)
            if resolved is None:
                return {
                    "success": False,
                    "error": "province_not_found",
                    "province": province,
                    "hint": "请先调用 get_available_filters 获取 provinces 或改用 province_id 传参。",
                }
            province_id = resolved

        # 站内 SSE 搜索是“全站意图识别”，不带学科时容易跑到其他学科/学段，
        # strict_subject 模式下自动补齐学科前缀以减少跨学科命中。
        sse_query = (keyword or "").strip()
        if strict_subject and resolved_subject:
            cfg = SUBJECTS.get(resolved_subject) or {}
            short_name = (cfg.get("short_name") or "").strip()
            if resolved_subject not in sse_query and (not short_name or short_name not in sse_query):
                sse_query = f"{resolved_subject} {sse_query}".strip()

        ai_result = await self._ai_search(sse_query)
        if not ai_result.get("success"):
            if meta_task:
                await meta_task
            return await self._fallback_question_list(
                keyword=keyword,
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                learn_grade=learn_grade,
                learn_grade_id=learn_grade_id,
                textbook_version=textbook_version,
                max_pages=max_pages,
                year=year,
                province=province,
                province_id=province_id,
                paper_type_id=paper_type_id,
                term=term,
                order_by=order_by,
                source_contains=source_contains,
                stem_contains=stem_contains,
                knowledge_contains=knowledge_contains,
                elective_mode=elective_mode,
                elective_keywords=elective_keywords,
                exclude_elective=exclude_elective,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                dedup_by_stem=dedup_by_stem,
                min_quality_score=min_quality_score,
                with_quality=with_quality,
            )

        payload = ai_result["payload"]
        target = self._parse_target_from_payload(payload)
        if not target:
            if meta_task:
                await meta_task
            return await self._fallback_question_list(
                keyword=keyword,
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                learn_grade=learn_grade,
                learn_grade_id=learn_grade_id,
                textbook_version=textbook_version,
                max_pages=max_pages,
                year=year,
                province=province,
                province_id=province_id,
                paper_type_id=paper_type_id,
                term=term,
                order_by=order_by,
                source_contains=source_contains,
                stem_contains=stem_contains,
                knowledge_contains=knowledge_contains,
                elective_mode=elective_mode,
                elective_keywords=elective_keywords,
                exclude_elective=exclude_elective,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                dedup_by_stem=dedup_by_stem,
                min_quality_score=min_quality_score,
                with_quality=with_quality,
            )

        if meta_task:
            await meta_task

        resolved_textbook_category_id = self._resolve_textbook_category_id(textbook_version)
        resolved_learn_grade_id = self._resolve_learn_grade_id(learn_grade, learn_grade_id)

        # 部分学科会返回 zsd0（未指定知识点/目录），此时用当前学科默认分类兜底，
        # 避免 categoryId=0 导致的“跟随 cookie 的题库”混入。
        if _safe_int(target.get("category_id"), 0) == 0 and getattr(self, "category_id", ""):
            target["category_id_original"] = target.get("category_id")
            if resolved_textbook_category_id:
                target["category_id"] = resolved_textbook_category_id
                target["textbook_version_applied"] = textbook_version
            else:
                target["category_id"] = str(self.category_id)

        # 严格学科约束：搜索结果必须落在当前学科 bankId 下。
        # 组卷网的 /zujuan-api/search（SSE）偶发返回其他学科的 bank_id，导致跨学段混入。
        expected_bank_id = _safe_int(getattr(self, "bank_id", 0), 0)
        target_bank_id = _safe_int(target.get("bank_id"), 0)
        bank_id_for_request = target_bank_id or expected_bank_id
        bank_id_mismatch = False
        if strict_subject and expected_bank_id:
            if target_bank_id and target_bank_id != expected_bank_id:
                bank_id_mismatch = True
            bank_id_for_request = expected_bank_id
            # SSE 给出的 categoryId 通常属于其 bank_id；当 bank 不一致时直接用
            # 当前学科默认分类，避免无结果/跨库混入。
            if bank_id_mismatch and getattr(self, "category_id", ""):
                target["category_id_original"] = target.get("category_id")
                target["category_id"] = resolved_textbook_category_id or str(self.category_id)

        target["bank_id_expected"] = expected_bank_id
        target["bank_id_for_request"] = bank_id_for_request
        if bank_id_mismatch:
            target["bank_id_mismatch"] = True

        year = _safe_int(year, 0)
        province_id = _safe_int(province_id, -1)
        paper_type_id = _safe_int(paper_type_id, 0)
        term = _safe_int(term, 0)
        order_by = _safe_int(order_by, 2)

        selected_questions: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_stem_fps: set[str] = set()
        debug_pages = []
        target_question_type_id = _safe_int(target.get("question_type_id"), 0)
        question_type_id_for_request = (
            target_question_type_id if not (question_type or "").strip() else 0
        )
        min_quality_score = _safe_int(min_quality_score, 0)
        for page_idx in range(1, max_pages + 1):
            questions, dbg = await self._fetch_question_list(
                page_name=target["page_name"],
                bank_id=bank_id_for_request,
                category_id=target["category_id"],
                cur_page=page_idx,
                difficulty=difficulty,
                question_type=question_type,
                question_type_id=question_type_id_for_request,
                learn_grade_id=resolved_learn_grade_id,
                year=year,
                province_id=province_id,
                paper_type_id=paper_type_id,
                term=term,
                order_by=order_by,
                parse_content=True,  # 解析完整内容
            )
            for q in questions:
                qid = (q.get("question_id") or "").strip()
                if not qid or qid in seen_ids:
                    continue
                seen_ids.add(qid)
                if self._matches_local_filters(
                    q,
                    source_contains=source_contains,
                    stem_contains=stem_contains,
                    knowledge_contains=knowledge_contains,
                    elective_mode=elective_mode,
                    elective_keywords=elective_keywords,
                    exclude_elective=exclude_elective,
                    year=year,
                    difficulty_value_min=difficulty_value_min,
                    difficulty_value_max=difficulty_value_max,
                ):
                    score, flags = self._quality_score(q)
                    if with_quality:
                        q["quality_score"] = score
                        if flags:
                            q["quality_flags"] = flags
                    if min_quality_score > 0 and score < min_quality_score:
                        continue
                    if dedup_by_stem:
                        fp = self._stem_fingerprint(q.get("stem") or "")
                        if fp and fp in seen_stem_fps:
                            continue
                        if fp:
                            seen_stem_fps.add(fp)
                    selected_questions.append(q)
            debug_pages.append(dbg)
            if len(selected_questions) >= limit or (dbg.get("raw_count", 0) == 0):
                break

        # 如果 SSE 返回了错误学科的 bankId 且强制校正后没有结果，降级到兜底路径：
        # 直接用当前学科默认 categoryId 拉取，至少保证学科/学段不会混入。
        if bank_id_mismatch and not selected_questions:
            return await self._fallback_question_list(
                keyword=keyword,
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                learn_grade=learn_grade,
                learn_grade_id=learn_grade_id,
                textbook_version=textbook_version,
                max_pages=max_pages,
                year=year,
                province=province,
                province_id=province_id,
                paper_type_id=paper_type_id,
                term=term,
                order_by=order_by,
                source_contains=source_contains,
                stem_contains=stem_contains,
                knowledge_contains=knowledge_contains,
                elective_mode=elective_mode,
                elective_keywords=elective_keywords,
                exclude_elective=exclude_elective,
                difficulty_value_min=difficulty_value_min,
                difficulty_value_max=difficulty_value_max,
                dedup_by_stem=dedup_by_stem,
                min_quality_score=min_quality_score,
                with_quality=with_quality,
            )

        return {
            "success": True,
            "keyword": keyword,
            "count": len(selected_questions[:limit]),
            "questions": selected_questions[:limit],
            "trace": {
                "target": target,
                "filters": {
                    "learn_grade_id": resolved_learn_grade_id,
                    "textbook_version": (textbook_version or "").strip(),
                    "year": year,
                    "province_id": province_id,
                    "paper_type_id": paper_type_id,
                    "term": term,
                    "order_by": order_by,
                    "source_contains": (source_contains or "").strip(),
                    "stem_contains": (stem_contains or "").strip(),
                    "knowledge_contains": (knowledge_contains or "").strip(),
                    "exclude_elective": bool(exclude_elective),
                    "elective_mode": self._normalize_elective_mode(elective_mode, exclude_elective),
                    "dedup_by_stem": bool(dedup_by_stem),
                    "min_quality_score": min_quality_score,
                    "with_quality": bool(with_quality),
                    "difficulty_value_min": difficulty_value_min,
                    "difficulty_value_max": difficulty_value_max,
                },
                "pages": debug_pages,
            },
        }

    async def search_by_knowledge(
        self,
        knowledge_point: str,
        subject: str,
        edu_level: str = "",
        limit: int = 20,
        difficulty: str = "",
        question_type: str = "",
        learn_grade: str = "",
        learn_grade_id: int = 0,
        textbook_version: str = "",
        max_pages: int = 2,
        year: int = 0,
        province: str = "",
        province_id: int = -1,
        paper_type_id: int = 0,
        term: int = 0,
        order_by: int = 2,
        source_contains: str = "",
        stem_contains: str = "",
        knowledge_contains: str = "",
        difficulty_value_min: Optional[float] = None,
        difficulty_value_max: Optional[float] = None,
        require_difficulty: bool = False,
        strict_subject: bool = True,
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        dedup_by_stem: bool = False,
        min_quality_score: int = 0,
        with_quality: bool = True,
    ) -> Dict[str, Any]:
        """
        通过知识点搜索（内部复用关键词搜索）。
        """
        return await self.search_by_keyword(
            keyword=knowledge_point,
            subject=subject,
            edu_level=edu_level,
            limit=limit,
            difficulty=difficulty,
            question_type=question_type,
            learn_grade=learn_grade,
            learn_grade_id=learn_grade_id,
            textbook_version=textbook_version,
            max_pages=max_pages,
            year=year,
            province=province,
            province_id=province_id,
            paper_type_id=paper_type_id,
            term=term,
            order_by=order_by,
            source_contains=source_contains,
            stem_contains=stem_contains,
            knowledge_contains=knowledge_contains,
            difficulty_value_min=difficulty_value_min,
            difficulty_value_max=difficulty_value_max,
            require_difficulty=require_difficulty,
            strict_subject=strict_subject,
            elective_mode=elective_mode,
            elective_keywords=elective_keywords,
            exclude_elective=exclude_elective,
            dedup_by_stem=dedup_by_stem,
            min_quality_score=min_quality_score,
            with_quality=with_quality,
        )

    async def get_available_filters(self) -> Dict[str, Any]:
        """
        返回当前学科（bankId）下可用的筛选项（年级/试卷类型/教材版本/题型等）。
        用于 MCP/前端做下拉选择，避免“写死 ID”。
        """
        await self._ensure_bank_meta_loaded()
        await self._ensure_province_meta_loaded()

        grades = [
            {"id": gid, "name": name}
            for gid, name in sorted(self.learn_grade_id_to_name.items(), key=lambda x: x[0])
        ]
        paper_types_by_grade = {}
        for gid, paper_types in (self.paper_types_by_grade or {}).items():
            paper_types_by_grade[str(gid)] = paper_types

        return {
            "success": True,
            "subject": getattr(self, "subject", ""),
            "bank_id": _safe_int(getattr(self, "bank_id", 0), 0),
            "default_category_id": str(getattr(self, "category_id", "")),
            "grades": grades,
            "paper_types_by_grade": paper_types_by_grade,
            "textbook_versions": list(self.textbook_versions or []),
            "question_types": list(self.question_types or []),
            "provinces": list(self.provinces or []),
            "elective_modes": ["include", "exclude", "only"],
        }

    async def compose_paper_blueprint(
        self,
        blueprint: List[Dict[str, Any]],
        *,
        subject: str = "",
        edu_level: str = "",
        learn_grade: str = "",
        learn_grade_id: int = 0,
        textbook_version: str = "",
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        year: int = 0,
        province: str = "",
        province_id: int = -1,
        paper_type_id: int = 0,
        term: int = 0,
        order_by: int = 2,
        max_pages: int = 2,
        per_slot_expand: int = 3,
        min_quality_score: int = 0,
        dedup_by_stem: bool = True,
        strict_subject: bool = True,
    ) -> Dict[str, Any]:
        """
        根据蓝图（多个“检索槽位”）批量检索并组装题目列表。

        blueprint 每项示例：
        {
          "keyword": "阅读理解",
          "count": 4,
          "difficulty": "中等",
          "question_type": "",
          "source_contains": "",
          "stem_contains": "",
          "knowledge_contains": ""
        }
        """
        if not isinstance(blueprint, list) or not blueprint:
            return {"success": False, "error": "blueprint 不能为空"}

        per_slot_expand = _safe_int(per_slot_expand, 3)
        per_slot_expand = max(1, min(6, per_slot_expand))

        max_pages_default = _safe_int(max_pages, 2)
        max_pages_default = max(1, min(8, max_pages_default))
        max_pages_cap = 8

        min_quality_score = _safe_int(min_quality_score, 0)
        min_quality_floor = 0

        global_seen_ids: set[str] = set()
        global_seen_fps: set[str] = set()

        selected_questions: List[Dict[str, Any]] = []
        sections: List[Dict[str, Any]] = []

        slot_items: List[Dict[str, Any]] = []
        for idx, slot in enumerate(blueprint):
            if not isinstance(slot, dict):
                continue

            slot_keyword = (slot.get("keyword") or "").strip()
            slot_knowledge_point = (slot.get("knowledge_point") or "").strip()
            count = _safe_int(slot.get("count"), 0)
            if count <= 0 or (not slot_keyword and not slot_knowledge_point):
                continue

            slot_max_pages = _safe_int(slot.get("max_pages"), 0) or max_pages_default
            slot_max_pages = max(1, min(max_pages_cap, slot_max_pages))

            search_limit = max(count * per_slot_expand, count)
            search_limit = min(search_limit, 50)

            slot_items.append(
                {
                    "index": idx,
                    "slot": slot,
                    "keyword": slot_keyword,
                    "knowledge_point": slot_knowledge_point,
                    "requested": count,
                    "difficulty": (slot.get("difficulty") or "").strip(),
                    "question_type": (slot.get("question_type") or "").strip(),
                    "source_contains": (slot.get("source_contains") or "").strip(),
                    "stem_contains": (slot.get("stem_contains") or "").strip(),
                    "knowledge_contains": (slot.get("knowledge_contains") or "").strip(),
                    "max_pages": slot_max_pages,
                    "search_limit": search_limit,
                }
            )

        if not slot_items:
            return {
                "success": True,
                "count": 0,
                "question_ids": [],
                "sections": [],
                "questions_preview": [],
            }

        def _sort_candidates(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            cands.sort(key=lambda q: _safe_int(q.get("quality_score"), 0), reverse=True)
            return cands

        async def _run_slot_search(slot_item: Dict[str, Any], *, slot_max_pages: int) -> Dict[str, Any]:
            """
            Fetch a wider candidate pool for a slot.

            Important:
            - We always fetch with `min_quality_score=0` and `dedup_by_stem=False`,
              then apply quality/dedup constraints locally in the blueprint composer,
              so later "auto relax" steps don't need extra network calls (except max_pages).
            """
            common_kwargs = dict(
                subject=subject,
                edu_level=edu_level,
                limit=slot_item["search_limit"],
                difficulty=slot_item["difficulty"],
                question_type=slot_item["question_type"],
                learn_grade=learn_grade,
                learn_grade_id=learn_grade_id,
                textbook_version=textbook_version,
                max_pages=slot_max_pages,
                year=year,
                province=province,
                province_id=province_id,
                paper_type_id=paper_type_id,
                term=term,
                order_by=order_by,
                source_contains=slot_item["source_contains"],
                stem_contains=slot_item["stem_contains"],
                knowledge_contains=slot_item["knowledge_contains"],
                require_difficulty=True,
                strict_subject=strict_subject,
                elective_mode=elective_mode,
                elective_keywords=elective_keywords,
                exclude_elective=exclude_elective,
                dedup_by_stem=False,
                min_quality_score=0,
                with_quality=True,
            )
            if slot_item["keyword"]:
                return await self.search_by_keyword(keyword=slot_item["keyword"], **common_kwargs)
            return await self.search_by_knowledge(
                knowledge_point=slot_item["knowledge_point"], **common_kwargs
            )

        slot_concurrency = 3
        sem = asyncio.Semaphore(slot_concurrency)

        async def _prefetch_one(slot_item: Dict[str, Any]) -> Dict[str, Any]:
            async with sem:
                result = await _run_slot_search(slot_item, slot_max_pages=slot_item["max_pages"])
                candidates = list(result.get("questions") or [])
                _sort_candidates(candidates)
                return {
                    "success": bool(result.get("success")),
                    "error": result.get("error") or "",
                    "candidates": candidates,
                    "trace": result.get("trace"),
                }

        prefetch_results = await asyncio.gather(
            *[asyncio.create_task(_prefetch_one(s)) for s in slot_items],
            return_exceptions=True,
        )

        prefetched_by_index: Dict[int, Dict[str, Any]] = {}
        for slot_item, res in zip(slot_items, prefetch_results):
            idx = slot_item["index"]
            if isinstance(res, Exception):
                prefetched_by_index[idx] = {
                    "success": False,
                    "error": str(res),
                    "candidates": [],
                    "trace": None,
                }
            else:
                prefetched_by_index[idx] = res

        def _maybe_fp(question: Dict[str, Any]) -> str:
            return self._stem_fingerprint(question.get("stem") or "")

        def _select_more(
            candidates: List[Dict[str, Any]],
            *,
            remaining: int,
            quality_threshold: int,
            dedup_stem: bool,
        ) -> List[Dict[str, Any]]:
            newly: List[Dict[str, Any]] = []
            for q in candidates:
                qid = (q.get("question_id") or "").strip()
                if not qid or qid in global_seen_ids:
                    continue

                score = _safe_int(q.get("quality_score"), 0)
                if quality_threshold > 0 and score < quality_threshold:
                    continue

                fp = _maybe_fp(q)
                if dedup_stem and fp and fp in global_seen_fps:
                    continue

                global_seen_ids.add(qid)
                if fp:
                    global_seen_fps.add(fp)
                newly.append(q)
                if len(newly) >= remaining:
                    break
            return newly

        for slot_item in slot_items:
            idx = slot_item["index"]
            requested = slot_item["requested"]

            relax_trace: List[Dict[str, Any]] = []
            slot_selected: List[Dict[str, Any]] = []

            # Start from prefetched candidates if available; if prefetch failed, we can still try in-band later.
            pre = prefetched_by_index.get(idx) or {}
            candidates: List[Dict[str, Any]] = list(pre.get("candidates") or [])
            seen_candidate_ids: set[str] = {
                (q.get("question_id") or "").strip() for q in candidates if q.get("question_id")
            }

            # Effective parameters that may be relaxed.
            slot_max_pages = slot_item["max_pages"]
            quality_threshold = min_quality_score
            dedup_stem = bool(dedup_by_stem)

            attempt = 1

            def _trace(action: str, *, fetched: bool, fetch_success: bool, fetch_error: str = "") -> None:
                relax_trace.append(
                    {
                        "attempt": attempt,
                        "action": action,
                        "max_pages": slot_max_pages,
                        "min_quality_score": quality_threshold,
                        "dedup_by_stem": dedup_stem,
                        "fetched": fetched,
                        "fetch_success": fetch_success,
                        "fetch_error": fetch_error,
                        "candidate_pool": len(candidates),
                        "selected_total": len(slot_selected),
                        "requested": requested,
                    }
                )

            # If prefetch failed (or returned empty), fetch once in-band.
            if not candidates:
                initial = await _run_slot_search(slot_item, slot_max_pages=slot_max_pages)
                if not initial.get("success"):
                    _trace(
                        "initial_fetch",
                        fetched=True,
                        fetch_success=False,
                        fetch_error=initial.get("error") or "search_failed",
                    )
                    sections.append(
                        {
                            "index": idx,
                            "slot": slot_item["slot"],
                            "success": False,
                            "error": initial.get("error") or "search_failed",
                            "requested": requested,
                            "selected": 0,
                            "question_ids": [],
                            "relax_trace": relax_trace,
                        }
                    )
                    continue

                candidates = list(initial.get("questions") or [])
                _sort_candidates(candidates)
                seen_candidate_ids = {
                    (q.get("question_id") or "").strip()
                    for q in candidates
                    if q.get("question_id")
                }
                _trace("initial_fetch", fetched=True, fetch_success=True)
                attempt += 1

            # Initial select (strict, no relaxation yet)
            newly = _select_more(
                candidates,
                remaining=requested - len(slot_selected),
                quality_threshold=quality_threshold,
                dedup_stem=dedup_stem,
            )
            slot_selected.extend(newly)
            _trace("initial_select", fetched=False, fetch_success=True)
            attempt += 1

            # 1) Auto-expand max_pages (requires extra network calls).
            while len(slot_selected) < requested and slot_max_pages < max_pages_cap:
                next_pages = min(max_pages_cap, slot_max_pages + 2)
                if next_pages <= slot_max_pages:
                    break
                slot_max_pages = next_pages

                expanded = await _run_slot_search(slot_item, slot_max_pages=slot_max_pages)
                if not expanded.get("success"):
                    _trace(
                        "increase_max_pages",
                        fetched=True,
                        fetch_success=False,
                        fetch_error=expanded.get("error") or "search_failed",
                    )
                    attempt += 1
                    break

                added = 0
                for q in expanded.get("questions") or []:
                    qid = (q.get("question_id") or "").strip()
                    if not qid or qid in seen_candidate_ids:
                        continue
                    seen_candidate_ids.add(qid)
                    candidates.append(q)
                    added += 1
                _sort_candidates(candidates)

                newly = _select_more(
                    candidates,
                    remaining=requested - len(slot_selected),
                    quality_threshold=quality_threshold,
                    dedup_stem=dedup_stem,
                )
                slot_selected.extend(newly)
                _trace("increase_max_pages", fetched=True, fetch_success=True)
                attempt += 1

            # 2) Auto-lower min_quality_score (no network).
            while len(slot_selected) < requested and quality_threshold > min_quality_floor:
                quality_threshold = max(min_quality_floor, quality_threshold - 10)
                newly = _select_more(
                    candidates,
                    remaining=requested - len(slot_selected),
                    quality_threshold=quality_threshold,
                    dedup_stem=dedup_stem,
                )
                slot_selected.extend(newly)
                _trace("lower_min_quality_score", fetched=False, fetch_success=True)
                attempt += 1

            # 3) Disable dedup_by_stem for this slot (no network).
            if len(slot_selected) < requested and dedup_stem:
                dedup_stem = False
                newly = _select_more(
                    candidates,
                    remaining=requested - len(slot_selected),
                    quality_threshold=quality_threshold,
                    dedup_stem=dedup_stem,
                )
                slot_selected.extend(newly)
                _trace("disable_dedup_by_stem", fetched=False, fetch_success=True)
                attempt += 1

            selected_questions.extend(slot_selected)
            sections.append(
                {
                    "index": idx,
                    "slot": slot_item["slot"],
                    "success": True,
                    "requested": requested,
                    "selected": len(slot_selected),
                    "question_ids": [q.get("question_id") for q in slot_selected if q.get("question_id")],
                    "relax_trace": relax_trace,
                }
            )

        question_ids = [q.get("question_id") for q in selected_questions if q.get("question_id")]
        return {
            "success": True,
            "count": len(question_ids),
            "question_ids": question_ids,
            "sections": sections,
            # 返回精简预览，避免输出过大
            "questions_preview": [
                {
                    "question_id": q.get("question_id"),
                    "type": q.get("type"),
                    "difficulty": q.get("difficulty"),
                    "difficulty_value": q.get("difficulty_value"),
                    "source": q.get("source"),
                    "date": q.get("date"),
                    "source_url": q.get("source_url") or (
                        f"https://zujuan.xkw.com/q/{q.get('question_id')}" if q.get("question_id") else ""
                    ),
                    "quality_score": q.get("quality_score"),
                    "quality_flags": q.get("quality_flags", []),
                }
                for q in selected_questions
            ],
        }

    async def filter_questions(
        self,
        question_ids: List[str],
        difficulty: str = "",
        question_type: str = "",
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        由于未登录无法精确过滤，此处简单截取并附带筛选字段。
        """
        questions = []
        for qid in question_ids[:limit]:
            questions.append(
                {
                    "question_id": qid,
                    "type": question_type,
                    "difficulty": difficulty,
                    "knowledge_point": "",
                    "source_url": self._question_url(qid),
                }
            )
        return {"success": True, "count": len(questions), "questions": questions}

    async def get_question_info(self, question_id: str) -> Dict[str, Any]:
        """
        无登录版仅返回基础元数据和链接。
        """
        return {
            "success": True,
            "question_id": question_id,
            "type": "",
            "difficulty": "",
            "knowledge_points": "",
            "year": "",
            "source": "",
            "url": self._question_url(question_id),
        }

    def _build_curl_cmd(self, url: str, timeout: int = 30, use_login_cookie: bool = True) -> list:
        """构建带header的curl命令"""
        cmd = [
            'curl', '-s',
            '-H', f'User-Agent: {self.user_agent}',
            '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            '-H', 'Accept-Language: zh-CN,zh;q=0.9,en;q=0.8',
            '-H', 'Referer: https://zujuan.xkw.com/',
        ]

        # 优先使用登录 cookie（反爬能力更强）
        cookie_to_use = self.cookies
        if use_login_cookie:
            env_session = _load_env_login()
            if env_session.get("is_logged_in") and env_session.get("cookies"):
                cookie_to_use = env_session["cookies"]

        if cookie_to_use:
            cmd.extend(['-H', f'Cookie: {cookie_to_use}'])
        cmd.append(url)
        return cmd

    async def _fetch_formula_svg(self, png_url: str) -> str:
        """获取公式的SVG源码"""
        svg_url = png_url.replace('.png', '.svg')
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ['curl', '-s', svg_url],
                    capture_output=True,
                    timeout=10
                )
            )
            svg = result.stdout.decode('utf-8', errors='ignore')
            if svg.startswith('<svg'):
                return svg
        except:
            pass
        return ""

    async def _replace_formulas_with_latex(self, html: str) -> str:
        """
        将HTML中的公式图片替换为LaTeX表达式
        使用字形签名精确匹配法（非OCR），精确度高
        """
        try:
            # 导入SVG转LaTeX工具
            from utils.svg_to_latex import replace_formulas_with_latex, svg_content_to_latex

            # 使用工具替换公式
            # 静态资源域名通常允许较高并发，适当提高并发以显著减少等待时间
            result, unknown_sigs = await replace_formulas_with_latex(html, concurrency=12, use_advanced=True)

            # 如果有未识别的签名，记录到文件用于后续完善签名库
            if unknown_sigs:
                try:
                    from utils.unknown_signatures import record_unknown_signatures
                    # unknown_sigs 格式为 {svg_url: [sig1, sig2, ...]}
                    for svg_url, sigs in unknown_sigs.items():
                        if sigs:
                            record_unknown_signatures(
                                unknown_sigs=sigs,
                                source_url=svg_url,
                                context=None
                            )
                except ImportError:
                    pass  # 模块不存在时静默忽略

            return result
        except ImportError:
            # 如果导入失败，回退到SVG源码模式
            return await self._replace_formulas_with_svg(html)
        except Exception as e:
            # 其他错误也回退
            print(f"LaTeX转换失败，回退到SVG模式: {e}")
            return await self._replace_formulas_with_svg(html)

    async def _replace_formulas_with_svg(self, html: str) -> str:
        """将HTML中的公式图片替换为SVG源码（回退方案）"""
        # 找到所有公式图片
        formula_pattern = r'<img[^>]*src="(https://[^"]+/formula/[^"]+\.png)"[^>]*>'
        matches = list(set(re.findall(formula_pattern, html)))

        if not matches:
            return html

        # 批量获取SVG（限制数量避免太慢）
        svg_map = {}
        for url in matches[:20]:
            svg = await self._fetch_formula_svg(url)
            if svg:
                svg_map[url] = svg

        # 替换
        result = html
        for png_url, svg in svg_map.items():
            # 用SVG源码替换img标签，添加标记方便AI识别
            img_pattern = f'<img[^>]*src="{re.escape(png_url)}"[^>]*>'
            result = re.sub(img_pattern, f'[公式:{svg}]', result)

        return result

    async def _replace_formulas_with_inline_svg(self, html: str) -> str:
        """
        将HTML中的公式图片替换为内联 SVG（用于前端渲染）。

        说明：
        - 公式图片通常在 /formula/*.png 下，可替换为对应的 .svg 内容。
        - 该模式不做 svg->latex 转换，避免转换误差。
        """
        formula_pattern = r'<img[^>]*src="([^"]+)"[^>]*>'
        matches = re.findall(formula_pattern, html)
        formula_srcs = []
        for src in matches:
            if "/formula/" not in src:
                continue
            if not src.endswith(".png"):
                continue
            formula_srcs.append(src)

        # Preserve order + de-dupe
        formula_srcs = list(dict.fromkeys(formula_srcs))
        if not formula_srcs:
            return html

        svg_map = {}
        for src in formula_srcs[:20]:
            resolved = src
            if resolved.startswith("//"):
                resolved = f"https:{resolved}"
            elif resolved.startswith("/"):
                resolved = f"{self.base_url.rstrip('/')}{resolved}"
            svg = await self._fetch_formula_svg(resolved)
            if svg:
                svg_map[src] = svg

        result = html
        for src, svg in svg_map.items():
            img_pattern = f'<img[^>]*src="{re.escape(src)}"[^>]*>'
            replacement = f'<span class="epa-formula" data-formula-src="{src}">{svg}</span>'
            result = re.sub(img_pattern, replacement, result)

        return result

    async def get_question_detail(
        self,
        question_id: str,
        *,
        formula_mode: str = "latex",
        stem_mode: str = "text",
    ) -> Dict[str, Any]:
        """
        使用 curl 获取题目详情（httpx会被反爬拦截）。
        返回题目的题干、选项、答案、解析等信息。

        Args:
            formula_mode:
                - "latex"（默认）：将公式图片替换为 LaTeX（字形签名精确匹配，非OCR）。
                - "svg"：将公式图片替换为 SVG（用于 AI/前端渲染，避免 svg2latex 转换误差）。
            stem_mode:
                - "text"（默认）：返回 `stem`（纯文本，必要时含 [公式:<svg...>] 标记）。
                - "html"：额外返回 `stem_html`（HTML 片段，公式为内联 SVG）。
        """
        url = self._question_url(question_id)
        formula_mode = (formula_mode or "").strip().lower()
        stem_mode = (stem_mode or "").strip().lower()

        try:
            # 使用curl获取页面（在线程池中运行避免阻塞）
            loop = asyncio.get_event_loop()
            cmd = self._build_curl_cmd(url)
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=30
                )
            )
            html = result.stdout.decode('utf-8', errors='ignore')

            if len(html) < 10000:  # 被反爬拦截
                # 检查是否已登录
                env_session = _load_env_login()
                if not env_session.get("is_logged_in"):
                    return {
                        "success": False,
                        "question_id": question_id,
                        "error": "页面被反爬拦截，请先登录",
                        "login_required": True,
                        "url": url,
                        "login_instructions": [
                            "获取题目详情需要登录：",
                            "1. 双击运行 scripts/登录组卷网.bat",
                            "2. 在弹出的浏览器中登录组卷网",
                            "3. 登录成功后按回车保存",
                            "4. 重新获取题目详情"
                        ]
                    }
                else:
                    return {
                        "success": False,
                        "question_id": question_id,
                        "error": "页面被反爬拦截，Cookie 可能已过期",
                        "cookie_expired": True,
                        "url": url,
                        "login_instructions": [
                            "Cookie 已过期，请重新登录：",
                            "1. 双击运行 scripts/登录组卷网.bat",
                            "2. 在弹出的浏览器中登录组卷网",
                            "3. 登录成功后按回车保存",
                            "4. 重新获取题目详情"
                        ]
                    }

            res = {
                "success": True,
                "question_id": question_id,
                "url": url,
            }

            # 提取题型和难度
            info_match = re.search(r'<span class="info-item">题型：([^<]+)</span>', html)
            res["type"] = info_match.group(1).strip() if info_match else ""

            diff_match = re.search(r'<span class="info-item">难度：([^<]+)</span>', html)
            res["difficulty"] = diff_match.group(1).strip() if diff_match else ""

            # 提取题干（class="quest-cnt " 注意有空格）
            stem_match = re.search(r'<div class="quest-cnt\s*">([\s\S]*?)</div>\s*<div class="quest-exam">', html)
            if stem_match:
                stem_html = stem_match.group(1)
                if formula_mode == "svg":
                    if stem_mode == "html":
                        stem_html = await self._replace_formulas_with_inline_svg(stem_html)
                    else:
                        stem_html = await self._replace_formulas_with_svg(stem_html)
                else:
                    stem_html = await self._replace_formulas_with_latex(stem_html)

                if stem_mode == "html":
                    res["stem_html"] = stem_html

                # 清理HTML标签（保留 LaTeX 或 [公式:<svg...>] 标记）
                stem_text = re.sub(r'<[^>]+>', '', stem_html)
                stem_text = re.sub(r'\s+', ' ', stem_text).strip()
                res["stem"] = stem_text[:3000]
            else:
                res["stem"] = ""
                if stem_mode == "html":
                    res["stem_html"] = ""

            # 提取知识点
            kp_matches = re.findall(r'class="knowledge-name[^"]*"[^>]*>([^<]+)</a>', html)
            res["knowledge_points"] = ', '.join(kp_matches) if kp_matches else ""

            # 提取来源
            source_match = re.search(r'class="src-item[^"]*"[^>]*title="([^"]+)"', html)
            res["source"] = source_match.group(1).strip() if source_match else ""

            # 答案需要登录
            res["answer"] = "(需登录查看)"
            res["options"] = []

            return res

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "question_id": question_id,
                "error": "请求超时",
                "url": url
            }
        except Exception as e:
            return {
                "success": False,
                "question_id": question_id,
                "error": str(e),
                "url": url
            }

    async def batch_get_question_details(self, question_ids: List[str], max_concurrent: int = 5) -> Dict[str, Any]:
        """
        批量获取题目详情。
        """
        if not question_ids:
            return {"success": True, "questions": [], "count": 0}

        # 限制最多10个
        question_ids = question_ids[:10]

        results = []
        # 分批执行，避免并发过高
        for i in range(0, len(question_ids), max_concurrent):
            batch = question_ids[i:i + max_concurrent]
            tasks = [self.get_question_detail(qid) for qid in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for qid, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "success": False,
                        "question_id": qid,
                        "error": str(result)
                    })
                else:
                    results.append(result)
            # 添加小延迟避免请求过快（减少延迟以提升速度）
            if i + max_concurrent < len(question_ids):
                await asyncio.sleep(0.2)

        return {
            "success": True,
            "questions": results,
            "count": len(results)
        }

    async def export_to_basket(
        self,
        question_ids: List[str],
        question_details: Optional[List[Dict]] = None,
        auto_login: bool = True,
        auto_switch_subject: bool = True,
    ) -> Dict[str, Any]:
        """
        导出题目到组卷网题篮

        Args:
            question_ids: 题目ID列表
            question_details: 题目详情列表（可选，如果提供则使用其中的信息）
            auto_login: 未登录时是否自动弹出登录窗口
            auto_switch_subject: Cookie题库不一致时是否自动切换bankId

        Returns:
            导出结果，包含成功/失败状态和消息
        """
        # 获取登录会话
        session = await _get_login_session_with_playwright()

        if not session.get("is_logged_in"):
            if auto_login:
                # 自动弹出登录窗口
                print("检测到未登录，正在打开登录窗口...")
                login_result = await self.login_interactive()

                if not login_result.get("success"):
                    return {
                        "success": False,
                        "error": "登录失败或用户取消登录",
                        "login_required": True
                    }

                # 重新获取会话
                session = await _get_login_session_with_playwright()

                if not session.get("is_logged_in"):
                    return {
                        "success": False,
                        "error": "登录后仍无法获取会话，请重试",
                        "login_required": True
                    }
            else:
                return {
                    "success": False,
                    "error": "未登录组卷网，请先在浏览器中登录 https://zujuan.xkw.com",
                    "login_required": True,
                    "help": "提示：首次使用需要在浏览器中登录组卷网，登录状态会被保存"
                }

        # 构建题篮数据
        basket_items = []
        current_time = int(time.time() * 1000)  # 毫秒时间戳

        # 如果有详情，使用详情中的信息
        details_map = {}
        if question_details:
            for d in question_details:
                if d.get("question_id"):
                    details_map[str(d["question_id"])] = d

        for idx, qid in enumerate(question_ids):
            detail = details_map.get(str(qid), {})

            # 题型映射
            type_name = detail.get("type", "解答题")
            type_id_map = {
                "单选题": 2701, "选择题": 2701,
                "多选题": 2702,
                "填空题": 2703,
                "解答题": 2704,
                "判断题": 2705,
            }
            ques_type_id = type_id_map.get(type_name, 2704)

            # 难度映射 (1-5, 5为最难)
            diff_name = detail.get("difficulty", "中等")
            diff_map = {"简单": 2, "中等": 3, "困难": 5, "较难": 4, "容易": 1}
            ques_diff = diff_map.get(diff_name, 3)

            item = {
                "questionId": int(qid),
                "addTime": current_time + idx,  # 确保每个题目时间戳不同
                "childNum": 1,
                "quesDiff": ques_diff,
                "quesTypeId": ques_type_id,
                "quesTypeName": type_name,
                "status": "CHECK",
                "from": detail.get("source", "AI组卷"),
                "ext": {
                    "isSelectType": ques_type_id in [2701, 2702],
                    "title": detail.get("source", ""),
                    "categoryName": detail.get("knowledge_points", ""),
                    "categoryId": 0
                }
            }
            basket_items.append(item)

        # 构建请求数据
        basket_json = json.dumps(basket_items, ensure_ascii=False)

        # 导出时使用“当前学科”的 bankId；若登录态 cookie 的 bankId 不一致，通常会导致导出不生效
        export_bank_id = str(self.bank_id)
        cookie_str = session.get("cookies", "") or ""
        cookie_bank_id: Optional[str] = None
        cookie_bank_id_original: Optional[str] = None
        cookie_switched = False
        if cookie_str:
            cookie_dict = _parse_cookie_string(cookie_str)
            cookie_bank_id = cookie_dict.get("bankId")
            cookie_bank_id_original = cookie_bank_id
            if export_bank_id and cookie_bank_id != export_bank_id:
                if auto_switch_subject:
                    cookie_dict["bankId"] = export_bank_id
                    cookie_str = _build_cookie_string(cookie_dict)
                    session["cookies"] = cookie_str
                    cookie_bank_id = export_bank_id
                    cookie_switched = True
                    refreshed_csrf = await _fetch_csrf_token_from_page(cookie_str)
                    if refreshed_csrf:
                        session["csrf_token"] = refreshed_csrf
                else:
                    return {
                        "success": False,
                        "error": (
                            f"当前登录态题库(bankId={cookie_bank_id})与当前学科“{self.subject}”(bankId={export_bank_id})不一致，"
                            "请切换到目标学科后重新登录保存Cookie再导出"
                        ),
                        "user_action_required": True,
                        "bank_id_cookie": cookie_bank_id,
                        "bank_id_target": export_bank_id,
                        "login_instructions": [
                            f"1. 打开 https://zujuan.xkw.com/ 并在左上角切换到“{self.subject}”",
                            f"2. 运行 scripts/登录组卷网.bat \"{self.subject}\" 重新登录并保存 Cookie",
                            "3. 再次执行导出",
                        ],
                    }

        payload = {
            "bankId": export_bank_id,
            "syncFlag": "9",
            "basketJson": basket_json
        }

        # 发送请求
        try:
            referer_url = "https://zujuan.xkw.com/"
            if question_ids:
                # 使用题目页作为 Referer，避免学科入口路径（如 gzsx）硬编码
                referer_url = f"{self.base_url}/{export_bank_id}q{question_ids[0]}.html"

            headers = {
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": session["cookies"],
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://zujuan.xkw.com",
                "Referer": referer_url,
            }

            # 添加CSRF token
            if session.get("csrf_token"):
                headers["RequestVerification"] = session["csrf_token"]

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                    data=payload,
                    headers=headers
                )

                # 检测 cookie 过期的情况
                if resp.status_code in [401, 403]:
                    return {
                        "success": False,
                        "error": "登录已过期，请重新登录",
                        "cookie_expired": True,
                        "login_instructions": [
                            "Cookie 已过期，请重新登录：",
                            "1. 双击运行 scripts/登录组卷网.bat",
                            "2. 在弹出的浏览器中登录组卷网",
                            "3. 登录成功后按回车保存",
                            "4. 重新尝试导出"
                        ]
                    }

                if resp.status_code == 200:
                    result = resp.json() if resp.text else {}

                    # 检查响应内容是否表示未登录
                    if isinstance(result, dict):
                        # 检查常见的未登录响应
                        error_code = result.get("code") or result.get("errCode") or result.get("status")
                        error_msg = result.get("msg") or result.get("message") or result.get("error") or ""

                        if error_code in [401, 403, -1, 1001] or "登录" in str(error_msg) or "login" in str(error_msg).lower():
                            return {
                                "success": False,
                                "error": "登录已过期，请重新登录",
                                "cookie_expired": True,
                                "api_response": result,
                                "login_instructions": [
                                    "Cookie 已过期，请重新登录：",
                                    "1. 双击运行 scripts/登录组卷网.bat",
                                    "2. 在弹出的浏览器中登录组卷网",
                                    "3. 登录成功后按回车保存",
                                    "4. 重新尝试导出"
                                ]
                            }

                    # 兼容：有时 API 会返回 200 但未真正写入题篮（questions 为空）
                    questions = result.get("questions") if isinstance(result, dict) else None
                    if not isinstance(questions, list):
                        questions = []

                    requested_ids = []
                    for qid in question_ids:
                        try:
                            requested_ids.append(int(qid))
                        except Exception:
                            pass
                    requested_set = set(requested_ids)
                    returned_set = set()
                    for q in questions:
                        try:
                            returned_set.add(int(q.get("questionId")))
                        except Exception:
                            pass

                    hit_ids = sorted(requested_set.intersection(returned_set))
                    if len(question_ids) > 0 and len(hit_ids) == 0:
                        auto_switch_note = "（已尝试自动切换学科Cookie）" if cookie_switched else ""
                        return {
                            "success": False,
                            "error": (
                                "导出未生效：sync_baskets 返回空题篮或未包含所选题目"
                                f"{auto_switch_note}（通常是 bankId 与登录态 token 不一致，请在网页切到“{self.subject}”后重新登录再导出）"
                            ),
                            "bank_id_used": export_bank_id,
                            "bank_id_cookie": cookie_bank_id,
                            "bank_id_cookie_original": cookie_bank_id_original,
                            "auto_switched_subject": cookie_switched,
                            "referer_used": referer_url,
                            "api_response": result,
                            "debug": {
                                "requested_count": len(question_ids),
                                "returned_count": len(questions),
                                "returned_sample_ids": sorted(list(returned_set))[:10],
                            },
                            "user_action_required": True,
                            "login_instructions": [
                                f"1. 打开 https://zujuan.xkw.com/ 并确认左上角为“{self.subject}”",
                                f"2. 运行 scripts/登录组卷网.bat \"{self.subject}\" 重新登录并保存 Cookie",
                                "3. 再次执行导出",
                            ],
                        }

                    result_payload = {
                        "success": True,
                        "message": f"成功添加 {len(question_ids)} 道题目到组卷网题篮",
                        "question_count": len(question_ids),
                        "question_ids": question_ids,
                        "bank_id_used": export_bank_id,
                        "basket_url": "https://zujuan.xkw.com/basket/",
                        "api_response": result,
                        "note": "题目已同步到服务器，请在组卷网题篮中查看",
                    }
                    if cookie_switched:
                        result_payload["auto_switched_subject"] = True
                        result_payload["bank_id_cookie_original"] = cookie_bank_id_original
                    if len(hit_ids) != len(requested_set) and len(hit_ids) > 0:
                        missing_ids = sorted(list(requested_set.difference(hit_ids)))
                        result_payload["warning"] = "部分题目未出现在返回列表中，可能存在延迟或被过滤"
                        result_payload["missing_question_ids"] = [str(i) for i in missing_ids[:50]]
                    return result_payload
                else:
                    # 其他 HTTP 错误也可能是登录问题
                    error_text = resp.text[:500] if resp.text else ""
                    if "登录" in error_text or "login" in error_text.lower() or resp.status_code in [302, 307]:
                        return {
                            "success": False,
                            "error": "登录已过期，请重新登录",
                            "cookie_expired": True,
                            "login_instructions": [
                                "Cookie 已过期，请重新登录：",
                                "1. 双击运行 scripts/登录组卷网.bat",
                                "2. 在弹出的浏览器中登录组卷网",
                                "3. 登录成功后按回车保存",
                                "4. 重新尝试导出"
                            ]
                        }
                    return {
                        "success": False,
                        "error": f"API请求失败: HTTP {resp.status_code}",
                        "response": error_text
                    }

        except Exception as e:
            return {
                "success": False,
                "error": f"导出失败: {str(e)}"
            }

    async def login_interactive(self) -> Dict[str, Any]:
        """
        交互式登录：打开浏览器让用户手动登录
        登录成功后会话会被保存，后续可直接使用

        注意：在MCP等后台环境中可能无法直接弹出窗口，
        此时会尝试启动独立进程来显示登录窗口
        """
        try:
            from playwright.sync_api import sync_playwright
            import concurrent.futures

            def _sync_login():
                with sync_playwright() as p:
                    user_data_dir = os.path.join(os.path.dirname(__file__), ".playwright_data")
                    os.makedirs(user_data_dir, exist_ok=True)

                    # 使用非headless模式让用户登录
                    browser = p.chromium.launch_persistent_context(
                        user_data_dir,
                        headless=False,  # 显示浏览器
                    )
                    page = browser.pages[0] if browser.pages else browser.new_page()

                    # 打开登录页
                    page.goto("https://zujuan.xkw.com/", timeout=30000)

                    print("请在浏览器中登录组卷网...")
                    print("登录成功后，请关闭浏览器窗口")

                    # 等待用户关闭浏览器或登录成功
                    try:
                        # 等待userId cookie出现（表示登录成功）
                        page.wait_for_function(
                            "document.cookie.includes('userId=')",
                            timeout=300000  # 5分钟超时
                        )
                        print("检测到登录成功！")
                    except:
                        pass

                    # 获取登录状态
                    cookies = browser.cookies()
                    user_id = None
                    for c in cookies:
                        if c['name'] == 'userId':
                            user_id = c['value']
                            break

                    browser.close()

                    return {
                        "success": user_id is not None,
                        "user_id": user_id,
                        "message": "登录成功" if user_id else "未检测到登录"
                    }

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = await loop.run_in_executor(pool, _sync_login)
            return result

        except Exception as e:
            return {
                "success": False,
                "error": f"登录失败: {str(e)}"
            }

    async def login_via_subprocess(self) -> Dict[str, Any]:
        """
        通过启动独立子进程来执行登录
        用于MCP等后台环境无法直接显示GUI的情况
        """
        try:
            import sys

            project_root = os.path.dirname(os.path.dirname(__file__))
            scripts_dir = os.path.join(project_root, "scripts")
            bat_path = os.path.join(scripts_dir, "登录组卷网.bat")
            py_path = os.path.join(scripts_dir, "save_login.py")

            if not (os.path.exists(bat_path) or os.path.exists(py_path)):
                return {
                    "success": False,
                    "error": f"登录脚本不存在: {bat_path} / {py_path}"
                }

            # 使用 pythonw 或 start 命令启动独立窗口（Windows）
            if sys.platform == "win32":
                # Windows：在新窗口中运行，传入学科名以保存对应 bankId 的登录态
                if os.path.exists(bat_path):
                    cmd = f'start "组卷网登录" "{bat_path}" "{self.subject}"'
                else:
                    cmd = f'start "组卷网登录" cmd /c "python \"{py_path}\" --subject \"{self.subject}\""'
                subprocess.Popen(cmd, shell=True)
            else:
                # Linux/Mac：直接运行
                subprocess.Popen([sys.executable, py_path, "--subject", self.subject])

            return {
                "success": True,
                "message": f"已启动登录窗口，请在弹出的浏览器中登录并切换到“{self.subject}”",
                "note": "登录完成后请重新尝试导出"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"启动登录窗口失败: {str(e)}"
            }


# 手动测试
async def test_crawler():
    crawler = ZujuanCrawler()
    await crawler.initialize()
    try:
        print("测试关键词搜索（无需 Cookie）...")
        res = await crawler.search_by_keyword("函数", limit=5)
        print(res)
    finally:
        await crawler.close()


if __name__ == "__main__":
    asyncio.run(test_crawler())
