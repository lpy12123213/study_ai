"""Utilities for extending glyph signatures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


def load_signatures(path: Path) -> Dict[str, str]:
    """Load signatures from a JSON file."""
    if not path.exists():
        return {}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_signatures(signatures: Dict[str, str], path: Path) -> None:
    """Save signatures to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(signatures, f, ensure_ascii=False, indent=2)


def add_signature(
    glyph_id: str,
    latex: str,
    path: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Add a new glyph signature.
    
    Args:
        glyph_id: The glyph identifier from the SVG
        latex: The LaTeX equivalent
        path: Optional path to the signatures file
    
    Returns:
        Updated signatures dict
    """
    if path is None:
        path = Path(__file__).parent / "glyph_signatures.json"
    
    signatures = load_signatures(path)
    signatures[glyph_id] = latex
    save_signatures(signatures, path)
    return signatures


def add_signatures_batch(
    mappings: Dict[str, str],
    path: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Add multiple glyph signatures.
    
    Args:
        mappings: Dict of glyph_id -> latex
        path: Optional path to the signatures file
    
    Returns:
        Updated signatures dict
    """
    if path is None:
        path = Path(__file__).parent / "glyph_signatures.json"
    
    signatures = load_signatures(path)
    signatures.update(mappings)
    save_signatures(signatures, path)
    return signatures


def get_missing_glyphs(svg_content: str, signatures: Dict[str, str]) -> List[str]:
    """
    Find glyph IDs in SVG content that don't have signatures.
    
    Args:
        svg_content: SVG string
        signatures: Current signatures dict
    
    Returns:
        List of missing glyph IDs
    """
    import re
    
    # Find all glyph references
    use_pattern = r'<use[^>]*xlink:href="#([^"]+)"'
    glyph_ids = set(re.findall(use_pattern, svg_content))
    
    # Filter to those without signatures
    missing = [gid for gid in glyph_ids if gid not in signatures]
    return sorted(missing)
