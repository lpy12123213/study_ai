from __future__ import annotations

import os
from typing import Any, Optional

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

_OTEL_INITIALIZED = False


def _truthy(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _get_str(name: str, default: str = "") -> str:
    raw = str(os.getenv(name) or "").strip()
    return raw or str(default or "")


def setup_otel(app: Any) -> None:
    """Enable OpenTelemetry tracing (best-effort, optional).

    This function intentionally does nothing unless OTEL is enabled via env.
    """

    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return

    enabled = _truthy("OTEL_ENABLE", default=False)
    if not enabled:
        return

    service_name = _get_str("OTEL_SERVICE_NAME", "study_ai").strip() or "study_ai"
    endpoint = (
        _get_str("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        or _get_str("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
        or ""
    ).strip()

    try:
        from opentelemetry import trace  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.sdk.resources import SERVICE_NAME  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
    except Exception:
        logger.warning("otel_not_installed; skipping tracing")
        return

    exporter = None
    if endpoint:
        exporter = _build_otlp_exporter(endpoint)
    if exporter is None:
        exporter = _build_console_exporter()

    try:
        resource = Resource.create({SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except Exception:
        logger.warning("otel_tracer_provider_init_failed; skipping tracing", exc_info=True)
        return

    # FastAPI (ASGI) instrumentation
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        logger.debug("otel_fastapi_instrument_failed", exc_info=True)

    # HTTPX instrumentation (covers crawler + LLM HTTP calls if using httpx)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # type: ignore

        HTTPXClientInstrumentor().instrument()
    except Exception:
        logger.debug("otel_httpx_instrument_failed", exc_info=True)

    _OTEL_INITIALIZED = True
    logger.info(
        "otel_enabled",
        extra={
            "service_name": service_name,
            "exporter": type(exporter).__name__ if exporter else "",
            "endpoint": endpoint,
        },
    )


def _build_console_exporter() -> Optional[Any]:  # noqa: ANN401
    try:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter  # type: ignore

        return ConsoleSpanExporter()
    except Exception:
        return None


def _build_otlp_exporter(endpoint: str) -> Optional[Any]:  # noqa: ANN401
    # Prefer OTLP/HTTP. If exporter package is missing, return None and fall back.
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore

        return OTLPSpanExporter(endpoint=str(endpoint or "").strip())
    except Exception:
        return None

