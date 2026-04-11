"""
测试登录脚本 - 检查 cookie 是否正确保存
"""

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = str(PROJECT_ROOT / "crawler" / ".playwright_data")

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

    # 刷新页面确保 cookie 更新
    print("刷新页面...")
    page.reload()
    time.sleep(3)

    # 获取 cookie
    cookies = browser.cookies()
    print(f"\n当前共有 {len(cookies)} 个 cookie:")

    user_id = None
    for c in cookies:
        if c["name"] == "userId":
            user_id = c["value"]
        print(f"  {c['name']}: {c['value'][:40]}...")

    print()
    if user_id:
        print(f"[OK] 找到 userId: {user_id}")
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
