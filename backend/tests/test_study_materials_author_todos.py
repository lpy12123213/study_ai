import tempfile
import unittest
from pathlib import Path

from backend.generation.study_materials.author.todos import TodoItem, TodoList


class TodoModelTests(unittest.TestCase):
    def test_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            TodoItem(id="t1", type="bogus")

    def test_all_cleared_requires_done_or_waived(self):
        tl = TodoList(items=[
            TodoItem(id="t1", type="fill", ref="sec-1", status="done"),
            TodoItem(id="t2", type="fig", ref="1", status="waived", note="engine down"),
        ])
        self.assertTrue(tl.all_cleared())
        tl.items[1].status = "pending"
        self.assertFalse(tl.all_cleared())

    def test_roundtrip_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "todos.json"
            tl = TodoList(items=[TodoItem(id="t1", type="research", acceptance=">=3 sources")])
            tl.save(p)
            loaded = TodoList.load(p)
            self.assertEqual(loaded.items[0].acceptance, ">=3 sources")
            self.assertFalse(p.with_suffix(".json.tmp").exists())

    def test_next_pending_respects_deps(self):
        tl = TodoList(items=[
            TodoItem(id="a", type="backbone"),
            TodoItem(id="b", type="fill", ref="sec-1", deps=["a"]),
        ])
        self.assertEqual(tl.next_pending().id, "a")
        tl.mark("a", "done")
        self.assertEqual(tl.next_pending().id, "b")


if __name__ == "__main__":
    unittest.main()
