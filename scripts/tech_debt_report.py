from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


TAG_RE = re.compile(r"\b(TODO|FIXME|HACK)\b")
ENV_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
PY_ENV_LITERAL_RE = re.compile(r"""(?:os\.getenv|_get_(?:str|int|float|bool))\(\s*["']([A-Z0-9_]+)["']""")
FRONTEND_ROUTE_RE = re.compile(r"\<Route\b")
BACKEND_INCLUDE_ROUTER_RE = re.compile(r"\.include_router\(")


@dataclass(frozen=True)
class DebtItem:
    tag: str
    file: str
    line: int
    text: str
    module: str
    file_last_commit_utc: str


@dataclass(frozen=True)
class LargeFile:
    file: str
    lines: int
    bytes: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_git(args: List[str], *, cwd: Path) -> str:
    try:
        out = subprocess.check_output(["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _git_ls_files(*, cwd: Path) -> List[str]:
    # Include untracked files (but respect .gitignore) so the report reflects the
    # current workspace state during refactors.
    raw = _run_git(["ls-files", "--cached", "--others", "--exclude-standard"], cwd=cwd)
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _git_last_commit_iso(*, cwd: Path, path: str) -> str:
    # ISO 8601 commit date for the file (best-effort).
    raw = _run_git(["log", "-1", "--format=%cI", "--", path], cwd=cwd).strip()
    if raw:
        return raw
    return ""


def _module_for_path(path: str) -> str:
    p = path.replace("\\", "/").lstrip("./")
    if not p:
        return ""
    parts = p.split("/")
    if len(parts) == 1:
        return parts[0]
    # Group by top 2 directories to keep it readable.
    return "/".join(parts[:2])


def _iter_debt_items(*, cwd: Path, files: Iterable[str]) -> Iterable[DebtItem]:
    root = cwd
    # Only scan likely text/code files.
    allowed_exts = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".md",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        ".css",
        ".html",
        ".bat",
        ".sh",
    }

    last_commit_cache: Dict[str, str] = {}

    for rel in files:
        p = rel.replace("\\", "/")
        if not p or p.endswith("/"):
            continue
        ext = Path(p).suffix.lower()
        if ext not in allowed_exts:
            continue
        if p.startswith(".local/") or p.startswith("frontend/node_modules/") or p.startswith("scripts/venv/"):
            continue

        abs_path = (root / p).resolve()
        if not abs_path.exists() or not abs_path.is_file():
            continue

        try:
            raw = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for idx, line in enumerate(raw.splitlines(), start=1):
            m = TAG_RE.search(line)
            if not m:
                continue
            if p not in last_commit_cache:
                # Only hit git once per file, and only if the file actually contains debt tags.
                last_commit_cache[p] = _git_last_commit_iso(cwd=root, path=p)
            last_commit = last_commit_cache.get(p, "")
            tag = m.group(1)
            text = line.strip()
            yield DebtItem(
                tag=tag,
                file=p,
                line=idx,
                text=text,
                module=_module_for_path(p),
                file_last_commit_utc=last_commit,
            )


def _read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _iter_env_keys_from_env_example(text: str) -> Iterable[str]:
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        left = line.split("=", 1)[0].strip()
        if not left:
            continue
        # Support "export KEY=..." style.
        if left.lower().startswith("export "):
            left = left[7:].strip()
        if ENV_KEY_RE.fullmatch(left):
            yield left


def _iter_env_keys_from_python(text: str) -> Iterable[str]:
    for m in PY_ENV_LITERAL_RE.finditer(text or ""):
        key = str(m.group(1) or "").strip()
        if ENV_KEY_RE.fullmatch(key):
            yield key


def _count_frontend_routes(*, repo_root: Path) -> int:
    app = repo_root / "frontend" / "src" / "App.tsx"
    if not app.exists():
        return 0
    text = _read_text_best_effort(app)
    return len(FRONTEND_ROUTE_RE.findall(text))


def _count_frontend_pages(*, files: Sequence[str]) -> int:
    n = 0
    for rel in files:
        p = rel.replace("\\", "/")
        if not p.startswith("frontend/src/pages/"):
            continue
        if Path(p).suffix.lower() != ".tsx":
            continue
        n += 1
    return n


def _count_backend_router_includes(*, repo_root: Path) -> int:
    router = repo_root / "backend" / "api" / "router.py"
    if not router.exists():
        return 0
    text = _read_text_best_effort(router)
    return len(BACKEND_INCLUDE_ROUTER_RE.findall(text))


def _find_task_runtime_impls(*, files: Sequence[str]) -> List[str]:
    hits: List[str] = []
    for rel in files:
        p = rel.replace("\\", "/")
        if not p.startswith("backend/"):
            continue
        if p.endswith("task_manager.py") or p.endswith("tasks_singleton.py") or p.endswith("/shared/tasks/runtime.py"):
            hits.append(p)
    return sorted(set(hits))


def _find_legacy_shims(*, files: Sequence[str]) -> List[str]:
    hits: List[str] = []
    for rel in files:
        p = rel.replace("\\", "/")
        name = Path(p).name.lower()
        if not p.startswith("backend/") and not p.startswith("frontend/"):
            continue
        if "legacy" in name or "shim" in name or "compat" in name:
            hits.append(p)
            continue
        # Common explicit shims.
        if p in {
            "backend/api/models.py",
            "backend/database/models.py",
            "backend/database/repositories/__init__.py",
            "backend/agent/tools/__init__.py",
        }:
            hits.append(p)
    return sorted(set(hits))


def _iter_large_files(*, repo_root: Path, files: Sequence[str]) -> Iterable[LargeFile]:
    allow_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".md"}
    for rel in files:
        p = rel.replace("\\", "/")
        if not p:
            continue
        if (
            p.startswith(".local/")
            or p.startswith("frontend/node_modules/")
            or p.startswith("venv/")
            or p.startswith("scripts/venv/")
        ):
            continue
        ext = Path(p).suffix.lower()
        if ext not in allow_exts:
            continue
        abs_path = (repo_root / p).resolve()
        if not abs_path.exists() or not abs_path.is_file():
            continue
        text = _read_text_best_effort(abs_path)
        try:
            size_b = abs_path.stat().st_size
        except Exception:
            size_b = 0
        yield LargeFile(file=p, lines=len(text.splitlines()), bytes=size_b)


