"""
深入分析题篮页面和localStorage机制
"""
import asyncio
import re
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT_DIR / ".local" / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
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

async def analyze_basket():
    env = load_env()
    cookies = env.get("ZUJUAN_COOKIES", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Cookie": cookies,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # 获取题篮页面
        print("=== 获取题篮页面 ===")
        resp = await client.get("https://zujuan.xkw.com/basket/", headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Content Length: {len(resp.text)}")

        html = resp.text

        # 保存完整HTML
        output_path = ARTIFACTS_DIR / "basket_full.html"
        with output_path.open("w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved to {output_path}")

        # 查找关键信息
        print("\n=== 页面关键信息 ===")

        # localStorage相关
        if "localStorage" in html:
            print("Found localStorage references")
            # 找到localStorage的使用
            ls_matches = re.findall(r'localStorage[.\[\'"](.*?)[\'"\]]', html)
            print(f"  Keys: {list(set(ls_matches))}")

        # 查找basket相关的JS变量
        basket_vars = re.findall(r'(basket|questions?)\s*[=:]\s*(\[[^\]]*\]|\{[^}]*\})', html, re.IGNORECASE)
        if basket_vars:
            print(f"Basket vars found: {basket_vars[:5]}")

        # 查找初始化数据
        init_data = re.findall(r'window\.__(\w+)__\s*=\s*(\{[\s\S]*?\});', html)
        if init_data:
            for key, val in init_data[:3]:
                print(f"  window.__{key}__: {val[:100]}...")

        # 找Vue/React数据
        state_match = re.search(r'__INITIAL_STATE__\s*=\s*(\{[\s\S]*?\})\s*;', html)
        if state_match:
            print(f"Found __INITIAL_STATE__: {state_match.group(1)[:200]}...")

        # 查找API调用
        api_calls = re.findall(r'[\'"]/(zujuan-api/[^\'"]+)[\'"]', html)
        if api_calls:
            print(f"\nAPIs in page: {list(set(api_calls))}")

        # 检查是否有同步逻辑
        if "sync_baskets" in html:
            idx = html.find("sync_baskets")
            context = html[max(0, idx-100):idx+200]
            print(f"\nsync_baskets context: {context}")

        # 查找题篮数据格式
        print("\n=== 搜索题目列表页的加入题篮逻辑 ===")
        resp2 = await client.get("https://zujuan.xkw.com/gzsx/zsd100693/", headers=headers)
        html2 = resp2.text

        # 找到加入题篮的点击处理
        add_basket_patterns = [
            r'addToBasket[^}]*\{[^}]*\}',
            r'onAddBasket[^}]*\{[^}]*\}',
            r'\.basket[^}]*\{[^}]*\}',
            r'click.*basket[^;]*;',
        ]
        for pattern in add_basket_patterns:
            matches = re.findall(pattern, html2, re.IGNORECASE | re.DOTALL)
            if matches:
                print(f"\nPattern '{pattern[:30]}...':")
                for m in matches[:2]:
                    print(f"  {m[:200]}")

        # 找到JS bundle文件
        js_files = re.findall(r'src="([^"]*\.js[^"]*)"', html2)
        print(f"\nJS files: {js_files[:5]}")

        # 下载并分析主JS
        for js_url in js_files[:3]:
            if not js_url.startswith("http"):
                if js_url.startswith("//"):
                    js_url = "https:" + js_url
                elif js_url.startswith("/"):
                    js_url = "https://zujuan.xkw.com" + js_url

            if "chunk" in js_url or "main" in js_url or "app" in js_url:
                print(f"\n=== 分析 {js_url[:60]}... ===")
                try:
                    js_resp = await client.get(js_url, headers=headers)
                    js_code = js_resp.text

                    # 找sync_baskets调用
                    if "sync_baskets" in js_code:
                        idx = js_code.find("sync_baskets")
                        # 找到完整的函数调用
                        context_start = max(0, idx - 300)
                        context_end = min(len(js_code), idx + 500)
                        context = js_code[context_start:context_end]
                        print(f"sync_baskets code:\n{context}")

                    # 找localStorage.setItem("basket"
                    if "localStorage" in js_code and "basket" in js_code.lower():
                        # 找到相关代码
                        for m in re.finditer(r'localStorage[.\[](.*?)basket', js_code, re.IGNORECASE):
                            idx = m.start()
                            context = js_code[max(0, idx-50):idx+150]
                            print(f"\nlocalStorage basket: {context}")
                            break

                except Exception as e:
                    print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(analyze_basket())
