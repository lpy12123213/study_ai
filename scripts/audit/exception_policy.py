from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.exception_policy import iter_python_files, scan_paths


def _parse_kind_limits(raw_limits: list[str], parser: argparse.ArgumentParser) -> dict[str, int]:
    limits: dict[str, int] = {}
    for raw in raw_limits:
        if "=" not in raw:
            parser.error("--max-kind must use KIND=COUNT")
        kind, raw_count = raw.split("=", 1)
        kind = kind.strip()
        if not kind:
            parser.error("--max-kind kind cannot be empty")
        try:
            count = int(raw_count)
        except ValueError:
            parser.error("--max-kind count must be an integer")
        if count < 0:
            parser.error("--max-kind count cannot be negative")
        limits[kind] = count
    return limits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit broad backend exception handlers.")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["backend"],
        help="Python files or directories to scan. Defaults to backend/.",
    )
    parser.add_argument("--strict", action="store_true", help="exit with code 1 when findings are found")
    parser.add_argument("--limit", type=int, default=80, help="maximum findings to print")
    parser.add_argument("--max-total", type=int, default=None, help="allow up to N current findings in strict mode")
    parser.add_argument(
        "--max-kind",
        action="append",
        default=[],
        metavar="KIND=COUNT",
        help="allow up to COUNT findings for a specific kind in strict mode; repeatable",
    )
    args = parser.parse_args(argv)
    if args.max_total is not None and args.max_total < 0:
        parser.error("--max-total cannot be negative")
    kind_limits = _parse_kind_limits(args.max_kind, parser)

    scan_files = []
    for raw in args.paths:
        path = (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw)
        if path.is_dir():
            scan_files.extend(iter_python_files(path))
        else:
            scan_files.append(path)

    findings = scan_paths(scan_files)
    if not findings:
        print("exception_policy: ok")
        return 0

    counts = Counter(f.kind for f in findings)
    print(
        "exception_policy: warnings "
        + " ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        + f" total={len(findings)}"
    )
    for finding in findings[: max(0, int(args.limit))]:
        path = Path(finding.path)
        try:
            label = path.relative_to(ROOT).as_posix()
        except ValueError:
            label = path.as_posix()
        print(f"- {label}:{finding.line} {finding.kind}: {finding.message}")
    if len(findings) > args.limit:
        print(f"... {len(findings) - args.limit} more")

    if not args.strict:
        return 0

    if args.max_total is None and not kind_limits:
        return 1

    exceeded = []
    if args.max_total is not None and len(findings) > args.max_total:
        exceeded.append(f"total={len(findings)}>{args.max_total}")
    for kind, allowed in sorted(kind_limits.items()):
        actual = counts.get(kind, 0)
        if actual > allowed:
            exceeded.append(f"{kind}={actual}>{allowed}")

    if exceeded:
        print("exception_policy: strict budget exceeded " + " ".join(exceeded))
        return 1
    print("exception_policy: strict budget ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
