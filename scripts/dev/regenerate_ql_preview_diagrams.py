from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.question_library.diagram_utils import render_tikz_to_url  # noqa: E402
from backend.question_library.preview_store import load_preview, load_session, save_preview, save_session  # noqa: E402


def _as_str(v: Any) -> str:
    return str(v or "").strip()


def _preview_path_from_id(preview_id: str) -> Path:
    pid = _as_str(preview_id)
    if not pid:
        raise ValueError("missing_preview_id")
    return (ROOT / ".local" / "question_library" / "previews" / f"{pid}.json").resolve()


def _latest_pending_preview_path() -> Optional[Path]:
    base = (ROOT / ".local" / "question_library" / "previews").resolve()
    if not base.exists():
        return None

    best: Optional[Tuple[float, Path]] = None
    for path in base.glob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if _as_str(obj.get("status")).lower() != "pending_review":
            continue
        try:
            score = float(obj.get("updated_at_s") or obj.get("created_at_s") or 0.0)
        except Exception:
            try:
                score = float(path.stat().st_mtime)
            except Exception:
                score = 0.0
        if best is None or score > best[0]:
            best = (score, path)
    return best[1] if best else None


def _contains_any(text: str, needles: List[str]) -> bool:
    t = str(text or "")
    return any(n in t for n in needles)


def _infer_b_symbol(stem: str) -> str:
    s = str(stem or "")
    if "向下" in s:
        return r"\otimes"  # into page
    if "向上" in s:
        return r"\odot"  # out of page
    return r"\odot"


def _infer_resistor_label(stem: str) -> str:
    s = str(stem or "")
    if "电阻为 \\( r" in s or "电阻为 r" in s or "电阻为\\( r" in s:
        return "r"
    if _contains_any(s, ["电阻 \\(R", "电阻 \\( R", "R=", " R ="]):
        return "R"
    return ""


def _build_dual_rail_tikz(
    *,
    stem: str,
    show_v0: bool,
    show_force: bool,
    show_drag: bool,
    include_capacitor: bool,
    include_inductor: bool,
    resistor_label: str,
) -> str:
    b_symbol = _infer_b_symbol(stem)

    tikz_lines: List[str] = [
        r"\begin{tikzpicture}[x=1cm,y=1cm,>=Latex, line cap=round, line join=round]",
        r"  % rails",
        r"  \draw[very thick] (0,0) -- (6,0);",
        r"  \draw[very thick] (0,2) -- (6,2);",
        r"  % rod",
        r"  \draw[ultra thick] (2.8,0) -- (2.8,2);",
    ]

    if resistor_label:
        tikz_lines.append(rf"  \node[anchor=west] at (2.85,1.0) {{$ {resistor_label} $}};")

    tikz_lines.extend(
        [
            r"  % spacing",
            r"  \draw[<->] (6.3,0) -- (6.3,2) node[midway,right] {$L$};",
            r"  % magnetic field (out/in of page)",
            r"  \foreach \x in {0.6,1.4,2.2,3.0,3.8,4.6,5.4} {",
            rf"    \node at (\x,1) {{$ {b_symbol} $}};",
            r"  }",
            r"  \node[anchor=west] at (0.1,2.45) {$\vec{B}$};",
            rf"  \node[anchor=west] at (0.7,2.45) {{$ {b_symbol} $}};",
        ]
    )

    # Circuit element(s) at left side.
    if include_capacitor and include_inductor:
        tikz_lines.extend(
            [
                r"  % series elements between rails (L_i then C) drawn on the left bridge",
                r"  \draw[very thick] (0,2) -- (-1.6,2);",
                r"  \draw[very thick] (0,0) -- (-1.6,0);",
                r"  \draw[very thick] (-1.6,2) -- (-1.6,1.70);",
                r"  \draw[very thick, decorate, decoration={coil,aspect=0.45,segment length=2.3mm,amplitude=2.0mm}] (-1.6,1.70) -- (-1.6,1.20);",
                r"  \node[anchor=east] at (-1.75,1.45) {$L_i$};",
                r"  \draw[very thick] (-1.6,1.20) -- (-1.6,0.92);",
                r"  % capacitor plates (gap between 0.92 and 0.72)",
                r"  \draw[very thick] (-1.85,0.92) -- (-1.35,0.92);",
                r"  \draw[very thick] (-1.85,0.72) -- (-1.35,0.72);",
                r"  \node[anchor=east] at (-1.75,0.82) {$C$};",
                r"  \draw[very thick] (-1.6,0.72) -- (-1.6,0);",
            ]
        )
    elif include_capacitor:
        tikz_lines.extend(
            [
                r"  % capacitor between rails",
                r"  \draw[very thick] (0,2) -- (-1.2,2);",
                r"  \draw[very thick] (0,0) -- (-1.2,0);",
                r"  \draw[very thick] (-1.2,2) -- (-1.2,1.15);",
                r"  \draw[very thick] (-1.45,1.15) -- (-0.95,1.15);",
                r"  \draw[very thick] (-1.45,0.85) -- (-0.95,0.85);",
                r"  \node[anchor=east] at (-1.35,1.0) {$C$};",
                r"  \draw[very thick] (-1.2,0.85) -- (-1.2,0);",
            ]
        )

    # Kinematics/forces annotations.
    if show_v0:
        tikz_lines.append(r"  \draw[->, thick] (2.8,2.4) -- (4.2,2.4) node[midway,above] {$v_0$};")
    else:
        tikz_lines.append(r"  \draw[->, thick] (2.8,2.4) -- (4.0,2.4) node[midway,above] {$v(t)$};")

    if show_force:
        tikz_lines.append(r"  \draw[->, thick] (2.8,1.6) -- (4.2,1.6) node[midway,above] {$F$};")
    if show_drag:
        tikz_lines.append(r"  \draw[->, thick] (2.8,0.4) -- (1.2,0.4) node[midway,below] {$f=kv^2$};")

    tikz_lines.append(r"\end{tikzpicture}")
    return "\n".join(tikz_lines).strip() + "\n"