def _top_large_files(*, repo_root: Path, files: Sequence[str], limit: int = 20) -> List[LargeFile]:
    items = list(_iter_large_files(repo_root=repo_root, files=files))
    items.sort(key=lambda it: (-it.lines, it.file))
    return items[: max(1, int(limit or 20))]


def _load_nextstep_tasks(*, repo_root: Path) -> List[dict]:
    p = repo_root / "nextstep.csv"
    if not p.exists():
        return []
    text = _read_text_best_effort(p)
    rows: List[dict] = []
    try:
        reader = csv.DictReader(text.splitlines())
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in (r or {}).items()})
    except Exception:
        return []
    return rows


def _summarize_nextstep(tasks: List[dict]) -> Dict[str, Any]:
    by_prio: Dict[str, int] = {}
    by_cat: Dict[str, int] = {}
    done = 0
    for t in tasks:
        pr = str(t.get("优先级") or "").strip() or "unknown"
        cat = str(t.get("分类") or "").strip() or "unknown"
        ok = str(t.get("是否完成") or "").strip()
        if ok in {"是", "true", "True", "1", "yes", "y"}:
            done += 1
        by_prio[pr] = by_prio.get(pr, 0) + 1
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {"total": len(tasks), "done": done, "by_priority": by_prio, "by_category": by_cat}


