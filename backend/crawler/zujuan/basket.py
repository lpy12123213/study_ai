from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.core.logging_utils import get_logger
from backend.crawler.zujuan.cookies import (
    build_cookie_string,
    fetch_csrf_token_from_page,
    get_login_session_with_playwright,
    get_playwright_login_user_data_dir,
    parse_cookie_string,
)

logger = get_logger(__name__)


def _repo_relative_path(path: Path, *, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def resolve_login_script_paths(project_root: Path) -> Dict[str, Path]:
    scripts_dir = project_root / "scripts"
    canonical_dir = scripts_dir / "ops" / "crawler"
    wrapper_bat = scripts_dir / "登录组卷网.bat"
    canonical_bat = canonical_dir / "登录组卷网.bat"
    canonical_py = canonical_dir / "save_login.py"
    legacy_py = scripts_dir / "save_login.py"
    return {
        "wrapper_bat": wrapper_bat,
        "canonical_bat": canonical_bat,
        "canonical_py": canonical_py,
        "legacy_py": legacy_py,
    }


def build_login_subprocess_command(
    *,
    project_root: Path,
    subject: str,
    python_executable: str,
    platform_name: str,
) -> List[str]:
    paths = resolve_login_script_paths(project_root)
    bat_path = paths["wrapper_bat"] if paths["wrapper_bat"].exists() else paths["canonical_bat"]
    py_path = paths["canonical_py"] if paths["canonical_py"].exists() else paths["legacy_py"]

    if platform_name == "win32" and bat_path.exists():
        return [str(bat_path), subject]

    if py_path.exists():
        return [python_executable, str(py_path), "--subject", subject]

    raise FileNotFoundError(f"登录脚本不存在: {bat_path} / {py_path}")


async def _resolve_question_type_ids(crawler: Any) -> Dict[str, int]:
    type_map: Dict[str, int] = {}

    get_filters = getattr(crawler, "get_available_filters", None)
    if callable(get_filters):
        try:
            filters = await get_filters()
        except Exception:
            logger.warning("zujuan_question_type_filters_failed", exc_info=True)
            filters = {}
        for item in (filters or {}).get("question_types", []) or []:
            name_clean = str((item or {}).get("name") or "").strip()
            try:
                qid_int = int((item or {}).get("id") or 0)
            except (TypeError, ValueError):
                continue
            if name_clean and qid_int > 0:
                type_map[name_clean] = qid_int

    raw_map = getattr(crawler, "ques_type_map", None)
    if isinstance(raw_map, dict):
        for name, qid in raw_map.items():
            name_clean = str(name or "").strip()
            try:
                qid_int = int(qid or 0)
            except (TypeError, ValueError):
                continue
            if name_clean and qid_int > 0 and name_clean not in type_map:
                type_map[name_clean] = qid_int

    return type_map


def _resolve_export_question_type_id(type_name: str, type_map: Dict[str, int]) -> int:
    name = str(type_name or "").strip() or "解答题"
    candidates = [name]

    if "-" in name:
        base_name = name.split("-", 1)[0].strip()
        if base_name:
            candidates.append(base_name)

    aliases = {
        "单选题": ["选择题"],
        "选择题": ["单选题"],
        "多选题": ["选择题"],
        "简答题": ["解答题"],
        "综合题": ["解答题"],
        "问答题": ["解答题"],
        "实验题": ["解答题"],
    }
    extra_candidates: List[str] = []
    for candidate in list(candidates):
        extra_candidates.extend(aliases.get(candidate, []))
    candidates.extend(extra_candidates)

    for candidate in candidates:
        qid = int(type_map.get(candidate) or 0)
        if qid > 0:
            return qid

    legacy_type_id_map = {
        "单选题": 2701,
        "选择题": 2701,
        "多选题": 2702,
        "填空题": 2703,
        "解答题": 2704,
        "判断题": 2705,
    }
    return int(legacy_type_id_map.get(name, 2704))


def _is_select_question_type(type_name: str, ques_type_id: int, type_map: Dict[str, int]) -> bool:
    name = str(type_name or "").strip()
    candidates = {name}

    if "-" in name:
        base_name = name.split("-", 1)[0].strip()
        if base_name:
            candidates.add(base_name)

    if candidates.intersection({"单选题", "多选题", "选择题"}):
        return True

    select_ids = {2701, 2702}
    for candidate in ("单选题", "多选题", "选择题"):
        resolved_id = int(type_map.get(candidate) or 0)
        if resolved_id > 0:
            select_ids.add(resolved_id)

    return int(ques_type_id or 0) in select_ids


async def export_to_basket(
    crawler: Any,
    question_ids: List[str],
    question_details: Optional[List[Dict]] = None,
    auto_login: bool = True,
    auto_switch_subject: bool = True,
) -> Dict[str, Any]:
    session = await get_login_session_with_playwright()

    if not session.get("is_logged_in"):
        if auto_login:
            logger.info("zujuan not logged in; opening interactive login")
            login_result = await login_via_subprocess(crawler)
            if login_result.get("success"):
                return {
                    "success": False,
                    "error": "未登录组卷网，已弹出登录窗口，请登录后重试导出",
                    "login_required": True,
                    "login_started": True,
                    "help": "登录成功后重试当前导出即可。",
                }
            return {
                "success": False,
                "error": "未登录组卷网，请先在浏览器中登录 https://zujuan.xkw.com",
                "login_required": True,
                "help": "提示：首次使用需要在浏览器中登录组卷网，登录状态会被保存。",
            }
        return {
            "success": False,
            "error": "未登录组卷网，请先在浏览器中登录 https://zujuan.xkw.com",
            "login_required": True,
            "help": "提示：首次使用需要在浏览器中登录组卷网，登录状态会被保存。",
        }

    basket_items = []
    current_time = int(time.time() * 1000)
    details_map = {}
    type_id_map = await _resolve_question_type_ids(crawler)
    if question_details:
        for detail in question_details:
            if detail.get("question_id"):
                details_map[str(detail["question_id"])] = detail

    for idx, qid in enumerate(question_ids):
        detail = details_map.get(str(qid), {})
        type_name = detail.get("type", "解答题")
        ques_type_id = _resolve_export_question_type_id(type_name, type_id_map)

        diff_name = detail.get("difficulty", "中等")
        diff_map = {"简单": 2, "中等": 3, "困难": 5, "较难": 4, "容易": 1}
        ques_diff = diff_map.get(diff_name, 3)

        basket_items.append(
            {
                "questionId": int(qid),
                "addTime": current_time + idx,
                "childNum": 1,
                "quesDiff": ques_diff,
                "quesTypeId": ques_type_id,
                "quesTypeName": type_name,
                "status": "CHECK",
                "from": detail.get("source", "AI组卷"),
                "ext": {
                    "isSelectType": _is_select_question_type(type_name, ques_type_id, type_id_map),
                    "title": detail.get("source", ""),
                    "categoryName": detail.get("knowledge_points", ""),
                    "categoryId": 0,
                },
            }
        )

    basket_json = json.dumps(basket_items, ensure_ascii=False)
    export_bank_id = str(crawler.bank_id)
    cookie_str = session.get("cookies", "") or ""
    cookie_bank_id: Optional[str] = None
    cookie_bank_id_original: Optional[str] = None
    cookie_switched = False
    if cookie_str:
        cookie_dict = parse_cookie_string(cookie_str)
        cookie_bank_id = cookie_dict.get("bankId")
        cookie_bank_id_original = cookie_bank_id
        if export_bank_id and cookie_bank_id != export_bank_id:
            if auto_switch_subject:
                cookie_dict["bankId"] = export_bank_id
                cookie_str = build_cookie_string(cookie_dict)
                session["cookies"] = cookie_str
                cookie_bank_id = export_bank_id
                cookie_switched = True
                refreshed_csrf = await fetch_csrf_token_from_page(cookie_str)
                if refreshed_csrf:
                    session["csrf_token"] = refreshed_csrf
            else:
                return {
                    "success": False,
                    "error": (
                        f"当前登录态题库 bankId={cookie_bank_id} 与当前学科 “{crawler.subject}” bankId={export_bank_id} 不一致，"
                        "请切换到目标学科后重新登录保存 Cookie 再导出。"
                    ),
                    "user_action_required": True,
                    "bank_id_cookie": cookie_bank_id,
                    "bank_id_target": export_bank_id,
                    "login_instructions": [
                        f"1. 打开 https://zujuan.xkw.com/ 并在左上角切换到 “{crawler.subject}”",
                        f'2. 运行 scripts/登录组卷网.bat "{crawler.subject}" 重新登录并保存 Cookie',
                        "3. 再次执行导出",
                    ],
                }

    payload = {"bankId": export_bank_id, "syncFlag": "9", "basketJson": basket_json}

    try:
        referer_url = "https://zujuan.xkw.com/"
        if question_ids:
            referer_url = f"{crawler.base_url}/{export_bank_id}q{question_ids[0]}.html"

        headers = {
            "User-Agent": crawler.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": session["cookies"],
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://zujuan.xkw.com",
            "Referer": referer_url,
        }
        if session.get("csrf_token"):
            headers["RequestVerification"] = session["csrf_token"]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://zujuan.xkw.com/zujuan-api/sync_baskets", data=payload, headers=headers)

            if resp.status_code in [401, 403]:
                return {
                    "success": False,
                    "error": "登录已过期，请重新登录",
                    "cookie_expired": True,
                    "login_instructions": [
                        "Cookie 已过期，请重新登录：",
                        "1. 双击运行 scripts/登录组卷网.bat",
                        "2. 在弹出的浏览器中登录组卷网",
                        "3. 登录成功后等待脚本自动保存",
                        "4. 重新尝试导出",
                    ],
                }

            if resp.status_code != 200:
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
                            "3. 登录成功后等待脚本自动保存",
                            "4. 重新尝试导出",
                        ],
                    }
                return {
                    "success": False,
                    "error": f"API请求失败: HTTP {resp.status_code}",
                    "response": error_text,
                }

            result = resp.json() if resp.text else {}
            if isinstance(result, dict):
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
                            "3. 登录成功后等待脚本自动保存",
                            "4. 重新尝试导出",
                        ],
                    }

            questions = result.get("questions") if isinstance(result, dict) else None
            if not isinstance(questions, list):
                questions = []

            requested_ids = []
            for qid in question_ids:
                try:
                    requested_ids.append(int(qid))
                except (TypeError, ValueError):
                    logger.warning("zujuan_invalid_question_id", extra={"question_id": str(qid)}, exc_info=True)
            requested_set = set(requested_ids)
            returned_set = set()
            for question in questions:
                if not isinstance(question, dict):
                    continue
                try:
                    returned_set.add(int(question.get("questionId")))
                except (TypeError, ValueError):
                    logger.warning(
                        "zujuan_invalid_question_detail_id",
                        extra={"question_id": str(question.get("questionId") or "")},
                        exc_info=True,
                    )

            hit_ids = sorted(requested_set.intersection(returned_set))
            if question_ids and not hit_ids:
                auto_switch_note = "（已尝试自动切换学科 Cookie）" if cookie_switched else ""
                return {
                    "success": False,
                    "error": (
                        "导出未生效：sync_baskets 返回空题篮或未包含所选题目。"
                        f"{auto_switch_note}（通常是 bankId 与登录态 token 不一致，请在网页切到 “{crawler.subject}” 后重新登录再导出）"
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
                        f"1. 打开 https://zujuan.xkw.com/ 并确认左上角为 “{crawler.subject}”",
                        f'2. 运行 scripts/登录组卷网.bat "{crawler.subject}" 重新登录并保存 Cookie',
                        "3. 再次执行导出",
                    ],
                }

            payload = {
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
                payload["auto_switched_subject"] = True
                payload["bank_id_cookie_original"] = cookie_bank_id_original
            if len(hit_ids) != len(requested_set) and hit_ids:
                missing_ids = sorted(list(requested_set.difference(hit_ids)))
                payload["warning"] = "部分题目未出现在返回列表中，可能存在延迟或被过滤"
                payload["missing_question_ids"] = [str(i) for i in missing_ids[:50]]
            return payload

    except Exception as exc:
        logger.warning("zujuan_export_to_basket_failed", exc_info=True)
        return {"success": False, "error": f"导出失败: {exc}"}


async def login_interactive(_crawler: Any) -> Dict[str, Any]:
    try:
        import concurrent.futures

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        def _sync_login():
            with sync_playwright() as playwright:
                user_data_dir = str(get_playwright_login_user_data_dir().resolve())
                os.makedirs(user_data_dir, exist_ok=True)
                browser = playwright.chromium.launch_persistent_context(user_data_dir, headless=False)
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto("https://zujuan.xkw.com/", timeout=30000)

                logger.info("please login in the browser window (zujuan)")
                logger.info("after login, close the browser window")

                try:
                    page.wait_for_function("document.cookie.includes('userId=')", timeout=300000)
                    logger.info("login detected (zujuan)")
                except PlaywrightTimeoutError:
                    logger.info("zujuan_login_cookie_wait_timeout")

                cookies = browser.cookies()
                user_id = None
                for cookie in cookies:
                    if cookie["name"] == "userId":
                        user_id = cookie["value"]
                        break
                browser.close()

                return {
                    "success": user_id is not None,
                    "user_id": user_id,
                    "message": "登录成功" if user_id else "未检测到登录",
                }

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, _sync_login)
    except Exception as exc:
        logger.warning("zujuan_interactive_login_failed", exc_info=True)
        return {"success": False, "error": f"登录失败: {exc}"}


