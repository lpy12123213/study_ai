# 自学资料生成质量 Benchmark

对 `POST /api/study-materials/generate` 的真实生成结果做困难、可重复、便于定位的离线评测。
Challenge v2 同时报告两种分数：

- **原始诊断分**：六个维度直接相加，用于观察局部能力进展。
- **最终成熟度分**：原始诊断分再受四个必要质量门槛封顶，用于回答“现在能否交给学习者”。

这种形式避免检索次数、篇幅或 Markdown 外形抵消截断、知识错误、无来源、无练习反馈等
致命问题。benchmark 只观察生成链路，不修改生成实现。

## 快速开始

```bash
# 1. 校验 48 个用例和评分契约（不跑生成）
python -m backend.evals.study_materials.runner --case all --dry-run

# 2. 启动后端后先跑单例真实探针，再按需跑轻量回归套件（14 例）
python -m uvicorn backend.app:app --port 8000
python -m backend.evals.study_materials.runner --case light-probe
python -m backend.evals.study_materials.runner --case light

# 3. 跑单例，或对已落盘结果复评而不重新生成
python -m backend.evals.study_materials.runner --case derivative_monotonicity_optimization
python -m backend.evals.study_materials.runner \
  --regrade artifacts/evals/study_materials/<case_id>/<timestamp>

# 4. 可选：检索/撰写分阶段评测（省 token；全量仍用默认 --stage full）
python -m backend.evals.study_materials.runner --case light --stage research
python -m backend.evals.study_materials.runner --case light --stage write

# 5. 可选 LLM 语义复核与联网链接诊断
python -m backend.evals.study_materials.runner --case light --llm-judge --check-links
```

每个用例在 `artifacts/evals/study_materials/<case_id>/<timestamp>/` 产出：
`events.jsonl`、`final.md`、`meta.json`、`task_info.json`、`score.json` 和 `report.md`。
报告包含成熟度分、原始诊断分、实际封顶、逐门槛证据、逐项扣分和不计分的过程诊断。

### 轻量、重量与分片

runner 把生成等待视为 I/O 密集任务：`--parallel 0`（默认）在单例时串行，在多例时自动使用
`min(4, 用例数)` 个线程。可用 `--parallel 1` 强制串行，或显式指定服务端能够承受的并发数。
离线 `--dry-run` 只解析并编译评分正则，不发 HTTP 请求。

负载套件按运行规模划分，评分权重和成熟度门槛保持一致。`light` 包含 14 个以高中课程为
主线的高难例，并允许每例 2–3 个明确标为 `[拓展:主题名]` 的大学桥接概念；这些概念必须从高中
知识推导、说明对高中解题/实验/材料分析的帮助，且不得作为默认前置知识。`heavy` 包含其余
34 个大学或专业主题。两者互斥，且并集严格等于 `all`。因此日常反馈跑 `light`，
夜间或发布前可以跑 `heavy` 补齐覆盖；需要一条命令完成发布门禁时直接跑 `all`。
`light-probe` 固定选择其中的含参导数最优化用例，题目和门槛完全相同，只把一次真实反馈
从 11 例缩成 1 例；适合生成链路改动后的第一轮验证，不能替代完整 `light` 覆盖。

