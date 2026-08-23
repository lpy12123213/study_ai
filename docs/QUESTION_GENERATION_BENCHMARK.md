# AI 出题质量 Benchmark

对 `POST /api/question-library/generate` 的真实出题结果做困难、可重复、便于定位的离线评测。
与自学资料 benchmark（`docs/STUDY_MATERIALS_BENCHMARK.md`）同构：原始诊断分观察局部能力，
必要质量门槛封顶回答「现在能否直接入库」。

## 设计

用例是自包含的评分契约。请求侧把题目数据用 LaTeX 钉死在 `topic` 里（如
「椭圆 $\frac{x^{2}}{4}+\frac{y^{2}}{3}=1$ 过右焦点斜率 1，弦长 $|AB|=\frac{24}{7}$」），
评分侧用三类确定性锚点逐题判定：

- **题干锚点**（stem_anchors）：题目必须携带的给定数据；
- **答案锚点**（answer_anchors）：可验证的最终结果（答案与解析联合匹配，兼容 `\frac{24}{7}` 等 LaTeX 写法）；
- **解析锚点**（analysis_anchors）：方法线索（韦达定理、动量定理、电子守恒、错位相减……）；
- **禁用模式**（forbidden_patterns）：命中即 D2 归零的典型错误结论。

### 维度与门槛

| 项 | 分值 | 确定性判定 |
|---|---:|---|
| D1 交付完整度 | 25 | 数量足额、题干/答案/解析三段完整、题干之间不近重复（字符二元组 Jaccard） |
| D2 答案正确性 | 35 | 逐题命中锚点且不触发禁用模式 |
| D3 教学性 | 25 | 解析步骤线索、解析篇幅、知识点语义片段进入题目 |
| D4 题型契约 | 15 | 题面结构（选项/空线/设问）与答案形态（选项字母等）匹配题型 |

| 门槛 | 未通过封顶 | 判定 |
|---|---:|---|
| GQ_delivery | 9 | 交付 ≥ ⌈0.8×count⌉ 且三段完整比例 ≥ 80% |
| GQ_correctness | 19 | 锚点命中 ≥ 80% 且禁用模式零命中 |

生成链路自评（draft.review 的 verdict/overall_score）只作过程诊断，不影响分数，避免自评循环。

在四个基础维度之后，`question_gen_v2` 还会扣除两类可定位的进化惩戒：

- **难度不匹配**：DeepSeek Go 必须给出候选原文证据后，才按目标与实测难度的等级差扣分；每差一级扣 8 分，最多 24 分。无证据标签不进入适应度。
- **解法过度模仿**：只比较抽象解法指纹，不保存或转发完整参考解答。本地概念序列匹配与有证据的独立监督取较高值，超过用例阈值才扣分，最多 30 分；普通的“反证法”等通用动作不能单独触发。

这两项同时影响候选排序与策略适应度，但属于软惩戒，不能推翻答案错误、条件不足等确定性硬门槛。

### 难度分层

- **困难（15 例）**：高考压轴级——椭圆焦点弦、含参导数零点与 `e^x≥x+1`、错位相减上界、
  电磁感应电荷量/焦耳热、弹性与非弹性碰撞、弱酸 Ka 与半中和点、高锰酸钾滴定电子守恒、双病遗传概率、
  正三棱锥体积与外接球、解三角形面积最值、二项分布期望、光电效应三连计算、化学平衡三段法 K、
  生态能量流动最值、柯西不等式（恩格尔形式）填空。
- **压轴（11 例）**：竞赛/强基及高考新定义迁移——2026 全国一卷压轴题认知结构迁移、同余与费马小定理、函数方程+数学归纳、Σ1/k²<7/4 分段裂项、
  Ramsey R(3,3)=6 与五人反例、刚体纯滚动、收臂角动量、NaCl 晶胞密度、哈代-温伯格致死选择、
  双星系统轨道半径、惰性电极电解电子守恒。

## 使用

```bash
# 1. 校验 26 个用例（解析锚点正则，不出题）
python -m backend.evals.question_generation.runner --case all --dry-run

# 2. 启动后端后真实出题并评分
python -m uvicorn backend.app:app --port 8000
python -m backend.evals.question_generation.runner --case all
python -m backend.evals.question_generation.runner --case physics_rolling_cylinder_incline  # 单例
python -m backend.evals.question_generation.runner --case math_2026_gaokao_finale_transfer # 2026 压轴迁移

# 可选参数：--base-url、--out、--timeout-s（默认 900s）、--parallel（0=自动≤4）
```

每个用例在 `artifacts/evals/question_generation/<case_id>/<timestamp>/` 产出
`events.jsonl`、`preview.json`、`meta.json`、`score.json` 和 `report.md`；
报告含成熟度分、原始诊断分、逐门槛证据、逐题锚点未命中明细与近重复下标。

离线测试：`python -m unittest backend.tests.test_question_generation_evals`（不触网、不调 LLM，
含 26 例模型解锚点验证、难度错配/仿题惩戒与坏草稿反例）。

## OpenCode Go 进化式 A/B

生成请求默认使用：

```json
{
  "generation_strategy": "adaptive_evolution",
  "supervision_mode": "tiered_consensus",
  "policy_mode": "champion"
}
```

对照组改为 `generation_strategy=legacy_beam`；影子策略评测使用 `policy_mode=shadow_compare`。真实测试必须按以下顺序执行，并保留每一步产物：

1. `GET https://opencode.ai/zen/go/v1/models`，确认 `muse-spark-1.2-contributor` 与 `deepseek-v4-flash` 均存在；
2. Muse `/responses` JSON/流式冒烟；
3. DeepSeek `/chat/completions` 监督冒烟；
4. 单题生成—确定性硬门槛—主监督—必要时仲裁—定向变异闭环；
5. 同一固定用例执行 `legacy_beam` / `adaptive_evolution` 小型 A/B。

首轮真实验证按 3 美元等价预算控制，并同时使用更严格的机械上限：Muse 最多 40 次、DeepSeek（主监督与仲裁合计）最多 20 次；任一调用或输出 Token 上限先达到即停止。单次 Muse 输出最多 6000 Token，单次 DeepSeek 输出最多 4000 Token；调用方传入 0 表示使用角色上限，而不是省略上限。SSE 中的 `strategy_evolution`、`draft_evolution` 与 `ai_supervision` 记录模型、协议、策略版本、代数、适应度、Token、延迟、仲裁数和停止原因。草稿及入库题目只保存谱系和监督摘要，不保存隐藏推理。

仅在需要观察长思考模型的人工真实测试中，可为该测试进程设置
`QUESTION_GENERATION_UNBOUNDED_LIVE_TEST=1`。此开关使专项出题调用不发送单次输出 Token 上限、
不设置单请求 HTTP 超时，并跳过 Muse/DeepSeek 累计输出 Token 上限；测试进程的调用预算提高为
Muse 60 次、DeepSeek 40 次，正常任务仍使用 40/20。
不要在常驻服务环境中设置该变量，未设置时继续使用上述所有生产限制。
