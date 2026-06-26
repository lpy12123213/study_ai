from __future__ import annotations

import time
from typing import Tuple

from fastapi import FastAPI, Request, Response
from starlette.routing import Match

from backend.core.logging_utils import get_logger
from backend.core.settings import env_bool

logger = get_logger(__name__)



def metrics_enabled() -> bool:
    # Default: enabled in all environments (low overhead, useful for debugging).
    return env_bool("PROMETHEUS_METRICS_ENABLED", default=True)


def _safe_import_prometheus():
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest  # type: ignore

        return (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest)
    except ImportError:
        return None


_PROM = _safe_import_prometheus()

_REQUESTS_TOTAL = None
_REQUEST_DURATION = None
_IN_PROGRESS = None


def _ensure_metrics_objects() -> Tuple[object, object, object]:
    """Create Prometheus metric objects once per process (default registry)."""

    global _REQUESTS_TOTAL, _REQUEST_DURATION, _IN_PROGRESS
    if _REQUESTS_TOTAL is not None and _REQUEST_DURATION is not None and _IN_PROGRESS is not None:
        return (_REQUESTS_TOTAL, _REQUEST_DURATION, _IN_PROGRESS)

    if _PROM is None:
        raise RuntimeError("prometheus_client_not_installed")

    _CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, _generate_latest = _PROM
    _ = (_CONTENT_TYPE_LATEST, _generate_latest)

    # Core HTTP metrics. These register into the default global registry.
    _REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests.",
        ["method", "path", "status_code"],
    )
    _REQUEST_DURATION = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30),
    )
    _IN_PROGRESS = Gauge(
        "http_requests_in_progress",
        "In-progress HTTP requests.",
        ["method"],
    )
    return (_REQUESTS_TOTAL, _REQUEST_DURATION, _IN_PROGRESS)


def _route_template(request: Request) -> str:
    """Return a low-cardinality path label (FastAPI route template when possible)."""

    try:
        # FastAPI mounts APIRoute objects in app.routes; use route.matches to find the
        # matching template path (`/api/tasks/{task_id}` instead of `/api/tasks/abc`).
        from fastapi.routing import APIRoute  # local import: optional in some minimal envs
    except ImportError:
        APIRoute = None  # type: ignore[assignment]

    if APIRoute is not None:
        try:
            for route in request.app.routes:
                if not isinstance(route, APIRoute):
                    continue
                match, _ = route.matches(request.scope)
                if match == Match.FULL:
                    return str(getattr(route, "path", "") or request.url.path or "")
        except (RuntimeError, AttributeError, KeyError, TypeError):
            logger.warning("prom_route_template_match_failed", exc_info=True)

    return "<unmatched>"


def _metric_path_label(request: Request, *, status_code: int) -> str:
    template = _route_template(request) or "<unmatched>"
    if int(status_code or 0) == 404 and template == "<unmatched>":
        return "<not_found>"
    return template


def generate_metrics() -> Tuple[bytes, str]:
    """Generate Prometheus text format metrics payload."""

    if _PROM is None:
        return (b"# prometheus_client_not_installed\n", "text/plain; charset=utf-8")

    CONTENT_TYPE_LATEST, _Counter, _Gauge, _Histogram, generate_latest = _PROM
    _ = (_Counter, _Gauge, _Histogram)
    try:
        data = generate_latest()  # default global registry
    except (RuntimeError, ValueError):
        logger.exception("prom_generate_latest_failed")
        return (b"# prom_generate_latest_failed\n", "text/plain; charset=utf-8")
    return (data, str(CONTENT_TYPE_LATEST))


def instrument_app(app: FastAPI) -> None:
    """Attach request metrics middleware + `/metrics` endpoint to a FastAPI app."""

    if not metrics_enabled():
        return

    if _PROM is None:
        logger.warning("prometheus_client_missing; /metrics will return a stub payload")
        # Still mount the route so operators can detect misconfiguration.
        if not getattr(app.state, "_prom_metrics_instrumented", False):
            app.state._prom_metrics_instrumented = True

            @app.get("/metrics", include_in_schema=False)
            async def _metrics() -> Response:  # pragma: no cover (thin wrapper)
                body, content_type = generate_metrics()
                return Response(content=body, media_type=content_type)

        return

    # Avoid double-instrumentation if create_app() is called multiple times.
    if getattr(app.state, "_prom_metrics_instrumented", False):
        return
    app.state._prom_metrics_instrumented = True

    try:
        requests_total, request_duration, in_progress = _ensure_metrics_objects()
    except (RuntimeError, ValueError, ImportError):
        logger.exception("prom_metrics_init_failed")
        return

    def _warn_metrics_update_once(op: str) -> None:
        # Avoid warning spam if the metrics backend is misconfigured.
        if getattr(app.state, "_prom_metrics_update_failed", False):
            return
        app.state._prom_metrics_update_failed = True
        logger.warning("prom_metrics_update_failed", extra={"op": op}, exc_info=True)

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):  # noqa: ANN001
        path = str(request.url.path or "")
        if path == "/metrics":
            return await call_next(request)

        method = str(request.method or "").upper() or "GET"
        t0 = time.perf_counter()
        in_progress.labels(method=method).inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = int(getattr(response, "status_code", 200) or 200)
            return response
        finally:
            elapsed = max(0.0, time.perf_counter() - t0)
            label_path = _metric_path_label(request, status_code=status_code)
            try:
                in_progress.labels(method=method).dec()
            except (RuntimeError, ValueError):
                logger.warning("prom_metrics_update_failed", extra={"op": "in_progress.dec"}, exc_info=True)
                _warn_metrics_update_once("in_progress.dec")
            try:
                requests_total.labels(method=method, path=label_path, status_code=str(status_code)).inc()
            except (RuntimeError, ValueError):
                logger.warning("prom_metrics_update_failed", extra={"op": "requests_total.inc"}, exc_info=True)
                _warn_metrics_update_once("requests_total.inc")
            try:
                request_duration.labels(method=method, path=label_path).observe(elapsed)
            except (RuntimeError, ValueError):
                logger.warning("prom_metrics_update_failed", extra={"op": "request_duration.observe"}, exc_info=True)
                _warn_metrics_update_once("request_duration.observe")

    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> Response:  # pragma: no cover (thin wrapper)
        body, content_type = generate_metrics()
        return Response(content=body, media_type=content_type)
