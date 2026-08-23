# AI 出题质量 benchmark（backend/evals/question_generation）

用例驱动 → HTTP/SSE 跑真实出题 → 拉取预览草稿 → 确定性评分 → 原始诊断分 + 门槛成熟度分。
完整说明见 `docs/QUESTION_GENERATION_BENCHMARK.md`。

```bash
python -m backend.evals.question_generation.runner --case all --dry-run  # 校验用例
python -m backend.evals.question_generation.runner --case all            # 26 例真实出题并评分（自动 4 并发）
python -m backend.evals.question_generation.runner --case math_conic_focus_chord  # 跑单个用例
```

- `case_schema.py` — 出题用例 schema：请求参数 + 题干/答案/解析锚点 + 禁用模式 + 抽象解法指纹；`cases/` — 26 个用例（困难 15 + 压轴 11）
- 用例分两档：**困难**（高考压轴级：椭圆焦点弦、导数零点讨论、错位相减、电磁感应电荷量、碰撞能量、弱酸 Ka、滴定电子守恒、双病遗传概率）与**压轴**（竞赛/强基级：同余与费马小定理、函数方程归纳、级数放缩 7/4、Ramsey 抽屉、刚体纯滚动、角动量收臂、NaCl 晶胞密度、哈代-温伯格选择、双星系统、电解电子守恒）；第二批扩充覆盖立体几何外接球、解三角形最值、二项分布期望、光电效应、化学平衡三段法、生态能量流动与柯西不等式填空（含填空题型）
- 题面契约用 LaTeX 记号书写并把数值结论钉死在 topic 里；锚点同时兼容 LaTeX（`\frac{24}{7}`、`\ln 2`、`\,`）与普通文本写法，全部经过手写模型解验证
- `graders.py` — D1 交付 / D2 正确性 / D3 教学性 / D4 契约；门槛 GQ_delivery、GQ_correctness 封顶；另扣难度错配与解法过度模仿惩戒；生成链路自评只作过程诊断
- `runner.py` — `POST /api/question-library/generate`（SSE）→ done 取 preview_id → `GET /previews/{id}` 取草稿 → 评分落盘
- 每个用例在 `artifacts/evals/question_generation/<case_id>/<timestamp>/` 产出：`events.jsonl`、`preview.json`、`meta.json`、`score.json`、`report.md`
- 测试：`backend/tests/test_question_generation_evals.py`（离线 fixture，含锚定模型解与坏草稿反例）
