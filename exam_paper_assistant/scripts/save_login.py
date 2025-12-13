"""
组卷网登录并保存 Cookie 到 `.env` 文件（自动模式，不需要按回车）。

说明：
- 脚本会打开浏览器，你在浏览器里完成登录即可；
- 脚本会自动检测 `userId` Cookie 出现后保存登录信息并退出；
- 默认打开高中数学页面，避免导出到错误学科题篮（可用环境变量覆盖）。

可选环境变量：
- `ZUJUAN_LOGIN_URL`：登录打开的页面（默认 `https://zujuan.xkw.com/gzsx/`）
- `ZUJUAN_LOGIN_WAIT_SECONDS`：最长等待秒数（默认 `1800`）
- `ZUJUAN_LOGIN_POLL_SECONDS`：轮询间隔秒数（默认 `2`）
- `ZUJUAN_EXPECT_BANKID`：期望的 bankId（默认 `11`，高中数学）
- `ZUJUAN_EXPECT_BANKNAME`：期望的 bankname（默认 `gzsx`，高中数学入口）
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ENV_FILE = PROJECT_ROOT / ".env"

LOGIN_URL = os.getenv("ZUJUAN_LOGIN_URL", "https://zujuan.xkw.com/gzsx/")
WAIT_SECONDS = int(os.getenv("ZUJUAN_LOGIN_WAIT_SECONDS", "1800"))
POLL_INTERVAL_SECONDS = float(os.getenv("ZUJUAN_LOGIN_POLL_SECONDS", "2"))
EXPECT_BANKID = os.getenv("ZUJUAN_EXPECT_BANKID", "11").strip() or "11"
EXPECT_BANKNAME = os.getenv("ZUJUAN_EXPECT_BANKNAME", "gzsx").strip() or "gzsx"


def extract_cookie_values(cookies: list[dict]) -> tuple[str | None, str | None, str]:
    user_id: str | None = None
    csrf_token: str | None = None
    cookie_str_parts: list[str] = []

    for cookie in cookies:
        cookie_str_parts.append(f"{cookie['name']}={cookie['value']}")
        if cookie["name"] == "userId" and cookie["value"]:
            user_id = cookie["value"]
        if cookie["name"] == "__RequestVerificationToken" and cookie["value"]:
            csrf_token = cookie["value"]

    return user_id, csrf_token, "; ".join(cookie_str_parts)


def extract_cookie_value(cookie_str: str, name: str) -> str | None:
    for part in cookie_str.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part.split("=", 1)[1].strip()
    return None


def remove_existing_login_config(existing_content: str) -> str:
    filtered_lines: list[str] = []
    for line in existing_content.splitlines():
        if line.startswith("ZUJUAN_USER_ID="):
            continue
        if line.startswith("ZUJUAN_CSRF_TOKEN="):
            continue
        if line.startswith("ZUJUAN_COOKIES="):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines).rstrip()


print("=" * 50)
print("组卷网登录工具（自动保存 Cookie）")
print("=" * 50)
print(f"打开页面：{LOGIN_URL}")
print(f"等待登录：最多 {WAIT_SECONDS} 秒（检测到登录且题库匹配即自动保存并退出）")
print(f"期望题库：bankId={EXPECT_BANKID} bankname={EXPECT_BANKNAME}")
print()

user_id: str | None = None
csrf_token: str | None = None
cookie_str: str = ""

with sync_playwright() as p:
    print("启动浏览器...")
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    print("打开组卷网...")
    page.goto(LOGIN_URL)

    print("\n请在浏览器中登录组卷网（无需回到控制台按回车）。")
    deadline = time.time() + WAIT_SECONDS

    while time.time() < deadline:
        cookies = context.cookies()
        user_id, csrf_from_cookie, cookie_str = extract_cookie_values(cookies)
        if user_id:
            bank_id = extract_cookie_value(cookie_str, "bankId")
            bank_name = extract_cookie_value(cookie_str, "bankname")
            if bank_id == EXPECT_BANKID and bank_name == EXPECT_BANKNAME:
                csrf_token = csrf_from_cookie
                break
            print(
                f"已登录但题库未匹配（当前 bankId={bank_id} bankname={bank_name}），"
                "请在页面左上角切换到“高中数学”后等待自动保存..."
            )
        time.sleep(POLL_INTERVAL_SECONDS)

    if user_id:
        try:
            page.reload()
            time.sleep(2)
            csrf_from_dom = page.evaluate(
                """
                () => {
                    const input = document.querySelector('input[name="__RequestVerificationToken"]');
                    return input ? input.value : null;
                }
                """
            )
            if csrf_from_dom:
                csrf_token = csrf_from_dom
        except Exception:
            pass

    browser.close()

if user_id:
    print(f"\n[OK] 登录成功：userId={user_id}")

    existing_content = ""
    if ENV_FILE.exists():
        existing_content = ENV_FILE.read_text(encoding="utf-8")

    existing_content = remove_existing_login_config(existing_content)

    new_config = (
        "\n\n# 组卷网登录信息（自动生成）\n"
        f"ZUJUAN_USER_ID={user_id}\n"
        f"ZUJUAN_CSRF_TOKEN={csrf_token or ''}\n"
        f"ZUJUAN_COOKIES={cookie_str}\n"
    )

    ENV_FILE.write_text(existing_content + new_config, encoding="utf-8")
    print(f"已保存到：{ENV_FILE}")
else:
    print("\n[FAIL] 未检测到登录状态（超时或未完成登录）。")
    print("建议：确认已在浏览器中完成登录；或延长等待时间：设置环境变量 ZUJUAN_LOGIN_WAIT_SECONDS")
