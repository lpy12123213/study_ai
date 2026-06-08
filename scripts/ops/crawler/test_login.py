"""
测试登录脚本 - 检查 cookie 是否正确保存。
"""

from __future__ import annotations

import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = str(PROJECT_ROOT / "crawler" / ".playwright_data")


def _cookie_debug_value(value: str) -> str:
    if not value:
        return "<empty>"
    return f"<redacted len={len(value)}>"


def main() -> int:
    from playwright.sync_api import sync_playwright

    print(f"数据目录: {DATA_DIR}")
    print()

    with sync_playwright() as p:
        print("启动浏览器...")
        browser = p.chromium.launch_persistent_context(
            DATA_DIR,
            headless=False,
            args=["--start-maximized"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        print("打开组卷网...")
        page.goto("https://zujuan.xkw.com/")

        print()
        print("=" * 50)
        print("请在浏览器中登录组卷网")
        print("登录后按回车继续（不要关闭浏览器！）")
        print("=" * 50)
        input()

        print("刷新页面...")
        page.reload()
        time.sleep(3)

        cookies = browser.cookies()
        print(f"\n当前共有 {len(cookies)} 个 cookie:")

        user_id = None
        for cookie in cookies:
            name = str(cookie.get("name") or "")
            value = str(cookie.get("value") or "")
            if name == "userId":
                user_id = value
            print(f"  {name}: {_cookie_debug_value(value)}")

        print()
        if user_id:
            print(f"[OK] 找到 userId: {_cookie_debug_value(user_id)}")
        else:
            print("[FAIL] 没有找到 userId cookie!")
            print("可能原因：")
            print("  1. 登录没有成功")
            print("  2. 网站使用了其他方式存储登录状态")

        print()
        print("等待 5 秒确保 cookie 写入磁盘...")
        time.sleep(5)

        print("关闭浏览器...")
        browser.close()

    print()
    print("完成！")
    input("按 Enter 退出...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
