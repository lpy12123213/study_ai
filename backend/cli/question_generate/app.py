"""Entry point wiring argparse subcommands to the CLI command handlers."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from .args import _build_parser, _resolve_params_from_args
from .helpers import _console, _safe_user_id
from .review import (
    _commit_confirmed,
    _export_markdown,
    _list_sessions_cmd,
    _print_params_summary,
    _review_session,
)
from .runner import _run_generation


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cmd = str(getattr(args, "cmd", "") or "generate").strip()
    if cmd == "sessions":
        _list_sessions_cmd(user_id=_safe_user_id(args.user_id), limit=int(args.limit or 60))
        return

    if cmd == "review":
        _review_session(user_id=_safe_user_id(args.user_id), session_id=str(args.session_id or "").strip())
        return

    if cmd == "commit":
        asyncio.run(_commit_confirmed(user_id=_safe_user_id(args.user_id), session_id=str(args.session_id or "").strip()))
        return

    if cmd == "export":
        asyncio.run(
            _export_markdown(
                user_id=_safe_user_id(args.user_id),
                session_id=str(args.session_id or "").strip(),
                path=str(args.path or "").strip(),
            )
        )
        return

    # generate (default)
    params = _resolve_params_from_args(args)
    _print_params_summary(_console(), params)
    session = asyncio.run(_run_generation(params))
    _review_session(user_id=params.user_id, session_id=str(session.get("session_id") or params.session_id))
