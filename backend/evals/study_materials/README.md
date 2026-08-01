# 自学资料生成质量 benchmark（backend/evals/study_materials）

用例驱动 → HTTP/SSE 跑真实生成 → 事件流 + 成稿确定性评分 → 百分制报告。
完整说明见 `docs/STUDY_MATERIALS_BENCHMARK.md`。

```bash
python -m backend.evals.study_materials.runner --case all --dry-run   # 校验用例
python -m backend.evals.study_materials.runner --case lebesgue_integral  # 跑单个用例
python -m backend.evals.study_materials.runner --regrade artifacts/evals/study_materials/<case>/<ts>  # 复评已落盘运行
```

- `case_schema.py` — 用例 schema 与校验；`cases/` — 首批 6 个用例
- `graders/` — R 检索 / K 知识 / S 子代理 / F 结构 / A 美观 / C 引用六个确定性评分器
- `scorecard.py` — 汇总与报告；`runner.py` — 采集与编排 CLI
- 测试：`backend/tests/test_study_materials_evals.py`（离线 fixture，含"现行链路产物 <20 分"锚点）
