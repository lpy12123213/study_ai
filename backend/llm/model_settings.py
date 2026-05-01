from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.core.encryption import encrypt_string, is_encrypted_string, mask_secret
from backend.llm.model_config import load_model_json_config, normalize_base_url, resolve_model_config_path

_PROVIDER_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")

DEFAULT_PROVIDER_BASE_URLS: Dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
}


def _normalize_provider_name(value: str) -> str:
    raw = str(value or "").strip().lower()
    raw = _PROVIDER_NAME_RE.sub("-", raw).strip(".-_")
    return raw[:64]


def _json_loads(raw: str) -> Dict[str, Any]:
    try:
        obj = json.loads(str(raw or ""))
    except Exception:
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
            "models": {},
            "params": {},
        }
    try:
        return _json_loads(path.read_text(encoding="utf-8"))
    except Exception:
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
    for key in ("main", "sub", "lesson_plan", "review"):
        raw = value.get(key)
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


def _sanitize_params(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in ("main_temperature", "sub_temperature"):
        number = _number_field(value.get(key))
        if number is not None:
            out[key] = max(0.0, min(float(number), 2.0))
    for key in ("main_max_tokens", "sub_max_tokens"):
        number = _number_field(value.get(key))
        if number is not None:
            out[key] = max(1, min(int(number), 500_000))
    effort = _string_field(value.get("thinking_effort"), max_len=20).lower().replace("-", "").replace("_", "")
    if effort in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        out["thinking_effort"] = effort
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
    return {
        "active_provider": active_provider,
        "pinned": pinned,
        "providers": providers,
        "models": dict(models),
        "params": dict(params),
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

    params = dict(current_raw.get("params") if isinstance(current_raw.get("params"), dict) else {})
    params.update(_sanitize_params(payload.get("params")))

    pinned = _bool_field(payload.get("pinned"), default=True)
    next_payload = {
        "active_provider": active_provider,
        "pinned": pinned,
        "auto": not pinned,
        "providers": providers,
        "models": models,
        "params": params,
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
    except Exception:
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
                except Exception:
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
