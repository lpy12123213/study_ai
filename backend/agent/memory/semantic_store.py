from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)

_WORD_RE = re.compile(r"[a-z0-9_]{2,}", flags=re.I)


def _cjk_bigrams(text: str) -> List[str]:
    chars: List[str] = []
    for ch in str(text or ""):
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            chars.append(ch)
    if len(chars) < 2:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def _tokenize(text: str) -> List[str]:
    raw = str(text or "").lower()
    words = _WORD_RE.findall(raw)
    return [*words, *_cjk_bigrams(raw)]


def _stable_hash_u64(text: str) -> int:
    # Keep hashing deterministic across processes (avoid Python's randomized hash()).
    h = hashlib.blake2b(str(text or "").encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, byteorder="little", signed=False)


def _embed_hashing(text: str, *, dim: int) -> List[float]:
    dim = int(dim or 0)
    if dim <= 8:
        dim = 256

    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vec

    for tok in tokens[:4000]:
        h = _stable_hash_u64(tok)
        idx = int(h % dim)
        sign = -1.0 if ((h >> 63) & 1) else 1.0
        vec[idx] += sign

    # L2 normalize.
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _safe_meta(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:480]
    # Chroma metadata must be scalar; stringify anything else.
    try:
        return str(value)[:480]
    except Exception:
        return ""


def _safe_collection_name(user_id: str) -> str:
    uid = str(user_id or "anonymous").strip() or "anonymous"
    uid = re.sub(r"[^a-zA-Z0-9_-]+", "_", uid)
    uid = uid.strip("_-") or "anonymous"
    return f"mem_{uid[:48]}"


@dataclass
class SemanticDoc:
    doc_id: str
    text: str
    metadata: Dict[str, Any]


