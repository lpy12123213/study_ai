from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from backend.crawler.interface import CrawlerInterface
from backend.core.subjects import SUBJECTS


async def diagnose_export(
    *,
    current_subject: str,
    crawler: Optional[CrawlerInterface],
    test_question_id: str = "70287",
) -> dict:
    """Diagnose export-to-zujuan (sync_baskets) issues and return a detailed report."""

    diagnosis: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": [],
        "issues": [],
        "recommendations": [],
        "raw_data": {},
    }

    # 1) Check .env login vars
    env_file = str(Path(__file__).resolve().parents[2] / ".env")
    env_check: Dict[str, Any] = {"name": "ENV文件检查", "status": "unknown", "details": {}}

    cookies = ""
    csrf_token = ""
    cookie_bank_id: Optional[str] = None

    if os.path.exists(env_file):
        env_check["status"] = "exists"
        try:
            env_data: Dict[str, str] = {}
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    env_data[key] = value

            user_id = env_data.get("ZUJUAN_USER_ID", "")
            csrf_token = env_data.get("ZUJUAN_CSRF_TOKEN", "")
            cookies = env_data.get("ZUJUAN_COOKIES", "")

            env_check["details"] = {
                "user_id": user_id if user_id else "❌ 未设置",
                "csrf_token_length": len(csrf_token) if csrf_token else 0,
                "cookies_length": len(cookies) if cookies else 0,
                "has_user_id_in_cookie": "userId=" in cookies,
            }

            if not user_id:
                diagnosis["issues"].append("❌ .env中未找到ZUJUAN_USER_ID，表示未登录")
                env_check["status"] = "missing_user_id"
            elif not cookies:
                diagnosis["issues"].append("❌ .env中未找到ZUJUAN_COOKIES")
                env_check["status"] = "missing_cookies"
            else:
                env_check["status"] = "ok"

        except Exception as exc:
            env_check["status"] = "error"
            env_check["error"] = str(exc)
            diagnosis["issues"].append(f"❌ 读取.env文件失败: {exc}")
    else:
        env_check["status"] = "not_found"
        diagnosis["issues"].append("❌ .env文件不存在")

    diagnosis["checks"].append(env_check)

    # 2) BankID mismatch between cookie and configured crawler subject
    bank_id_check: Dict[str, Any] = {"name": "BankID检查", "status": "unknown", "details": {}}

    if cookies:
        for part in cookies.split(";"):
            part = part.strip()
            if part.startswith("bankId="):
                cookie_bank_id = part.split("=", 1)[1].strip()
                break

        config_bank_id = str(getattr(crawler, "bank_id", None) or "11") if crawler else "11"

        cookie_subject = "未知"
        config_subject = str(current_subject or "").strip()
        for subj_name, subj_config in SUBJECTS.items():
            if str(subj_config.get("bank_id")) == str(cookie_bank_id or "").strip():
                cookie_subject = subj_name
                break

        bank_id_check["details"] = {
            "cookie_bank_id": cookie_bank_id or "❌ 未找到",
            "cookie_subject": cookie_subject,
            "config_bank_id": config_bank_id,
            "config_subject": config_subject,
            "match": cookie_bank_id == config_bank_id if cookie_bank_id else False,
        }

        if not cookie_bank_id:
            diagnosis["issues"].append("⚠️ Cookie中未找到bankId")
            bank_id_check["status"] = "missing"
        elif cookie_bank_id != config_bank_id:
            diagnosis["issues"].append(
                f"⚠️ BankID不匹配: Cookie中是{cookie_subject}(bankId={cookie_bank_id}), 当前配置是{config_subject}(bankId={config_bank_id})"
            )
            bank_id_check["status"] = "mismatch"
            bank_id_check["note"] = f"当前登录态题库为 {cookie_subject}，导出目标为 {config_subject}"
            diagnosis["recommendations"].append(f"💡 请先切换到“{config_subject}”并重新登录保存Cookie，再执行导出")
        else:
            bank_id_check["status"] = "ok"
    else:
        bank_id_check["status"] = "no_cookies"

    diagnosis["checks"].append(bank_id_check)

    # 3) API connectivity test (sync_baskets)
    api_check: Dict[str, Any] = {"name": "API连通性测试", "status": "unknown", "details": {}}

    if cookies and csrf_token:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": cookies,
                    "Accept": "application/json",
                    "Origin": "https://zujuan.xkw.com",
                    "Referer": "https://zujuan.xkw.com/",
                    "RequestVerification": csrf_token,
                }

                # Prefer bankId found in cookie; fall back to crawler config.
                test_bank_id = cookie_bank_id if cookie_bank_id else str(getattr(crawler, "bank_id", None) or "11")

                resp = await client.post(
                    "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                    data={"bankId": test_bank_id, "syncFlag": "9", "basketJson": "[]"},
                    headers=headers,
                )
                api_check["details"]["empty_sync"] = {
                    "status_code": resp.status_code,
                    "bank_id_used": test_bank_id,
                }
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        api_check["details"]["empty_sync"]["response"] = {
                            "serverVersion": data.get("serverVersion"),
                            "questions_count": len(data.get("questions", [])),
                        }
                        diagnosis["raw_data"]["empty_sync_response"] = data
                    except Exception:
                        api_check["details"]["empty_sync"]["response_text"] = (resp.text or "")[:200]

                current_time = int(time.time() * 1000)
                test_basket = [
                    {
                        "questionId": int(test_question_id),
                        "addTime": current_time,
                        "childNum": 1,
                        "quesDiff": 3,
                        "quesTypeId": 2703,
                        "quesTypeName": "填空题",
                        "status": "CHECK",
                    }
                ]

                resp2 = await client.post(
                    "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                    data={
                        "bankId": test_bank_id,
                        "syncFlag": "9",
                        "basketJson": json.dumps(test_basket, ensure_ascii=False),
                    },
                    headers=headers,
                )
                api_check["details"]["add_question"] = {
                    "status_code": resp2.status_code,
                    "test_question_id": test_question_id,
                    "bank_id_used": test_bank_id,
                }

                if resp2.status_code == 200:
                    try:
                        data2 = resp2.json()
                        server_version = data2.get("serverVersion")
                        questions = data2.get("questions", [])
                        api_check["details"]["add_question"]["response"] = {
                            "serverVersion": server_version,
                            "questions_count": len(questions),
                            "question_ids_returned": [q.get("questionId") for q in questions[:5]],
                        }
                        diagnosis["raw_data"]["add_question_response"] = data2

                        test_qid = int(test_question_id)
                        question_added = any(q.get("questionId") == test_qid for q in questions)
                        if question_added:
                            api_check["status"] = "ok"
                            api_check["details"]["add_question"]["question_added"] = True
                        else:
                            api_check["status"] = "question_not_in_response"
                            api_check["details"]["add_question"]["question_added"] = False
                            diagnosis["issues"].append(f"⚠️ 题目{test_question_id}未出现在响应的questions中")

                    except Exception as exc:
                        api_check["details"]["add_question"]["parse_error"] = str(exc)
                        api_check["details"]["add_question"]["response_text"] = (resp2.text or "")[:200]
                else:
                    api_check["status"] = "http_error"
                    diagnosis["issues"].append(f"❌ API返回HTTP {resp2.status_code}")

        except Exception as exc:
            api_check["status"] = "error"
            api_check["error"] = str(exc)
            diagnosis["issues"].append(f"❌ API测试失败: {exc}")
    else:
        api_check["status"] = "skipped"
        api_check["reason"] = "缺少cookies或csrf_token"

    diagnosis["checks"].append(api_check)

    # 4) Suggestions
    if not diagnosis["issues"]:
        diagnosis["overall_status"] = "✅ 所有检查通过"
        diagnosis["recommendations"].append("导出功能应该正常工作，如果仍有问题请检查网络连接")
    else:
        diagnosis["overall_status"] = f"⚠️ 发现 {len(diagnosis['issues'])} 个问题"

        if any("未登录" in issue or "ZUJUAN_USER_ID" in issue for issue in diagnosis["issues"]):
            diagnosis["recommendations"].append(f'🔧 请运行 scripts/登录组卷网.bat "{current_subject}" 进行登录')

        if any("BankID不匹配" in issue for issue in diagnosis["issues"]):
            diagnosis["recommendations"].append(
                "🔧 如需导出到其他学科题篮，请在浏览器中切换到目标学科后重新登录保存Cookie"
            )
            diagnosis["recommendations"].append(
                f"🔧 例如：访问 https://zujuan.xkw.com/ 并切换到“{current_subject}”后重新运行登录脚本"
            )

        if any("API" in issue or "HTTP" in issue for issue in diagnosis["issues"]):
            diagnosis["recommendations"].append("🔧 检查网络连接，或尝试重新登录获取新的Cookie")

    diagnosis["debug_info"] = {
        "current_subject": current_subject,
        "crawler_bank_id": getattr(crawler, "bank_id", None) if crawler else None,
        "test_question_id": test_question_id,
    }

    return diagnosis
