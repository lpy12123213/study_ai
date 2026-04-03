from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["SecretString"]


@dataclass(frozen=True)
class SecretString:
    """
    A tiny secret wrapper (similar to pydantic's SecretStr) with safe string/repr.

    - `str(secret)` and `repr(secret)` never reveal the underlying value.
    - Use `get_secret_value()` to access the real string.
    """

    _value: str = ""

    def get_secret_value(self) -> str:
        return str(self._value or "")

    def is_set(self) -> bool:
        return bool(str(self._value or "").strip())

    def __bool__(self) -> bool:  # pragma: no cover (tiny helper)
        return self.is_set()

    def __str__(self) -> str:
        return "****" if self.is_set() else ""

    def __repr__(self) -> str:
        return "SecretString('****')" if self.is_set() else "SecretString('')"

    def __eq__(self, other: Any) -> bool:  # noqa: ANN401
        if isinstance(other, SecretString):
            return self.get_secret_value() == other.get_secret_value()
        if isinstance(other, str):
            return self.get_secret_value() == other
        return False

