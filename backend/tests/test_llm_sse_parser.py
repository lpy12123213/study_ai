from __future__ import annotations

import json
import unittest

from backend.llm.sse_parser import finalize_tool_call_chunks, merge_tool_call_chunks, parse_sse_chat_response


class TestLLMSSEParser(unittest.TestCase):
    def test_parse_sse_response_merges_content_tool_calls_and_usage(self) -> None:
        payloads = [
            {"choices": [{"delta": {"content": "hel"}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "content": "lo",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_a",
                                    "type": "function",
                                    "function": {"name": "search", "arguments": '{"q"'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1},
            },
            {
                "choices": [
                    {
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ': "algebra"}'}}]},
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {"usage": {"prompt_tokens": 2, "completion_tokens": 3}},
        ]
        raw = "\n".join(
            [
                ": keep-alive",
                "data: not-json",
                *[f"data: {json.dumps(payload)}" for payload in payloads],
                "data: [DONE]",
            ]
        )

        parsed = parse_sse_chat_response(raw)

        self.assertIsInstance(parsed, dict)
        message = parsed["choices"][0]["message"]
        self.assertEqual(message["content"], "hello")
        self.assertEqual(parsed["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(parsed["usage"], {"prompt_tokens": 2, "completion_tokens": 3})
        self.assertEqual(message["tool_calls"][0]["id"], "call_a")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "search")
        self.assertEqual(message["tool_calls"][0]["function"]["arguments"], '{"q": "algebra"}')

    def test_parse_sse_response_returns_none_without_valid_chunks(self) -> None:
        self.assertIsNone(parse_sse_chat_response("plain text"))
        self.assertIsNone(parse_sse_chat_response("data: not-json\n"))

    def test_finalize_tool_call_chunks_adds_id_and_ignores_empty_chunks(self) -> None:
        chunks: dict[int, dict] = {}
        merge_tool_call_chunks(
            chunks,
            [
                {"index": 2, "function": {"arguments": '{"x": 1}'}},
                {"index": 1, "function": {}},
            ],
        )

        finalized = finalize_tool_call_chunks(chunks)

        self.assertEqual(len(finalized), 1)
        self.assertEqual(finalized[0]["id"], "call_2")
        self.assertEqual(finalized[0]["type"], "function")
        self.assertEqual(finalized[0]["function"]["arguments"], '{"x": 1}')


if __name__ == "__main__":
    unittest.main()
