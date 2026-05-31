"""Sidecar persistence of diagram source code.

Each rendered diagram writes a JSON sidecar next to its output file:
`.local/media/generated/<filename>.source.json`. The sidecar records the
generator inputs so a later revision can read them back, ask an LLM to
patch the source, and re-render — without needing a DB schema change.

Sidecar schema:
{
  "kind": "tikz" | "asy" | "matplotlib_2d" | "matplotlib_3d" | "chemistry" | "circuit" | "graphviz" | "svg" | "schematic",
  "source": <kind-specific>,
  "alt": "string",
  "created_at": "2026-05-23T..."
}

For text-source kinds (tikz / asy / dot / mhchem), `source` is `{code, preamble?}`.
For spec-driven kinds (matplotlib_2d / matplotlib_3d / svg / schematic / circuit),
`source` is the full spec dict the renderer consumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.core.logging_utils import get_logger
from backend.core.time_utils import utcnow_naive

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERATED_DIR = (_REPO_ROOT / ".local" / "media" / "generated").resolve()

_SOURCE_SUFFIX = ".source.json"


def _sidecar_path(filename: str) -> Optional[Path]:
    name = (filename or "").strip().lstrip("/")
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = (_GENERATED_DIR / f"{name}{_SOURCE_SUFFIX}").resolve()
    try:
        path.relative_to(_GENERATED_DIR)
    except ValueError:
        return None
    return path


def write_source_sidecar(
    *,
    filename: str,
    kind: str,
    source: Any,
    alt: str = "",
) -> None:
    """Write a source sidecar for a rendered diagram. Best-effort; never raises."""

    path = _sidecar_path(filename)
    if path is None:
        return
    try:
        _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": str(kind or "").strip(),
            "source": source,
            "alt": str(alt or "").strip(),
            "created_at": utcnow_naive().isoformat() + "Z",
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        logger.debug("diagram_source_sidecar_write_failed", exc_info=True)


def read_source_sidecar(filename: str) -> Optional[Dict[str, Any]]:
    """Return the sidecar dict if it exists and is readable; else None."""

    path = _sidecar_path(filename)
    if path is None or not path.exists() or not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None
