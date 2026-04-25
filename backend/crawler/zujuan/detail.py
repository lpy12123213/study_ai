"""Zujuan question detail fetcher."""

from __future__ import annotations

import asyncio
import re
import subprocess
from typing import Any, Dict, List, Tuple

from backend.core.logging_utils import get_logger
from backend.crawler.zujuan.cookies import (
    load_env_login,
)

logger = get_logger(__name__)


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
            - "latex"（默认）：将公式图片替换为 LaTeX（优先 `{hash}.mml` MathML sidecar → pandoc；必要时回退 SVG 方案）。
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
        loop = asyncio.get_running_loop()
        cmd = self._build_curl_cmd(url)
        result = await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, timeout=30))
        html = result.stdout.decode("utf-8", errors="ignore")

        def _looks_like_login_page(text: str) -> bool:
            s = text or ""
            if not s:
                return False
            lower = s.lower()
            if "passport" in lower and "login" in lower:
                return True
            if "login" in lower and ("password" in lower or "username" in lower):
                return True
            if ("登录" in s or "登陆" in s) and ("密码" in s or "账号" in s or "用户名" in s):
                return True
            return False

        if len(html) < 10000 or _looks_like_login_page(html):  # 被反爬拦截/登录页
            # 检查是否已登录
            env_session = load_env_login()
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
                        "3. 登录成功后等待脚本自动保存",
                        "4. 重新获取题目详情",
                    ],
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
                        "3. 登录成功后等待脚本自动保存",
                        "4. 重新获取题目详情",
                    ],
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
            stem_text = re.sub(r"<[^>]+>", "", stem_html)
            stem_text = re.sub(r"\s+", " ", stem_text).strip()
            res["stem"] = stem_text[:3000]
        else:
            res["stem"] = ""
            if stem_mode == "html":
                res["stem_html"] = ""

        # 提取知识点
        kp_matches = re.findall(r'class="knowledge-name[^"]*"[^>]*>([^<]+)</a>', html)
        res["knowledge_points"] = ", ".join(kp_matches) if kp_matches else ""

        # 提取来源
        source_match = re.search(r'class="src-item[^"]*"[^>]*title="([^"]+)"', html)
        res["source"] = source_match.group(1).strip() if source_match else ""

        # Best-effort: extract answer/analysis when the page includes them (logged-in sessions).
        res["answer"] = ""
        res["analysis"] = ""
        res["options"] = []

        try:
            from bs4 import BeautifulSoup  # type: ignore
        except Exception:
            BeautifulSoup = None  # type: ignore

        def _extract_sections(text: str) -> Tuple[str, str]:
            raw = (text or "").strip()
            if not raw:
                return "", ""
            raw = re.sub(r"\r", "", raw)
            raw = re.sub(r"\n{3,}", "\n\n", raw)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return "", ""

            def _find_heading(keys: List[str]) -> int:
                for i, ln in enumerate(lines):
                    for k in keys:
                        k = (k or "").strip()
                        if not k:
                            continue
                        if ln == k or ln.startswith(f"{k}：") or ln.startswith(f"{k}:"):
                            return i
                        if ln.startswith(f"【{k}】") or ln.startswith(f"[{k}]"):
                            return i
                return -1

            answer_i = _find_heading(["答案", "参考答案", "答案与解析"])
            analysis_i = _find_heading(["解析", "解答", "参考解析", "答案解析"])

            def _inline_value(idx: int) -> str:
                if idx < 0:
                    return ""
                ln = lines[idx]
                m = re.search(r"(?:答案|参考答案|解析|解答)[:：]\\s*(.+)$", ln)
                if m and m.group(1):
                    return m.group(1).strip()
                return ""

            ans_inline = _inline_value(answer_i)
            ana_inline = _inline_value(analysis_i)

            ans = ans_inline
            ana = ana_inline

            def _slice(idx: int, next_idx: int) -> str:
                if idx < 0:
                    return ""
                start = idx + 1
                end = next_idx if next_idx > start else len(lines)
                block = "\n".join(lines[start:end]).strip()
                return block

            if not ans and answer_i >= 0:
                ans = _slice(answer_i, analysis_i)
            if not ana and analysis_i >= 0:
                # Stop at the next major heading if present (to avoid capturing whole pages).
                stop_i = len(lines)
                for j in range(analysis_i + 1, len(lines)):
                    if lines[j] in {"知识点", "考点", "易错点", "来源", "下载"}:
                        stop_i = j
                        break
                ana = _slice(analysis_i, stop_i)

            # Avoid placeholders like "登录后查看答案/解析".
            for key in ("登录", "登陆", "注册", "扫码", "会员"):
                if ans and key in ans and len(ans) < 40:
                    ans = ""
                if ana and key in ana and len(ana) < 60:
                    ana = ""

            if len(ans) > 6000:
                ans = ans[:5999].rstrip() + "…"
            if len(ana) > 12000:
                ana = ana[:11999].rstrip() + "…"
            return ans, ana

        try:
            if BeautifulSoup is not None:
                soup = BeautifulSoup(html, "lxml")
                for tag in soup.select("script,style"):
                    try:
                        tag.decompose()
                    except Exception:
                        continue
                raw_text = soup.get_text("\n", strip=True)
            else:
                raw_text = re.sub(r"<[^>]+>", "\n", html)

            ans, ana = _extract_sections(raw_text)
            if ans:
                res["answer"] = ans
            if ana:
                res["analysis"] = ana
        except Exception:
            logger.debug("zujuan_parse_answer_or_analysis_failed", exc_info=True)

        return res

    except subprocess.TimeoutExpired:
        return {"success": False, "question_id": question_id, "error": "请求超时", "url": url}
    except Exception as e:
        return {"success": False, "question_id": question_id, "error": str(e), "url": url}