```bash
# 探针：与 light 相同难度和评分门槛，只生成 1 例
python -m backend.evals.study_materials.runner --case light-probe

# 轻量：14 个高中主线 + 受控大学拓展高难例，自动 4 并发
python -m backend.evals.study_materials.runner --case light

# 重量：其余 34 例；可在 CI 中继续分片
python -m backend.evals.study_materials.runner --case heavy --shard-count 4 --shard-index 0

# 完整 48 例；显式把本机并发限制到 2
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
| G1 核心正确性 | 至少 80% 事实命中、80% 误区明确驳正、80% 概念对比成立；受控拓展逐项含 `[拓展:主题名]` 与 `[高中连接]` | 19 |
| G2 证据闭环 | 参考文献达到 75%、有效内联对应达到 75%、权威域名达到 50% | 19 |
| G3 学习反馈闭环 | L 维度达到 70%，且题目—答案—评分点子项达到 70% | 39 |

因此，“内容很长但截断”的文件最多 9 分；完整但存在关键知识缺口或不可核验的文件最多
19 分。原始诊断分仍会完整展示，不会因为压分而掩盖已有局部能力。

## 可评分输出协议

runner 会按每个用例的门槛动态生成 Challenge v2 协议，写入生成请求 `requirements`，并强制
`with_questions=true`。协议保持在 API 的 600 字符限制内；默认要求：

- 学习目标和前置知识；
- 至少两个带完整步骤、标为 `[EX1]` 起的例题；
- 至少六道标为 `[Q1]` 起的自测题，并覆盖 `[基础]`、`[应用]`、`[迁移]`；
- 标为 `[A1]` 起且与题号一一对应的答案和评分点；
- 关键事实句后的 `[^n]` 引文，以及文末含标题与 URL 的脚注；
- 明确的边界条件、误区和反例。

`light` 至少把上述数量提高到 5 个目标、4 个例题和 12 道逐题评分自测；新增的三道综合题
进一步提高到 6 个目标、5 个例题和 14 道自测。受控拓展还必须逐项使用完整主题名标记，
并在下一个拓展主题前给出 `[高中连接]`，不能用集中堆放的标签替代解释。

标签用于确定性定位，不替代内容评分。即使标签齐全，事实、误区、对比、来源和交付门槛
仍会独立判定。测试中同时有“当前风格低分锚点”和“可通过全部门槛的 golden fixture”，
避免 benchmark 退化成谁都过不了的格式陷阱。

## 生成链路如何响应门槛

benchmark 的门槛已落实到生成链路，而不是仅在评分阶段事后扣分：

- 用例把最低学习者可见知识点小节数写入输出协议；拆分阶段同时接收 `min_points`、
  `max_points`、全局要求和受控拓展主题，数量不足会重试，受控拓展会被保留为独立知识点。
- 来源候选先按机构权威性排序，再在权威事实、常见误区与百科查询之间轮转，最后按知识点
  轮转写入有容量上限的来源注册表；这同时避免单一查询类型或前几个知识点耗尽额度。
  填充与核查只接收当前知识点的研究切片和对应编号来源，避免后半篇长期看到研究笔记前缀。
- `light` 与 `light-probe` 自动发送 `research_budget=lean`。它仍为每个生成知识点执行“权威事实 +
  常见误区”两类检索，并按最低知识点小节数保留足以覆盖评分门槛的深读；只把 Wikipedia
  补充限制为均匀分布的至多 3 次，并把 deep 模式原本每点 2 次的深读降到每点 1 次加少量补位。
  例如生成 8 点、最低要求 8 个小节时，计划外部研究调用由 24 次搜索 + 16 次深读降为
  19 次搜索 + 10 次深读（40→29，减少 27.5%）。`research_budget` 事件会把计划量写入 trace。
- 蓝图按知识点一一映射小节；骨架缺少知识点标题时会按蓝图补齐。受控拓展使用精确的
  `[拓展:主题全名]` 标记，并要求该节正文包含带实际解释的 `[高中连接]`。
- 小节写手接收原始核心问题、全局输出要求和本节硬性标记；有可用来源却没有有效内联引用、
  有来源易错点却未明确驳正、要求辨析却没有比较语义时都会重试。各小节局部生成的 `[EXn]`、
  `[Qn]`、`[An]` 按整书目标精确分配（配额为 0 的小节不强制生成），在全书汇编前统一连续编号；
  单节上限之外的真实缺口才交给学习修复补全，避免把整书题量重复到每个小节。
- 作者验收会联合检查知识点小节数量、标题覆盖、受控拓展连接、学习闭环、占位符和篇幅。
  未达标会显式降级；残留占位符仍会令任务失败，不能由较长篇幅掩盖。

已有 artifact 是冻结产物，`--regrade` 只会用新评分规则重算旧 Markdown，不会自动经过新生成
链路。因此旧产物继续低于 20 分仍是有效的历史基线，但不能当作本次链路修改后的实测成绩。
新链路效果需要重新运行真实生成 benchmark 验证。

### 阶段评测：检索与撰写分开

全量 `--stage full`（默认）仍是端到端门禁。为了少烧 token、把失败定位到具体环节，可以把同一套
评分契约拆成两段：

```bash
# 1) 只评检索：跑拆分 + 检索，落盘研究快照并写入 <out>/_fixtures/<case_id>/
python -m backend.evals.study_materials.runner --case light --stage research

