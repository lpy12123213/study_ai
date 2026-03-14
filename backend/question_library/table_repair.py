from __future__ import annotations

import re
from typing import List


_VALUE_HEADERS = {"ξ", "\\xi", "xi"}
_PROB_HEADERS = {"p", "P"}
_ELLIPSIS_TOKENS = {"...", "…", "\\cdots", "\\ldots"}


def _strip_math_wrappers(token: str) -> str:
    value = str(token or "").strip()
    while True:
        next_value = value
        if next_value.startswith("\\(") and next_value.endswith("\\)") and len(next_value) >= 4:
            next_value = next_value[2:-2].strip()
        elif next_value.startswith("\\[") and next_value.endswith("\\]") and len(next_value) >= 4:
            next_value = next_value[2:-2].strip()
        elif next_value.startswith("$$") and next_value.endswith("$$") and len(next_value) >= 4:
            next_value = next_value[2:-2].strip()
        elif next_value.startswith("$") and next_value.endswith("$") and len(next_value) >= 2:
            next_value = next_value[1:-1].strip()
        if next_value == value:
            return value
        value = next_value


def _normalize_token(token: str) -> str:
    value = _strip_math_wrappers(token)
    value = re.sub(r"\s+", " ", value).strip()
    if value in {"…", "..."}:
        return "\\cdots"
    return value


def _looks_like_value_token(token: str) -> bool:
    value = _normalize_token(token)
    if not value:
        return False
    if value in _ELLIPSIS_TOKENS:
        return True
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return True
    if re.fullmatch(r"[a-zA-Z]", value):
        return True
    if re.fullmatch(r"[a-zA-Z]_\d+", value):
        return True
    return value in {"n", "m", "k", "\\xi", "ξ"}


def _looks_like_prob_token(token: str) -> bool:
    value = _normalize_token(token)
    if not value:
        return False
    if value in _ELLIPSIS_TOKENS:
        return True
    if re.fullmatch(r"[pqPQ]_\d+", value):
        return True
    if re.fullmatch(r"[pqPQ]_[a-zA-Z]", value):
        return True
    if re.fullmatch(r"[pqPQ]_[a-zA-Z0-9]+", value):
        return True
    return value in {"p_n", "q_n", "p", "P"}


def _looks_like_generic_header_token(token: str) -> bool:
    value = _normalize_token(token)
    if not value:
        return False
    if any(ch.isdigit() for ch in value):
        return False
    return len(value) <= 16


def _looks_like_generic_value_token(token: str) -> bool:
    value = _normalize_token(token)
    if not value:
        return False
    if value in _ELLIPSIS_TOKENS:
        return True
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:次|个|人|项|分|天|%|cm|m|kg)?", value):
        return True
    if re.fullmatch(r"-?\d+/\d+", value):
        return True
    return value.startswith("\\frac{")


def _to_row_tokens(paragraph: str) -> List[str]:
    return [str(line or "").strip() for line in re.split(r"\r\n|\r|\n", paragraph or "") if str(line or "").strip()]


def _is_distribution_pair(first_row: List[str], second_row: List[str]) -> bool:
    if len(first_row) < 4 or len(second_row) < 4:
        return False

    header_a = _normalize_token(first_row[0]).lower()
    header_b = _normalize_token(second_row[0])
    if header_a not in {item.lower() for item in _VALUE_HEADERS}:
        return False
    if header_b not in _PROB_HEADERS:
        return False

    if abs(len(first_row) - len(second_row)) > 1:
        return False

    return all(_looks_like_value_token(token) for token in first_row[1:]) and all(
        _looks_like_prob_token(token) for token in second_row[1:]
    )


def _build_array(first_row: List[str], second_row: List[str]) -> str:
    width = max(len(first_row), len(second_row))
    row_a = [_normalize_token(token) for token in first_row] + [""] * (width - len(first_row))
    row_b = [_normalize_token(token) for token in second_row] + [""] * (width - len(second_row))
    return _build_array_rows([row_a, row_b], normalized=True)


def _build_array_rows(rows: List[List[str]], *, normalized: bool = False) -> str:
    width = max(len(row) for row in rows)
    processed_rows = []
    for row in rows:
        values = row if normalized else [_normalize_token(token) for token in row]
        processed_rows.append(values + [""] * (width - len(values)))
    align = "c" * max(2, width)
    body = " \\\\ ".join([" & ".join(row) for row in processed_rows])
    return f"$$\\begin{{array}}{{{align}}}{body}\\end{{array}}$$"


def _match_generic_matrix(
    paragraphs: List[str], index: int
) -> tuple[List[str], List[List[str]], int] | None:
    lines = _to_row_tokens(paragraphs[index])
    if len(lines) < 3:
        return None

    for offset in range(0, len(lines) - 2):
        header_row = lines[offset:]
        if len(header_row) < 3 or not all(_looks_like_generic_header_token(token) for token in header_row):
            continue

        matrix_rows: List[List[str]] = [header_row]
        next_index = index + 1
        while next_index < len(paragraphs):
            data_row = _to_row_tokens(paragraphs[next_index])
            if (
                len(data_row) == len(header_row)
                and _looks_like_generic_header_token(data_row[0])
                and all(_looks_like_generic_value_token(token) for token in data_row[1:])
            ):
                matrix_rows.append(data_row)
                next_index += 1
                continue
            break

        if len(matrix_rows) >= 3:
            return lines[:offset], matrix_rows, next_index

    return None


def repair_obvious_broken_tables(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return raw

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", raw) if part.strip()]
    if len(paragraphs) < 2:
        return raw

    changed = False
    rebuilt: List[str] = []
    index = 0
    while index < len(paragraphs):
        if index + 1 < len(paragraphs):
            first_row = _to_row_tokens(paragraphs[index])
            second_row = _to_row_tokens(paragraphs[index + 1])
            if _is_distribution_pair(first_row, second_row):
                rebuilt.append(_build_array(first_row, second_row))
                changed = True
                index += 2
                continue

        generic_matrix = _match_generic_matrix(paragraphs, index)
        if generic_matrix is not None:
            prefix_lines, matrix_rows, next_index = generic_matrix
            if prefix_lines:
                rebuilt.append("\n".join(prefix_lines))
            rebuilt.append(_build_array_rows(matrix_rows))
            changed = True
            index = next_index
            continue

        rebuilt.append(paragraphs[index])
        index += 1

    if not changed:
        return raw
    return "\n\n".join(rebuilt).strip()
