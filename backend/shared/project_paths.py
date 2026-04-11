from __future__ import annotations

from pathlib import Path


def resolve_repo_root() -> Path:
    """Return the repository root for runtime path resolution."""

    return Path(__file__).resolve().parents[2]


def resolve_repo_local_dir() -> Path:
    """Return the repo-local runtime state directory."""

    return (resolve_repo_root() / ".local").resolve()
