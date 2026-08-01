"""自学资料生成质量 benchmark：用例驱动、事件流 + 成稿多维评分。

只观察、不修改生成链路：runner 通过 HTTP/SSE 调
``POST /api/study-materials/generate`` 采集 ``events.jsonl`` 与 ``final.md``，
graders 对二者做确定性评分，scorecard 汇总为百分制报告。
"""
