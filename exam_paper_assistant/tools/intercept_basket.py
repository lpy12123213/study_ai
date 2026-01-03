"""
使用Playwright拦截添加到题篮的真实网络请求
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT_DIR / ".local" / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def intercept_basket_api():
    with sync_playwright() as p:
        # 使用已有的登录数据
        user_data_dir = ROOT_DIR / "crawler" / ".playwright_data"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        browser = p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,  # 显示浏览器以便观察
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        # 存储捕获的请求
        captured_requests = []

        def handle_request(request):
            if "basket" in request.url.lower() or "sync" in request.url.lower():
                print(f"\n=== 捕获请求 ===")
                print(f"URL: {request.url}")
                print(f"Method: {request.method}")
                print(f"Headers: {dict(request.headers)}")
                if request.post_data:
                    print(f"Post Data: {request.post_data[:500]}")
                captured_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "post_data": request.post_data
                })

        def handle_response(response):
            if "basket" in response.url.lower() or "sync" in response.url.lower():
                print(f"\n=== 捕获响应 ===")
                print(f"URL: {response.url}")
                print(f"Status: {response.status}")
                try:
                    body = response.text()
                    print(f"Body: {body[:500]}")
                except:
                    pass

        # 监听网络请求
        page.on("request", handle_request)
        page.on("response", handle_response)

        # 打开题目列表页
        print("正在打开题目列表页...")
        page.goto("https://zujuan.xkw.com/gzsx/zsd100693/", timeout=30000)
        page.wait_for_timeout(3000)

        # 找到并点击"加入题篮"按钮
        print("\n查找'加入题篮'按钮...")

        # 尝试不同的选择器
        selectors = [
            'text="加入题篮"',
            '.btn-basket',
            '[class*="basket"]',
            'button:has-text("题篮")',
            '.exam-item__opt button',
            '.tk-quest-item button',
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible():
                    print(f"找到按钮: {selector}")
                    print(f"按钮文本: {btn.text_content()}")

                    # 点击按钮
                    print("点击按钮...")
                    btn.click()
                    page.wait_for_timeout(2000)
                    break
            except Exception as e:
                print(f"选择器 {selector} 未找到: {e}")

        # 等待用户观察
        print("\n请在浏览器中手动点击'加入题篮'按钮观察网络请求...")
        print("30秒后自动关闭...")
        page.wait_for_timeout(30000)

        # 保存捕获的请求
        if captured_requests:
            output_path = ARTIFACTS_DIR / "captured_requests.json"
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(captured_requests, f, ensure_ascii=False, indent=2)
            print(f"\n已保存 {len(captured_requests)} 个请求到 {output_path}")

        browser.close()


if __name__ == "__main__":
    intercept_basket_api()