async def login_via_subprocess(crawler: Any) -> Dict[str, Any]:
    try:
        import sys

        try:
            from backend.core.subjects import SUBJECTS as valid_subjects

            if crawler.subject not in valid_subjects:
                return {"success": False, "error": f"非法学科名称: {crawler.subject}"}
        except ImportError:
            import re as regex

            if not regex.match(r"^[\u4e00-\u9fff\w]+$", crawler.subject or ""):
                return {"success": False, "error": f"学科名称包含非法字符: {crawler.subject}"}

        project_root = Path(__file__).resolve().parents[3]
        paths = resolve_login_script_paths(project_root)
        command = build_login_subprocess_command(
            project_root=project_root,
            subject=str(crawler.subject or "").strip(),
            python_executable=sys.executable,
            platform_name=sys.platform,
        )
        login_script_path = paths["wrapper_bat"] if paths["wrapper_bat"].exists() else paths["canonical_bat"]
        if not login_script_path.exists():
            login_script_path = paths["canonical_py"] if paths["canonical_py"].exists() else paths["legacy_py"]

        if sys.platform == "win32":
            subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(command)

        login_script = _repo_relative_path(login_script_path, project_root=project_root)
        login_command = (
            f'"{login_script}" "{crawler.subject}"'
            if login_script_path.suffix.lower() == ".bat"
            else f'"{sys.executable}" "{login_script}" --subject "{crawler.subject}"'
        )

        return {
            "success": True,
            "message": f"已启动登录窗口，请在弹出的浏览器中登录并切换到 “{crawler.subject}”",
            "note": "登录完成后请重新尝试导出",
            "login_script": login_script,
            "login_command": login_command,
        }
    except Exception as exc:
        logger.warning("zujuan_login_subprocess_failed", exc_info=True)
        return {"success": False, "error": f"启动登录窗口失败: {exc}"}
