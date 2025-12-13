"""
直接检查题篮页面状态
"""
import asyncio
import httpx
import re
import json

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

async def check_basket():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Cookie": cookies,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # 获取题篮页面
        print("=== 获取题篮页面 ===")
        resp = await client.get("https://zujuan.xkw.com/basket/", headers=headers)
        print(f"Status: {resp.status_code}")

        # 分析页面内容
        html = resp.text

        # 找题目数量相关信息
        count_patterns = [
            r'题篮.*?(\d+).*?题',
            r'(\d+)\s*道题',
            r'共\s*(\d+)',
            r'basket.*?count.*?(\d+)',
        ]
        for pattern in count_patterns:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                print(f"Found count pattern: {m.group(0)}")

        # 找到预加载的数据
        data_patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'window\.basketData\s*=\s*({.*?});',
            r'"questions":\s*\[(.*?)\]',
            r'"basket":\s*({.*?})',
        ]
        for pattern in data_patterns:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                print(f"\nFound data pattern '{pattern[:30]}...':")
                print(f"  {m.group(1)[:300]}...")

        # 检查是否显示"题篮为空"
        if "题篮为空" in html or "暂无" in html:
            print("\n*** 题篮为空 ***")

        # 找到题目ID
        question_ids = re.findall(r'questionid="(\d+)"', html, re.IGNORECASE)
        if question_ids:
            print(f"\n找到题目ID: {question_ids}")
        else:
            print("\n未找到题目ID")

        # 获取题篮数据API
        print("\n=== 尝试获取题篮数据API ===")

        # 尝试不同的API
        apis = [
            ("https://zujuan.xkw.com/zujuan-api/basket/list", "POST", {"bankId": "11"}),
            ("https://zujuan.xkw.com/zujuan-api/basket_list", "POST", {"bankId": "11"}),
            ("https://zujuan.xkw.com/zujuan-api/get_basket", "POST", {"bankId": "11"}),
            ("https://zujuan.xkw.com/api/basket", "GET", {"bankId": "11"}),
        ]

        for url, method, data in apis:
            try:
                if method == "POST":
                    r = await client.post(url, data=data, headers={**headers, "Content-Type": "application/x-www-form-urlencoded"})
                else:
                    r = await client.get(url, params=data, headers=headers)
                print(f"{method} {url}: {r.status_code}")
                if r.status_code == 200:
                    print(f"  Response: {r.text[:200]}")
            except Exception as e:
                print(f"{method} {url}: Error - {e}")

        # 保存HTML供分析
        with open("basket_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\n已保存题篮页面到 basket_page.html")

if __name__ == "__main__":
    asyncio.run(check_basket())
