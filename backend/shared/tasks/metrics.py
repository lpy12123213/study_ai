from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional

_EVENTS_QUEUED = None
_FLUSH_BATCHES = None
_FLUSH_EVENTS = None
_FLUSH_EVENTS_PER_BATCH = None
_FLUSH_DURATION = None
_PENDING_EVENTS = None
_SSE_CONNECTIONS = None
_SSE_OPENED = None
_METRICS_READY = False
_METRICS_DISABLED = False


def _label(value: str, *, max_chars: int = 80) -> str:
    raw = str(value or "").strip() or "unknown"
    return raw[:max_chars]


def _metrics_enabled() -> bool:
    raw = (os.getenv("PROMETHEUS_METRICS_ENABLED") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _ensure_metrics() -> bool:
    global _EVENTS_QUEUED, _FLUSH_BATCHES, _FLUSH_EVENTS, _FLUSH_EVENTS_PER_BATCH, _FLUSH_DURATION
    global _PENDING_EVENTS, _SSE_CONNECTIONS, _SSE_OPENED, _METRICS_READY, _METRICS_DISABLED

    if _METRICS_READY:
        return True
    if _METRICS_DISABLED or not _metrics_enabled():
        return False

    try:
        from prometheus_client import Counter, Gauge, Histogram  # type: ignore

        _EVENTS_QUEUED = Counter(
            "study_ai_task_events_queued_total",
            "Task events queued for durable persistence.",
            ["task_type", "event_type"],
        )
        _FLUSH_BATCHES = Counter(
            "study_ai_task_event_flush_batches_total",
            "Task event persistence flush batches.",
            ["task_type", "status"],
        )
        _FLUSH_EVENTS = Counter(
            "study_ai_task_event_flush_events_total",
            "Task events written during persistence flushes.",
            ["task_type", "status"],
        )
        _FLUSH_EVENTS_PER_BATCH = Histogram(
            "study_ai_task_event_flush_events_per_batch",
            "Task events written per persistence flush batch.",
            ["task_type", "status"],
        )
        _FLUSH_DURATION = Histogram(
            "study_ai_task_event_flush_duration_seconds",
            "Task event persistence flush duration.",
            ["task_type", "status"],
        )
        _PENDING_EVENTS = Gauge(
            "study_ai_task_event_pending",
            "Task events pending durable persistence.",
            ["task_type"],
        )
        _SSE_CONNECTIONS = Gauge(
            "study_ai_task_sse_connections",
            "Active in-memory task SSE streams.",
            ["task_type"],
        )
        _SSE_OPENED = Counter(
            "study_ai_task_sse_connections_opened_total",
            "Task SSE streams opened.",
            ["task_type"],
        )
        _METRICS_READY = True
        return True
    except (ImportError, RuntimeError, ValueError):
        _METRICS_DISABLED = True
        return False


def event_queued(*, task_type: str, event_type: str, pending: int) -> None:
    if not _ensure_metrics():
        return
    try:
        _EVENTS_QUEUED.labels(_label(task_type), _label(event_type, max_chars=50)).inc()
        _PENDING_EVENTS.labels(_label(task_type)).set(max(0, int(pending or 0)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def pending_events(*, task_type: str, pending: int) -> None:
    if not _ensure_metrics():
        return
    try:
        _PENDING_EVENTS.labels(_label(task_type)).set(max(0, int(pending or 0)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


def event_flush(*, task_type: str, status: str, count: int, duration_s: float) -> None:
    if not _ensure_metrics():
        return
    try:
        labels = (_label(task_type), _label(status, max_chars=30))
        _FLUSH_BATCHES.labels(*labels).inc()
        _FLUSH_EVENTS.labels(*labels).inc(max(0, int(count or 0)))
        _FLUSH_EVENTS_PER_BATCH.labels(*labels).observe(max(0, int(count or 0)))
        _FLUSH_DURATION.labels(*labels).observe(max(0.0, float(duration_s or 0.0)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return


@contextmanager
def sse_connection(task_type: Optional[str]) -> Iterator[None]:
    if not _ensure_metrics():
        yield
        return

    label = _label(task_type or "unknown")
    try:
        _SSE_OPENED.labels(label).inc()
        _SSE_CONNECTIONS.labels(label).inc()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        yield
        return

    try:
        yield
    finally:
        try:
            _SSE_CONNECTIONS.labels(label).dec()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return


def now_s() -> float:
    return time.perf_counter()
