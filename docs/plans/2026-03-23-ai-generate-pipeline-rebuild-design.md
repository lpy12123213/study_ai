# AI 出题生成链路重构设计说明

## 背景

当前 AI 出题链路已经具备会话、审查、reasoning 展示和透明工作台，但仍存在四组关键问题：

- 生成性能过慢：`spec -> realize -> judge` 的多个阶段存在明显串行执行。
- 恢复能力不足：任务运行中、异常中断后，session 内的 `draft_questions` 不能稳定保留中间成果。
- 候选题同质化：spec 扩展、打分、beam 选择和终选都偏确定性，容易让候选池快速收敛到单一风格。
- 难度控制失真：system prompt、beam 打分和 judge 筛选没有真正围绕用户指定的难度工作。

`nextstep.csv` 中未完成项 `213-227` 本质上都集中在这条生成主链路，因此这次采用一次性重构方案，而不是零散补丁。

## 目标

- 将草稿生成和判题阶段改为受控并发，显著降低端到端耗时。
- 让 session 在运行中持续保存已通过草稿，并在失败或取消时保留可用中间成果。
- 提升 spec 搜索与终选的多样性，降低“换皮题”和单一维度集中问题。
- 让简单 / 中等 / 困难三档难度真正影响 prompt、spec 排序和最终筛选。
- 保持现有 API 形状基本稳定，优先复用现有前端和任务事件体系。

## 非目标

- 不重写整套 question-library 路由结构。
- 不新建独立的运行时队列系统或外部任务执行器。
- 不引入新的数据库表；继续复用当前 preview/session 文件持久层和任务事件存储。

## 范围

本次重构覆盖以下未完成项：

- 213：`realize_drafts` 并发化
- 214：判题链路并发化
- 215：动态收缩默认搜索参数
- 216：轻量判断模型分流
- 217：运行中增量写入 session 草稿
- 218：失败/中断后保留部分草稿
- 219：前端 running session 自动恢复
- 220-224：生成多样性治理
- 225-227：难度约束治理

## 核心决策

### 1. 保持 `generate_questions()` 主返回值不变

`generate_questions()` 继续返回最终题目列表 `List[dict]`，避免上层接口和测试大面积改造。

为了支持运行中持久化和恢复，新增两个可选回调：

- `on_candidate_accepted(candidate)`：每当一题进入 accepted pool 时触发。
- `on_generation_snapshot(snapshot)`：在阶段推进时输出当前 `raw_candidates`、`accepted`、统计信息和阶段标记。

这样 `backend/api/question_library.py` 可以在不依赖最终 `finals` 的情况下持续落盘。

### 2. 并发不是“全放开”，而是“分层限流”

本次并发化遵循三个原则：

- 同层独立任务可并发。
- 每层必须显式限流，避免压垮模型供应商或触发前端节奏失控。
- 顺序相关的阶段边界仍然保留，避免任务事件失真。

具体策略：

- `realize_drafts`：spec 间使用 `asyncio.gather + Semaphore(max_concurrent_realize)`。
- `_solve_with_consensus`：单个 candidate 内部的多次 solve 并发。
- candidate 判题：`solve` 与 `ambiguity` 并发，不同 candidate 间再做一层 `Semaphore(max_concurrent_judge)`。

### 3. session 恢复依赖“增量快照”，不是只看 done preview

过去只有任务完成后才把 `draft_questions` 写回 session，因此 running/failed 状态刷新会丢内容。

本次将 session 视为“生成过程快照”：

- accepted 新增一题，就更新 session `draft_questions`
- 阶段中间状态也保存 `raw_candidates_sample`
- 异常和取消时，把当前已 accepted 的题优先落盘；若还没有 accepted，则尽量保存可展示的原始草稿

新增状态语义：

- `running`
- `pending_review`
- `partial_failure`
- `failed`
- `stopped`

其中 `partial_failure` 表示任务未完整成功，但会话中保留了可继续审核的草稿。

### 4. 多样性治理贯穿四个环节

只在终选阶段去重不够，需要在更前面就阻止 beam 过早塌缩。

具体处理：

