"""
组卷网爬虫（无登录版）
仅返回题号和元数据，不抓取题干/答案。
核心思路：
- 使用公开的 /zujuan-api/search (SSE) 获取推荐的知识点/筛选参数
- 使用 /zujuan-api/question/list POST 拉取题目列表（返回 HTML），从中解析题号
- 使用 ZujuanCrawler 的 HTTP client 获取题目详情
- 支持导出题目到组卷网题篮（需要登录）
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.core.cache import TTLCache
from backend.core.logging_utils import get_logger
from backend.core.record_replay import RecordReplayStore, record_enabled, replay_enabled
from backend.core.settings import DIFFICULTY_QUERY_MODE
from backend.core.subjects import (
    DEFAULT_DIFFICULTY,
    normalize_difficulty,
    resolve_subject,
)
from backend.integrations.crawler.rate_limiter import get_rate_limiter
from backend.integrations.crawler.zujuan.cookies import (
    DEFAULT_USER_AGENT,
    build_cookie_string,
    get_cookies_with_playwright,
    get_login_session_with_playwright,
    load_antibot_cookie_cache,
    load_env_login,
    missing_antibot_keys,
    parse_cookie_string,
    save_antibot_cookie_cache,
)
from backend.integrations.crawler.zujuan.utils import (
    PROVINCE_UNLIMITED_ALIASES,
    _normalize_province_name,
    _parse_base_json,
    _parse_province_list_json,
    _safe_float,
    _safe_int,
)

logger = get_logger(__name__)
_record_replay_store = RecordReplayStore("crawler")


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
        self._cache = TTLCache(
            name=f"zujuan_cache:{subject}",
            max_entries=int(os.getenv("ZUJIAN_CACHE_MAX_ENTRIES") or "256"),
            default_ttl_s=0.0,
        )

        # /zujuan-api/base: QuesBankList[].courseId / courseIdPy
        # - courseId: observed as required by /zujuan-api/question/list (visitor mode)
        # - courseIdPy: used for building referer URLs like /gzsx/zsd{categoryId}/
        self.course_id: int = 0
        self.course_id_py: str = ""

        # Formula cache: {hash -> latex}, populated via {hash}.mml (MathML base64) + pandoc.
        self._formula_cache = TTLCache(
            name=f"zujuan_formula_cache:{subject}",
            max_entries=int(os.getenv("ZUJIAN_FORMULA_CACHE_MAX_ENTRIES") or "4096"),
            default_ttl_s=float(os.getenv("ZUJIAN_FORMULA_CACHE_TTL_S") or str(30 * 24 * 60 * 60)),
        )
        self._formula_inflight: Dict[str, "asyncio.Future[str]"] = {}
        self._formula_http_sem = asyncio.Semaphore(20)
        self._formula_pandoc_sem = asyncio.Semaphore(8)
        self._subject_lock = asyncio.Lock()

        # Global crawler rate limiter (process-local). This limits outbound requests
        # to reduce anti-bot triggers when multiple tasks run concurrently.
        rps_raw = os.getenv("ZUJUAN_RATE_LIMIT_RPS") or os.getenv("ZUJIAN_RATE_LIMIT_RPS") or "2.0"
        burst_raw = os.getenv("ZUJUAN_RATE_LIMIT_BURST") or os.getenv("ZUJIAN_RATE_LIMIT_BURST") or "4"
        try:
            rps = float(rps_raw)
        except (TypeError, ValueError):
            rps = 2.0
        try:
            burst = int(burst_raw)
        except (TypeError, ValueError):
            burst = 4
        self._http_rate_limiter = get_rate_limiter(key="zujuan", rate_per_s=rps, burst=burst)

        # 学科配置
        self.subject = subject
        self._load_subject_config()

    def _record_replay_request(self, fn: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Build a stable request object for record/replay fixtures.

        We intentionally exclude `self` (non-serializable) and drop `None` values to keep keys stable.
        """

        cleaned: Dict[str, Any] = {}
        for k, v in (kwargs or {}).items():
            if k in {"self", "impl"}:
                continue
            if v is None:
                continue
            if isinstance(v, Path):
                cleaned[k] = str(v)
            else:
                cleaned[k] = v

        return {
            "fn": str(fn or "").strip() or "unknown",
            "subject": str(getattr(self, "subject", "") or "").strip(),
            "bank_id": int(getattr(self, "bank_id", 0) or 0),
            "kwargs": cleaned,
        }

    def _maybe_replay(self, request_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not replay_enabled():
            return None
        fixture, key = _record_replay_store.load(request=request_obj)
        if not fixture:
            return None
        resp = fixture.get("response")
        if not isinstance(resp, dict):
            return None
        out = dict(resp)
        out.setdefault("record_replay", {"mode": "replay", "key": key})
        return out

    def _maybe_record(self, request_obj: Dict[str, Any], response_obj: Any) -> None:
        if not record_enabled():
            return
        try:
            _record_replay_store.save(request=request_obj, response=response_obj, meta={"fn": request_obj.get("fn")})
        except Exception:
            logger.warning("zujuan_record_replay_save_failed", extra={"fn": request_obj.get("fn")}, exc_info=True)
            return

    async def _apply_cookie_string(self, cookie_str: str) -> None:
        cookie_str = str(cookie_str or "").strip()
        if not cookie_str:
            return
        self.cookies = cookie_str
        if self.client is not None:
            try:
                self.client.headers["Cookie"] = cookie_str
            except (AttributeError, TypeError):
                return

    def _load_subject_config(self):
        """加载学科配置"""
        try:
            import sys
            from pathlib import Path

            sys.path.append(str(Path(__file__).parent.parent))
            from backend.core.subjects import get_subject_config

            config = get_subject_config(self.subject)
            self.bank_id = config["bank_id"]
            self.category_id = config["category_id"]
            self.edu_id = config["edu_id"]
            self.course_id = _safe_int(config.get("course_id"), 0)
            self.course_id_py = str(config.get("course_id_py") or "").strip()
        except Exception:
            logger.warning("zujuan_load_subject_config_failed", extra={"subject": self.subject}, exc_info=True)
            # 默认高中数学
            self.bank_id = 11
            self.category_id = "100693"
            self.edu_id = 3
            self.course_id = 0
            self.course_id_py = "gzsx"

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
        """初始化 HTTP 客户端。

        Search/list endpoints work in visitor mode. Avoid loading login cookies or
        bootstrapping anti-bot cookies unless explicitly requested, because using a
        stale account cookie can make otherwise-public requests look risky.
        """
        # 已初始化则复用（MCP 模式下避免每次工具调用都做一次网络/浏览器初始化）
        if self.client is not None:
            return

        def env_truthy(name: str, *, default: bool = False) -> bool:
            raw = str(os.getenv(name) or "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "y", "on"}

        use_env_cookies = env_truthy("ZUJUAN_USE_ENV_COOKIES_FOR_SEARCH", default=False)
        use_cached_antibot = env_truthy("ZUJUAN_USE_CACHED_ANTIBOT_COOKIES", default=False)
        auto_bootstrap = env_truthy("ZUJUAN_AUTO_BOOTSTRAP_COOKIES", default=False) or env_truthy(
            "ZUJIAN_AUTO_BOOTSTRAP_COOKIES", default=False
        )

        env_session = load_env_login() if use_env_cookies else {"cookies": "", "is_logged_in": False}
        env_cookies = (env_session.get("cookies") or "").strip()
        is_logged_in = bool(env_session.get("is_logged_in")) if use_env_cookies else False

        if use_env_cookies and env_cookies and not self.cookies:
            self.cookies = env_cookies

        env_cookie_dict = parse_cookie_string(self.cookies)

        # Optional: merge cached visitor anti-bot cookies. Disabled by default because
        # question/list can be requested without cookies and stale cookies can trigger WAF.
        cached_antibot = load_antibot_cookie_cache() if use_cached_antibot else ""
        if cached_antibot:
            cached_dict = parse_cookie_string(cached_antibot)
            cached_dict.update(env_cookie_dict)  # 以 .env Cookie 为准覆盖
            self.cookies = build_cookie_string(cached_dict)
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
            except (httpx.HTTPError, ValueError):
                return False

        missing_antibot = missing_antibot_keys(self.cookies)
        if auto_bootstrap and (missing_antibot or (self.cookies and not await cookie_can_access_api(self.cookies))):
            # 缺失/过期：用 Playwright 获取最新的反爬 Cookie，再与 .env Cookie 合并
            logger.info("refreshing zujuan antibot cookies via playwright")
            base_cookie_str = await get_cookies_with_playwright()
            if base_cookie_str:
                save_antibot_cookie_cache(base_cookie_str)
                base_cookie_dict = parse_cookie_string(base_cookie_str)
                base_cookie_dict.update(env_cookie_dict)  # 以 .env Cookie 为准覆盖
                self.cookies = build_cookie_string(base_cookie_dict)
                env_cookie_dict = base_cookie_dict

        # Optional fallback for environments that explicitly choose browser bootstrap.
        if auto_bootstrap and not self.cookies:
            logger.info("bootstrapping zujuan cookies via playwright")
            self.cookies = await get_cookies_with_playwright()
            if self.cookies:
                logger.info("zujuan cookie bootstrap ok", extra={"cookie_prefix": self.cookies[:50]})
            else:
                logger.warning("zujuan cookie bootstrap failed; some features may be limited")
        else:
            missing_antibot = missing_antibot_keys(self.cookies)
            if is_logged_in:
                logger.info("zujuan cookie mode: logged_in")
            elif env_cookies:
                logger.info("zujuan cookie mode: dotenv")
            elif not self.cookies:
                logger.info("zujuan cookie mode: visitor_no_cookie")
            else:
                logger.info("zujuan cookie mode: antibot" if not missing_antibot else "zujuan cookie mode: incomplete")

        async def _rate_limit(_request: httpx.Request) -> None:
            await self._http_rate_limiter.acquire(1.0)

        headers = {
            "User-Agent": self.user_agent,
        }
        if self.cookies:
            headers["Cookie"] = self.cookies

        client_kwargs = dict(
            headers=headers,
            timeout=30.0,
            event_hooks={"request": [_rate_limit]},
        )
        try:
            self.client = httpx.AsyncClient(http2=True, **client_kwargs)
        except ImportError:
            # http2 需要额外依赖（h2）；缺失时自动降级
            self.client = httpx.AsyncClient(**client_kwargs)
        logger.info("zujuan http client initialized")

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
            pname = item.get("name") or item.get("Name") or item.get("province_name") or item.get("provinceName") or ""
            pname = str(pname).strip()
            if not pname:
                continue

            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            provinces.append({"id": pid, "name": pname})

            raw_key = re.sub(r"\s+", "", pname)
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
        except (httpx.HTTPError, ValueError):
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

        raw_compact = re.sub(r"\s+", "", raw)
        if raw_compact in PROVINCE_UNLIMITED_ALIASES:
            return -1

        # Allow passing numeric ID via `province` to reduce caller friction.
        if raw_compact.isdigit():
            try:
                return int(raw_compact)
            except ValueError:
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
        logger.info("zujuan http client closed")

    def _cache_get(self, key: str) -> Optional[Any]:
        return self._cache.get(str(key or "").strip())

    def _cache_set(self, key: str, value: Any, ttl: float) -> None:
        self._cache.set(str(key or "").strip(), value, ttl_s=float(ttl or 0.0))

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

        # QuesBankList[].courseId / courseIdPy are useful for building referer
        # and required parameters for question/list.
        course_id = _safe_int(bank.get("courseId") or bank.get("courseID"), 0)
        if course_id:
            self.course_id = course_id
        course_id_py = str(bank.get("courseIdPy") or bank.get("courseIDPy") or "").strip()
        if course_id_py:
            self.course_id_py = course_id_py

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
            logger.exception("zujuan_load_base_meta_failed", extra={"subject": str(getattr(self, "subject", "") or "")})

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
                        except json.JSONDecodeError:
                            continue
                if not end_payload:
                    return {"success": False, "error": "未获取到搜索结果指引"}
                result = {"success": True, "payload": end_payload}
                self._cache_set(cache_key, result, ttl=15 * 60)
                return result
        except httpx.HTTPError as e:
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
        """Backwards-compatible wrapper around :func:`quality_score`.

        See :mod:`backend.integrations.crawler.zujuan.quality_score` for the
        rule list. Kept on the class to preserve the existing call sites.
        """

        from backend.integrations.crawler.zujuan.quality_score import quality_score

        return quality_score(question)

    def _parse_target_from_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从 SSE payload 中提取 question/list 所需参数。
        示例 payload.data.params: { bank_id, knowledges, ... }
        示例 url: /gzsx/zsd131011/o2  => pageName=zsd, categoryId=131011
        """
        url_path = str(payload.get("url") or "").strip()
        if not url_path:
            return None

        # Common variants:
        # - /gzsx/zsd131011/o2
        # - /gzyy/zsd0/qt2809o2   (qt filter packed with order suffix)
        course_id_py = ""
        m_course = re.search(r"^/([a-z]+)/", url_path)
        if m_course:
            course_id_py = m_course.group(1)

        m = re.search(r"/(zsd|zj|jtff|zhangjie)(\d+)", url_path)
        if not m:
            return None
        page_name = m.group(1)
        cat_id = m.group(2)

        qt_id = None
        m_qt = re.search(r"/qt(\d+)", url_path)
        if m_qt:
            qt_id = m_qt.group(1)

        order_by = None
        m_order = re.search(r"o(\d+)$", url_path)
        if m_order:
            order_by = m_order.group(1)

        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        params = data_obj.get("params", {}) if isinstance(data_obj.get("params"), dict) else {}
        bank_id = params.get("bank_id") or params.get("bankId") or 0
        course_id = params.get("course_id") or params.get("courseId") or 0
        target: Dict[str, Any] = {
            "page_name": page_name,
            "category_id": cat_id,
            "bank_id": bank_id,
        }
        if course_id:
            target["course_id"] = course_id
        if course_id_py:
            target["course_id_py"] = course_id_py
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
        # 注意：要区分“较难”(4) 与 “困难”(5)，不能仅凭包含“难”就一刀切。
        if "较难" in d or "偏难" in d:
            return 4
        if "困难" in d or "很难" in d:
            return 5
        if "难" in d:
            return 4
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
        require_difficulty_value: bool = False,
        dedup_by_stem: bool = False,
        min_quality_score: int = 0,
        with_quality: bool = True,
    ) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.question_list import fallback_question_list as impl

        kwargs = dict(locals())
        kwargs.pop("self", None)
        kwargs.pop("impl", None)
        return await impl(self, **kwargs)

    async def _fetch_question_list(
        self,
        page_name: str,
        bank_id: int,
        category_id: str,
        course_id: int = 0,
        course_id_py: str = "",
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
        from backend.integrations.crawler.zujuan.question_list import fetch_question_list as impl

        kwargs = dict(locals())
        kwargs.pop("self", None)
        kwargs.pop("impl", None)
        return await impl(self, **kwargs)

    async def _parse_questions_from_html(
        self,
        html: str,
        bank_id: int,
        *,
        parse_content: bool = True,
    ) -> List[Dict[str, Any]]:
        from backend.integrations.crawler.zujuan.question_parsing import parse_questions_from_html as impl

        kwargs = dict(locals())
        kwargs.pop("self", None)
        kwargs.pop("impl", None)
        return await impl(self, **kwargs)

    async def _batch_convert_formulas(
        self,
        questions: List[Dict[str, Any]],
        question_stems: List[Tuple[int, str]],
        *,
        convert_formulas: bool = True,
        stem_max_chars: int = 2500,
    ) -> None:
        from backend.integrations.crawler.zujuan.question_parsing import batch_convert_formulas as impl

        kwargs = dict(locals())
        kwargs.pop("self", None)
        kwargs.pop("impl", None)
        await impl(self, **kwargs)

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
        require_difficulty_value: bool = False,
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
                except (TypeError, ValueError):
                    logger.debug(
                        "zujuan_parse_date_year_failed",
                        extra={"date": str(date_str or ""), "expected_year": int(year or 0)},
                        exc_info=True,
                    )

        if difficulty_value_min is not None or difficulty_value_max is not None:
            dv = _safe_float(question.get("difficulty_value"))
            if dv is None:
                # Some questions don't expose the numeric difficulty coefficient. Keep the previous permissive
                # behavior unless the caller explicitly requires a coefficient for strict filtering.
                return not bool(require_difficulty_value)
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
        require_difficulty_value: Optional[bool] = None,
        require_difficulty: bool = False,
        strict_subject: bool = True,
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        dedup_by_stem: bool = False,
        min_quality_score: int = 0,
        with_quality: bool = True,
        parse_content: bool = True,
    ) -> Dict[str, Any]:
        async with self._subject_lock:
            from backend.integrations.crawler.zujuan.search import search_by_keyword as impl

            kwargs = dict(locals())
            kwargs.pop("impl", None)

            rr_req = self._record_replay_request("search_by_keyword", kwargs)
            replayed = self._maybe_replay(rr_req)
            if replayed is not None:
                return replayed

            res = await impl(**kwargs)
            self._maybe_record(rr_req, res)
            return res

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
        require_difficulty_value: Optional[bool] = None,
        require_difficulty: bool = False,
        strict_subject: bool = True,
        elective_mode: str = "",
        elective_keywords: Optional[List[str]] = None,
        exclude_elective: bool = False,
        dedup_by_stem: bool = False,
        min_quality_score: int = 0,
        with_quality: bool = True,
        parse_content: bool = True,
    ) -> Dict[str, Any]:
        async with self._subject_lock:
            from backend.integrations.crawler.zujuan.search import search_by_knowledge as impl

            kwargs = dict(locals())
            kwargs.pop("impl", None)

            rr_req = self._record_replay_request("search_by_knowledge", kwargs)
            replayed = self._maybe_replay(rr_req)
            if replayed is not None:
                return replayed

            res = await impl(**kwargs)
            self._maybe_record(rr_req, res)
            return res

    async def get_available_filters(self) -> Dict[str, Any]:
        """
        返回当前学科（bankId）下可用的筛选项（年级/试卷类型/教材版本/题型等）。
        用于 MCP/前端做下拉选择，避免“写死 ID”。
        """
        await self._ensure_bank_meta_loaded()
        await self._ensure_province_meta_loaded()

        grades = [
            {"id": gid, "name": name} for gid, name in sorted(self.learn_grade_id_to_name.items(), key=lambda x: x[0])
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
        slot_concurrency: int = 0,
        slot_delay_s: float = 0.0,
        slot_retries: int = 1,
    ) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.blueprint import compose_paper_blueprint as impl

        kwargs = dict(locals())
        kwargs.pop("impl", None)

        rr_req = self._record_replay_request("compose_paper_blueprint", kwargs)
        replayed = self._maybe_replay(rr_req)
        if replayed is not None:
            return replayed

        res = await impl(**kwargs)
        self._maybe_record(rr_req, res)
        return res

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

    def _resolve_url(self, url: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import resolve_url as impl

        return impl(self, url)

    def _formula_cache_get(self, formula_hash: str) -> Optional[str]:
        from backend.integrations.crawler.zujuan.formulas import formula_cache_get as impl

        return impl(self, formula_hash)

    def _formula_cache_set(self, formula_hash: str, latex: str) -> None:
        from backend.integrations.crawler.zujuan.formulas import formula_cache_set as impl

        impl(self, formula_hash, latex)

    async def _fetch_formula_mathml(self, formula_hash: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import fetch_formula_mathml as impl

        return await impl(self, formula_hash)

    async def _mathml_to_latex_via_pandoc(self, mathml_xml: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import mathml_to_latex_via_pandoc as impl

        return await impl(self, mathml_xml)

    async def _get_formula_latex(self, formula_hash: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import get_formula_latex as impl

        return await impl(self, formula_hash)

    async def _replace_formulas_with_latex(self, html: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import replace_formulas_with_latex as impl

        return await impl(self, html)

    async def _replace_formulas_with_svg(self, html: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import replace_formulas_with_svg as impl

        return await impl(self, html)

    async def _replace_formulas_with_inline_svg(self, html: str) -> str:
        from backend.integrations.crawler.zujuan.formulas import replace_formulas_with_inline_svg as impl

        return await impl(self, html)

    async def get_question_detail(
        self,
        question_id: str,
        *,
        formula_mode: str = "latex",
        stem_mode: str = "text",
    ) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.detail import get_question_detail as impl

        kwargs = dict(locals())
        kwargs.pop("impl", None)

        rr_req = self._record_replay_request("get_question_detail", kwargs)
        replayed = self._maybe_replay(rr_req)
        if replayed is not None:
            return replayed

        res = await impl(**kwargs)

        # Best-effort: when login cookie expires, try refreshing once before returning an error.
        try:
            cookie_expired = bool(res.get("cookie_expired")) if isinstance(res, dict) else False
            login_required = bool(res.get("login_required")) if isinstance(res, dict) else False
        except (AttributeError, TypeError):
            cookie_expired = False
            login_required = False

        auto_refresh = str(os.getenv("ZUJUAN_AUTO_REFRESH_LOGIN") or "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }
        if auto_refresh and (cookie_expired or login_required):
            try:
                session = await get_login_session_with_playwright(force_refresh=True)
                refreshed = str(session.get("cookies") or "").strip()
                if refreshed:
                    await self._apply_cookie_string(refreshed)
                    res = await impl(**kwargs)
            except Exception as exc:
                logger.warning("auto refresh login cookie failed", extra={"error": str(exc)}, exc_info=True)

        self._maybe_record(rr_req, res)
        return res

    async def batch_get_question_details(self, question_ids: List[str], max_concurrent: int = 5) -> Dict[str, Any]:
        """
        批量获取题目详情。
        """
        if not question_ids:
            return {"success": True, "questions": [], "count": 0}

        # 限制最多10个
        max_total_raw = (
            os.getenv("ZUJUAN_BATCH_GET_DETAILS_MAX")
            or os.getenv("ZUJUAN_BATCH_GET_DETAILS_LIMIT")
            or os.getenv("ZUJUAN_MAX_QUESTION_DETAILS")
            or "0"
        )
        max_total = _safe_int(max_total_raw, 0)
        max_total = max(0, min(max_total, 500))
        if max_total:
            question_ids = question_ids[:max_total]

        max_concurrent = _safe_int(max_concurrent, 5)
        max_concurrent = max(1, min(max_concurrent, 20))

        delay_raw = os.getenv("ZUJUAN_BATCH_GET_DETAILS_DELAY_S") or "0.2"
        try:
            delay_s = float(delay_raw)
        except (TypeError, ValueError):
            delay_s = 0.2
        delay_s = max(0.0, min(delay_s, 3.0))

        results = []
        # 分批执行，避免并发过高
        for i in range(0, len(question_ids), max_concurrent):
            batch = question_ids[i : i + max_concurrent]
            tasks = [self.get_question_detail(qid) for qid in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for qid, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({"success": False, "question_id": qid, "error": str(result)})
                else:
                    results.append(result)
            # 添加小延迟避免请求过快（减少延迟以提升速度）
            if delay_s > 0 and i + max_concurrent < len(question_ids):
                await asyncio.sleep(delay_s)

        return {"success": True, "questions": results, "count": len(results)}

    async def export_to_basket(
        self,
        question_ids: List[str],
        question_details: Optional[List[Dict]] = None,
        auto_login: bool = True,
        auto_switch_subject: bool = True,
    ) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.basket import export_to_basket as impl

        return await impl(
            self,
            question_ids,
            question_details=question_details,
            auto_login=auto_login,
            auto_switch_subject=auto_switch_subject,
        )

    async def login_interactive(self) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.basket import login_interactive as impl

        return await impl(self)

    async def login_via_subprocess(self) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.basket import login_via_subprocess as impl

        return await impl(self)

    async def get_knowledge_tree(self) -> Dict[str, Any]:
        from backend.integrations.crawler.zujuan.knowledge_tree import get_knowledge_tree as impl

        return await impl(self)

    def _parse_knowledge_sidebar(
        self, html_text: str, course_id_py: str, category_id: str, subject: str
    ) -> List[Dict[str, Any]]:
        from backend.integrations.crawler.zujuan.knowledge_tree import parse_knowledge_sidebar as impl

        return impl(self, html_text, course_id_py, category_id, subject)

    def _parse_sidebar_container(self, container, RE_ZSD_ID) -> List[Dict[str, Any]]:
        from backend.integrations.crawler.zujuan.knowledge_tree import parse_sidebar_container as impl

        return impl(self, container, RE_ZSD_ID)


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
