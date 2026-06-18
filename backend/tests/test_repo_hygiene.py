"""Repository hygiene regression tests.

Codifies the P0+P1 cleanup so the repo cannot regress:

P0.1 - No Next.js scaffolding files tracked (project uses Vite).
P0.2 - No migrated-empty source directories left behind (only __pycache__).
P1.1 - nextstep/ plans archived into docs/plans/ (no loose nextstep/*.md).
P1.2 - .env.example documents every env key referenced in backend Python.

P2.1 - Every router defined in backend/api/*.py is aggregated by a domain or router.py.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- P0.1: Next.js scaffolding that must NOT be tracked (project uses Vite) ---
NEXTJS_SCAFFOLDING_PATHS = [
    "frontend/app/layout.tsx",
    "frontend/app/page.tsx",
    "frontend/app/globals.css",
    "frontend/app/favicon.ico",
    "frontend/next-env.d.ts",
    "frontend/next.config.ts",
    "frontend/.next/types/cache-life.d.ts",
    "frontend/.next/types/routes.d.ts",
    "frontend/.next/types/validator.ts",
]

# --- P0.2: Source dirs whose code migrated to backend/generation/ or backend/workspace/ ---
MIGRATED_EMPTY_DIRS = [
    "backend/chat",
    "backend/crawler",
    "backend/lesson_plan",
    "backend/paper_compose",
    "backend/question_library",
    "backend/deepthink",
    "backend/study_materials",
    "backend/question_evaluate",
    "mcp_server",
]

# --- P1.1: nextstep/ plan docs must be archived, not loose ---
NEXTSTEP_LOOSE_PLANS = [
    "nextstep/ai-paper-compose-enhancement.md",
    "nextstep/aurora-glass-design-system-plan.md",
    "nextstep/canvas-frontend-plan.md",
    "nextstep/chat-tool-expansion-plan.md",
    "nextstep/deprecate-legacy-code-plan.md",
    "nextstep/generation-quality-small-wins-plan.md",
    "nextstep/insights-learning-analytics-plan.md",
    "nextstep/master-detail-layout-plan.md",
    "nextstep/online-exam-plan.md",
    "nextstep/question-bank-tui-and-launcher-plan.md",
    "nextstep/question-library-fts-plan.md",
    "nextstep/wrongbook-srs-mastery-plan.md",
]

# --- P1.2: env key extraction (same regex as scripts/tech_debt_report.py) ---
ENV_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
PY_ENV_LITERAL_RE = re.compile(
    r"""(?:os\.getenv|os\.environ\.get|_get_(?:str|int|float|bool))\(\s*["']([A-Z0-9_]+)["']"""
)
# Accept both "KEY=value" and "# KEY=value" (commented optional keys with defaults).
ENV_EXAMPLE_KEY_RE = re.compile(r"^(?:#\s*)?([A-Z][A-Z0-9_]{2,})\s*=")

# Internal/test-only env keys that are allowed to be absent from .env.example.
# These are runtime-injected or test harness keys, not user-facing config.
ENV_KEY_ALLOWLIST = {
    "JWT_SECRET_OVERRIDE_FOR_TESTS",
    "ADMIN_PASSWORD_OVERRIDE_FOR_TESTS",
}


def _git_ls_files() -> set[str]:
    try:
        out = subprocess.check_output(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return {ln.strip() for ln in out.decode("utf-8", errors="ignore").splitlines() if ln.strip()}
    except (subprocess.CalledProcessError, OSError):
        return set()


def _env_keys_from_env_example() -> set[str]:
    path = REPO_ROOT / ".env.example"
    if not path.exists():
        return set()
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        m = ENV_EXAMPLE_KEY_RE.match(line)
        if m:
            key = m.group(1).strip()
            if ENV_KEY_RE.fullmatch(key):
                keys.add(key)
    return keys


def _env_keys_from_backend_python() -> set[str]:
    keys: set[str] = set()
    backend_dir = REPO_ROOT / "backend"
    for py_file in backend_dir.rglob("*.py"):
        parts = py_file.parts
        if "__pycache__" in parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in PY_ENV_LITERAL_RE.finditer(text):
            key = m.group(1).strip()
            if ENV_KEY_RE.fullmatch(key):
                keys.add(key)
    return keys


class TestRepoHygieneP0(unittest.TestCase):
    """P0: dead code removal regression tests."""

    def test_no_nextjs_scaffolding_tracked(self):
        """Project uses Vite; Next.js scaffolding files must not be git-tracked."""
        tracked = _git_ls_files()
        found = sorted(p for p in NEXTJS_SCAFFOLDING_PATHS if p in tracked)
        self.assertEqual(found, [], f"Next.js scaffolding still tracked: {found}")

    def test_no_migrated_empty_source_dirs(self):
        """Migrated source dirs must not exist (not even as __pycache__-only shells)."""
        remaining = []
        for d in MIGRATED_EMPTY_DIRS:
            path = REPO_ROOT / d
            if path.exists():
                remaining.append(d)
        self.assertEqual(remaining, [], f"Empty migrated dirs still present: {remaining}")


class TestRepoHygieneP1(unittest.TestCase):
    """P1: plan archival and env documentation coverage."""

    def test_nextstep_plans_archived_not_loose(self):
        """nextstep/*.md plan files must be archived into docs/plans/, not loose."""
        remaining = []
        for rel in NEXTSTEP_LOOSE_PLANS:
            if (REPO_ROOT / rel).exists():
                remaining.append(rel)
        self.assertEqual(remaining, [], f"Loose nextstep plans not archived: {remaining}")

    def test_env_example_covers_backend_keys(self):
        """Every env key referenced in backend Python must appear in .env.example."""
        documented = _env_keys_from_env_example()
        used = _env_keys_from_backend_python()
        missing = sorted((used - documented) - ENV_KEY_ALLOWLIST)
        self.assertEqual(
            missing,
            [],
            f"Env keys used in backend but not in .env.example ({len(missing)}): {missing}",
        )


# --- P2.1: router aggregation ---
ROUTER_DEF_RE = re.compile(r"^(\w+_router|router)\s*=\s*APIRouter\(", re.MULTILINE)
ROUTER_IMPORT_RE = re.compile(r"^from\s+backend\.api\.([\w.]+)\s+import\s+(.+)$", re.MULTILINE)


def _routers_defined_in_api_flat() -> dict[str, list[str]]:
    """Map module name -> list of router variable names defined in backend/api/*.py (flat, not domains/)."""
    api_dir = REPO_ROOT / "backend" / "api"
    result: dict[str, list[str]] = {}
    for py in api_dir.glob("*.py"):
        if py.name in {"__init__.py", "router.py"}:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        names = [m.group(1) for m in ROUTER_DEF_RE.finditer(text)]
        if names:
            result[py.stem] = names
    # Also include nested integrations/openai_adapter.py
    nested = api_dir / "integrations" / "openai_adapter.py"
    if nested.exists():
        try:
            text = nested.read_text(encoding="utf-8", errors="ignore")
            names = [m.group(1) for m in ROUTER_DEF_RE.finditer(text)]
            if names:
                result["integrations/openai_adapter"] = names
        except OSError:
            pass
    return result


def _aggregated_module_names() -> set[str]:
    """Module names imported by domains/*.py or router.py (the aggregation layer)."""
    aggregated: set[str] = set()
    candidates: list[Path] = []
    domains_dir = REPO_ROOT / "backend" / "api" / "domains"
    if domains_dir.exists():
        candidates.extend(domains_dir.glob("*.py"))
    candidates.append(REPO_ROOT / "backend" / "api" / "router.py")
    for p in candidates:
        if not p.exists() or p.name == "__init__.py":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in ROUTER_IMPORT_RE.finditer(text):
            mod = m.group(1)
            # Normalize "integrations.openai_adapter" -> "integrations/openai_adapter"
            mod_norm = mod.replace(".", "/", 1) if "." in mod else mod
            aggregated.add(mod_norm)
            aggregated.add(mod)  # also keep dotted form
    return aggregated


class TestRepoHygieneP2(unittest.TestCase):
    """P2.1: every router defined in backend/api/ must be aggregated."""

    def test_every_api_router_is_aggregated(self):
        """Every `*_router = APIRouter(...)` in backend/api/*.py must be imported by a domain or router.py."""
        defined = _routers_defined_in_api_flat()
        aggregated = _aggregated_module_names()
        unaggregated = sorted(set(defined) - aggregated)
        self.assertEqual(
            unaggregated,
            [],
            f"Router modules not aggregated by any domain or router.py: {unaggregated}",
        )


if __name__ == "__main__":
    unittest.main()
