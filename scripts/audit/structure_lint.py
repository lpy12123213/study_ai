from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DOMAIN_ROUTERS = {
    "system_domain_router",
    "integrations_domain_router",
    "workspace_domain_router",
    "auth_domain_router",
    "generation_domain_router",
    "tasks_domain_router",
}

BANNED_LONG_LIVED_DIR_NAMES = {"legacy", "compat", "shim"}
BANNED_LONG_LIVED_FILE_PATTERNS = [
    re.compile(r".*_(?:legacy|compat|shim)\.py$"),
    re.compile(r".*_v\d+\.py$"),
]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def check_app_router() -> list[str]:
    app_py = ROOT / "backend" / "app.py"
    text = read_text(app_py)
    problems: list[str] = []
    if "from backend.api.router import api_router" not in text:
        problems.append("backend/app.py must import api_router from backend.api.router")
    if "app.include_router(api_router)" not in text:
        problems.append("backend/app.py must include only the aggregated api_router")

    direct_includes = [
        line.strip()
        for line in text.splitlines()
        if ".include_router(" in line and "api_router" not in line
    ]
    for line in direct_includes:
        problems.append(f"backend/app.py contains direct router registration: {line}")
    return problems


def check_domain_aggregation() -> list[str]:
    router_py = ROOT / "backend" / "api" / "router.py"
    text = read_text(router_py)
    problems: list[str] = []
    for name in sorted(DOMAIN_ROUTERS):
        if f"include_router({name})" not in text:
            problems.append(f"backend/api/router.py must include {name}")

    domain_dir = ROOT / "backend" / "api" / "domains"
    expected = {"__init__.py", "auth.py", "generation.py", "integrations.py", "system.py", "tasks.py", "workspace.py"}
    actual = {path.name for path in domain_dir.glob("*.py")}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        problems.append(f"backend/api/domains missing expected files: {', '.join(missing)}")
    if extra:
        problems.append(f"backend/api/domains has unplanned domain files: {', '.join(extra)}")
    return problems


def check_migration_doc() -> list[str]:
    path = ROOT / "docs" / "MIGRATION_PLAN.md"
    text = read_text(path)
    if not text:
        return ["docs/MIGRATION_PLAN.md is required for domain migration work"]
    required_terms = ["system", "auth", "workspace", "generation", "tasks", "integrations", "shared"]
    missing = [term for term in required_terms if term not in text]
    if missing:
        return [f"docs/MIGRATION_PLAN.md missing target domains: {', '.join(missing)}"]
    return []


def check_banned_dir_names() -> list[str]:
    problems: list[str] = []
    roots = [ROOT / "backend", ROOT / "frontend" / "src"]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_dir():
                continue
            name = path.name.lower()
            if name in BANNED_LONG_LIVED_DIR_NAMES or re.search(r"_v\d+$", name):
                problems.append(f"long-lived compatibility directory is not allowed: {rel(path)}")
    return problems


def check_banned_file_names() -> list[str]:
    problems: list[str] = []
    roots = [ROOT / "backend", ROOT / "frontend" / "src"]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            name = path.name.lower()
            if any(pattern.match(name) for pattern in BANNED_LONG_LIVED_FILE_PATTERNS):
                problems.append(f"long-lived compatibility module is not allowed: {rel(path)}")
    return problems


def check_expiring_compat_modules() -> list[str]:
    """Compatibility wrappers are tracked externally during the migration."""

    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Study AI domain-boundary structure.")
    parser.add_argument("--strict", action="store_true", help="exit with code 1 when problems are found")
    args = parser.parse_args(argv)

    problems: list[str] = []
    for check in (
        check_app_router,
        check_domain_aggregation,
        check_migration_doc,
        check_banned_dir_names,
        check_banned_file_names,
        check_expiring_compat_modules,
    ):
        problems.extend(check())

    if not problems:
        print("structure_lint: ok")
        return 0

    print("structure_lint: warnings")
    for problem in problems:
        print(f"- {problem}")
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
