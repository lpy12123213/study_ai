# 自学资料生成质量 benchmark（backend/evals/study_materials）

用例驱动 → HTTP/SSE 跑真实生成 → 事件流 + 成稿确定性评分 → 原始诊断分 + 门槛成熟度分。
完整说明见 `docs/STUDY_MATERIALS_BENCHMARK.md`。

```bash
python -m backend.evals.study_materials.runner --case all --dry-run   # 校验用例
python -m backend.evals.study_materials.runner --case light           # 轻量 8 例，默认自动 4 并发
python -m backend.evals.study_materials.runner --case heavy           # 重量 32 例（与 light 互斥）
python -m backend.evals.study_materials.runner --case lebesgue_integral  # 跑单个用例
python -m backend.evals.study_materials.runner --regrade artifacts/evals/study_materials/<case>/<ts>  # 复评已落盘运行
```

- `case_schema.py` — 单用例/case pack schema、学习闭环阈值与统一输出协议；`cases/` — 40 个逻辑用例
- `graders/` — R 检索 / K 知识 / L 学习 / F 结构 / A 美观 / C 引用；S 子代理仅作过程诊断
- `scorecard.py` — 四个必要门槛、成熟度封顶与报告；`runner.py` — 分层选择、稳定分片、自动并发与采集 CLI
- 测试：`backend/tests/test_study_materials_evals.py`（离线 fixture，含"现行链路产物 <20 分"锚点）
