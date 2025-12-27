"""
分析组卷网前端JS，找到添加到题篮的API
"""
import asyncio
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

async def analyze_frontend():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Cookie": cookies,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # 获取题目列表页面
        print("=== 分析题目列表页面 ===")
        resp = await client.get(
            "https://zujuan.xkw.com/gzsx/zsd100693/",
            headers=headers
        )
        print(f"Status: {resp.status_code}")

        # 找到添加到题篮相关的代码
        html = resp.text

        # 搜索"加入题篮"相关的代码
        basket_patterns = [
            r'addToBasket[^"]*',
            r'add.*basket[^"]*',
            r'basket.*add[^"]*',
            r'"basket"[^}]*',
            r'sync_baskets[^"]*',
            r'questionBasket[^"]*',
        ]

        for pattern in basket_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                print(f"\nPattern '{pattern}':")
                for m in list(set(matches))[:5]:
                    print(f"  {m[:100]}")

        # 找到JS文件链接
        js_files = re.findall(r'src="([^"]*\.js[^"]*)"', html)
        print(f"\n=== JS Files ===")
        for js in js_files[:10]:
            print(f"  {js}")

        # 下载并分析主要JS文件
        for js_url in js_files[:5]:
            if not js_url.startswith("http"):
                if js_url.startswith("//"):
                    js_url = "https:" + js_url
                elif js_url.startswith("/"):
                    js_url = "https://zujuan.xkw.com" + js_url

            print(f"\n=== 分析 JS: {js_url[:60]}... ===")
            try:
                js_resp = await client.get(js_url, headers=headers)
                js_code = js_resp.text

                # 搜索basket相关的API调用
                api_calls = re.findall(r'/zujuan-api/[a-zA-Z_/]+', js_code)
                if api_calls:
                    print(f"Found APIs: {list(set(api_calls))[:15]}")

                # 搜索sync_baskets的用法
                if 'sync_baskets' in js_code:
                    # 找到sync_baskets周围的代码
                    idx = js_code.find('sync_baskets')
                    context = js_code[max(0, idx-200):idx+300]
                    print(f"sync_baskets context:\n{context[:500]}")

                # 搜索localStorage关键词
                if 'localStorage' in js_code and 'basket' in js_code.lower():
                    idx = js_code.lower().find('basket')
                    while idx != -1:
                        if 'localStorage' in js_code[max(0, idx-100):idx+100]:
                            context = js_code[max(0, idx-100):idx+100]
                            print(f"localStorage basket: {context}")
                        idx = js_code.lower().find('basket', idx+1)
                        if idx > 0 and js_code.lower().find('basket', idx+1) - idx > 1000:
                            break

            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(analyze_frontend())
