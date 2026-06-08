"""Foreground subprocess launcher for local Study AI tools."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from backend.cli.common import _console, _prompt_text, _rich_available, _safe_user_id

ROOT = Path(__file__).resolve().parents[3]


_MENU_ROWS = [
    ("1", "题库浏览", "backend.cli.question_bank.browse"),
    ("2", "题库审核", "backend.cli.question_bank.review"),
    ("3", "题库校验", "backend.cli.question_bank.validate"),
    ("4", "统计去重", "backend.cli.question_bank.stats --dedup"),
    ("5", "AI 出题", "backend.cli.question_generate"),
    ("6", "题库爬取", "backend.cli.question_library_crawl"),
    ("7", "后端服务", "scripts/start.py backend"),
    ("8", "前端服务", "scripts/start.py frontend"),
    ("9", "MCP 服务", "scripts/start.py mcp"),
    ("10", "开发服务", "scripts/start.py dev"),
    ("11", "全部服务", "scripts/start.py all"),
    ("0", "退出", ""),
]

_MODULE_CHOICES = {
    "1": "backend.cli.question_bank.browse",
    "2": "backend.cli.question_bank.review",
    "3": "backend.cli.question_bank.validate",
    "4": "backend.cli.question_bank.stats",
    "5": "backend.cli.question_generate",
    "6": "backend.cli.question_library_crawl",
}

_SERVICE_CHOICES = {
    "7": "backend",
    "8": "frontend",
    "9": "mcp",
    "10": "dev",
    "11": "all",
}


def build_dispatch_command(
    choice: str,
    *,
    user_id: str,
    root: Path = ROOT,
    python_executable: str = sys.executable,
) -> Optional[list[str]]:
    key = str(choice or "").strip()
    uid = _safe_user_id(user_id)

    if key in _MODULE_CHOICES:
        cmd = [python_executable, "-m", _MODULE_CHOICES[key], "--user-id", uid]
        if key == "4":
            cmd.append("--dedup")
        return cmd

    if key in _SERVICE_CHOICES:
        return [python_executable, str(root / "scripts" / "start.py"), _SERVICE_CHOICES[key]]

    return None


def dispatch_choice(choice: str, *, user_id: str, root: Path = ROOT) -> int:
    cmd = build_dispatch_command(choice, user_id=user_id, root=root)
    if not cmd:
        return 0
    try:
        return int(subprocess.call(cmd, cwd=str(root)))
    except KeyboardInterrupt:
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="打开 Study AI 本地工具启动箱。")
    parser.add_argument("--user-id", default="1")
    parser.add_argument("--choice", default="", help="调试用：执行一次指定菜单项后退出")
    return parser


def _render_menu(console, *, user_id: str) -> None:  # noqa: ANN001
    if not _rich_available():
        console.rule(f"Study AI 启动箱 user={user_id}")
        for key, label, target in _MENU_ROWS:
            suffix = f" - {target}" if target else ""
            console.print(f"{key}. {label}{suffix}")
        return

    from rich.panel import Panel
    from rich.table import Table

    table = Table(show_header=True, header_style="bold cyan", show_lines=False)
    table.add_column("编号", no_wrap=True)
    table.add_column("工具", no_wrap=True)
    table.add_column("目标")
    for key, label, target in _MENU_ROWS:
        table.add_row(key, label, target)
    console.print(Panel(table, title=f"Study AI 启动箱 user={user_id}", border_style="cyan"))


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    uid = _safe_user_id(str(args.user_id or ""))

    if str(args.choice or "").strip():
        return dispatch_choice(str(args.choice), user_id=uid, root=ROOT)

    console = _console()
    uid = _safe_user_id(_prompt_text("用户 ID", default=uid))

    while True:
        try:
            _render_menu(console, user_id=uid)
            choice = _prompt_text("选择", default="0").strip()
        except KeyboardInterrupt:
            console.print("\n已退出。")
            return 0

        if choice in {"0", "q", "quit", "exit"}:
            return 0
        code = dispatch_choice(choice, user_id=uid, root=ROOT)
        if code not in {0, 130}:
            console.print(f"子进程退出码: {code}")
