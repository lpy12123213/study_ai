from __future__ import annotations

"""Repo-local Python startup tweaks.

Python automatically imports `sitecustomize` (if available on `sys.path`) during
startup. Because we run commands from the repo root, this file is picked up in
development and CI.

Why this exists:
In some sandboxed Windows environments, `tempfile.mkdtemp()` uses
`os.mkdir(path, 0o700)` which results in directories that are not writable and
not deletable (WinError 5). This breaks unit tests (and any code using
`tempfile.TemporaryDirectory()`).

We patch `tempfile.mkdtemp` to create directories with default permissions
instead of mode 0o700, and we point `TEMP/TMP/TMPDIR` at a repo-local temp dir.
The patch is best-effort and only applied on Windows.
"""

import os
import tempfile
import uuid
from pathlib import Path


def _patch_tempfile_for_windows_sandbox() -> None:
    if os.name != "nt":
        return

    # Prefer a repo-local temp dir so we don't depend on the user/system temp
    # behavior in sandboxed environments.
    try:
        repo_root = Path(__file__).resolve().parent
        tmp_root = repo_root / ".local" / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = str(tmp_root)
        os.environ["TEMP"] = str(tmp_root)
        os.environ["TMP"] = str(tmp_root)
    except Exception:
        tmp_root = None

    try:
        real_mkdtemp = tempfile.mkdtemp

        def mkdtemp_safe(
            suffix: str | None = None,
            prefix: str | None = None,
            dir: str | None = None,
        ) -> str:
            suf = "" if suffix is None else str(suffix)
            pre = "tmp" if prefix is None else str(prefix)

            base = dir or os.environ.get("TMPDIR") or os.environ.get("TEMP") or tempfile.gettempdir()
            root = Path(base)
            root.mkdir(parents=True, exist_ok=True)

            # Keep behavior close to stdlib: try many candidates.
            for _ in range(200):
                candidate = root / f"{pre}{uuid.uuid4().hex}{suf}"
                try:
                    # IMPORTANT: do not pass mode=0o700 on this environment.
                    os.mkdir(candidate)
                    return str(candidate)
                except FileExistsError:
                    continue

            # Last resort: fall back to the original implementation.
            return real_mkdtemp(suffix=suf, prefix=pre, dir=str(root))

        tempfile.mkdtemp = mkdtemp_safe  # type: ignore[assignment]
    except Exception:
        # Best-effort only.
        return


_patch_tempfile_for_windows_sandbox()

