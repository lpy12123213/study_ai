import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.cli.launcher.app import build_dispatch_command, dispatch_choice


class LauncherDispatchTests(unittest.TestCase):
    def test_builds_question_bank_tool_argv_with_user_id(self) -> None:
        cmd = build_dispatch_command("1", user_id="teacher-1", root=Path("C:/repo"), python_executable="py")

        self.assertEqual(
            cmd,
            ["py", "-m", "backend.cli.question_bank.browse", "--user-id", "teacher-1"],
        )

    def test_dispatches_start_service_through_scripts_start_without_shell(self) -> None:
        root = Path("C:/repo")

        with patch("backend.cli.launcher.app.subprocess.call", return_value=0) as call:
            code = dispatch_choice("7", user_id="teacher-1", root=root)

        self.assertEqual(code, 0)
        call.assert_called_once_with(
            [sys.executable, str(root / "scripts" / "start.py"), "backend"],
            cwd=str(root),
        )


if __name__ == "__main__":
    unittest.main()
