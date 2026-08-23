from __future__ import annotations

from typing import Tuple

CHAT_COMPLETIONS_PROTOCOL = "chat_completions"
RESPONSES_PROTOCOL = "responses"


def resolve_protocol(*, provider: str, model: str) -> str:
    """Select the wire protocol without rewriting the provider's raw model id."""

    provider_name = str(provider or "").strip().lower()
    model_id = str(model or "").strip().lower()
    if provider_name == "opencode_go" and model_id == "muse-spark-1.2-contributor":
        return RESPONSES_PROTOCOL
    return CHAT_COMPLETIONS_PROTOCOL


def resolve_provider(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    moonshot_key: str,
    moonshot_base_url: str,
    allow_moonshot_auto_switch: bool = True,
) -> Tuple[str, str, str, str]:
    normalized_provider = (provider or "").strip().lower() or "openrouter"
    normalized_base_url = (base_url or "").strip().rstrip("/")
    normalized_api_key = (api_key or "").strip()

    normalized_model = (model or "").strip()
    model_lower = normalized_model.lower()
    m_key = (moonshot_key or "").strip()
    m_base_url = (moonshot_base_url or "").strip().rstrip("/")

    if normalized_provider == "moonshot" or (
        allow_moonshot_auto_switch
        and normalized_provider == "openrouter"
        and m_key
        and (
            model_lower.startswith("moonshotai/")
            or model_lower.startswith("kimi-")
            or model_lower.startswith("moonshot-")
        )
    ):
        normalized_provider = "moonshot"
        normalized_api_key = m_key or normalized_api_key
        normalized_base_url = m_base_url or normalized_base_url
        if "/" in normalized_model:
            normalized_model = normalized_model.split("/")[-1]

    return normalized_provider, normalized_base_url, normalized_api_key, normalized_model