def _compute_baseline(*, repo_root: Path, files: Sequence[str]) -> Dict[str, Any]:
    env_example = _read_text_best_effort(repo_root / ".env.example")
    env_keys_example = sorted(set(_iter_env_keys_from_env_example(env_example)))

    env_keys_used: set[str] = set()
    for rel in files:
        p = rel.replace("\\", "/")
        if not p.startswith("backend/"):
            continue
        if Path(p).suffix.lower() != ".py":
            continue
        env_keys_used.update(_iter_env_keys_from_python(_read_text_best_effort((repo_root / p).resolve())))

    large_files = _top_large_files(repo_root=repo_root, files=files, limit=30)
    big_over_800 = [asdict(it) for it in large_files if int(it.lines or 0) >= 800]

    nextstep = _load_nextstep_tasks(repo_root=repo_root)
    nextstep_summary = _summarize_nextstep(nextstep)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_runtimes": _find_task_runtime_impls(files=files),
        "legacy_shims": _find_legacy_shims(files=files),
        "env_keys": {
            "env_example_count": len(env_keys_example),
            "env_example": env_keys_example,
            "python_used_count": len(env_keys_used),
            "python_used": sorted(env_keys_used),
        },
        "routes": {
            "backend_include_router_count": _count_backend_router_includes(repo_root=repo_root),
            "frontend_route_count": _count_frontend_routes(repo_root=repo_root),
            "frontend_pages_count": _count_frontend_pages(files=files),
        },
        "large_files_top": [asdict(it) for it in large_files],
        "large_files_over_800_loc": big_over_800,
        "nextstep": {
            "summary": nextstep_summary,
            "high_priority_incomplete": [
                {
                    "编号": t.get("编号"),
                    "分类": t.get("分类"),
                    "标题": t.get("标题"),
                }
                for t in nextstep
                if str(t.get("优先级") or "") == "高" and str(t.get("是否完成") or "") not in {"是", "true", "True", "1", "yes", "y"}
            ][:30],
        },
    }


