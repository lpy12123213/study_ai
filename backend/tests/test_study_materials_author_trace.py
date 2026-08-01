import unittest

from backend.generation.study_materials.author.trace import TRACE_EVENT_TYPES, make_event


class TraceTests(unittest.TestCase):
    def test_event_carries_agent_path(self):
        ev = make_event("thinking_delta", agent_path="fill:sec-1.2", data={"text": "嗯"})
        self.assertEqual(ev["type"], "thinking_delta")
        self.assertEqual(ev["agent_path"], "fill:sec-1.2")

    def test_declared_types_cover_design_contract(self):
        for t in {"thinking_delta", "note_write", "todo_update", "figure_trace"}:
            self.assertIn(t, TRACE_EVENT_TYPES)

    def test_rejects_undeclared_type(self):
        with self.assertRaises(ValueError):
            make_event("mystery", agent_path="main", data={})


if __name__ == "__main__":
    unittest.main()
