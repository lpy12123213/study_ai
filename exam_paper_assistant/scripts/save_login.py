"""
组卷网登录并保存 Cookie 到 `.env` 文件（自动模式，不需要按回车）。

说明：
- 脚本会打开浏览器，你在浏览器里完成登录即可；
- 脚本会自动检测 `userId` Cookie 出现后保存登录信息并退出；
- 默认打开组卷网首页；如需固定入口可用环境变量覆盖。
- 浏览器使用 Playwright 持久化用户数据目录（含登录态），后续切换学科时通常无需重复登录。

可选环境变量：
 - `ZUJUAN_LOGIN_URL`：登录打开的页面（默认 `https://zujuan.xkw.com/`）
- `ZUJUAN_LOGIN_WAIT_SECONDS`：最长等待秒数（默认 `1800`）
- `ZUJUAN_LOGIN_POLL_SECONDS`：轮询间隔秒数（默认 `2`）
- `ZUJUAN_EXPECT_BANKID`：期望的 bankId（默认 `11`，高中数学）
- `ZUJUAN_EXPECT_BANKNAME`：期望的 bankname（默认 `gzsx`，高中数学入口）
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ENV_FILE = PROJECT_ROOT / ".env"
sys.path.append(str(PROJECT_ROOT))
USER_DATA_DIR = PROJECT_ROOT / ".playwright_zujuan_user_data"

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument(
    "--subject",
    default=os.getenv("ZUJUAN_SUBJECT", "").strip(),
    help="学科全名，如：高中数学/初中物理/小学语文",
)
parser.add_argument(
    "--bank-id",
    default="",
    help="期望的 bankId（优先级高于 subject，默认从环境变量/subject 推导）",
)
parser.add_argument(
    "--user-data-dir",
    default=os.getenv("ZUJUAN_USER_DATA_DIR", "").strip(),
    help="Playwright 持久化用户数据目录（默认使用项目下 .playwright_zujuan_user_data）",
)
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="仅打印解析后的学科/bankId，不启动浏览器",
)
args, _unknown = parser.parse_known_args()

subject = (args.subject or "").strip().strip('"').strip("'").strip()

default_login_url = "https://zujuan.xkw.com/"
LOGIN_URL = os.getenv("ZUJUAN_LOGIN_URL", default_login_url)

WAIT_SECONDS = int(os.getenv("ZUJUAN_LOGIN_WAIT_SECONDS", "1800"))
POLL_INTERVAL_SECONDS = float(os.getenv("ZUJUAN_LOGIN_POLL_SECONDS", "2"))

EXPECT_BANKID = (args.bank_id or "").strip()
EXPECT_BANKNAME = os.getenv("ZUJUAN_EXPECT_BANKNAME", "gzsx").strip() or "gzsx"

if subject:
    try:
        from backend.subjects import SUBJECTS, get_subject_config

        resolved_subject = subject
        if resolved_subject not in SUBJECTS:
            candidates: list[str] = []
            for name, cfg in SUBJECTS.items():
                if cfg.get("short_name") == subject or subject in name or name in subject:
                    candidates.append(name)

            suffix_candidates = [n for n in candidates if n.endswith(subject)]
            if suffix_candidates:
                candidates = suffix_candidates

            prefer_prefix = "高中"
            default_subject = (os.getenv("DEFAULT_SUBJECT", "") or "高中数学").strip()
            if default_subject.startswith(("小学", "初中", "高中")):
                prefer_prefix = default_subject[:2]

            preferred = [n for n in candidates if n.startswith(prefer_prefix)]
            if len(preferred) == 1:
                resolved_subject = preferred[0]
            elif len(candidates) == 1:
                resolved_subject = candidates[0]
            else:
                if candidates:
                    print(f"[WARN] 学科“{subject}”匹配到多个候选：{', '.join(candidates[:20])}")
                    print("请使用完整学科名（如：高中生物/初中生物），或通过 DEFAULT_SUBJECT 指定默认学段偏好。")
                else:
                    print(f"[WARN] 未识别学科“{subject}”，将回退到默认学科。")

        subject = resolved_subject

        if not EXPECT_BANKID and subject in SUBJECTS:
            EXPECT_BANKID = str(get_subject_config(subject)["bank_id"])
        # 不强制校验 bankname：不同学科入口路径可变，bankId 可靠性更高
        EXPECT_BANKNAME = ""
    except Exception as e:
        print(f"[WARN] 解析学科失败（无法加载 backend.subjects）：{e}")

EXPECT_BANKID = EXPECT_BANKID or os.getenv("ZUJUAN_EXPECT_BANKID", "11").strip() or "11"

if args.dry_run:
    expect_desc = f"bankId={EXPECT_BANKID}"
    if subject:
        expect_desc += f"（学科：{subject}）"
    print(expect_desc)
    raise SystemExit(0)


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
expect_desc = f"bankId={EXPECT_BANKID}"
if EXPECT_BANKNAME:
    expect_desc += f" bankname={EXPECT_BANKNAME}"
if subject:
    expect_desc += f"（学科：{subject}）"
print(f"期望题库：{expect_desc}")
print()

user_id: str | None = None
csrf_token: str | None = None
cookie_str: str = ""

with sync_playwright() as p:
    print("启动浏览器...")
    user_data_dir = Path(args.user_data_dir).expanduser() if args.user_data_dir else USER_DATA_DIR
    print(f"持久化用户数据目录：{user_data_dir}")

    def _cleanup_singleton_files() -> list[str]:
        removed: list[str] = []
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            fp = user_data_dir / name
            try:
                if fp.exists():
                    fp.unlink()
                    removed.append(name)
            except Exception:
                continue
        return removed

    try:
        context = p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            args=["--disable-gpu"],
        )
    except Exception as e:
        removed = _cleanup_singleton_files()
        if removed:
            print(f"[WARN] 检测到残留锁文件并已尝试清理：{', '.join(removed)}，准备重试启动浏览器...")
            try:
                context = p.chromium.launch_persistent_context(
                    str(user_data_dir),
                    headless=False,
                    args=["--disable-gpu"],
                )
            except Exception as e2:
                print("[FAIL] 清理锁文件后仍无法启动持久化浏览器。")
                print(f"底层错误：{e2}")
                sys.exit(2)
        else:
            print("[FAIL] 启动持久化浏览器失败。常见原因：")
            print("1) 该持久化目录已被另一个浏览器实例占用（请关闭相关 Chrome/Edge 窗口或任务管理器结束残留进程）")
            print(f"2) 持久化目录损坏：可尝试删除目录后重试：{user_data_dir}")
            print("3) 路径/权限问题：可设置环境变量 ZUJUAN_USER_DATA_DIR 指向一个可写目录后重试")
            print(f"底层错误：{e}")
            sys.exit(2)
    page = context.pages[0] if context.pages else context.new_page()

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
            bank_ok = bank_id == EXPECT_BANKID
            bankname_ok = True if not EXPECT_BANKNAME else (bank_name == EXPECT_BANKNAME)
            if bank_ok and bankname_ok:
                csrf_token = csrf_from_cookie
                break
            target_hint = f"切换到“{subject}”" if subject else "切换到目标学科题库"
            print(
                f"已登录但题库未匹配（当前 bankId={bank_id} bankname={bank_name}），"
                f"请在页面左上角{target_hint}后等待自动保存..."
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

    context.close()

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
