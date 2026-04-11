from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path


def _configure_project_local_tempdir() -> None:
    """Force unittest temp directories under the repo-local `.local/`.

    The sandbox used for CI/dev tooling may deny writes to system temp (WinError 5),
    causing flaky failures when tests use `tempfile.TemporaryDirectory()` defaults.
    """

    try:
        repo_root = Path(__file__).resolve().parents[2]
        tmp_root = repo_root / ".local" / "tmp" / "unittest"
        tmp_root.mkdir(parents=True, exist_ok=True)

        # Prefer env vars for any subprocesses, but also set tempfile's cached value
        # so callers that already imported tempfile behave consistently.
        # Always override: the default user temp directory may be non-writable
        # in sandboxed environments.
        os.environ["TMPDIR"] = str(tmp_root)
        os.environ["TEMP"] = str(tmp_root)
        os.environ["TMP"] = str(tmp_root)
        tempfile.tempdir = str(tmp_root)

        if os.name == "nt":
            # In some sandboxed Windows environments, `tempfile.mkdtemp()` uses
            # `os.mkdir(path, 0o700)` which produces an unwritable directory.
            # Patch mkdtemp to create directories with default permissions.
            _real_mkdtemp = tempfile.mkdtemp

            def _mkdtemp_safe(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
                suf = "" if suffix is None else str(suffix)
                pre = "tmp" if prefix is None else str(prefix)
                root = Path(dir or tempfile.gettempdir())
                root.mkdir(parents=True, exist_ok=True)
                for _ in range(200):
                    # Keep the name format close to stdlib: `prefix + random + suffix`.
                    name = f"{pre}{uuid.uuid4().hex}{suf}"
                    candidate = root / name
                    try:
                        os.mkdir(candidate)  # default mode (writable in sandbox)
                        return str(candidate)
                    except FileExistsError:
                        continue
                # Fall back to stdlib behavior as a last resort.
                return _real_mkdtemp(suffix=suf, prefix=pre, dir=str(root))

            tempfile.mkdtemp = _mkdtemp_safe  # type: ignore[assignment]
    except Exception:
        # Best-effort only: falling back to system temp is acceptable outside sandbox.
        pass


_configure_project_local_tempdir()


def _configure_required_auth_env() -> None:
    """Set required auth env vars for test imports.

    `backend.core.auth` requires JWT_SECRET and ADMIN_PASSWORD (or ADMIN_PASSWORD_HASH).
    Tests should not depend on a developer's local `.env` being present.
    """

    os.environ.setdefault("JWT_SECRET", "test-jwt-secret-change-me")
    os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password-change-me")


_configure_required_auth_env()