def _parse_iso_dt(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _age_bucket(last_commit_iso: str) -> str:
    dt = _parse_iso_dt(last_commit_iso)
    if not dt:
        return "unknown"
    days = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
    if days <= 7:
        return "0-7d"
    if days <= 30:
        return "8-30d"
    if days <= 90:
        return "31-90d"
    if days <= 365:
        return "91-365d"
    return "365d+"


def _summarize(items: List[DebtItem]) -> Dict[str, Dict[str, int]]:
    by_tag: Dict[str, int] = {}
    by_module: Dict[str, int] = {}
    by_age: Dict[str, int] = {}
    for it in items:
        by_tag[it.tag] = by_tag.get(it.tag, 0) + 1
        by_module[it.module] = by_module.get(it.module, 0) + 1
        by_age[_age_bucket(it.file_last_commit_utc)] = by_age.get(_age_bucket(it.file_last_commit_utc), 0) + 1
    return {"by_tag": by_tag, "by_module": by_module, "by_age": by_age}


def _emit_baseline_md(baseline: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Baseline Snapshot")
    lines.append("")
    lines.append(f"- Generated at (UTC): {baseline.get('generated_at_utc')}")
    lines.append("")

    env_keys = baseline.get("env_keys") if isinstance(baseline.get("env_keys"), dict) else {}
    routes = baseline.get("routes") if isinstance(baseline.get("routes"), dict) else {}
    nextstep = baseline.get("nextstep") if isinstance(baseline.get("nextstep"), dict) else {}

    task_runtimes = baseline.get("task_runtimes") if isinstance(baseline.get("task_runtimes"), list) else []
    legacy_shims = baseline.get("legacy_shims") if isinstance(baseline.get("legacy_shims"), list) else []

    lines.append("## Task Runtime")
    lines.append(f"- Task runtime implementations found: {len(task_runtimes)}")
    for p in task_runtimes[:50]:
        lines.append(f"  - `{p}`")
    lines.append("")

    lines.append("## Legacy / Shim")
    lines.append(f"- Legacy/shim entrypoints found: {len(legacy_shims)}")
    for p in legacy_shims[:50]:
        lines.append(f"  - `{p}`")
    lines.append("")

    lines.append("## Configuration (Env Keys)")
    lines.append(f"- Keys in `.env.example`: {int(env_keys.get('env_example_count') or 0)}")
    lines.append(f"- Keys referenced in backend Python: {int(env_keys.get('python_used_count') or 0)}")
    lines.append("")

    lines.append("## Routes / Pages")
    lines.append(
        f"- Backend routers (`include_router`) in `backend/api/router.py`: {int(routes.get('backend_include_router_count') or 0)}"
    )
    lines.append(f"- Frontend pages under `frontend/src/pages`: {int(routes.get('frontend_pages_count') or 0)}")
    lines.append(f"- Frontend route nodes in `frontend/src/App.tsx`: {int(routes.get('frontend_route_count') or 0)}")
    lines.append("")

    big_files = baseline.get("large_files_over_800_loc") if isinstance(baseline.get("large_files_over_800_loc"), list) else []
    if big_files:
        lines.append("## Large Files (LOC >= 800)")
        for it in big_files[:30]:
            try:
                lines.append(f"- `{it.get('file')}` ({int(it.get('lines') or 0)} LOC)")
            except Exception:
                continue
        lines.append("")

    ns_summary = nextstep.get("summary") if isinstance(nextstep.get("summary"), dict) else {}
    if ns_summary:
        lines.append("## nextstep.csv Progress (Best-Effort)")
        lines.append(f"- Total items: {int(ns_summary.get('total') or 0)}")
        lines.append(f"- Done: {int(ns_summary.get('done') or 0)}")
        lines.append(f"- By priority: {ns_summary.get('by_priority')}")
        lines.append(f"- By category: {ns_summary.get('by_category')}")
        hi = nextstep.get("high_priority_incomplete") if isinstance(nextstep.get("high_priority_incomplete"), list) else []
        if hi:
            lines.append("- High priority incomplete (top 30):")
            for it in hi:
                lines.append(f"  - {it.get('编号')}. {it.get('分类')} - {it.get('标题')}")
        lines.append("")

    return "\n".join(lines)


def _emit_todo_md(items: List[DebtItem]) -> str:
    summary = _summarize(items)
    lines: List[str] = []
    lines.append("# TODO/FIXME/HACK Report")
    lines.append("")
    lines.append(f"- Total: {len(items)}")
    lines.append(f"- Tags: {summary['by_tag']}")
    lines.append(f"- Age buckets (by file last commit): {summary['by_age']}")
    lines.append("")
    lines.append("## Top Modules")
    for mod, n in sorted(summary["by_module"].items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
        lines.append(f"- {mod}: {n}")
    lines.append("")
    lines.append("## Items")
    for it in items[:500]:
        lines.append(f"- `{it.tag}` {it.file}:{it.line}  {it.text}")
    if len(items) > 500:
        lines.append(f"- (truncated; showing first 500 of {len(items)})")
    lines.append("")
    lines.append("## Annotation Convention (Recommended)")
    lines.append("- Use `TODO(owner=..., due=YYYY-MM-DD): ...` for new debt.")
    lines.append("- Prefer actionable TODOs; link an issue id if applicable.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a TODO/FIXME/HACK tech-debt report for the repo.")
    ap.add_argument(
        "--section",
        choices=["all", "baseline", "todo"],
        default="all",
        help="Which sections to include in markdown output (default: all).",
    )
    ap.add_argument("--format", choices=["md", "json", "csv"], default="md")
    ap.add_argument("--out", default="", help="Output file path (default: stdout)")
    ap.add_argument("--limit", type=int, default=0, help="Fail with exit code 2 if debt items exceed this number.")
    args = ap.parse_args()

    root = _repo_root()
    files = [p for p in _git_ls_files(cwd=root) if (root / p).resolve().exists()]
    baseline = _compute_baseline(repo_root=root, files=files)

    need_todo = args.format != "md" or args.section in {"all", "todo"}
    items: List[DebtItem] = list(_iter_debt_items(cwd=root, files=files)) if need_todo else []

    if args.limit and need_todo and len(items) > int(args.limit):
        # Still emit output for visibility.
        pass

    out_text = ""
    if args.format == "md":
        if args.section == "baseline":
            out_text = _emit_baseline_md(baseline)
        elif args.section == "todo":
            out_text = _emit_todo_md(items)
        else:
            out_text = "\n\n".join([_emit_baseline_md(baseline), _emit_todo_md(items)])
        if args.out:
            Path(args.out).write_text(out_text, encoding="utf-8")
        else:
            print(out_text)
    elif args.format == "json":
        payload = {
            "baseline": baseline,
            "todo": {"summary": _summarize(items), "items": [asdict(i) for i in items]},
        }
        out_text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(out_text, encoding="utf-8")
        else:
            print(out_text)
    else:
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["tag", "file", "line", "module", "file_last_commit_utc", "text"])
                for it in items:
                    w.writerow([it.tag, it.file, it.line, it.module, it.file_last_commit_utc, it.text])
        else:
            w = csv.writer(sys.stdout)
            w.writerow(["tag", "file", "line", "module", "file_last_commit_utc", "text"])
            for it in items:
                w.writerow([it.tag, it.file, it.line, it.module, it.file_last_commit_utc, it.text])

    if args.limit and len(items) > int(args.limit):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
