"""Durable author notes (research / blueprint / backbone / section summaries).

Design doc §4: the author relies on external notes, not raw context. Every write
can emit a `note_write` trace event via the `on_write` callback.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


class NotesStore:
    def __init__(self, root: Path, on_write: Optional[Callable[[str, int], None]] = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._on_write = on_write

    def _path(self, name: str) -> Path:
        if not _NAME_RE.match(name):
            raise ValueError(f"invalid note name: {name!r}")
        return self.root / f"{name}.md"

    def write(self, name: str, content: str) -> Path:
        p = self._path(name)
        p.write_text(content, encoding="utf-8")
        if self._on_write:
            self._on_write(name, len(content))
        return p

    def append(self, name: str, line: str) -> Path:
        p = self._path(name)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if p.stat().st_size else "") + line)
        if self._on_write:
            self._on_write(name, len(p.read_text(encoding="utf-8")))
        return p

    def read(self, name: str) -> str:
        p = self._path(name)
        return p.read_text(encoding="utf-8") if p.exists() else ""
