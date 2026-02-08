"""
组卷网登录工具
运行此脚本会打开浏览器，让你手动登录组卷网。
登录成功后，会话会被保存，之后可以直接使用导出功能。
"""
import os
import sys
from pathlib import Path

# 确保能找到 crawler 模块
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def check_playwright():
    """检查 playwright 是否安装"""
    try:
        import playwright
        return True
    except ImportError:
        print("=" * 50)
        print("错误: 未安装 playwright")
        print("=" * 50)
        print()
        print("请运行以下命令安装:")
        print(f"  {sys.executable} -m pip install playwright")
        print(f"  {sys.executable} -m playwright install chromium")
        print()
        return False


def main():
    print("=" * 50)
    print("组卷网登录工具")
    print("=" * 50)
    print()

    if not check_playwright():
        input("按 Enter 键退出...")
        return

    print("即将打开浏览器，请在浏览器中登录组卷网账号。")
    print("登录成功后，脚本会自动检测并保存登录状态。")
    print()
    input("按 Enter 键继续...")

    try:
        from playwright.sync_api import sync_playwright

        # 数据目录 - 使用绝对路径，确保与 zujuan_crawler.py 一致
        user_data_dir = str(PROJECT_ROOT / "crawler" / ".playwright_data")
        os.makedirs(user_data_dir, exist_ok=True)

        print(f"\n数据目录: {user_data_dir}")
        print("正在启动浏览器...")

        with sync_playwright() as p:
            # 使用持久化上下文
            browser = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,  # 显示浏览器窗口
                args=["--start-maximized"],  # 最大化窗口
            )
            page = browser.pages[0] if browser.pages else browser.new_page()

            # 打开组卷网
            print("正在打开组卷网...")
            page.goto("https://zujuan.xkw.com/", timeout=30000)

            print("\n" + "=" * 50)
            print("请在浏览器窗口中登录组卷网账号")
            print("登录完成后，脚本会自动检测")
            print("=" * 50 + "\n")

            # 等待用户登录（检测 userId cookie）
            try:
                page.wait_for_function(
                    "document.cookie.includes('userId=')",
                    timeout=300000  # 5分钟超时
                )
                print("检测到登录成功！")
            except Exception as e:
                print(f"等待超时或用户关闭了浏览器: {e}")

            # 获取登录结果
            cookies = browser.cookies()
            user_id = None
            for c in cookies:
                if c['name'] == 'userId':
                    user_id = c['value']
                    break

            browser.close()

            print()
            print("=" * 50)
            if user_id:
                print(f"[OK] 登录成功! 用户ID: {user_id}")
                print()
                print("现在可以使用导出功能了！")
                print()
                print("在 Cherry Studio 中使用示例：")
                print('  "帮我把这些题目导出到组卷网：29811335, 29811336"')
            else:
                print("[FAIL] 未检测到登录状态")
                print("请确保在浏览器中完成了登录")
            print("=" * 50)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

    input("\n按 Enter 键退出...")


if __name__ == "__main__":
    main()
