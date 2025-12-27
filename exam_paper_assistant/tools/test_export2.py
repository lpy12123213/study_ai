"""
测试组卷网题篮API - 查找正确的添加接口
"""
import asyncio
import json
import re
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

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

async def test_add_basket():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")
    csrf_token = env.get("ZUJUAN_CSRF_TOKEN", "")

    base_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Cookie": cookies,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://zujuan.xkw.com",
        "Referer": "https://zujuan.xkw.com/gzsx/",
        "RequestVerification": csrf_token,
    }

    test_question_id = "70287"

    async with httpx.AsyncClient(timeout=30) as client:
        # 测试1: 直接添加到basket的API
        print("=== 测试 add_basket API ===")
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/add_basket",
            data={
                "bankId": "11",
                "questionId": test_question_id,
            },
            headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded"}
        )
        print(f"add_basket Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 测试2: basket/add API
        print("\n=== 测试 basket/add API ===")
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/basket/add",
            data={
                "bankId": "11",
                "questionId": test_question_id,
            },
            headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded"}
        )
        print(f"basket/add Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 测试3: question/add_basket API
        print("\n=== 测试 question/add_basket API ===")
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/question/add_basket",
            data={
                "bankId": "11",
                "questionId": test_question_id,
            },
            headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded"}
        )
        print(f"question/add_basket Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 测试4: addToBasket API
        print("\n=== 测试 addToBasket API ===")
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/addToBasket",
            data={
                "bankId": "11",
                "questionId": test_question_id,
            },
            headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded"}
        )
        print(f"addToBasket Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 测试5: 带JSON body的请求
        print("\n=== 测试 JSON body add_basket ===")
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/add_basket",
            json={
                "bankId": 11,
                "questionId": int(test_question_id),
            },
            headers={**base_headers, "Content-Type": "application/json"}
        )
        print(f"JSON add_basket Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 测试6: ques_basket
        print("\n=== 测试 ques_basket API ===")
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/ques_basket",
            data={
                "bankId": "11",
                "questionId": test_question_id,
                "operate": "add",
            },
            headers={**base_headers, "Content-Type": "application/x-www-form-urlencoded"}
        )
        print(f"ques_basket Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 测试7: 查看题篮页面获取API线索
        print("\n=== 获取题篮页面 ===")
        resp = await client.get(
            "https://zujuan.xkw.com/basket/",
            headers={**base_headers, "Accept": "text/html"}
        )
        print(f"Basket Page Status: {resp.status_code}")
        # 搜索API相关的JS代码
        api_matches = re.findall(r'/zujuan-api/[\w/]+', resp.text)
        print(f"Found APIs: {list(set(api_matches))[:20]}")

if __name__ == "__main__":
    asyncio.run(test_add_basket())
