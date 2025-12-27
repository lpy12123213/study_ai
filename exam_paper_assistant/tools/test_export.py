"""
测试导出到组卷网API - 调试脚本
"""
import asyncio
import json
import re
import time
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

# 从.env加载登录信息
def load_env():
    env_data = {}
    with ENV_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_data[key.strip()] = value.strip()
    return env_data

async def test_export():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")
    csrf_token = env.get("ZUJUAN_CSRF_TOKEN", "")

    print(f"User ID: {env.get('ZUJUAN_USER_ID')}")
    print(f"CSRF Token (env): {csrf_token[:50]}...")

    # 从cookie中提取__RequestVerificationToken
    cookie_csrf = ""
    for part in cookies.split(";"):
        if "__RequestVerificationToken=" in part:
            cookie_csrf = part.split("=", 1)[1].strip()
            break
    print(f"CSRF Token (cookie): {cookie_csrf[:50]}...")

    # 先获取页面上的最新CSRF token
    print("\n=== 获取页面CSRF Token ===")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://zujuan.xkw.com/gzsx/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
                "Cookie": cookies,
            }
        )
        # 从页面提取token
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', resp.text)
        page_csrf = m.group(1) if m else ""
        print(f"CSRF Token (page): {page_csrf[:50]}..." if page_csrf else "Page CSRF: Not found")

        # 检查是否有basket版本信息
        basket_ver_match = re.search(r'"basketVersion":\s*(\d+)', resp.text)
        if basket_ver_match:
            print(f"Basket Version: {basket_ver_match.group(1)}")

    # 构建题目数据
    test_question_id = "70287"  # 测试用题目ID
    current_time = int(time.time() * 1000)

    basket_item = {
        "questionId": int(test_question_id),
        "addTime": current_time,
        "childNum": 1,
        "quesDiff": 3,
        "quesTypeId": 2703,
        "quesTypeName": "填空题",
        "status": "CHECK",
        "from": "测试导出",
        "ext": {
            "isSelectType": False,
            "title": "",
            "categoryName": "",
            "categoryId": 0
        }
    }

    basket_json = json.dumps([basket_item], ensure_ascii=False)
    print(f"\n=== 测试Payload ===")
    print(f"basketJson: {basket_json}")

    # 测试不同的请求方式
    test_cases = [
        ("RequestVerification", page_csrf or csrf_token),
        ("RequestVerificationToken", page_csrf or csrf_token),
        ("X-CSRF-TOKEN", page_csrf or csrf_token),
        ("X-RequestVerificationToken", page_csrf or csrf_token),
    ]

    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookies,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://zujuan.xkw.com",
        "Referer": "https://zujuan.xkw.com/gzsx/",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for header_name, token in test_cases:
            print(f"\n=== 测试 Header: {header_name} ===")
            headers = {**base_headers, header_name: token}

            payload = {
                "bankId": "11",  # 高中数学
                "syncFlag": "9",
                "basketJson": basket_json
            }

            resp = await client.post(
                "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                data=payload,
                headers=headers
            )

            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:500]}")

            # 检查题篮
            print("\n检查题篮状态...")
            basket_resp = await client.get(
                "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                params={"bankId": "11", "syncFlag": "9", "syncVersion": "0"},
                headers={**base_headers}
            )
            print(f"Basket Status: {basket_resp.status_code}")
            print(f"Basket Response: {basket_resp.text[:500]}")

            # 只测试第一个成功的
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("questions"):
                        print("*** 成功! ***")
                        break
                except:
                    pass

if __name__ == "__main__":
    asyncio.run(test_export())
