"""
使用Playwright验证题篮功能和捕获网络请求
"""
import asyncio
import json
import os
import time
from pathlib import Path

# 添加父目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent))


def run_playwright_test():
    from playwright.sync_api import sync_playwright

    # 使用已有的登录数据
    user_data_dir = os.path.join(os.path.dirname(__file__), "crawler", ".playwright_data")
    os.makedirs(user_data_dir, exist_ok=True)

    captured_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,  # 显示浏览器
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        # 捕获网络请求
        def handle_request(request):
            url = request.url
            if "basket" in url.lower() or "sync" in url.lower() or "zujuan-api" in url:
                req_info = {
                    "url": url,
                    "method": request.method,
                    "headers": dict(request.headers),
                }
                if request.post_data:
                    req_info["post_data"] = request.post_data
                captured_requests.append(req_info)
                print(f"\n[REQUEST] {request.method} {url}")
                if request.post_data:
                    print(f"  Data: {request.post_data[:200]}")

        def handle_response(response):
            url = response.url
            if "basket" in url.lower() or "sync" in url.lower():
                print(f"\n[RESPONSE] {response.status} {url}")
                try:
                    body = response.text()
                    print(f"  Body: {body[:200]}")
                except:
                    pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        # 1. 先检查题篮
        print("=" * 50)
        print("1. 检查当前题篮状态...")
        print("=" * 50)
        page.goto("https://zujuan.xkw.com/basket/", timeout=30000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # 截图
        page.screenshot(path="basket_before.png")
        print("已保存截图: basket_before.png")

        # 获取题篮数量
        try:
            count_elem = page.locator(".basket-count, .quest-count, [class*='count']").first
            if count_elem.is_visible():
                print(f"题篮数量元素: {count_elem.text_content()}")
        except:
            pass

        # 检查是否为空
        if "题篮为空" in page.content() or "暂无试题" in page.content():
            print("*** 题篮为空 ***")
        else:
            # 尝试获取题目列表
            items = page.locator(".quest-item, .basket-item, [class*='question']").all()
            print(f"找到 {len(items)} 个题目元素")

        # 2. 去题目列表页添加题目
        print("\n" + "=" * 50)
        print("2. 去题目列表页添加题目...")
        print("=" * 50)
        page.goto("https://zujuan.xkw.com/gzsx/zsd100693/", timeout=30000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # 找到加入题篮按钮
        basket_btns = page.locator("text=加入题篮").all()
        print(f"找到 {len(basket_btns)} 个'加入题篮'按钮")

        if basket_btns:
            # 点击第一个按钮
            print("点击第一个'加入题篮'按钮...")
            basket_btns[0].click()
            page.wait_for_timeout(2000)

            # 检查是否有确认弹窗
            try:
                confirm_btn = page.locator("text=确定").first
                if confirm_btn.is_visible():
                    confirm_btn.click()
                    page.wait_for_timeout(1000)
            except:
                pass

            page.screenshot(path="after_add.png")
            print("已保存截图: after_add.png")

        # 3. 再次检查题篮
        print("\n" + "=" * 50)
        print("3. 再次检查题篮...")
        print("=" * 50)
        page.goto("https://zujuan.xkw.com/basket/", timeout=30000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        page.screenshot(path="basket_after.png")
        print("已保存截图: basket_after.png")

        # 保存捕获的请求
        if captured_requests:
            with open("captured_basket_requests.json", "w", encoding="utf-8") as f:
                json.dump(captured_requests, f, ensure_ascii=False, indent=2)
            print(f"\n已保存 {len(captured_requests)} 个请求到 captured_basket_requests.json")

            # 打印关键请求
            print("\n=== 关键API请求 ===")
            for req in captured_requests:
                if "sync" in req["url"].lower():
                    print(f"\nURL: {req['url']}")
                    print(f"Method: {req['method']}")
                    if "post_data" in req:
                        print(f"Data: {req['post_data'][:500]}")

        print("\n10秒后关闭浏览器...")
        page.wait_for_timeout(10000)

        browser.close()


if __name__ == "__main__":
    run_playwright_test()
