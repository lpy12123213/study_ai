"""
测试正确的bankId - 从cookie中获取
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

async def test_correct_bankid():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")
    csrf_token = env.get("ZUJUAN_CSRF_TOKEN", "")

    # 从cookie中提取bankId
    bank_id = "11"  # 默认
    for part in cookies.split(";"):
        if "bankId=" in part:
            bank_id = part.split("=")[1].strip()
            break

    print(f"Cookie中的bankId: {bank_id}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookies,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://zujuan.xkw.com",
        "Referer": "https://zujuan.xkw.com/",
        "RequestVerification": csrf_token,
    }

    test_question_id = "70287"  # 高中数学题目
    current_time = int(time.time() * 1000)

    # 测试不同bankId
    bank_ids_to_test = [bank_id, "11", "13"]  # cookie中的、高中数学、初中数学

    async with httpx.AsyncClient(timeout=30) as client:
        for bid in bank_ids_to_test:
            print(f"\n=== 测试 bankId={bid} ===")

            basket_item = {
                "questionId": int(test_question_id),
                "addTime": current_time,
                "childNum": 1,
                "quesDiff": 3,
                "quesTypeId": 2703,
                "quesTypeName": "填空题",
                "status": "CHECK",
            }

            payload = {
                "bankId": bid,
                "syncFlag": "9",
                "basketJson": json.dumps([basket_item], ensure_ascii=False)
            }

            resp = await client.post(
                "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                data=payload,
                headers=headers
            )

            print(f"Status: {resp.status_code}")
            try:
                data = resp.json()
                print(f"Response: {json.dumps(data, ensure_ascii=False)}")

                sv = data.get("serverVersion", "")
                qs = data.get("questions", [])

                if qs:
                    print(f"*** 返回了 {len(qs)} 个题目! ***")
            except:
                print(f"Response: {resp.text[:300]}")

        # 检查空篮子同步后返回的serverVersion是否变化
        print("\n=== 检查空篮子同步 ===")
        for bid in [bank_id]:
            payload = {
                "bankId": bid,
                "syncFlag": "9",
                "basketJson": "[]"  # 空篮子
            }
            resp = await client.post(
                "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                data=payload,
                headers=headers
            )
            print(f"bankId={bid}: {resp.text[:200]}")

if __name__ == "__main__":
    asyncio.run(test_correct_bankid())
