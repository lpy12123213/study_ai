from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Mapping

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

_PROVIDER_KEYS = {
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
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


def _provider_key(provider: str) -> str:
    return _PROVIDER_KEYS.get(str(provider or "").strip().lower(), "")


def _check_provider(env: Mapping[str, str], *, provider_key: str, setting_key: str, default: str) -> list[ConfigIssue]:
    provider = _get(env, provider_key, default).lower()
    key = _provider_key(provider)
    if not key:
        return [
            ConfigIssue(
                level="missing",
                key=provider_key,
                message=f"{provider_key} must be one of: openrouter, fireworks, moonshot",
                action=f"Set {provider_key}=openrouter|fireworks|moonshot",
            )
        ]
    if not _is_present_secret(_get(env, key)):
        return [
            ConfigIssue(
                level="missing",
                key=key,
                message=f"{setting_key} uses {provider}, but {key} is not configured",
                action=f"Set {key} or configure the provider in config/model.json",
            )
        ]
    return []


def check_config(env: Mapping[str, str] | None = None) -> dict:
    source = env if env is not None else os.environ
    issues: list[ConfigIssue] = []

    issues.extend(
        _check_provider(source, provider_key="CHAT_PROVIDER", setting_key="chat", default="openrouter")
    )
    issues.extend(
        _check_provider(source, provider_key="LESSON_PLAN_PROVIDER", setting_key="lesson_plan", default=_get(source, "CHAT_PROVIDER", "openrouter"))
    )

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


def log_config_check(env: Mapping[str, str] | None = None) -> dict:
    result = check_config(env)
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
