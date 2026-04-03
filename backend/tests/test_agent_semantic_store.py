from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from backend.agent.memory import SemanticDoc, SemanticStore


class TestSemanticStore(unittest.IsolatedAsyncioTestCase):
    def _tmp_dir(self) -> Path:
        base_dir = Path(__file__).resolve().parents[2] / ".local" / "test_tmp"
        base_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = base_dir / f"semantic-store-{uuid.uuid4().hex[:12]}"
        tmp_path.mkdir(parents=True, exist_ok=True)
        return tmp_path

    async def test_upsert_and_search_isolated_by_user(self) -> None:
        tmp_path = self._tmp_dir()
        try:
            store = SemanticStore(persist_dir=str(tmp_path))

            await store.upsert(
                user_id="u-1",
                docs=[
                    SemanticDoc(
                        doc_id="doc-1",
                        text="导数用于刻画函数的瞬时变化率，常用于单调性与极值判断。",
                        metadata={"subject": "高中数学", "topic": "导数"},
                    )
                ],
            )

            await store.upsert(
                user_id="u-2",
                docs=[
                    SemanticDoc(
                        doc_id="doc-2",
                        text="概率用于刻画事件发生的可能性，注意独立事件与互斥事件的区别。",
                        metadata={"subject": "高中数学", "topic": "概率"},
                    )
                ],
            )

            hits_u1 = await store.search(user_id="u-1", subject="高中数学", query="导数 单调性", limit=5)
            self.assertTrue(any("导数" in str(h.get("text") or "") for h in hits_u1))

            hits_u2 = await store.search(user_id="u-2", subject="高中数学", query="导数 单调性", limit=5)
            self.assertFalse(any("导数" in str(h.get("text") or "") for h in hits_u2))
        finally:
            shutil.rmtree(tmp_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

