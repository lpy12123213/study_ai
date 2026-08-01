# 自学资料生成质量 Benchmark

对 `POST /api/study-materials/generate` 的真实生成结果做困难、可重复、便于定位的离线评测。
Challenge v2 同时报告两种分数：

- **原始诊断分**：六个维度直接相加，用于观察局部能力进展。
- **最终成熟度分**：原始诊断分再受四个必要质量门槛封顶，用于回答“现在能否交给学习者”。

这种形式避免检索次数、篇幅或 Markdown 外形抵消截断、知识错误、无来源、无练习反馈等
致命问题。benchmark 只观察生成链路，不修改生成实现。

## 快速开始

```bash
# 1. 校验 40 个用例和评分契约（不跑生成）
python -m backend.evals.study_materials.runner --case all --dry-run

# 2. 启动后端后跑轻量回归套件（8 例，默认自动 4 并发）
python -m uvicorn backend.app:app --port 8000
python -m backend.evals.study_materials.runner --case light

# 3. 跑单例，或对已落盘结果复评而不重新生成
python -m backend.evals.study_materials.runner --case lebesgue_integral
python -m backend.evals.study_materials.runner \
  --regrade artifacts/evals/study_materials/<case_id>/<timestamp>

# 4. 可选 LLM 语义复核与联网链接诊断
python -m backend.evals.study_materials.runner --case light --llm-judge --check-links
```

每个用例在 `artifacts/evals/study_materials/<case_id>/<timestamp>/` 产出：
`events.jsonl`、`final.md`、`meta.json`、`task_info.json`、`score.json` 和 `report.md`。
报告包含成熟度分、原始诊断分、实际封顶、逐门槛证据、逐项扣分和不计分的过程诊断。

### 轻量、重量与分片

runner 把生成等待视为 I/O 密集任务：`--parallel 0`（默认）在单例时串行，在多例时自动使用
`min(4, 用例数)` 个线程。可用 `--parallel 1` 强制串行，或显式指定服务端能够承受的并发数。
离线 `--dry-run` 只解析并编译评分正则，不发 HTTP 请求。

负载套件按运行规模划分，不改变题目难度、评分权重或成熟度门槛：`light` 包含 8 个代表例，
`heavy` 包含其余 32 个难例；两者互斥，且并集严格等于 `all`。因此日常反馈跑 `light`，
夜间或发布前可以跑 `heavy` 补齐覆盖；需要一条命令完成发布门禁时直接跑 `all`。

```bash
# 轻量：8 个跨学科代表例，自动 4 并发
python -m backend.evals.study_materials.runner --case light

# 重量：其余 32 例；可在 CI 中继续分片
python -m backend.evals.study_materials.runner --case heavy --shard-count 4 --shard-index 0

# 完整 40 例；显式把本机并发限制到 2
python -m backend.evals.study_materials.runner --case all --parallel 2

# CI/多机稳定分成 4 片；index 为 0-based，各片互斥且并集恰为所选套件
python -m backend.evals.study_materials.runner --case all --shard-count 4 --shard-index 0
python -m backend.evals.study_materials.runner --case all --shard-count 4 --shard-index 1
```

分片先按 case id 排序再取模，因此不受文件顺序影响。`--llm-judge` 和 `--check-links` 默认关闭；
它们分别增加模型调用与网络请求，仅建议用于发布前抽查。已有 artifacts 调权后优先用 `--regrade`，
无需再次承担完整生成时间。

## 原始诊断分（100 分）

| 维度 | 分值 | 确定性评分方式 |
|---|---:|---|
| R 多步检索过程 | 10 | 来源类别、逐知识点深读、唯一来源、检索轮次、权威域名 |
| K 知识理解 | 35 | 事实锚点与逐事实引用、明确纠错语境、显式概念对比 |
| L 学习闭环 | 20 | 学习目标、前置知识、带步骤例题、分层自测、Q/A 对应与评分点 |
| F 结构与格式 | 15 | 骨架、知识点小节、目录锚点、层级、数学 lint、关键公式、篇幅 |
| A 美观与可读性 | 5 | 图表计数和排版质量代理；可选 LLM rubric |
| C 引用与学术规范 | 15 | 参考文献数量、有效内联对应、用例指定权威域名 |