# 2) 只评撰写：从研究夹具起跑蓝图→填充→汇编，不再做真实检索
python -m backend.evals.study_materials.runner --case light --stage write
```

- `--stage research` 请求 `benchmark_stage=research`。管线在研究完成后即终态，`done` 携带
  `research_report`（知识点数、唯一来源、权威域名、逐知识点证据）。评分只算 R 维度（满分 10）
  和检索覆盖门槛 `GR_research_coverage`。成功快照会复制到运行目录与夹具目录，供撰写阶段复用。
- `--stage write` 请求 `research_fixture_dir`。管线跳过拆分与检索，从夹具注入知识点、研究笔记
  和来源登记表后进入撰写。评分仍走 K/L/F/A/C 与 G0–G3；R 维度只反映夹具内容，不代表检索能力。
  缺夹具时 runner 启动前统一失败，避免中途才发现而白烧已完成用例的 token。
- 夹具默认在 `artifacts/evals/study_materials/_fixtures/<case_id>/`，可用 `--fixture-dir` 覆盖。
  夹具文件为 `knowledge_points.json`、`research.md`、`source_registry.json`
  （可选 `research_evidence.json`）。
- 检索阶段与撰写阶段可以隔开跑：先批量检索、人工抽查来源质量，再对同一夹具反复迭代撰写提示词。
  全量 `full` 仍用于发布前确认两段衔接没有漂移。

正确关键词也不会自动通过误区与对比项：误区必须有明确纠错语境，对比必须有比较语义。
目录与图形工具降级等问题则继续反映在 F/A 维度。

难度旋钮集中在三处：`graders/common.py` 的维度权重、`scorecard.py` 的门槛与封顶，
以及用例 JSON/schema 中的来源、事实、学习和格式阈值。

## 用例集

共有 48 个逻辑用例。15 个独立 JSON 保留用于重点校准，33 个新增用例收在
`cases/challenge_v2_extended_pack.json`；pack 只复用 preset、生成选项和学习/格式门槛，
每个主题仍有独立知识点、事实正则、来源、误区和辨析对。

| selector | 数量 | 选择规则 | 用途 |
|---|---:|---|---|
| `light-probe` | 1 | 固定选择 `derivative_monotonicity_optimization` | 同门槛、低等待的真实生成探针 |
| `light` | 11 | `tier=smoke` 且 `curriculum_scope=high_school_plus` | 日常/PR 的高中主线 + 受控拓展回归 |
| `heavy` | 32 | `tier=core` 或 `extended` | 夜间或发布前补齐重负载覆盖 |
| `smoke` | 11 | `light` 的兼容别名 | 最快的高中主线 + 受控拓展回归 |
| `core` | 15 | smoke 11 + `tier=core` 4 | 主干质量门禁 |
| `extended` | 28 | 仅 `tier=extended` | 扩展主题专项覆盖 |
| `all` | 48 | 全部 tier | 发布前全量评测 |

主题覆盖如下：

- `light` 高中主线 14 例：诊断试验条件概率、含参导数最优化、斜抛与机械能、电表与电源内阻、
  化学平衡与滴定、光合—呼吸限制因素、季风与城市洪峰、法国大革命多层因果；三道更高门槛的
  综合题：数列递推与放缩证明、导轨电磁感应与能量链条、氧化还原/电化学与氯碱工业；以及三道
  新增高难例：遗传定律与伴性遗传（哈代-温伯格/连锁桥接）、万有引力与卫星轨道（活力公式/潮汐
  桥接）、地球运动与时区计算（太阳视运动/开普勒桥接）。每例另含
  似然比/数值迭代/戴维南等效/活度/史料批判/特征根/能斯特等受控桥接内容。
  综合题把知识点/事实点提到 12、陷阱与辨析提到 5、篇幅 12000、自测 14 道。
- `heavy` 数学/统计 10 例：特征分解、梯度下降、傅里叶/采样、群同态、ODE 数值稳定性、
  KKT、PCA/SVD、因果 DAG、实验设计、信息论。
- `heavy` 物理/化学 8 例：量子谐振子、狭义相对论、麦克斯韦方程、热力学熵、PN 结、
  化学平衡热力学、Nernst 方程、SN1/SN2/E1/E2。
- `heavy` 结构压力 2 例：流体力学伯努利、分子轨道理论——以 12 个知识点小节、4 图 4 表、
  6 条关键公式与 15000 字篇幅下限专项压测结构（F）与美观（A）维度的交付上限。
- `heavy` 生命科学 5 例：CRISPR、孟德尔连锁、免疫与疫苗、细胞呼吸、Hardy–Weinberg 平衡。
- `heavy` 计算机与 AI 5 例：Raft、虚拟内存、密码散列与签名、编译器、Transformer。
- `heavy` 社会与地球科学 4 例：货币政策、比较优势、宪政分权、板块构造。

新增单例可复制任一独立 JSON；批量扩展可在 case pack 的 `defaults` 下追加 `cases`，嵌套对象会
深合并、数组由具体用例替换。`required_facts` 至少一条且 id 唯一，每条至少有一个
`source_url`；正则必须可编译，`traps`、`contrasts`、`expected_domains` 和
`expected_knowledge_points` 都不能为空。当前 `light` 进一步强制每例至少 10 个知识点、10 个
事实点（其中至少 2 个是大学到高中的桥接事实）、4 个陷阱、4 组辨析、4 个完整例题和 12 道
逐题评分自测，最低篇幅 10000 字、来源 12 个；三道综合题在此之上再加严。请求协议会按用例
动态生成这些数量，并列出允许的拓展主题与用途约束。runner 会强制 `prefer_local_archive=false`，
避免历史归档跳过真实生成；smoke/light 请求默认使用 `research_budget=lean`，但不降低上述用例
和评分阈值。

## 校准记录

以下校准记录针对 2026-08-01 的旧 light 题集，仅保留为历史基线；其中旧用例 id 已不属于
当前高中 light 套件。

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
