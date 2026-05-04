from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import List, Optional

from backend.agent.memory.semantic_store import SemanticDoc, SemanticStore
from backend.agent.types import UserProfile


class MemoryStore:
    _lock = asyncio.Lock()

    def __init__(self, *, storage_path: Optional[str] = None) -> None:
        project_root = Path(__file__).resolve().parents[3]
        default_path = project_root / "data" / "memory" / "user_profiles.json"
        self._path = Path(storage_path) if storage_path else default_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def get_user_profile(self, *, user_id: str) -> UserProfile:
        uid = str(user_id or "anonymous")
        async with self._lock:
            data = self._load_all()
            raw = data.get(uid)
            if isinstance(raw, dict):
                return UserProfile.from_dict(raw)
            profile = UserProfile(user_id=uid)
            data[uid] = profile.to_dict()
            self._save_all(data)
            return profile

    async def update_user_profile(self, *, user_id: str, patch: dict) -> UserProfile:
        uid = str(user_id or "anonymous")
        patch = patch if isinstance(patch, dict) else {}
        async with self._lock:
            data = self._load_all()
            current = UserProfile.from_dict(data.get(uid) or {"user_id": uid})

            prefs = dict(current.preferences or {})
            for k, v in patch.items():
                prefs[str(k)] = v
            current.preferences = prefs

            data[uid] = current.to_dict()
            self._save_all(data)
            return current

    async def record_session(
        self, *, user_id: str, topic: str, passed: bool, issues: Optional[List[str]] = None
    ) -> None:
        uid = str(user_id or "anonymous")
        topic = str(topic or "").strip()
        issues = issues or []

        async with self._lock:
            data = self._load_all()
            profile = UserProfile.from_dict(data.get(uid) or {"user_id": uid})

            entry = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "topic": topic,
                "passed": bool(passed),
                "issues": [str(x) for x in issues[:10] if str(x).strip()],
            }
            hist = list(profile.history or [])
            hist.append(entry)
            if len(hist) > 200:
                hist = hist[-200:]
            profile.history = hist

            delta = 0.02 if passed else -0.02
            next_score = float(profile.ability_score or 0.5) + delta
            next_score = max(0.05, min(0.95, next_score))
            profile.ability_score = next_score
            if next_score < 0.35:
                profile.ability_level = "beginner"
            elif next_score < 0.7:
                profile.ability_level = "intermediate"
            else:
                profile.ability_level = "advanced"

            data[uid] = profile.to_dict()
            self._save_all(data)

    def _load_all(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
            obj = json.loads(raw) if raw.strip() else {}
            return obj if isinstance(obj, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError):
            return {}

    def _save_all(self, data: dict) -> None:
        try:
            self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            return None


__all__ = ["MemoryStore", "SemanticDoc", "SemanticStore"]
