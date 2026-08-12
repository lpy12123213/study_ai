"""TODO model for the author-agent study materials pipeline (design doc §5.3)."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

TODO_TYPES = frozenset({"research", "backbone", "fill", "fig", "audit", "revision", "learning_contract"})
TODO_STATUSES = frozenset({"pending", "in_progress", "done", "waived", "failed"})


@dataclass
class TodoItem:
    id: str
    type: str
    ref: str = ""
    acceptance: str = ""
    deps: List[str] = field(default_factory=list)
    status: str = "pending"
    retries: int = 0
    note: str = ""

    def __post_init__(self) -> None:
        if self.type not in TODO_TYPES:
            raise ValueError(f"unknown todo type: {self.type}")
        if self.status not in TODO_STATUSES:
            raise ValueError(f"unknown todo status: {self.status}")


class TodoList:
    def __init__(self, items: Optional[List[TodoItem]] = None) -> None:
        self.items: List[TodoItem] = list(items or [])

    def get(self, todo_id: str) -> TodoItem:
        for it in self.items:
            if it.id == todo_id:
                return it
        raise KeyError(todo_id)

    def mark(self, todo_id: str, status: str, note: str = "") -> None:
        it = self.get(todo_id)
        if status not in TODO_STATUSES:
            raise ValueError(f"unknown todo status: {status}")
        it.status = status
        if note:
            it.note = note

    def all_cleared(self) -> bool:
        return all(it.status in {"done", "waived"} for it in self.items)

    def pending(self) -> List[TodoItem]:
        done = {it.id for it in self.items if it.status in {"done", "waived"}}
        return [
            it for it in self.items
            if it.status in {"pending", "failed"} and all(d in done for d in it.deps)
        ]

    def next_pending(self) -> Optional[TodoItem]:
        items = self.pending()
        return items[0] if items else None

    def to_json(self) -> list:
        return [asdict(it) for it in self.items]

    @classmethod
    def from_json(cls, data: list) -> "TodoList":
        return cls(items=[TodoItem(**raw) for raw in data])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_json(), fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path: Path) -> "TodoList":
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))
