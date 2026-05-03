"""Unified task runtime.

The system has multiple long-running workflows (study materials, question library,
paper compose, exports, etc.). This package centralizes the in-memory runtime and
DB persistence glue so domains don't re-implement lifecycle and SSE replay logic.
"""

from __future__ import annotations

from backend.shared.tasks.runtime import RuntimeTask, TaskRuntime

__all__ = ["RuntimeTask", "TaskRuntime", "task_runtime"]


def __getattr__(name: str):
    if name == "task_runtime":
        from backend.shared.tasks.runtime_singleton import task_runtime

        return task_runtime
    raise AttributeError(name)
