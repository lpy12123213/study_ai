from __future__ import annotations

import json
import unittest


class TestLLMStreamToolCalls(unittest.TestCase):
    def test_parse_sse_chat_response_merges_incremental_tool_call_arguments(self) -> None:
        from backend.llm.client import _parse_sse_chat_response

        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "search_questions", "arguments": "{\"keyword\""},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": ": \"函数\"}"}},
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ]
        raw = "\n".join(f"data: {json.dumps(chunk, ensure_ascii=False)}" for chunk in chunks) + "\ndata: [DONE]\n"

        parsed = _parse_sse_chat_response(raw)

        self.assertIsInstance(parsed, dict)
        message = parsed["choices"][0]["message"]
        self.assertEqual(message["tool_calls"][0]["id"], "call_1")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "search_questions")
        self.assertEqual(message["tool_calls"][0]["function"]["arguments"], '{"keyword": "函数"}')


if __name__ == "__main__":
    unittest.main()
