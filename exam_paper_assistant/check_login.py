"""
检查登录状态
"""
import asyncio
import httpx
import re

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

async def check_login():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")
    user_id = env.get("ZUJUAN_USER_ID", "")

    print(f"User ID from .env: {user_id}")

    # 检查cookie中是否有userId
    has_user_cookie = "userId=" in cookies
    print(f"Cookie has userId: {has_user_cookie}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Cookie": cookies,
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # 检查用户API
        print("\n=== 检查用户API ===")
        resp = await client.get(
            "https://zujuan.xkw.com/zujuan-api/user",
            headers=headers
        )
        print(f"User API Status: {resp.status_code}")
        print(f"Response: {resp.text[:500]}")

        # 检查首页
        print("\n=== 检查首页登录状态 ===")
        resp = await client.get("https://zujuan.xkw.com/", headers=headers)
        print(f"Homepage Status: {resp.status_code}")

        # 查找登录相关元素
        if "退出" in resp.text or "个人中心" in resp.text:
            print("*** 已登录 (找到退出/个人中心) ***")
        elif "登录" in resp.text and "退出" not in resp.text:
            print("*** 未登录 (只找到登录按钮) ***")

        # 检查用户信息
        user_match = re.search(r'userId["\']?\s*:\s*["\']?(\d+)', resp.text)
        if user_match:
            print(f"页面中的userId: {user_match.group(1)}")

        # 检查登录cookie是否有效
        print("\n=== 检查登录cookie有效性 ===")
        # 访问需要登录的API
        resp = await client.post(
            "https://zujuan.xkw.com/zujuan-api/sync_baskets",
            data={"bankId": "11", "syncFlag": "9", "basketJson": "[]"},
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"}
        )
        print(f"Sync Basket Status: {resp.status_code}")
        print(f"Response: {resp.text[:300]}")

        # 检查篮子页面
        print("\n=== 检查题篮页面 ===")
        resp = await client.get(
            "https://zujuan.xkw.com/basket/",
            headers=headers,
        )
        print(f"Basket Page Status: {resp.status_code}")
        if resp.status_code == 404:
            print("*** 题篮页面404 - 可能session失效 ***")
        elif "登录" in resp.text and "退出" not in resp.text:
            print("*** 题篮页面要求登录 ***")

if __name__ == "__main__":
    asyncio.run(check_login())