- 扩展阶段：`_expand_field()` 不再固定取前 N，而是随机采样去重后的 options。
- 打分阶段：`score_spec()` 增加小幅随机扰动，并引入相对难度探索，而不是让难度分量恒定。
- beam 阶段：`beam_select()` 从纯分数 top-k 改为“先分桶后择优”，至少保留不同 `seed_tag/skill` 的代表。
- 终选阶段：`select_final()` 改为 `skill + reasoning + surface` 多维去重，并优先选择差异较大的候选。

### 5. 难度要影响 prompt、beam 和 judge 三层

当前问题不是某一处缺失，而是三处都不够：

- prompt 层还写着“优先中高难题”
- spec 打分里 `difficulty_match` 对整个候选池几乎是常数
- judge 虽给出 `difficulty_estimate`，但筛选阶段不使用

新方案：

- `build_generation_messages()` 根据目标难度生成不同 system 指令。
- spec 层加入难度梯度探索，例如目标为困难时，允许 `偏难/困难` 混合，但不会全同。
- judge 层根据 `difficulty_estimate` 和目标难度比对，偏差过大时扣分或淘汰。

## 数据流

### 后端生成流

1. `question_library.generate` 创建 task 和 session。
2. `build_source_pack()` 完成后进入 spec search。
3. `generate_questions()` 产出：
   - 阶段事件
   - reasoning 事件
   - accepted candidate 回调
   - generation snapshot 回调
4. API 层在 accepted/snapshot 回调中增量更新：
   - preview
   - session `draft_questions`
   - session `status`
   - task events
5. 若最终成功，状态为 `pending_review`。
6. 若异常或取消：
   - 有草稿则 `partial_failure` / `stopped`
   - 无草稿则 `failed`

### 前端恢复流

1. 若当前页面拥有活跃 SSE，则优先使用实时事件。
2. 若刷新后只剩 `session_id`，且 session 状态为 `running`：
   - 周期性拉取 `GET /question-library/sessions/{id}`
   - 用服务端 `draft_questions`、`task_events`、`reasoning_blocks` 重建工作台
3. 一旦任务进入终态，停止轮询。

## 错误处理

- 单个 spec 的 realize 失败只计数和记录日志，不中断整批任务。
- 单个 candidate 的 solve/ambiguity/judge 失败视为该 candidate 失败，不影响其他 candidate。
- 任务取消时优先保留已 accepted 草稿，并将 session 标记为 `stopped`。
- 未产生任何可用草稿时，仍维持 `failed`，避免把空任务伪装成可恢复会话。

## 测试策略

### 后端

- `test_question_library_generation_pipeline.py`
  - realize 并发后仍能容忍单 spec 失败
  - judge 并发后结果统计正确
  - 多样性约束生效
  - 难度 prompt 和难度筛选生效
- `test_question_library_api.py`
  - running 中 accepted 草稿会增量写入 session
  - 异常/取消后 session 保留部分草稿并进入 `partial_failure`

### 前端

- `AiGenerateStudioPage.test.tsx`
  - running session 刷新后自动恢复
  - 轮询结果能补回 draft stream
- `useAiGenerateSession.test.ts`
  - 服务端 session 草稿和本地状态能正确合并

## 风险与缓解

### 风险 1：并发导致事件顺序变乱

缓解：

- 阶段仍按顺序推进
- candidate 级别只在统计和 accepted 回调中写稳定结构
- 前端用排序后的 task events 和 session 快照复原，不依赖绝对到达顺序

### 风险 2：多样性随机化导致测试不稳定

缓解：

- 随机扰动和随机采样支持注入可测 seed 或替换随机源
- 测试重点验证“存在差异/不全同”，不验证具体排序

### 风险 3：partial failure 语义影响旧前端逻辑

缓解：

- 前端状态文案显式覆盖 `partial_failure`
- `pending_review` 的旧路径保持不变
- `draft_questions` 的数据结构不改

## 预期结果

- 草稿生成耗时显著下降，判题阶段总时长明显收缩。
- 页面刷新后，running session 可恢复已生成草稿与流程信息。
- 异常中断不再把已有草稿全部丢掉。
- 同一主题重复生成时，题目在 skill / reasoning / surface 上更分散。
- 用户指定简单/困难后，生成结果的难度方向与预期更一致。
