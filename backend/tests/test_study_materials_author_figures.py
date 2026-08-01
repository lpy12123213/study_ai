import asyncio
import unittest

from backend.generation.study_materials.author.figures import FigureForge


class FigureForgeTests(unittest.TestCase):
    def test_success_returns_artifact_and_trace(self):
        async def fake_render(kind, code):
            return {"url": "/media/generated/f1.svg", "engine": kind}

        async def fake_llm(spec):
            return "graph LR; A-->B"

        trace = []
        forge = FigureForge(llm_codegen=fake_llm, render_func=fake_render,
                            on_trace=lambda ev: trace.append(ev))
        out = asyncio.run(forge.generate(
            {"n": 1, "sec_id": "sec-1", "intent": "流程", "kind": "mermaid", "caption": "图1"}))
        self.assertEqual(out["url"], "/media/generated/f1.svg")
        self.assertTrue(any(e["data"].get("stage") == "render_ok" for e in trace))

    def test_engine_fallback_chain_then_structured_failure(self):
        attempts = []

        async def bad_render(kind, code):
            attempts.append(kind)
            raise RuntimeError("compile failed")

        async def fake_llm(spec):
            return "code"

        forge = FigureForge(llm_codegen=fake_llm, render_func=bad_render,
                            engine_order=["tikz", "mermaid"], on_trace=lambda e: None)
        out = asyncio.run(forge.generate(
            {"n": 2, "sec_id": "s", "intent": "i", "kind": "auto", "caption": "c"}))
        self.assertEqual(attempts, ["tikz", "mermaid"])   # 换引擎重试
        self.assertIsNone(out["url"])
        self.assertEqual(out["status"], "failed")          # 结构化失败，不抛异常

    def test_malformed_spec_rejected(self):
        forge = FigureForge(llm_codegen=None, render_func=None, on_trace=lambda e: None)
        with self.assertRaises(ValueError):
            asyncio.run(forge.generate({"n": 3}))


if __name__ == "__main__":
    unittest.main()
