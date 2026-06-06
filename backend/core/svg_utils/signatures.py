"""Glyph signature state and context-sensitive character resolution."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Set

from backend.core.logging_utils import get_logger
from backend.core.svg_utils.glyph_types import LARGE_OPERATORS as _LARGE_OPERATORS_BASE

logger = get_logger(__name__)

LARGE_OPERATORS: Set[str] = set(_LARGE_OPERATORS_BASE)
LARGE_OP_SIGNATURES: Set[str] = set()

AMBIGUOUS_SIGNATURES: Dict[str, Dict[str, str]] = {
    # D签名问题：在运算符上下文中可能是减号
    # "c36b3f1d": {"default": "D", "operator_context": "-"},
}

OPERAND_CHARS = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
OPERAND_CHARS.update({"\\pi", "\\alpha", "\\beta", "\\gamma", "\\theta", "\\phi"})

OPERATOR_CHARS = set("+-*/=<>")
OPERATOR_CHARS.update({"\\times", "\\div", "\\cdot", "\\pm", "\\mp", "\\leq", "\\geq", "\\neq"})

GLYPH_SIGNATURES: Dict[str, str] = {
    "b9716cb9": "2",
    "5f32a7e2": "4",
    "3b2fdd74": "1",
    "b673824f": "0",
    "0896fac2": "3",
    "5a9f14b0": "5",
    "71e8b9a1": "6",
    "96aeade1": "1",
    "cf58f988": "x",
    "6cb4ef65": "y",
    "2aa7df06": "o",
    "9fe3b8c9": "0",
    "f9e514d2": "c",
    "56274f04": "a",
    "34f7c565": ",",
    "803c545f": "h",
    "d3af06b5": "i",
    "ee57931a": "j",
    "099c8924": "b",
    "2273560c": "l",
    "b65ef479": "m",
    "e1096052": "m",
    "396a708d": "p",
    "9b58691c": "q",
    "7dd54be2": "r",
    "cd4e58fc": "s",
    "97e16f2e": "t",
    "cc0ab61a": "u",
    "1d0fc683": "v",
    "2fd59755": "w",
    "b1fb51b4": "z",
    "ee8570c5": "P",
    "d7198a8e": "O",
    "fd61fc79": "A",
    "c5232a6d": "B",
    "db65bd2f": "C",
    "c36b3f1d": "D",
    "da16791e": "E",
    "8637303d": "F",
    "7c7bb518": "G",
    "9315853a": "H",
    "10fb4c81": "I",
    "d45c14ff": "J",
    "e407c344": "K",
    "7cbdeebe": "-",
    "e113c1a7": "+",
    "a1040187": "=",
    "aecc1ab6": "<",
    "3a890ca6": ">",
    "8c6104df": ":",
    "cadf428a": "\\sqrt",
    "dfeccf59": "\\perp",
    "b6caebbe": "\\angle",
}

SIGNATURES_FILE = os.path.join(os.path.dirname(__file__), "glyph_signatures.json")
_signatures_loaded = False


def update_large_op_signatures() -> None:
    LARGE_OP_SIGNATURES.clear()
    for sig, char in GLYPH_SIGNATURES.items():
        if char in LARGE_OPERATORS:
            LARGE_OP_SIGNATURES.add(sig)


def load_signatures() -> Dict[str, str]:
    global _signatures_loaded
    if _signatures_loaded:
        return GLYPH_SIGNATURES

    if os.path.exists(SIGNATURES_FILE):
        try:
            with open(SIGNATURES_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, json.JSONDecodeError, TypeError):
            logger.warning("svg_signatures_load_failed", extra={"path": SIGNATURES_FILE}, exc_info=True)
        else:
            for key, value in saved.items() if isinstance(saved, dict) else []:
                if not str(key).startswith("_comment"):
                    GLYPH_SIGNATURES[str(key)] = str(value)

    update_large_op_signatures()
    _signatures_loaded = True
    return GLYPH_SIGNATURES


def save_signatures() -> None:
    try:
        with open(SIGNATURES_FILE, "w", encoding="utf-8") as f:
            json.dump(GLYPH_SIGNATURES, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning("failed to save glyph signatures", extra={"error": str(exc)}, exc_info=True)


def add_signature(signature: str, latex_char: str) -> None:
    GLYPH_SIGNATURES[signature] = latex_char
    save_signatures()


def add_signatures_batch(mappings: Dict[str, str]) -> None:
    GLYPH_SIGNATURES.update(mappings)
    save_signatures()


def is_operand_char(char: Optional[str]) -> bool:
    if not char:
        return False
    if char.startswith("[?") and char.endswith("]"):
        return False
    return char in OPERAND_CHARS or char.isalnum()


def resolve_ambiguous_char(glyph: Any, prev_glyph: Optional[Any] = None, next_glyph: Optional[Any] = None) -> str:
    sig = glyph.signature
    if sig not in AMBIGUOUS_SIGNATURES:
        return glyph.char

    ambig = AMBIGUOUS_SIGNATURES[sig]
    default_char = ambig.get("default", glyph.char)
    prev_is_operand = prev_glyph and is_operand_char(prev_glyph.char)
    next_is_operand = next_glyph and is_operand_char(next_glyph.char)

    if prev_is_operand and next_is_operand:
        return ambig.get("operator_context", default_char)

    if prev_glyph and next_glyph:
        gap_to_prev = glyph.x - (prev_glyph.x + prev_glyph.width)
        gap_to_next = next_glyph.x - (glyph.x + glyph.width)
        if abs(gap_to_prev - gap_to_next) < 5 and glyph.width < 10:
            return ambig.get("operator_context", default_char)

    return default_char
