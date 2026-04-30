import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import json
import subprocess
import sys


class TestZujuanLoginPaths(unittest.TestCase):
    def test_get_playwright_login_user_data_dir_defaults_to_canonical_dir(self) -> None:
        import backend.crawler.zujuan.cookies as cookies

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.object(cookies, "_PROJECT_ROOT", root), patch.dict("os.environ", {}, clear=False):
                resolved = cookies.get_playwright_login_user_data_dir()

            self.assertEqual(resolved, root / ".local" / "playwright" / "zujuan_user_data")

    def test_get_playwright_login_user_data_dir_reuses_legacy_dir(self) -> None:
        import backend.crawler.zujuan.cookies as cookies

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy = root / ".local" / "playwright" / "zujuan"
            legacy.mkdir(parents=True)
            with patch.object(cookies, "_PROJECT_ROOT", root), patch.dict("os.environ", {}, clear=False):
                resolved = cookies.get_playwright_login_user_data_dir()

            self.assertEqual(resolved, legacy)


class TestZujuanLoginSubprocess(unittest.TestCase):
    def test_build_login_subprocess_command_prefers_root_wrapper_script_on_windows(self) -> None:
        import backend.crawler.zujuan.basket as basket

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            wrapper = root / "scripts" / "登录组卷网.bat"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("@echo off\r\n", encoding="utf-8")

            command = basket.build_login_subprocess_command(
                project_root=root,
                subject="高中数学",
                python_executable="python.exe",
                platform_name="win32",
            )

            self.assertEqual(command, [str(wrapper), "高中数学"])


class TestMcpExportLoginHints(unittest.IsolatedAsyncioTestCase):
    async def test_export_to_zujuan_returns_login_script_and_command(self) -> None:
        from backend.mcp.tools.stdio_handlers import handle_tool_call

        class FakeCrawler:
            subject = "高中数学"

            async def batch_get_question_details(self, question_ids):  # type: ignore[no-untyped-def]
                return {"questions": [{"question_id": qid} for qid in question_ids]}

            async def export_to_basket(self, **kwargs):  # type: ignore[no-untyped-def]
                _ = kwargs
                return {"success": False, "login_required": True, "error": "未登录"}

            async def login_via_subprocess(self):  # type: ignore[no-untyped-def]
                return {
                    "success": True,
                    "login_script": "scripts/登录组卷网.bat",
                    "login_command": '"scripts/登录组卷网.bat" "高中数学"',
                }

        class FakeServer:
            current_subject = "高中数学"
            crawler = FakeCrawler()

        response = await handle_tool_call(FakeServer(), "export_to_zujuan", {"question_ids": ["1"]})
        payload = json.loads(response[0].text)

        self.assertTrue(payload["login_required"])
        self.assertEqual(payload["login_script"], "scripts/登录组卷网.bat")
        self.assertEqual(payload["login_command"], '"scripts/登录组卷网.bat" "高中数学"')
        self.assertIn('运行 "scripts/登录组卷网.bat" "高中数学"', payload["login_instructions"][1])


class TestZujuanLoginBatchScript(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows batch script test")
    def test_root_login_batch_supports_dry_run(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            ["cmd", "/c", "scripts\\登录组卷网.bat", "--dry-run"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=20,
        )

        output = f"{completed.stdout}\n{completed.stderr}"
        self.assertEqual(completed.returncode, 0, output)
        self.assertIn("bankId=", output)


if __name__ == "__main__":
    unittest.main()
