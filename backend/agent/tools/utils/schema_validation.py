from __future__ import annotations

from typing import Any, Dict, Optional


def _is_int(value: Any) -> bool:
    # bool is a subclass of int in Python; treat it as non-int for schema purposes.
    return isinstance(value, int) and not isinstance(value, bool)


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if _is_int(value):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clamp_number(value: Any, *, minimum: Optional[float], maximum: Optional[float]) -> Any:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    if minimum is not None:
        v = max(float(minimum), v)
    if maximum is not None:
        v = min(float(maximum), v)
    if _is_int(value):
        return int(v)
    return v


def validate_and_coerce_args(*, schema: Dict[str, Any], args: Any, tool_name: str = "") -> Dict[str, Any]:
    """Validate (lightly) + coerce tool arguments against a JSON-schema-like dict.

    Supported subset:
    - type=object + properties + required
    - property type: string|integer|number|boolean|array|object
    - enum
    - minimum/maximum (numbers)
    - minLength/maxLength (strings) (non-strict: clamp)
    - minItems/maxItems (arrays) (non-strict: clamp)

    This is not a full JSON Schema implementation. The goal is to:
    - prevent obvious shape mismatches
    - improve robustness (coerce "10" -> 10)
    - keep backwards compatibility (default allows additional properties)
    """

    if args is None:
        args_dict: Dict[str, Any] = {}
    elif isinstance(args, dict):
        args_dict = dict(args)
    else:
        raise ValueError(f"invalid_tool_arguments: {tool_name or ''} expects object")

    schema_type = str((schema or {}).get("type") or "").strip().lower()
    if schema_type and schema_type != "object":
        # Unexpected schemas are treated as best-effort passthrough.
        return args_dict

    props = (schema or {}).get("properties")
    props = props if isinstance(props, dict) else {}
    required = (schema or {}).get("required")
    required_list = [str(x).strip() for x in required] if isinstance(required, list) else []

    for key in required_list:
        if not key:
            continue
        if key not in args_dict:
            raise ValueError(f"missing_required_argument: {tool_name}:{key}")

    additional_allowed = True
    if "additionalProperties" in (schema or {}):
        additional_allowed = bool((schema or {}).get("additionalProperties"))

    if not additional_allowed and props:
        extra = [k for k in args_dict.keys() if k not in props]
        if extra:
            raise ValueError(f"unexpected_arguments: {tool_name}:{','.join(sorted(extra)[:8])}")

    out: Dict[str, Any] = dict(args_dict)

    for key, prop_schema in props.items():
        if key not in out:
            continue
        if not isinstance(prop_schema, dict):
            continue

        expected = str(prop_schema.get("type") or "").strip().lower()
        enum = prop_schema.get("enum")
        enum_list = list(enum) if isinstance(enum, list) else None

        value = out.get(key)
        if value is None:
            continue

        coerced: Any = value
        if expected == "boolean":
            v = _coerce_bool(value)
            if v is None and not isinstance(value, bool):
                raise ValueError(f"invalid_argument_type: {tool_name}:{key} expected boolean")
            coerced = bool(v) if v is not None else value
        elif expected == "integer":
            v = _coerce_int(value)
            if v is None:
                raise ValueError(f"invalid_argument_type: {tool_name}:{key} expected integer")
            minimum = prop_schema.get("minimum")
            maximum = prop_schema.get("maximum")
            coerced = _clamp_number(v, minimum=minimum, maximum=maximum)
            coerced = int(coerced) if coerced is not None else v
        elif expected == "number":
            v = _coerce_float(value)
            if v is None:
                raise ValueError(f"invalid_argument_type: {tool_name}:{key} expected number")
            minimum = prop_schema.get("minimum")
            maximum = prop_schema.get("maximum")
            coerced = _clamp_number(v, minimum=minimum, maximum=maximum)
        elif expected == "string":
            coerced = str(value)
            try:
                min_len = int(prop_schema.get("minLength")) if prop_schema.get("minLength") is not None else None
            except (TypeError, ValueError):
                min_len = None
            try:
                max_len = int(prop_schema.get("maxLength")) if prop_schema.get("maxLength") is not None else None
            except (TypeError, ValueError):
                max_len = None
            if max_len is not None and len(coerced) > max_len:
                coerced = coerced[:max_len]
            if min_len is not None and len(coerced) < min_len:
                raise ValueError(f"invalid_argument_length: {tool_name}:{key} too_short")
        elif expected == "array":
            if isinstance(value, (str, bytes)):
                raise ValueError(f"invalid_argument_type: {tool_name}:{key} expected array")
            if not isinstance(value, list):
                # allow a single item to be wrapped
                value = [value]
            items_schema = prop_schema.get("items") if isinstance(prop_schema.get("items"), dict) else {}
            item_type = str(items_schema.get("type") or "").strip().lower()
            coerced_items: list[Any] = []
            for it in value:
                if item_type == "string":
                    coerced_items.append(str(it))
                elif item_type == "integer":
                    v = _coerce_int(it)
                    if v is None:
                        continue
                    coerced_items.append(v)
                elif item_type == "number":
                    v = _coerce_float(it)
                    if v is None:
                        continue
                    coerced_items.append(v)
                elif item_type == "object":
                    if isinstance(it, dict):
                        coerced_items.append(dict(it))
                else:
                    coerced_items.append(it)
            # Clamp length if requested.
            try:
                max_items = int(prop_schema.get("maxItems")) if prop_schema.get("maxItems") is not None else None
            except (TypeError, ValueError):
                max_items = None
            if max_items is not None and len(coerced_items) > max_items:
                coerced_items = coerced_items[:max_items]
            coerced = coerced_items
        elif expected == "object":
            if not isinstance(value, dict):
                raise ValueError(f"invalid_argument_type: {tool_name}:{key} expected object")
            coerced = dict(value)
        else:
            # Unknown/unspecified expected type: leave as-is.
            coerced = value

        if enum_list is not None and enum_list:
            if coerced not in enum_list:
                raise ValueError(f"invalid_argument_enum: {tool_name}:{key}")

        out[key] = coerced

    return out
