"""Blueprint schema for the author-agent study materials pipeline (design doc §4-5).

The blueprint is the author agent's book plan: narrative arc, terminology/notation
table, section specs, figure plan, and *source-grounded* misconceptions. The LLM may
only list misconceptions that carry a source URL mined during research; validation
enforces it structurally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

FIGURE_KINDS = frozenset({"auto", "tikz", "mermaid", "manim", "image"})
DIFFICULTY_LEVELS = frozenset({"基础", "应用", "迁移"})

SECTION_FIELDS = ("id", "title", "purpose", "key_points", "target_chars", "difficulty", "misconceptions", "frontier")
FIGURE_FIELDS = ("n", "sec_id", "intent", "kind", "caption")


class BlueprintError(ValueError):
    """Raised when a blueprint dict fails schema or grounding validation."""


def _fail(msg: str) -> None:
    raise BlueprintError(msg)


def _require_fields(raw: Dict[str, Any], fields: tuple, where: str) -> None:
    for name in fields:
        if name not in raw:
            _fail(f"{where}: missing required field {name!r}")


def _require_str(raw: Dict[str, Any], name: str, where: str, *, allow_empty: bool = False) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        _fail(f"{where}: field {name!r} must be a non-empty string")
    return value


def _parse_misconceptions(raw: Any, where: str) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        _fail(f"{where}: 'misconceptions' must be a list")
    items: List[Dict[str, str]] = []
    for i, mc in enumerate(raw):
        mc_where = f"{where}.misconceptions[{i}]"
        if not isinstance(mc, dict):
            _fail(f"{mc_where}: must be an object")
        _require_fields(mc, ("claim", "source_url"), mc_where)
        claim = _require_str(mc, "claim", mc_where)
        source_url = _require_str(mc, "source_url", mc_where)
        if not source_url.startswith(("http://", "https://")):
            _fail(f"{mc_where}: 'source_url' must start with http:// or https:// (got {source_url!r})")
        items.append({"claim": claim, "source_url": source_url})
    return items


@dataclass
class SectionSpec:
    id: str
    title: str
    purpose: str
    key_points: List[str]
    target_chars: int
    difficulty: str
    misconceptions: List[Dict[str, str]] = field(default_factory=list)
    frontier: bool = False

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], where: str) -> "SectionSpec":
        if not isinstance(raw, dict):
            _fail(f"{where}: section must be an object")
        _require_fields(raw, SECTION_FIELDS, where)
        key_points = raw["key_points"]
        if not isinstance(key_points, list) or not all(isinstance(p, str) for p in key_points):
            _fail(f"{where}: 'key_points' must be a list of strings")
        target_chars = raw["target_chars"]
        if not isinstance(target_chars, int) or isinstance(target_chars, bool) or target_chars <= 0:
            _fail(f"{where}: 'target_chars' must be a positive integer")
        frontier = raw["frontier"]
        if not isinstance(frontier, bool):
            _fail(f"{where}: 'frontier' must be a boolean")
        difficulty = _require_str(raw, "difficulty", where)
        if difficulty not in DIFFICULTY_LEVELS:
            _fail(f"{where}: unknown difficulty {difficulty!r} (expected one of {sorted(DIFFICULTY_LEVELS)})")
        return cls(
            id=_require_str(raw, "id", where),
            title=_require_str(raw, "title", where),
            purpose=_require_str(raw, "purpose", where),
            key_points=list(key_points),
            target_chars=target_chars,
            difficulty=difficulty,
            misconceptions=_parse_misconceptions(raw["misconceptions"], where),
            frontier=frontier,
        )


@dataclass
class FigureSpec:
    n: int
    sec_id: str
    intent: str
    kind: str
    caption: str

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], where: str) -> "FigureSpec":
        if not isinstance(raw, dict):
            _fail(f"{where}: figure must be an object")
        _require_fields(raw, FIGURE_FIELDS, where)
        n = raw["n"]
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            _fail(f"{where}: 'n' must be a positive integer")
        kind = _require_str(raw, "kind", where)
        if kind not in FIGURE_KINDS:
            _fail(f"{where}: unknown figure kind {kind!r} (expected one of {sorted(FIGURE_KINDS)})")
        return cls(
            n=n,
            sec_id=_require_str(raw, "sec_id", where),
            intent=_require_str(raw, "intent", where),
            kind=kind,
            caption=_require_str(raw, "caption", where, allow_empty=True),
        )


@dataclass
class Blueprint:
    narrative: str
    terminology: List[Dict[str, str]]
    sections: List[SectionSpec]
    figures: List[FigureSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Blueprint":
        if not isinstance(raw, dict):
            _fail("blueprint must be an object")
        _require_fields(raw, ("narrative", "terminology", "sections"), "blueprint")

        narrative = raw["narrative"]
        if not isinstance(narrative, str):
            _fail("blueprint: 'narrative' must be a string")

        terminology_raw = raw["terminology"]
        if not isinstance(terminology_raw, list):
            _fail("blueprint: 'terminology' must be a list")
        terminology: List[Dict[str, str]] = []
        for i, term in enumerate(terminology_raw):
            where = f"blueprint.terminology[{i}]"
            if not isinstance(term, dict):
                _fail(f"{where}: must be an object")
            _require_fields(term, ("symbol", "meaning"), where)
            terminology.append({
                "symbol": _require_str(term, "symbol", where),
                "meaning": _require_str(term, "meaning", where),
            })

        sections_raw = raw["sections"]
        if not isinstance(sections_raw, list) or not sections_raw:
            _fail("blueprint: 'sections' must be a non-empty list")
        sections = [SectionSpec.from_dict(s, f"blueprint.sections[{i}]") for i, s in enumerate(sections_raw)]
        seen_ids: set = set()
        for s in sections:
            if s.id in seen_ids:
                _fail(f"blueprint: duplicate section id {s.id!r}")
            seen_ids.add(s.id)

        figures_raw = raw.get("figures", [])
        if not isinstance(figures_raw, list):
            _fail("blueprint: 'figures' must be a list")
        figures = [FigureSpec.from_dict(f, f"blueprint.figures[{i}]") for i, f in enumerate(figures_raw)]
        seen_ns: set = set()
        for f in figures:
            if f.n in seen_ns:
                _fail(f"blueprint: duplicate figure n={f.n}")
            seen_ns.add(f.n)
            if f.sec_id not in seen_ids:
                _fail(f"blueprint: figure n={f.n} references unknown section {f.sec_id!r}")

        return cls(narrative=narrative, terminology=terminology, sections=sections, figures=figures)
