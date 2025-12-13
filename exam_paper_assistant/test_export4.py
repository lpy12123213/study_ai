"""
测试sync_baskets API - 仔细分析请求/响应格式
"""
import asyncio
import json
import httpx
import time

def load_env():
    env_data = {}
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_data[key.strip()] = value.strip()
    return env_data

async def test_sync_format():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")
    csrf_token = env.get("ZUJUAN_CSRF_TOKEN", "")

    # 从cookie提取basketVersion
    basket_version = ""
    for part in cookies.split(";"):
        if "questionBasketVersion" in part:
            basket_version = part.split("=")[1].strip()
        if "quesBasketVersion" in part:
            basket_version = part.split("=")[1].strip()

    print(f"Cookie basketVersion: {basket_version}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookies,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://zujuan.xkw.com",
        "Referer": "https://zujuan.xkw.com/gzsx/",
        "RequestVerification": csrf_token,
    }

    test_question_id = "70287"
    current_time = int(time.time() * 1000)

    # 简化的basket格式
    simple_basket = [{
        "questionId": int(test_question_id),
        "addTime": current_time,
    }]

    # 完整格式尝试不同字段组合
    test_formats = [
        # 格式1: 最小字段
        {
            "basketJson": json.dumps([{"questionId": int(test_question_id)}]),
            "bankId": "11",
            "syncFlag": "9",
        },
        # 格式2: 添加版本
        {
            "basketJson": json.dumps([{"questionId": int(test_question_id), "addTime": current_time}]),
            "bankId": "11",
            "syncFlag": "9",
            "syncVersion": basket_version or "0",
        },
        # 格式3: 不同的syncFlag
        {
            "basketJson": json.dumps([{"questionId": int(test_question_id), "addTime": current_time}]),
            "bankId": "11",
            "syncFlag": "1",
        },
        # 格式4: 使用serverVersion
        {
            "basketJson": json.dumps([{"questionId": int(test_question_id), "addTime": current_time}]),
            "bankId": "11",
            "syncFlag": "9",
            "serverVersion": "0",
        },
        # 格式5: 带完整状态
        {
            "basketJson": json.dumps([{
                "questionId": int(test_question_id),
                "addTime": current_time,
                "status": "normal",
            }]),
            "bankId": "11",
            "syncFlag": "9",
        },
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        for i, payload in enumerate(test_formats):
            print(f"\n=== 测试格式 {i+1} ===")
            print(f"Payload: {payload}")

            resp = await client.post(
                "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                data=payload,
                headers=headers
            )

            print(f"Status: {resp.status_code}")
            try:
                data = resp.json()
                print(f"Response: {json.dumps(data, ensure_ascii=False)}")

                # 检查serverVersion是否改变
                sv = data.get("serverVersion", "")
                if sv and sv != "1765550310104":
                    print(f"*** serverVersion changed: {sv} ***")

                # 检查questions是否有数据
                qs = data.get("questions", [])
                if qs:
                    print(f"*** Got {len(qs)} questions! ***")
            except:
                print(f"Response: {resp.text[:300]}")

        # 最后尝试获取当前题篮状态
        print("\n=== 获取当前题篮状态 ===")
        # 尝试带参数的GET请求
        for method in ["POST", "GET"]:
            params = {
                "bankId": "11",
                "syncFlag": "9",
                "basketJson": "[]",
                "syncVersion": "0",
            }
            if method == "GET":
                resp = await client.get(
                    "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                    params=params,
                    headers=headers
                )
            else:
                resp = await client.post(
                    "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                    data=params,
                    headers=headers
                )
            print(f"\n{method} sync_baskets with empty basket:")
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text[:300]}")

if __name__ == "__main__":
    asyncio.run(test_sync_format())
