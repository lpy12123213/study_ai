"""Small shared helpers for local CLI tools.

The helpers in this module intentionally stay dependency-light.  Rich and
prompt_toolkit are imported lazily and every helper has a plain stdlib fallback
so local maintenance commands keep working in minimal terminals.
"""

from __future__ import annotations

import asyncio
from typing import List


def _safe_user_id(user_id: str) -> str:
    uid = str(user_id or "").strip()
    return uid[:64] if uid else "1"


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401

        return True
    except ImportError:
        return False


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


def _console():
    if _rich_available():
        from rich.console import Console

        return Console()

    class _PlainConsole:
        def print(self, *args, **kwargs):  # noqa: ANN001
            _ = kwargs
            print(*args)

        def rule(self, title: str = "") -> None:
            if title:
                print("=" * 8, title, "=" * 8)
            else:
                print("=" * 24)

    return _PlainConsole()


def _prompt_text(label: str, *, default: str = "") -> str:
    prompt_label = f"{label}"
    if default:
        prompt_label += f" (默认: {default})"
    prompt_label += ": "

    in_running_loop = False
    try:
        asyncio.get_running_loop()
        in_running_loop = True
    except RuntimeError:
        in_running_loop = False

    if _prompt_toolkit_available() and not in_running_loop:
        try:
            from prompt_toolkit import prompt as pt_prompt

            value = pt_prompt(prompt_label, default=str(default or ""))
            return str(value or "").strip() or str(default or "").strip()
        except RuntimeError:
            pass

    try:
        value = input(prompt_label)
    except EOFError:
        value = ""
    return str(value or "").strip() or str(default or "").strip()


def _prompt_choice(label: str, options: List[str], *, default: str) -> str:
    choices = [str(x).strip() for x in options if str(x).strip()]
    if not choices:
        return str(default or "").strip()

    normalized_default = str(default or "").strip()
    if normalized_default not in choices:
        normalized_default = choices[0]

    options_str = " ".join(f"{i + 1}.{c}" for i, c in enumerate(choices))
    raw = _prompt_text(f"{label} [{options_str}]", default=normalized_default)
    raw_norm = str(raw or "").strip()

    if raw_norm in choices:
        return raw_norm

    try:
        idx = int(raw_norm)
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
    except ValueError:
        pass

    for choice in choices:
        if choice.lower() == raw_norm.lower():
            return choice

    return normalized_default


def _prompt_bool(label: str, *, default: bool) -> bool:
    default_text = "y" if default else "n"
    raw = _prompt_text(f"{label} (y/n)", default=default_text).lower()
    if raw in {"y", "yes", "1", "true", "t"}:
        return True
    if raw in {"n", "no", "0", "false", "f"}:
        return False
    return bool(default)


def _prompt_int(label: str, *, min_val: int, max_val: int, default: int) -> int:
    default = max(min_val, min(int(default or min_val), max_val))
    while True:
        raw = _prompt_text(f"{label} ({min_val}-{max_val})", default=str(default))
        raw = str(raw).strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            print(f"  ! 请输入 {min_val}-{max_val} 之间的整数")
            continue
        if value < min_val or value > max_val:
            print(f"  ! 必须在 {min_val}-{max_val} 之间")
            continue
        return value
