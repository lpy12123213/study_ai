"""
组卷网爬虫（无登录版）
仅返回题号和元数据，不抓取题干/答案。
核心思路：
- 使用公开的 /zujuan-api/search (SSE) 获取推荐的知识点/筛选参数
- 使用 /zujuan-api/question/list POST 拉取题目列表（返回 HTML），从中解析题号
- 使用 curl + Playwright获取的cookie 获取题目详情
- 支持导出题目到组卷网题篮（需要登录）
"""
import asyncio
import html as html_module
import json
import os
import re
import subprocess
import time
import urllib.parse
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
_ANTIBOT_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    ".cache",
    "zujuan_antibot_cookies.json",
)
_ANTIBOT_CACHE_TTL_SECONDS = 6 * 60 * 60


def _load_antibot_cookie_cache() -> str:
    try:
        if not os.path.exists(_ANTIBOT_CACHE_FILE):
            return ""
        with open(_ANTIBOT_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookie_str = (data.get("cookies") or "").strip()
        ts = float(data.get("ts") or 0)
        if not cookie_str:
            return ""
        if ts and (time.time() - ts) > _ANTIBOT_CACHE_TTL_SECONDS:
            return ""
        return cookie_str
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



def _parse_base_json(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    /zujuan-api/base 返回 var edu=[...] 形式，这里提取出 JSON。
    """
    m = re.search(r"var\s+edu\s*=\s*(\[[\s\S]+)", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
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

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None
        print("HTTP 客户端已关闭")

    async def _load_base_meta(self):
        """获取题型 ID 映射（不同学段共用常见题型名称）。"""
        if not self.client:
            return
        try:
            resp = await self.client.get(f"{self.base_url}/zujuan-api/base")
            data = _parse_base_json(resp.text)
            if not data:
                return
            # 构建名称 -> ID 映射（简单/常见题型）
            for edu in data:
                for bank in edu.get("QuesBankList", []):
                    for q in bank.get("QuesTypeList", []):
                        name = q.get("Name")
                        if name:
                            self.ques_type_map[name] = q.get("ID", 0)
        except Exception:
            pass

    async def _ai_search(self, keyword: str) -> Dict[str, Any]:
        """
        调用 /zujuan-api/search SSE，返回推荐的检索参数。
        """
        if not self.client:
            return {"success": False, "error": "client not initialized"}

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
                return {"success": True, "payload": end_payload}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_target_from_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从 SSE payload 中提取 question/list 所需参数。
        示例 payload.data.params: { bank_id, knowledges, ... }
        示例 url: /gzsx/zsd131011/o2  => pageName=zsd, categoryId=131011
        """
        url_path = payload.get("url", "")
        m = re.search(r"/[a-z]+/(?P<page>zsd|zj|zh|zs)(?P<cat>\d+)/o\d+", url_path)
        if not m:
            return None
        page_name = m.group("page")
        cat_id = m.group("cat")
        params = payload.get("data", {}).get("params", {})
        bank_id = params.get("bank_id") or params.get("bankId") or 0
        return {"page_name": page_name, "category_id": cat_id, "bank_id": bank_id}

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
        limit: int = 20,
        difficulty: str = "",
        question_type: str = "",
        max_pages: int = 3,
    ) -> Dict[str, Any]:
        """
        官方 AI 搜索无法解析意图时的兜底：直接访问 question/list。
        使用当前学科配置的 bankId 和 categoryId。
        """
        if question_type and not self.ques_type_map and self.client is not None:
            await self._ensure_base_meta_loaded()
        page_name = "zsd"
        bank_id = self.bank_id
        category_id = self.category_id

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

        return {
            "success": True,
            "keyword": "",
            "count": len(all_questions[:limit]),
            "questions": all_questions[:limit],
            "trace": {
                "method": "fallback",
                "target": {
                    "page_name": page_name,
                    "bank_id": bank_id,
                    "category_id": category_id,
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
                "quesType": str(self._question_type_code(question_type)),
                "quesDiff": str(diff_code),
                "quesYear": "0",
                "paperTypeId": "0",
                "scenarioizedTypeId": "0",
                "tagId": "0",
                "provinceId": "-1",
                "learngrade": "0",
                "term": "0",
                "orderBy": "2",
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
        }
        if len(sub_requests) > 1:
            debug_info["difficulty_codes"] = difficulty_codes
            debug_info["sub_requests"] = sub_requests
        if errors:
            debug_info["errors"] = errors

        return all_questions, debug_info

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

    async def search_by_keyword(
        self,
        keyword: str,
        subject: str = "",
        edu_level: str = "",
        limit: int = 20,
        difficulty: str = "",
        question_type: str = "",
        max_pages: int = 2,
        require_difficulty: bool = False,
        strict_subject: bool = True,
    ) -> Dict[str, Any]:
        """
        关键词搜索（无需登录）：SSE 得到推荐参数 -> question/list 获取完整题目信息。
        返回的 questions 包含题干、难度、知识点等完整信息。
        """
        try:
            _, difficulty = self._apply_search_constraints(
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

        base_meta_task = None
        if question_type and not self.ques_type_map and self.client is not None:
            # 按需加载题型映射，并与 AI 搜索并行以减少等待
            base_meta_task = asyncio.create_task(self._ensure_base_meta_loaded())

        ai_result = await self._ai_search(keyword)
        if not ai_result.get("success"):
            if base_meta_task:
                await base_meta_task
            return await self._fallback_question_list(
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                max_pages=max_pages,
            )

        payload = ai_result["payload"]
        target = self._parse_target_from_payload(payload)
        if not target:
            if base_meta_task:
                await base_meta_task
            return await self._fallback_question_list(
                limit=limit,
                difficulty=difficulty,
                question_type=question_type,
                max_pages=max_pages,
            )

        if base_meta_task:
            await base_meta_task

        all_questions: List[Dict[str, Any]] = []
        debug_pages = []
        for page_idx in range(1, max_pages + 1):
            questions, dbg = await self._fetch_question_list(
                page_name=target["page_name"],
                bank_id=target["bank_id"],
                category_id=target["category_id"],
                cur_page=page_idx,
                difficulty=difficulty,
                question_type=question_type,
                parse_content=True,  # 解析完整内容
            )
            all_questions.extend(questions)
            debug_pages.append(dbg)
            if len(all_questions) >= limit or (dbg.get("raw_count", 0) == 0):
                break

        return {
            "success": True,
            "keyword": keyword,
            "count": len(all_questions[:limit]),
            "questions": all_questions[:limit],
            "trace": {"target": target, "pages": debug_pages},
        }

    async def search_by_knowledge(
        self,
        knowledge_point: str,
        subject: str,
        edu_level: str = "",
        limit: int = 20,
        difficulty: str = "",
        question_type: str = "",
        max_pages: int = 2,
        require_difficulty: bool = False,
        strict_subject: bool = True,
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
            max_pages=max_pages,
            require_difficulty=require_difficulty,
            strict_subject=strict_subject,
        )

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

    async def get_question_detail(self, question_id: str) -> Dict[str, Any]:
        """
        使用 curl 获取题目详情（httpx会被反爬拦截）。
        返回题目的题干、选项、答案、解析等信息。
        公式图片会被替换为LaTeX表达式（使用字形签名精确匹配，非OCR）。
        """
        url = self._question_url(question_id)

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
                # 将公式图片替换为LaTeX表达式
                stem_html = await self._replace_formulas_with_latex(stem_html)
                # 清理HTML标签，保留LaTeX公式
                stem_text = re.sub(r'<[^>]+>', '', stem_html)
                stem_text = re.sub(r'\s+', ' ', stem_text).strip()
                res["stem"] = stem_text[:3000]
            else:
                res["stem"] = ""

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