子代理使用（S）保留在 `process_diagnostics`，但不计入百分制。子代理是一种实现策略，
不是学习者可见质量，不能因为采用某种编排方式就给成稿加质量分。

### 逐事实可溯源门控

K1 会在每条事实所在段落寻找能映射到文末带 URL 定义的 `[^n]` 或 `[n]` 标记。
有事实且有对应引用时得该事实满分；只有事实、没有有效引用时仅保留 15% 草稿分。
文档其他位置的引用不能给所有事实统一增加“溯源分”。

C 维度也不再以“两条 URL”作为满分：参考文献数量使用用例的 `min_unique_sources`，
有效内联引用目标为事实点数量的 80%，权威域名目标为 `expected_domains` 的三分之二。
`--check-links` 仅把可访问性写进诊断，不因实时网络波动改变离线分数。

## 最终成熟度门槛

计算公式：

```text
最终成熟度分 = min(原始诊断分, 所有未通过门槛的最低封顶)
```

| 门槛 | 通过条件 | 未通过时封顶 |
|---|---|---:|
| G0 完整交付 | 成功终态、篇幅达标、至少 80% 知识点有正文、无截断/占位符/坏 Markdown lint | 9 |
| G1 核心正确性 | 至少 80% 事实命中、80% 误区明确驳正、80% 概念对比成立 | 19 |
| G2 证据闭环 | 参考文献达到 75%、有效内联对应达到 75%、权威域名达到 50% | 19 |
| G3 学习反馈闭环 | L 维度达到 70%，且题目—答案—评分点子项达到 70% | 39 |

因此，“内容很长但截断”的文件最多 9 分；完整但存在关键知识缺口或不可核验的文件最多
19 分。原始诊断分仍会完整展示，不会因为压分而掩盖已有局部能力。

## 可评分输出协议

runner 会把统一的 Challenge v2 协议写入生成请求 `requirements`，并强制
`with_questions=true`。协议保持在 API 的 600 字符限制内，要求：

- 学习目标和前置知识；
- 至少两个带完整步骤、标为 `[EX1]` 起的例题；
- 至少六道标为 `[Q1]` 起的自测题，并覆盖 `[基础]`、`[应用]`、`[迁移]`；
- 标为 `[A1]` 起且与题号一一对应的答案和评分点；
- 关键事实句后的 `[^n]` 引文，以及文末含标题与 URL 的脚注；
- 明确的边界条件、误区和反例。

标签用于确定性定位，不替代内容评分。即使标签齐全，事实、误区、对比、来源和交付门槛
仍会独立判定。测试中同时有“当前风格低分锚点”和“可通过全部门槛的 golden fixture”，
避免 benchmark 退化成谁都过不了的格式陷阱。

## 为什么当前系统低于 20 分是合理结果

这些失分对应真实生成缺口，而非单纯调低权重：

- 汇编收集 `refs_by_kp`，但没有把它渲染进最终 Markdown；小节写手 prompt 还明确禁止
  URL 和引用标记，因此检索结果与最终论断之间没有证据闭环。
- 生成阶段收集 `examples`/`exercises`，汇编却没有渲染它们；旧用例还普遍关闭题目。
  v2 全部开启题目，并要求答案、评分点和难度层级。
- 旧分数允许篇幅、标题层级、检索轮次独立加分。v2 的 G0 联合检查终态、知识点小节覆盖、
  篇幅和 lint，长文本不能掩盖只写了一部分或末尾截断。
- 正确关键词不再自动通过误区与对比项：误区必须有明确纠错语境，对比必须有比较语义。
- 目录仍是纯文本 bullet，且图形工具缺失时通常只有降级说明，这些继续反映在 F/A 维度。

难度旋钮集中在三处：`graders/common.py` 的维度权重、`scorecard.py` 的门槛与封顶，
以及用例 JSON/schema 中的来源、事实、学习和格式阈值。

## 用例集

共有 40 个逻辑用例。9 个独立 JSON 保留用于重点校准，31 个新增用例收在
`cases/challenge_v2_extended_pack.json`；pack 只复用 preset、生成选项和学习/格式门槛，
每个主题仍有独立知识点、事实正则、来源、误区和辨析对。