def _infer_features_from_stem(stem: str) -> Dict[str, Any]:
    s = str(stem or "")
    include_capacitor = _contains_any(s, ["电容", r"\( C", r"\(C", " C "])
    include_inductor = _contains_any(s, ["电感", "L_i", r"\( L_i", r"\(L_i"])
    show_v0 = _contains_any(s, ["v_0", "初速度"])
    show_force = _contains_any(s, ["推进力", " F ", "F ="])
    show_drag = _contains_any(s, ["空气阻力", "kv^", "kv^{2}", "v^{2}"])
    resistor_label = _infer_resistor_label(s)
    return {
        "show_v0": show_v0,
        "show_force": show_force,
        "show_drag": show_drag,
        "include_capacitor": include_capacitor,
        "include_inductor": include_inductor,
        "resistor_label": resistor_label,
    }


async def _regen_one(*, draft: Dict[str, Any], user_id: str, dry_run: bool) -> Tuple[bool, str]:
    stem = _as_str(draft.get("stem"))
    if not stem:
        return False, "empty_stem"

    features = _infer_features_from_stem(stem)
    tikz = _build_dual_rail_tikz(stem=stem, **features)

    qid = _as_str(draft.get("question_id"))
    if dry_run:
        return True, f"dry_run:{qid}"

    existing_diagrams = draft.get("diagrams")
    prev = existing_diagrams[0] if isinstance(existing_diagrams, list) and existing_diagrams and isinstance(existing_diagrams[0], dict) else {}
    alt = _as_str(prev.get("alt")) or "diagram"
    caption = _as_str(prev.get("caption"))

    published = await render_tikz_to_url(tikz=tikz, user_id=user_id, alt=alt, preamble="", timeout_s=240.0)
    if not isinstance(published, dict) or not bool(published.get("success")):
        return False, f"render_failed:{qid}:{_as_str((published or {}).get('error'))}"

    diagram = {
        "kind": "tikz",
        "url": _as_str(published.get("url")),
        "filename": _as_str(published.get("filename")),
        "media_id": _as_str(published.get("media_id") or published.get("sha256")),
        "alt": alt,
        "caption": caption,
        "markdown": _as_str(published.get("markdown")),
    }
    draft["diagrams"] = [diagram]
    return True, _as_str(published.get("url"))


async def _main_async(args: argparse.Namespace) -> int:
    preview_path = _preview_path_from_id(args.preview_id) if args.preview_id else _latest_pending_preview_path()
    if preview_path is None or not preview_path.exists():
        raise SystemExit("preview_not_found")

    preview_id = preview_path.stem
    preview = load_preview(preview_id)
    if not isinstance(preview, dict):
        raise SystemExit("preview_load_failed")

    user_id = _as_str(preview.get("user_id")) or "anonymous"
    drafts = preview.get("draft_questions")
    if not isinstance(drafts, list) or not drafts:
        raise SystemExit("no_draft_questions")

    limit = max(1, int(args.limit or 3))
    targets = [d for d in drafts if isinstance(d, dict)][-limit:]

    ok = 0
    for d in targets:
        success, msg = await _regen_one(draft=d, user_id=user_id, dry_run=bool(args.dry_run))
        qid = _as_str(d.get("question_id"))
        status = "OK" if success else "FAIL"
        print(f"{status} {qid} {msg}")
        ok += 1 if success else 0

    if args.dry_run:
        return 0 if ok == len(targets) else 2

    preview["draft_questions"] = drafts
    save_preview(preview)

    session_id = _as_str(preview.get("session_id"))
    if session_id:
        session = load_session(session_id)
        if isinstance(session, dict) and isinstance(session.get("draft_questions"), list):
            session_drafts = session.get("draft_questions")
            by_id = {str(x.get("question_id") or "").strip(): x for x in drafts if isinstance(x, dict)}
            changed = 0
            for idx, item in enumerate(session_drafts):
                if not isinstance(item, dict):
                    continue
                qid = _as_str(item.get("question_id"))
                if qid and qid in by_id:
                    session_drafts[idx] = by_id[qid]
                    changed += 1
            session["draft_questions"] = session_drafts
            save_session(session)
            print(f"session_updated {session_id} changed={changed}")

    print(f"preview_updated {preview_id} regenerated={ok}/{len(targets)}")
    return 0 if ok == len(targets) else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate diagrams for question-library preview drafts.")
    parser.add_argument("--preview-id", dest="preview_id", default="", help="Preview id, e.g. ql_preview_xxx")
    parser.add_argument("--limit", type=int, default=3, help="How many latest draft questions to regenerate")
    parser.add_argument("--dry-run", action="store_true", help="Do not render or persist; only print targets")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
