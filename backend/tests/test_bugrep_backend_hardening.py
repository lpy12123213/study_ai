from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.requests import Request

from backend.core.metrics import _route_template
from backend.core.plot.expression import _safe_eval_expr
from backend.generation.question_library.beam_search import expand_skill_layer
from scripts.replay_llm import convert_records


class BugrepBackendHardeningTests(unittest.TestCase):
    def test_plot_expression_rejects_constant_power_bombs(self) -> None:
        with self.assertRaises(ValueError):
            _safe_eval_expr("9**9**9", variables={})

    def test_beam_child_spec_ids_are_stable_and_distinct(self) -> None:
        specs = [{"spec_id": "root", "subject": "数学", "score": 1.0}]
        children = expand_skill_layer(
            specs,
            {
                "skill_branch_factor": 2,
                "expand_budget": 2,
            },
        )
        ids = [item["spec_id"] for item in children]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all("/skill:" in spec_id for spec_id in ids))

    def test_replay_llm_skips_copy_when_source_and_output_are_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "llm"
            source.mkdir()
            (source / "unknown.json").write_text('{"kind":"not-record"}', encoding="utf-8")

            out = convert_records(source, source, copy_unknown=True)

            self.assertEqual(out["copied"], 0)
            self.assertEqual(out["skipped"], 1)

    def test_unmatched_metrics_route_uses_constant_label(self) -> None:
        app = FastAPI()

        @app.get("/known/{item_id}")
        async def _known(item_id: str) -> dict:
            return {"item_id": item_id}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/scanner/12345",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
            "app": app,
            "router": app.router,
            "path_params": {},
        }
        request = Request(scope)
        self.assertEqual(_route_template(request), "<unmatched>")

        known_scope = dict(scope)
        known_scope["path"] = "/known/abc"
        known_request = Request(known_scope)
        match, child_scope = next(
            route.matches(known_scope)
            for route in app.routes
            if isinstance(route, APIRoute) and getattr(route, "path", "") == "/known/{item_id}"
        )
        self.assertTrue(match)
        known_scope.update(child_scope)
        self.assertEqual(_route_template(known_request), "/known/{item_id}")


if __name__ == "__main__":
    unittest.main()
