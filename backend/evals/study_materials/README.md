# 自学资料生成质量 benchmark（backend/evals/study_materials）

用例驱动 → HTTP/SSE 跑真实生成 → 事件流 + 成稿确定性评分 → 原始诊断分 + 门槛成熟度分。
完整说明见 `docs/STUDY_MATERIALS_BENCHMARK.md`。

```bash
python -m backend.evals.study_materials.runner --case all --dry-run   # 校验用例
python -m backend.evals.study_materials.runner --case light-probe     # 同一高难门槛的单例真实生成探针
python -m backend.evals.study_materials.runner --case light           # 高中主线 + 受控大学拓展 14 例，自动 4 并发
python -m backend.evals.study_materials.runner --case light --stage research  # 只评检索，落盘研究夹具
python -m backend.evals.study_materials.runner --case light --stage write     # 从夹具起跑撰写，不再检索
python -m backend.evals.study_materials.runner --case heavy           # 重量 34 例（与 light 互斥）
python -m backend.evals.study_materials.runner --case derivative_monotonicity_optimization  # 跑单个用例
python -m backend.evals.study_materials.runner --regrade artifacts/evals/study_materials/<case>/<ts>  # 复评已落盘运行
```

- `case_schema.py` — 单用例/case pack schema、高中/受控拓展范围、动态学习闭环协议；`cases/` — 48 个逻辑用例
- `graders/` — R 检索 / K 知识 / L 学习 / F 结构 / A 美观 / C 引用；S 子代理仅作过程诊断
- `scorecard.py` — 四个必要门槛、成熟度封顶与报告；检索阶段另有 `GR_research_coverage` 覆盖门槛
- `runner.py` — 分层选择、稳定分片、自动并发、`--stage full|research|write` 阶段评测与采集 CLI
- `light`/`light-probe` 请求使用 `research_budget=lean`：保留逐知识点事实/误区双检索和评分所需深读，只压缩百科补充与重复深读；题目、篇幅和质量门槛不变
- 生成链路按最低知识点小节数拆分，按权威性和查询意图轮转来源，并以逐知识点研究切片驱动填充/核查；分节引用、误区驳正、辨析语义、受控拓展和学习闭环进入作者验收
- 测试：`backend/tests/test_study_materials_evals.py`（离线 fixture，含历史链路产物 `<20` 分锚点）
- 新增两例结构压力用例（流体力学伯努利、分子轨道理论）以 12 知识点、4 图 4 表、15000 字下限压测结构维度