| selector | 数量 | 选择规则 | 用途 |
|---|---:|---|---|
| `light` | 8 | `tier=smoke` | 日常/PR 的轻量真实回归 |
| `heavy` | 32 | `tier=core` 或 `extended` | 夜间或发布前补齐重负载覆盖 |
| `smoke` | 8 | `light` 的兼容别名 | 最快的跨学科真实回归 |
| `core` | 12 | smoke 8 + `tier=core` 4 | 主干质量门禁 |
| `extended` | 28 | 仅 `tier=extended` | 扩展主题专项覆盖 |
| `all` | 40 | 全部 tier | 发布前全量评测 |

主题覆盖如下：

- 原 9 例：勒贝格积分、量子谐振子、TCP、CRISPR、法国大革命、梯度下降、特征分解、
  光合作用、医学筛查 Bayes。
- 数学与统计 6 例：中心极限定理、傅里叶/采样、群同态、ODE 数值稳定性、KKT、PCA/SVD。
- 物理与化学 7 例：狭义相对论、麦克斯韦方程、热力学熵、PN 结、化学平衡、
  Nernst 方程、SN1/SN2/E1/E2。
- 生命科学 4 例：孟德尔连锁、免疫与疫苗、细胞呼吸、Hardy–Weinberg 平衡。
- 计算机与 AI 6 例：事务/MVCC、Raft、虚拟内存、密码散列与签名、编译器、Transformer。
- 社会/地球/跨学科 8 例：货币政策、比较优势、因果 DAG、宪政分权、板块构造、
  气候反馈、实验设计、信息论。

新增单例可复制任一独立 JSON；批量扩展可在 case pack 的 `defaults` 下追加 `cases`，嵌套对象会
深合并、数组由具体用例替换。`required_facts` 至少一条且 id 唯一，每条至少有一个
`source_url`；正则必须可编译，`traps`、`contrasts`、`expected_domains` 和
`expected_knowledge_points` 都不能为空。挑战用例建议配置至少 5 个事实点、2–3 个陷阱和
2 组辨析对。runner 会强制 `prefer_local_archive=false`，避免历史归档跳过真实生成。

## 校准记录

### Challenge v1

2026-08-01 的首次真实校准中，生成失败/空壳产物分别为 10.0 和 15.2。修复写作超时、
零素材静默成功、审阅 JSON flake、done 空正文和 revise 截断后，同批主题的旧评分升至：

| 模型 | 用例 | v1 分数 |
|---|---|---:|
| deepseek-v4-pro | tcp_congestion_control | 44.9 |
| deepseek-v4-pro | lebesgue_integral | 36.8 |
| deepseek-v4-flash | tcp_congestion_control | 20.0（受 revise 截断污染的中间结果） |

旧评分上升暴露出独立加分可抵消致命缺陷的问题，因此引入 v2 门槛，而不是继续向缺口维度
机械增加权重。

### Challenge v2

2026-08-01 对修复后的同批真实 artifacts 离线复评（未重新生成）：

| 用例 | v1 当前分 | v2 原始诊断 | v2 成熟度 | 关键门槛证据 |
|---|---:|---:|---:|---|
| tcp_congestion_control | 41.6 | 37.1 | **9.0** | 仅 4/7 知识点小节，含占位符且末尾截断；无证据/学习闭环 |
| lebesgue_integral | 36.8 | 30.6 | **9.0** | 任务状态 failed，仅 1/7 小节；事实命中 40%，无证据/学习闭环 |

两个当前产物都低于 20 分，原始诊断分仍显示它们在检索、局部知识和格式上的进展。
合成 golden fixture 能通过全部四个门槛并获得 85 分以上，证明高分路径可达。

## 已知边界

- 仅支持 HTTP/SSE 采集；in-process runner 尚未实现。
- A2 是 Markdown 结构代理，尚无 HTML/PDF 渲染后的视觉评分。
- LLM judge 默认关闭以保证复现；启用后只补救语义表述，不会替没有证据的事实解除溯源门控。
- 多进程共享同一 SQLite 时，进程启动可能触发 `restart_recovery` 并中止 running 任务；
  benchmark 运行期间不要并行启动测试套件或重启同库服务。
