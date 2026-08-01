import tempfile
import unittest
from pathlib import Path

from backend.generation.study_materials.author.notes import NotesStore


class NotesStoreTests(unittest.TestCase):
    def test_write_read_append_and_events(self):
        events = []
        with tempfile.TemporaryDirectory() as d:
            store = NotesStore(Path(d), on_write=lambda name, n: events.append((name, n)))
            store.write("research", "# 研究笔记\n## 极限")
            store.append("research", "fact: 夹逼定理 | src: https://a | conf: 0.9")
            text = store.read("research")
            self.assertIn("夹逼定理", text)
            self.assertEqual(events, [("research", len("# 研究笔记\n## 极限")),
                                      ("research", len(text))])
            self.assertTrue((Path(d) / "research.md").exists())

    def test_read_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(NotesStore(Path(d)).read("blueprint"), "")

    def test_rejects_path_traversal_name(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                NotesStore(Path(d)).write("../evil", "x")


if __name__ == "__main__":
    unittest.main()
