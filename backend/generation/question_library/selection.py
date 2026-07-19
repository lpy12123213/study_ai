from __future__ import annotations

import re
from typing import List

from backend.generation.question_library.intuition_practice import intuition_packet_signature


def select_final(candidates: List[dict], count: int) -> List[dict]:
    n = max(1, min(int(count or 1), 20))
    out: List[dict] = []
    seen: set[str] = set()
    combo_used: set[tuple[str, str, str]] = set()
    packet_signatures: set[str] = set()

    def _norm(text: str) -> str:
        t = re.sub(r"\s+", " ", str(text or "").strip())
        t = re.sub(r"\\\([\\s\\S]*?\\\)", " <m> ", t)
        t = re.sub(r"\\\[([\\s\\S]*?)\\\]", " <M> ", t)
        t = re.sub(r"\$\$([\\s\\S]*?)\$\$", " <M> ", t)
        t = re.sub(r"\$([^\n$]*?)\$", " <m> ", t)
        return t[:300]

    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        stem = str(c.get("stem") or "").strip()
        if not stem:
            continue
        key = _norm(stem)
        if key in seen:
            continue
        packet_signature = intuition_packet_signature(c.get("intuition_packet"))
        if packet_signature and packet_signature in packet_signatures:
            continue
        seen.add(key)
        if packet_signature:
            packet_signatures.add(packet_signature)

        combo = (
            str(c.get("skill") or "").strip(),
            str(c.get("reasoning") or "").strip(),
            str(c.get("surface") or "").strip(),
        )
        if all(combo) and combo in combo_used:
            continue
        if all(combo):
            combo_used.add(combo)

        out.append(dict(c))
        if len(out) >= n:
            break

    # If diversity constraint filtered too much, fill remaining with best-effort uniques.
    if len(out) < n:
        for c in candidates or []:
            if not isinstance(c, dict):
                continue
            stem = str(c.get("stem") or "").strip()
            if not stem:
                continue
            key = _norm(stem)
            if key in {_norm(str(x.get("stem") or "")) for x in out}:
                continue
            packet_signature = intuition_packet_signature(c.get("intuition_packet"))
            if packet_signature and packet_signature in {
                intuition_packet_signature(x.get("intuition_packet")) for x in out
            }:
                continue
            out.append(dict(c))
            if len(out) >= n:
                break

    return out
