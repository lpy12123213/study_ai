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
from typing import Dict, Iterable, List, Optional, Tuple


TAG_RE = re.compile(r"\b(TODO|FIXME|HACK)\b")


@dataclass(frozen=True)
class DebtItem:
    tag: str
    file: str
    line: int
    text: str
    module: str
    file_last_commit_utc: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_git(args: List[str], *, cwd: Path) -> str:
    try:
        out = subprocess.check_output(["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _git_ls_files(*, cwd: Path) -> List[str]:
    raw = _run_git(["ls-files"], cwd=cwd)
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

        if p not in last_commit_cache:
            last_commit_cache[p] = _git_last_commit_iso(cwd=root, path=p)
        last_commit = last_commit_cache.get(p, "")

        for idx, line in enumerate(raw.splitlines(), start=1):
            m = TAG_RE.search(line)
            if not m:
                continue
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


def _emit_md(items: List[DebtItem]) -> str:
    summary = _summarize(items)
    lines: List[str] = []
    lines.append("# Tech Debt Report (TODO/FIXME/HACK)")
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
    ap.add_argument("--format", choices=["md", "json", "csv"], default="md")
    ap.add_argument("--out", default="", help="Output file path (default: stdout)")
    ap.add_argument("--limit", type=int, default=0, help="Fail with exit code 2 if debt items exceed this number.")
    args = ap.parse_args()

    root = _repo_root()
    files = _git_ls_files(cwd=root)
    items = list(_iter_debt_items(cwd=root, files=files))

    if args.limit and len(items) > int(args.limit):
        # Still emit output for visibility.
        pass

    out_text = ""
    if args.format == "md":
        out_text = _emit_md(items)
        if args.out:
            Path(args.out).write_text(out_text, encoding="utf-8")
        else:
            print(out_text)
    elif args.format == "json":
        payload = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "summary": _summarize(items), "items": [asdict(i) for i in items]}
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


if __name__ == \"__main__\":
    raise SystemExit(main())
