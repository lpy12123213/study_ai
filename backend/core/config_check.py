from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

_PLACEHOLDERS = {
    "",
    "your_api_key_here",
    "your_moonshot_key_here",
    "your_fireworks_key_here",
    "your_zhipu_api_key_here",
    "dev-jwt-secret-change-me",
    "dev-admin-change-me",
}

@dataclass(frozen=True)
class ConfigIssue:
    level: str
    key: str
    message: str
    action: str


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    if value is None:
        return default
    return str(value or "").strip()


def _is_truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_present_secret(value: str) -> bool:
    return str(value or "").strip() not in _PLACEHOLDERS


def _is_shared_deployment(env: Mapping[str, str]) -> bool:
    return (
        _is_truthy(_get(env, "STUDY_AI_SHARED_DEPLOYMENT"))
        or _is_truthy(_get(env, "PUBLIC_DEPLOYMENT"))
        or _get(env, "ENV").lower() in {"prod", "production"}
        or _get(env, "APP_ENV").lower() in {"prod", "production"}
    )


def _positive_int(env: Mapping[str, str], *keys: str) -> tuple[str, int] | None:
    for key in keys:
        value = _get(env, key)
        if not value:
            continue
        try:
            parsed = int(value)
        except ValueError:
            continue
        if parsed > 0:
            return key, parsed
    return None


def _runtime_model_config() -> dict[str, Any]:
    from backend.core.settings import settings

    return {
        "active_provider": settings.llm_active_provider,
        "routes": dict(settings.model_routes),
        "providers": {
            name: {"api_key_set": bool(provider.api_key), "base_url": provider.base_url}
            for name, provider in settings.model_providers.items()
        },
    }


def _check_model_provider(model_config: Mapping[str, Any], *, route: str) -> list[ConfigIssue]:
    routes = model_config.get("routes") if isinstance(model_config.get("routes"), Mapping) else {}
    provider = str(routes.get(route) or model_config.get("active_provider") or "").strip().lower()
    providers = model_config.get("providers") if isinstance(model_config.get("providers"), Mapping) else {}
    configured = providers.get(provider) if isinstance(providers.get(provider), Mapping) else {}
    if not provider or not configured:
        return [
            ConfigIssue(
                level="missing",
                key=f"routes.{route}",
                message=f"model route {route} does not reference a configured provider",
                action=f"Configure routes.{route} and providers in config/model.json",
            )
        ]
    api_key_set = bool(configured.get("api_key_set")) or _is_present_secret(str(configured.get("api_key") or ""))
    if not api_key_set:
        return [
            ConfigIssue(
                level="missing",
                key=f"providers.{provider}.api_key",
                message=f"model route {route} uses {provider}, but its API key is not configured",
                action=f"Configure providers.{provider}.api_key in config/model.json or the Web model settings page",
            )
        ]
    return []


def check_config(env: Mapping[str, str] | None = None, *, model_config: Mapping[str, Any] | None = None) -> dict:
    source = env if env is not None else os.environ
    resolved_model_config = model_config if model_config is not None else _runtime_model_config()
    issues: list[ConfigIssue] = []

    issues.extend(_check_model_provider(resolved_model_config, route="chat"))
    issues.extend(_check_model_provider(resolved_model_config, route="lesson_plan"))

    jwt_secret = _get(source, "JWT_SECRET")
    if not _is_present_secret(jwt_secret):
        level = "missing" if _is_shared_deployment(source) else "recommended"
        issues.append(
            ConfigIssue(
                level=level,
                key="JWT_SECRET",
                message="JWT_SECRET is empty or uses the development placeholder",
                action="Set a random long JWT_SECRET before shared or public deployment",
            )
        )

    admin_password = _get(source, "ADMIN_PASSWORD")
    if not _is_present_secret(admin_password):
        issues.append(
            ConfigIssue(
                level="recommended",
                key="ADMIN_PASSWORD",
                message="ADMIN_PASSWORD is empty or uses the development placeholder",
                action="Set a strong ADMIN_PASSWORD before shared or public deployment",
            )
        )

    search_mode = _get(source, "STUDY_MATERIALS_SEARCH_MODE", "tavily").lower()
    search_key_by_mode = {"tavily": "TAVILY_API_KEY", "metaso": "METASO_API_KEY", "exa": "EXA_API_KEY"}
    required_search_key = search_key_by_mode.get(search_mode)
    if required_search_key and not _is_present_secret(_get(source, required_search_key)):
        issues.append(
            ConfigIssue(
                level="recommended",
                key=required_search_key,
                message=f"STUDY_MATERIALS_SEARCH_MODE={search_mode} works best with {required_search_key}",
                action=f"Set {required_search_key} or choose another search mode",
            )
        )

    if _is_truthy(_get(source, "LLM_API_KEY_OVERRIDE_ENABLED")) and _is_truthy(
        _get(source, "LLM_API_KEY_OVERRIDE_REQUIRE_ADMIN", "1")
    ):
        if not _is_present_secret(admin_password):
            issues.append(
                ConfigIssue(
                    level="recommended",
                    key="LLM_API_KEY_OVERRIDE_REQUIRE_ADMIN",
                    message="per-request API key override requires an admin boundary, but admin password is still default",
                    action="Set ADMIN_PASSWORD before enabling browser-supplied API keys in shared environments",
                )
            )

    worker_setting = _positive_int(source, "WEB_CONCURRENCY", "UVICORN_WORKERS", "WORKERS")
    if worker_setting and worker_setting[1] > 1:
        issues.append(
            ConfigIssue(
                level="optional",
                key=worker_setting[0],
                message="API rate limits are process-local; multiple backend workers keep independent windows",
                action="Use one backend worker, Redis/shared rate limiting, or edge rate limiting for shared deployments",
            )
        )

    grouped = {
        "missing": [asdict(i) for i in issues if i.level == "missing"],
        "recommended": [asdict(i) for i in issues if i.level == "recommended"],
        "optional": [asdict(i) for i in issues if i.level == "optional"],
    }
    return {
        "ok": not grouped["missing"],
        "missing": grouped["missing"],
        "recommended": grouped["recommended"],
        "optional": grouped["optional"],
        "counts": {key: len(value) for key, value in grouped.items()},
    }


def log_config_check(env: Mapping[str, str] | None = None, *, model_config: Mapping[str, Any] | None = None) -> dict:
    result = check_config(env, model_config=model_config)
    for issue in result.get("missing", []):
        logger.warning("config_missing", extra=_log_extra(issue))
    for issue in result.get("recommended", []):
        logger.info("config_recommended", extra=_log_extra(issue))
    for issue in result.get("optional", []):
        logger.info("config_optional", extra=_log_extra(issue))
    return result


def _log_extra(issue: Mapping[str, object]) -> dict:
    extra = dict(issue)
    if "message" in extra:
        extra["config_message"] = extra.pop("message")
    return extra
