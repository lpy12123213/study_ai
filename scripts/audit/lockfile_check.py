from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Tools removed from the repo; their presence in a lock file means the snapshot
# was taken before the removal or was hand-edited. These are hard rejections.
_REMOVED_TOOLS = {"mypy", "mypy-extensions", "mypy_extensions"}


def _requirement_name(line: str) -> str:
    """Extract the normalized package name from a requirements line.

    Handles specifiers, extras and environment markers, e.g.
    "pkg[extra]==1.0; sys_platform == 'win32'" -> "pkg".
    """
    body = line.split(";", 1)[0].strip()
    for sep in ("===", "==", ">=", "<=", "~=", "!=", ">", "<", "@"):
        if sep in body:
            body = body.split(sep, 1)[0]
            break
    name = body.strip().lower().replace("_", "-")
    return name.split("[", 1)[0]


def _is_editable_or_local(line: str) -> bool:
    """Return True when a line pins an editable install or a local filesystem path."""
    stripped = line.strip()
    if stripped.startswith(("-e ", "--editable ")):
        return True
    req_part = stripped.split(";", 1)[0].strip()
    if req_part.startswith(("file://", "/", "./", "../")):
        return True
    # Windows drive-absolute path, e.g. C:\dev\pkg or C:/dev/pkg
    if len(req_part) >= 3 and req_part[0].isalpha() and req_part[1:3] in (":\\", ":/"):
        return True
    return False


def _detect_platform(lock_name: str) -> str:
    """Infer the target platform from the lock file name; unknown means non-Windows."""
    lower = lock_name.lower()
    if "win" in lower:
        return "win"
    return "linux"


def check_lock_file(path: Path, *, platform: str | None = None) -> list[str]:
    """Return a list of policy violations for a lock file (empty when valid)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"cannot_read_lock {path}: {exc}"]

    win_lock = (platform or _detect_platform(path.name)) == "win"
    findings: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _is_editable_or_local(stripped):
            findings.append(f"line {index}: editable/local path must not be locked: {stripped!r}")
            continue
        name = _requirement_name(stripped)
        if name in _REMOVED_TOOLS:
            findings.append(f"line {index}: removed tool {name!r} must not be locked")
            continue
        if name == "pywin32" and not win_lock:
            findings.append(f"line {index}: pywin32 is only allowed in a Windows lock")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a pip lock file against repo dependency policy.")
    parser.add_argument("lockfile", type=Path, help="path to the lock file to check")
    parser.add_argument(
        "--platform",
        choices=["win", "linux"],
        default=None,
        help="target platform; inferred from the filename when omitted (pywin32 allowed only for win)",
    )
    args = parser.parse_args(argv)

    if not args.lockfile.exists():
        print(f"lockfile_check: missing lockfile {args.lockfile}")
        return 1

    findings = check_lock_file(args.lockfile, platform=args.platform)
    if not findings:
        print("lockfile_check: ok")
        return 0

    for finding in findings:
        print(f"lockfile_check: {finding}")
    print(f"lockfile_check: {len(findings)} violation(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
