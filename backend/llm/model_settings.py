from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.core.encryption import encrypt_string, is_encrypted_string, mask_secret
from backend.llm.model_config import (
    DEFAULT_PROVIDER_BASE_URLS,
    load_model_json_config,
    normalize_base_url,
    resolve_model_config_path,
)

_PROVIDER_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _normalize_provider_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    raw = _PROVIDER_NAME_RE.sub("-", raw).strip(".-_")
    return raw[:64]


def _json_loads(raw: str) -> Dict[str, Any]:
    try:
        obj = json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _read_raw_payload(*, repo_root: Path) -> Dict[str, Any]:
    path = resolve_model_config_path(repo_root=repo_root)
    if not path.exists():
        return {
            "active_provider": "openrouter",
            "pinned": True,
            "auto": False,
            "providers": {
                "openrouter": {
                    "base_url": DEFAULT_PROVIDER_BASE_URLS["openrouter"],
                }
            },
            "routes": {},
            "models": {},
            "params": {},
            "context": {},
        }
    try:
        return _json_loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _providers_raw(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    providers = payload.get("providers")
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(providers, dict):
        return out
    for name, value in providers.items():
        provider_name = _normalize_provider_name(str(name or ""))
        if not provider_name or not isinstance(value, dict):
            continue
        out[provider_name] = dict(value)
    return out


def _string_field(value: Any, *, max_len: int = 500) -> str:
    return str(value or "").strip()[:max_len]


def _bool_field(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on"}


def _number_field(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _sanitize_models(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}
    for raw_key, raw in value.items():
        key = _normalize_provider_name(str(raw_key or "")).replace("-", "_").replace(".", "_")
        if not key:
            continue
        if isinstance(raw, str):
            model = raw.strip()[:200]
            if model:
                out[key] = model
        elif isinstance(raw, dict):
            scoped: Dict[str, str] = {}
            for provider, model_raw in raw.items():
                provider_name = _normalize_provider_name(str(provider or ""))
                model = _string_field(model_raw, max_len=200)
                if provider_name and model:
                    scoped[provider_name] = model
            if scoped:
                out[key] = scoped
    return out


def _sanitize_routes(value: Any, *, providers: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, str] = {}
    for raw_route, raw_provider in value.items():
        route = _normalize_provider_name(str(raw_route or "")).replace("-", "_").replace(".", "_")
        provider = _normalize_provider_name(str(raw_provider or ""))
        if route and provider and provider in providers:
            out[route] = provider
    return out


def _sanitize_params(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_provider_name(str(raw_key or "")).replace("-", "_").replace(".", "_")
        if not key:
            continue
        if key == "model_tier_map" and isinstance(raw_value, dict):
            tiers: Dict[str, str] = {}
            for tier in ("fast", "cheap", "main", "heavy"):
                model = _string_field(raw_value.get(tier), max_len=200)
                if model:
                    tiers[tier] = model
            if tiers:
                out[key] = tiers
            continue
        if key.endswith("_temperature"):
            number = _number_field(raw_value)
            if number is not None:
                out[key] = max(0.0, min(float(number), 2.0))
            continue
        if key.endswith("_max_tokens"):
            number = _number_field(raw_value)
            if number is not None:
                out[key] = max(0, min(int(number), 500_000))
            continue
        if key.endswith("_effort"):
            effort = _string_field(raw_value, max_len=20).lower().replace("-", "").replace("_", "")
            if effort in {"none", "minimal", "low", "medium", "high", "xhigh"}:
                out[key] = effort
            continue
        if isinstance(raw_value, bool):
            out[key] = raw_value
            continue
        if isinstance(raw_value, (int, float)):
            out[key] = raw_value
            continue
        text = _string_field(raw_value, max_len=500)
        if text:
            out[key] = text
    return out


def _sanitize_context(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}
    lengths_raw = value.get("lengths")
    if isinstance(lengths_raw, dict):
        lengths: Dict[str, int] = {}
        for model, raw_length in lengths_raw.items():
            model_name = _string_field(model, max_len=300).lower()
            number = _number_field(raw_length)
            if model_name and number is not None and int(number) > 0:
                lengths[model_name] = min(int(number), 10_000_000)
        if lengths:
            out["lengths"] = lengths
    multiplier = _number_field(value.get("input_multiplier"))
    if multiplier is not None:
        out["input_multiplier"] = max(1.0, min(float(multiplier), 2.0))
    reserve_ratio = _number_field(value.get("reserve_ratio"))
    if reserve_ratio is not None:
        out["reserve_ratio"] = max(0.0, min(float(reserve_ratio), 0.2))
    reserve_tokens = _number_field(value.get("reserve_tokens"))
    if reserve_tokens is not None:
        out["reserve_tokens"] = max(0, min(int(reserve_tokens), 8192))
    for key, minimum, maximum in (
        ("chat_message_max_tokens", 128, 250_000),
        ("chat_max_tokens", 512, 1_000_000),
    ):
        number = _number_field(value.get(key))
        if number is not None:
            out[key] = max(minimum, min(int(number), maximum))
    fetch_limits = value.get("openrouter_fetch_limits")
    if isinstance(fetch_limits, bool):
        out["openrouter_fetch_limits"] = fetch_limits
    cache_ttl = _number_field(value.get("openrouter_cache_ttl_s"))
    if cache_ttl is not None:
        out["openrouter_cache_ttl_s"] = max(10.0, min(float(cache_ttl), 24.0 * 3600.0))
    timeout = _number_field(value.get("openrouter_timeout_s"))
    if timeout is not None:
        out["openrouter_timeout_s"] = max(1.0, min(float(timeout), 20.0))
    return out


def _provider_secret_from_raw(raw: Dict[str, Any]) -> str:
    encrypted = _string_field(raw.get("api_key_encrypted"), max_len=20_000)
    if encrypted:
        return encrypted
    return _string_field(raw.get("api_key"), max_len=20_000)


def get_model_settings_payload(*, repo_root: Path) -> Dict[str, Any]:
    raw = _read_raw_payload(repo_root=repo_root)
    providers_raw = _providers_raw(raw)
    loaded = load_model_json_config(repo_root=repo_root)
    decrypted = loaded.providers if loaded else {}

    provider_names = sorted(set(providers_raw.keys()) | set(decrypted.keys()) | {str(raw.get("active_provider") or "")})
    providers: List[Dict[str, Any]] = []
    for provider_name in provider_names:
        provider = _normalize_provider_name(provider_name)
        if not provider:
            continue
        raw_provider = providers_raw.get(provider) or {}
        loaded_provider = decrypted.get(provider)
        api_key = loaded_provider.api_key if loaded_provider else ""
        secret_raw = _provider_secret_from_raw(raw_provider)
        providers.append(
            {
                "name": provider,
                "base_url": normalize_base_url(
                    str((loaded_provider.base_url if loaded_provider else "") or raw_provider.get("base_url") or "")
                ),
                "api_key_set": bool(api_key),
                "api_key_mask": mask_secret(api_key),
                "api_key_encrypted": bool(is_encrypted_string(secret_raw) or raw_provider.get("api_key_encrypted")),
            }
        )

    active_provider = _normalize_provider_name(str(raw.get("active_provider") or ""))
    if not active_provider and providers:
        active_provider = providers[0]["name"]
    pinned = bool(loaded.pinned) if loaded else _bool_field(raw.get("pinned"), default=True)

    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    context = raw.get("context") if isinstance(raw.get("context"), dict) else {}
    routes = raw.get("routes") if isinstance(raw.get("routes"), dict) else {}
    return {
        "active_provider": active_provider,
        "pinned": pinned,
        "providers": providers,
        "routes": dict(routes),
        "models": dict(models),
        "params": dict(params),
        "context": dict(context),
        "config_path": str(resolve_model_config_path(repo_root=repo_root)),
        "encryption": {
            "enabled": True,
        },
    }


def save_model_settings_payload(*, repo_root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")

    current_raw = _read_raw_payload(repo_root=repo_root)
    current_loaded = load_model_json_config(repo_root=repo_root)
    providers = _providers_raw(current_raw)

    provider_payload = payload.get("provider")
    if not isinstance(provider_payload, dict):
        provider_payload = {}

    active_provider = _normalize_provider_name(
        str(
            provider_payload.get("name")
            or payload.get("active_provider")
            or current_raw.get("active_provider")
            or "openrouter"
        )
    )
    if not active_provider:
        raise ValueError("invalid_provider")

    existing_provider = providers.get(active_provider) or {}
    loaded_provider = (current_loaded.providers or {}).get(active_provider) if current_loaded else None
    existing_api_key = str(loaded_provider.api_key if loaded_provider else "").strip()

    base_url = normalize_base_url(
        _string_field(
            provider_payload.get("base_url")
            or payload.get("base_url")
            or existing_provider.get("base_url")
            or DEFAULT_PROVIDER_BASE_URLS.get(active_provider, ""),
            max_len=500,
        )
    )
    if not base_url:
        raise ValueError("missing_base_url")

    new_api_key = _string_field(provider_payload.get("api_key") or payload.get("api_key"), max_len=20_000)
    clear_api_key = _bool_field(provider_payload.get("clear_api_key") or payload.get("clear_api_key"), default=False)
    if clear_api_key:
        encrypted_key = ""
    elif new_api_key:
        encrypted_key = encrypt_string(new_api_key)
    elif existing_api_key:
        encrypted_key = encrypt_string(existing_api_key)
    else:
        secret_raw = _provider_secret_from_raw(existing_provider)
        encrypted_key = secret_raw if is_encrypted_string(secret_raw) else ""

    providers[active_provider] = {
        "base_url": base_url,
        **({"api_key": encrypted_key} if encrypted_key else {}),
    }

    for provider_name, provider_raw in list(providers.items()):
        if not isinstance(provider_raw, dict):
            continue
        secret_raw = _provider_secret_from_raw(provider_raw)
        if secret_raw and not is_encrypted_string(secret_raw):
            provider_raw["api_key"] = encrypt_string(secret_raw)
            provider_raw.pop("api_key_encrypted", None)
        providers[provider_name] = provider_raw

    models = dict(current_raw.get("models") if isinstance(current_raw.get("models"), dict) else {})
    models.update(_sanitize_models(payload.get("models")))

    routes = dict(current_raw.get("routes") if isinstance(current_raw.get("routes"), dict) else {})
    routes.update(_sanitize_routes(payload.get("routes"), providers=providers))
    if "active_provider" in payload and "routes" not in payload and not provider_payload:
        for route in ("chat", "lesson_plan", "review"):
            routes[route] = active_provider

    params = dict(current_raw.get("params") if isinstance(current_raw.get("params"), dict) else {})
    params.update(_sanitize_params(payload.get("params")))

    context = dict(current_raw.get("context") if isinstance(current_raw.get("context"), dict) else {})
    context.update(_sanitize_context(payload.get("context")))

    pinned = _bool_field(payload.get("pinned"), default=True)
    next_payload = {
        "active_provider": active_provider,
        "pinned": pinned,
        "auto": not pinned,
        "providers": providers,
        "routes": routes,
        "models": models,
        "params": params,
        "context": context,
    }

    path = resolve_model_config_path(repo_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return get_model_settings_payload(repo_root=repo_root)


def _model_endpoint_candidates(base_url: str) -> List[str]:
    base = normalize_base_url(base_url)
    if not base:
        return []
    candidates = [f"{base}/models"]
    if base.endswith("/v1"):
        return candidates
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(base)
        if parts.scheme and parts.netloc and not str(parts.path or "").strip("/"):
            candidates.append(urlunsplit((parts.scheme, parts.netloc, "/v1/models", parts.query, parts.fragment)))
    except ValueError:
        pass
    return candidates


def _parse_model_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if data is None:
            data = payload.get("models")
    else:
        data = payload

    if not isinstance(data, list):
        return []

    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data[:10_000]:
        if isinstance(item, str):
            model_id = item.strip()
            owner = ""
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
            owner = str(item.get("owned_by") or item.get("owner") or "").strip()
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        out.append({"id": model_id, **({"owned_by": owner} if owner else {})})
    out.sort(key=lambda x: str(x.get("id") or "").lower())
    return out


async def fetch_provider_models(
    *,
    base_url: str,
    api_key: str = "",
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    candidates = _model_endpoint_candidates(base_url)
    if not candidates:
        raise ValueError("missing_base_url")

    headers = {"Accept": "application/json"}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    last_error = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(float(timeout_s))) as client:
        for url in candidates:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code in {404, 405}:
                    last_error = f"http_status_{resp.status_code}"
                    continue
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError:
                    last_error = "invalid_json_response"
                    continue
                models = _parse_model_items(data)
                return {"models": models, "count": len(models), "url": url}
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                last_error = f"http_status_{status}"
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_error = str(exc)[:200] or "request_failed"

    raise RuntimeError(last_error or "fetch_models_failed")