class SemanticStore:
    """Local semantic memory using ChromaDB persistent storage.

    This store is best-effort:
    - If chromadb isn't installed, it falls back to a simple JSONL store.
    - Embeddings are deterministic hashed vectors (no external model required).
    """

    def __init__(self, *, persist_dir: Optional[str] = None, dim: int = 384) -> None:
        project_root = Path(__file__).resolve().parents[3]
        default_dir = project_root / ".local" / "chromadb"
        self._persist_dir = Path(persist_dir) if persist_dir else default_dir
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._dim = int(dim or 384)
        self._lock = asyncio.Lock()

    def _enabled(self) -> bool:
        raw = str(os.getenv("AGENT_SEMANTIC_STORE") or "1").strip().lower()
        return raw not in {"0", "false", "off", "no"}

    def _fallback_path(self, user_id: str) -> Path:
        return self._persist_dir / "fallback" / f"{_safe_collection_name(user_id)}.jsonl"

    def _load_fallback(self, user_id: str) -> List[Dict[str, Any]]:
        path = self._fallback_path(user_id)
        if not path.exists():
            return []
        try:
            out: List[Dict[str, Any]] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict) and str(obj.get("text") or "").strip():
                    out.append(obj)
            return out
        except Exception:
            return []

    def _append_fallback(self, user_id: str, docs: List[SemanticDoc]) -> None:
        path = self._fallback_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not docs:
            return
        with path.open("a", encoding="utf-8") as f:
            for doc in docs:
                f.write(
                    json.dumps(
                        {
                            "id": doc.doc_id,
                            "text": doc.text,
                            "metadata": doc.metadata,
                            "created_at_s": float(doc.metadata.get("created_at_s") or time.time()),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def _chroma_client(self):  # noqa: ANN001
        import chromadb  # type: ignore

        # Keep API compatible with both old/new chromadb versions.
        try:
            from chromadb.config import Settings  # type: ignore

            settings = Settings(anonymized_telemetry=False)
            return chromadb.PersistentClient(path=str(self._persist_dir), settings=settings)
        except Exception:
            return chromadb.PersistentClient(path=str(self._persist_dir))

    def _get_collection(self, user_id: str):  # noqa: ANN001
        name = _safe_collection_name(user_id)
        client = self._chroma_client()
        try:
            return client.get_or_create_collection(name=name)
        except TypeError:
            # Some versions take positional args.
            return client.get_or_create_collection(name)

    def _query_fallback(
        self, *, user_id: str, subject: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        subject = str(subject or "").strip()
        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return []
        scored: List[tuple[float, Dict[str, Any]]] = []
        for item in self._load_fallback(user_id):
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if subject and str(meta.get("subject") or "").strip() and str(meta.get("subject") or "").strip() != subject:
                continue
            text = str(item.get("text") or "")
            tokens = set(_tokenize(text))
            if not tokens:
                continue
            overlap = len(query_tokens.intersection(tokens))
            score = float(overlap) / float(len(query_tokens) or 1)
            if score <= 0:
                continue
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: List[Dict[str, Any]] = []
        for score, item in scored[: max(0, int(limit or 0))]:
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            out.append(
                {
                    "id": str(item.get("id") or ""),
                    "text": str(item.get("text") or "")[:800],
                    "metadata": meta,
                    "score": score,
                }
            )
        return out

    async def upsert(self, *, user_id: str, docs: List[SemanticDoc]) -> None:
        if not self._enabled():
            return
        uid = str(user_id or "anonymous").strip() or "anonymous"
        cleaned: List[SemanticDoc] = []
        for doc in docs or []:
            text = str(getattr(doc, "text", "") or "").strip()
            if not text:
                continue
            meta = dict(getattr(doc, "metadata", {}) or {})
            meta.setdefault("created_at_s", time.time())
            meta["user_id"] = uid
            doc_id = str(doc.doc_id or "").strip() or uuid.uuid4().hex
            meta["doc_id"] = doc_id
            meta = {str(k): _safe_meta(v) for k, v in meta.items() if str(k).strip()}
            cleaned.append(SemanticDoc(doc_id=doc_id, text=text, metadata=meta))

        if not cleaned:
            return

        async with self._lock:
            try:
                await asyncio.to_thread(self._upsert_chroma_sync, uid, cleaned)
                return
            except Exception:
                logger.debug("semantic_store_upsert_chroma_failed", exc_info=True)
                try:
                    await asyncio.to_thread(self._append_fallback, uid, cleaned)
                except Exception:
                    logger.debug("semantic_store_fallback_write_failed", exc_info=True)

    def _upsert_chroma_sync(self, user_id: str, docs: List[SemanticDoc]) -> None:
        collection = self._get_collection(user_id)
        ids = [d.doc_id for d in docs]
        texts = [d.text for d in docs]
        metas = [d.metadata for d in docs]
        embeds = [_embed_hashing(f"{d.metadata.get('subject','')} {d.metadata.get('topic','')} {d.text}", dim=self._dim) for d in docs]
        if hasattr(collection, "upsert"):
            collection.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=embeds)
        else:
            collection.add(ids=ids, documents=texts, metadatas=metas, embeddings=embeds)

    async def search(
        self, *, user_id: str, subject: str, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        if not self._enabled():
            return []
        uid = str(user_id or "anonymous").strip() or "anonymous"
        subject = str(subject or "").strip()
        query = str(query or "").strip()
        limit = max(1, min(int(limit or 5), 10))
        if not query:
            return []

        async with self._lock:
            try:
                return await asyncio.to_thread(self._search_chroma_sync, uid, subject, query, limit)
            except Exception:
                logger.debug("semantic_store_search_chroma_failed", exc_info=True)
                return self._query_fallback(user_id=uid, subject=subject, query=query, limit=limit)

    def _search_chroma_sync(self, user_id: str, subject: str, query: str, limit: int) -> List[Dict[str, Any]]:
        collection = self._get_collection(user_id)
        where = {"subject": subject} if subject else None
        q_embed = _embed_hashing(query, dim=self._dim)
        if where:
            res = collection.query(query_embeddings=[q_embed], n_results=limit, where=where)
        else:
            res = collection.query(query_embeddings=[q_embed], n_results=limit)

        ids_blob = res.get("ids") if isinstance(res, dict) else None
        docs = res.get("documents") if isinstance(res, dict) else None
        metas = res.get("metadatas") if isinstance(res, dict) else None
        dists = res.get("distances") if isinstance(res, dict) else None

        ids = ids_blob[0] if isinstance(ids_blob, list) and ids_blob and isinstance(ids_blob[0], list) else []
        documents = docs[0] if isinstance(docs, list) and docs and isinstance(docs[0], list) else []
        metadatas = metas[0] if isinstance(metas, list) and metas and isinstance(metas[0], list) else []
        distances = dists[0] if isinstance(dists, list) and dists and isinstance(dists[0], list) else []

        out: List[Dict[str, Any]] = []
        for i, text in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) and isinstance(metadatas[i], dict) else {}
            dist = float(distances[i]) if i < len(distances) else 0.0
            out.append(
                {
                    "id": str(ids[i] if i < len(ids) else meta.get("doc_id") or ""),
                    "text": str(text or "")[:800],
                    "metadata": meta,
                    "score": max(0.0, 1.0 - dist),
                }
            )
        return out
