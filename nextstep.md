# 资料生成问题修复计划（StudyMaterials）-191dba

## 0. 目标与交付物

本计划用于修复「资料生成 / StudyMaterials」的 5 类关键问题，并将系统升级为“可恢复 + 可继续迭代 + 自适应检索深度”的更稳健形态。

- **交付物**
  - 前端：继续/恢复机制可用，错误提示可理解，支持“完成后继续迭代”。
  - 后端：任务可重连/可续跑（至少支持浏览器刷新；可选支持后端重启后恢复）。
  - 生成质量：更高的资料覆盖与严谨度；迭代次数由 agent 自主决定（在约束内）。
  - 速度：在质量不下降的前提下显著加速（并行、缓存、减少无效调用）。
  - 生图：依赖缺失或 API 未配置时可降级，不阻断整体生成。

---

## 1. 现状架构与关键链路（用于定位问题）

- **前端入口**：`frontend/src/pages/StudyMaterialsPage.tsx`
  - 发起生成：`POST /api/study-materials/generate`（fetch-SSE）
  - 重连（刷新恢复）：`GET /api/study-materials/tasks/{task_id}/stream?after_seq=...`
  - 持久化状态：`useConversationStore.ts`（含 `activeStream` / `resumable`）

- **后端入口**：`backend/api/study_materials.py`
  - 任务管理：`backend/study_materials/task_manager.py`（内存任务 + SSE 回放）

- **Agent 管线**
  - 核心循环：`backend/agent/core.py`（Plan → Act → Reflect → Iterate）
  - 规划：`backend/agent/planner.py`（preset / allowed tools / fallback plan）
  - 执行：`backend/agent/executor.py`（工具分发 + LLM 调用 + thinking/progress 事件）
  - 质量/自检：`backend/agent/tools/content_review.py` + `backend/agent/reflector.py`
  - 导出：`backend/agent/tools/latex_export.py`（MD→LaTeX + refine + compile）
  - 生图：`backend/agent/tools/diagram_planning.py` + `backend/agent/tools/diagrams.py` + `backend/agent/tools/plots.py`

---

## 2. 总体策略（关键设计原则）

- **把“继续”拆成两种语义**
  - **重连继续接收输出**：连接断了/刷新后，继续从 `after_seq` 拉取 SSE。
  - **继续迭代生成**：已完成后继续做“更深检索/更严谨修订/补图补例”。

- **Agent 自由度**：把 preset 从“固定动作清单”降级为“偏好/预算/上限”，由 agent 依据质量评估决定：
  - 需要几轮检索（甚至是否启用 deepresearch）
  - 是否追加 extra tools（Wiki/StackExchange/GitHub/网页正文等）
  - 是否进入下一轮迭代（以及迭代目标是什么）

- **速度优先级**：
  - 先消除“大调用 + 串行”的结构性瓶颈（分段并行、并行组、缓存）。
  - 再做“检索次数/篇幅”层面的策略优化（避免无效深挖）。

- **生图与导出坚持“可降级、不拖垮主流程”**：
  - 缺依赖/缺 Key：输出可理解的 warning，并继续完成 Markdown；LaTeX/PDF 失败不影响 Markdown。

---

## 3. 问题 1：继续按钮形同虚设（完全无法继续）

### 3.1 现象定义（需要先统一产品语义）

- **A 类：重连失败**：刷新/断线后点“继续”不再继续输出。
- **B 类：完成后无法继续迭代**：用户希望“继续”触发下一轮改进（加深、补全、修订）。
- **C 类：错误后无法继续**：导出/生图等非核心步骤失败后，用户希望“继续”只重跑失败阶段或跳过。

### 3.2 根因假设（以可观测为准）

- 前端 `activeStream/resumable` 的清理时机不一致（done/error/abort/网络异常）。
- 后端任务仅存在内存：
  - 后端重启/进程崩溃后，`task_id` 不可用 → 继续必然失败。
- 缺少“继续迭代”的后端语义：当前仅支持“流式输出 + 回放”，不支持“继续跑”。

### 3.3 修复方案（推荐按阶段落地）

#### 阶段 1：把“重连继续接收输出”做成可验收闭环

- **后端**
  - 追加诊断接口：`GET /api/study-materials/tasks/{task_id}`（已有）用于前端在点击继续前做一次状态探测。
  - 明确 status：`running/completed/failed`（必要时扩展 `paused`）。

- **前端**
  - “继续”按钮点击前：先请求 `/tasks/{id}`，若 404/expired → 提示“任务已丢失（后端重启/超时），请重新生成”。
  - 对网络中断（fetchSSE onComplete 但 `done=false`）的场景：
    - **保持** `activeStream`，并提示“连接中断，可继续接收”。
  - 对 `done`：
    - **A 类重连**完成后确实不需要继续接收 → 清理 `activeStream`。
    - 但要给 **B 类继续迭代**留入口（见阶段 2）。

#### 阶段 2：新增“继续迭代”的任务续跑能力（用户真正需要的“继续”）

- **新增 API**（建议）：`POST /api/study-materials/tasks/{task_id}/continue`
  - 请求体示例：
    - `mode`: `improve | deepen_research | fix_export | regenerate_kp`
    - `requirements_patch`: 用户补充要求（可选）
    - `max_extra_iterations`: 限制续跑上限（可选，防止无限循环）

- **TaskManager 扩展**
  - 在 `StudyMaterialsTask` 中保存（或可重建）最小续跑所需状态：
    - 用户输入、subject、options
    - 最近一次 `ctx.working_memory`（至少要能继续 plan/reflect）
    - 迭代计数、最后一次反思结果（可选）
  - 续跑时生成新的 runner，将事件继续 append 到同一个 task（或创建 child task，并建立 parent/child 映射）。

- **前端交互**
  - 完成后展示两类按钮：
    - **继续接收输出**（仅在 running 且连接断开时）
    - **继续迭代优化**（completed 后也可用）

#### 阶段 3（可选）：支持“后端重启后继续”

- 将任务事件与关键上下文落盘（例如 `.local/study_materials/tasks/{task_id}.json` 或 SQLite）。
- 启动时扫描并加载最近 N 个任务（受 TTL 限制）。

### 3.4 验收标准

- 刷新页面后：
  - 若任务仍在 running：能自动重连并继续输出；或点击“继续”后能接上输出。
  - 若任务已完成：不再显示“继续接收”，但显示“继续迭代优化”。
  - 若任务已过期/后端重启丢失：提示清晰，且不会“按钮无反应”。

---

## 4. 问题 2：MD → LaTeX 大概率不可一次性完成

### 4.1 根因

- Markdown 内容过长导致 LLM 输出截断；一次性转换/修订/编译属于长链路，任何环节失败会让用户感觉“转换没完成”。
- LaTeX 编译依赖（xelatex 等）缺失时，反复 refine 也无意义。

### 4.2 修复方案

- **转换策略**
  - 以“知识点标题”为主分块（`## <number>、...`）；无标题时按长度/语义分块。
  - 每块独立 LLM 转换，必要时做 continuation；最终拼接 body。
  - 并行化：对分块启用 `part_concurrency`（受限于速率/配额）。

- **对“未完成”的定义做成可观测**
  - 事件里明确输出：
    - `continuations` 次数
    - 每块是否被判定为 `looks_truncated` / `looks_incomplete`
  - 若达到 continuation 上限仍不完整：
    - 返回 partial 的 `.tex` + 在 done payload 里带 warning，提示用户手工补全或提高上限。

- **导出链路降级**
  - 若 `xelatex` 不存在：
    - 允许 `.tex` 正常生成并下载；PDF 阶段直接跳过并提示“缺少 LaTeX 引擎”。

### 4.3 可调配置（建议集中到 docs/.env.example）

- `STUDY_MATERIALS_LATEX_MAX_TOKENS`
- `STUDY_MATERIALS_LATEX_MAX_CONTINUATIONS`
- `STUDY_MATERIALS_LATEX_PART_CONCURRENCY`
- `STUDY_MATERIALS_LATEX_ALWAYS_REFINE`

### 4.4 验收标准

- 常见主题（3~8 个知识点、每点 1~2k 字）转换成功率显著提升；
- 即使失败，也能给出“原因 + 下一步动作”（提高上限/改用 stream/仅导出 tex）。

---

## 5. 问题 3：资料生成质量过低、迭代次数过少

### 5.1 质量目标（可量化）

- 每个知识点至少覆盖：
  - 动机/为什么需要
  - 定义/符号约定
  - 关键性质/结论（含适用条件）
  - 常见误区/反例/边界情况（视主题而定）
  - 典型应用/例题（可选）
- 资料来源覆盖达标（按 preset 不同阈值不同）。

### 5.2 提升质量的核心手段：自适应迭代 + 定向补检索/补写

#### (1) 让 agent 自主决定“检索深度/迭代次数”

- 将 preset 改为：
  - **预算**（最多调用多少轮检索/多少来源/最大时长）
  - **质量门槛**（review 通过/critique 分数达到阈值）
- 在每轮 Reflect 后生成“下一轮目标”：
  - 缺来源 → 追加检索（仅对缺的知识点）
  - 结构/严谨问题 → 定向修订（revise/refine）
  - 缺图 → 触发生图或降级为 matplotlib

#### (2) 定向修复，避免“整篇重写”

- `review_content` 输出若指出具体知识点不足：
  - 仅对该知识点触发：补检索 → 聚合 → 重写该 kp → 重新 assemble。

#### (3) “检索-写作”的中间层：源简报/结构化事实

- 引入/强化 `synthesize_sources`：
  - 降噪、提炼事实、给 writer 结构化输入
  - 避免 writer 直接吃原始搜索噪声

### 5.3 Planner 自由度（关键点）

- 放宽 planner prompt：
  - 不再强制固定“必须几轮搜索/必须哪些工具”，改为建议。
  - 明确允许 planner 在中途决定追加检索或跳过步骤。
- 允许 LLM planner 产生可变长度计划；执行端支持 `parallel_group` 并行。

### 5.4 验收标准

- 同一主题在 `standard/deep` 下，review 通过率提升；
- 迭代次数不再“固定很少”，而是由失败原因驱动；
- 失败时可看到“为何继续/为何停止”的状态信息。

---

## 6. 问题 4：速度过慢

### 6.1 目标与观测

- 建议先把每个工具的耗时（`elapsed_ms`）聚合成简单统计：
  - p50/p95
  - LLM 调用次数、总 token 估算
  - 每知识点平均耗时

### 6.2 优化杠杆（优先级从高到低）

- **并行化（结构性）**
  - 知识点间并行：`subagent_concurrency`（按 preset 调整上限）
  - 知识点内阶段并行：使用 `parallel_group`（如：synthesize_sources ∥ detect_knowledge_type）
  - 写作分段并行：按 outline sections 并行生成（受 semaphore 控制）

- **减少无效工作**
  - 缓存：web_search / browse / diagrams / latex 输出按 hash 复用（跨迭代复用）。
  - 只重做失败的知识点，不重做全部。

- **模型/参数策略**
  - 结构化中间层（source_brief、outline）用更快更便宜的模型；
  - 写作/修订用更强模型；
  - 预设 quick 模式直接降低 web_pages、diagram 数。

### 6.3 验收标准

- 在不降低 review 通过率的前提下：
  - 5 个知识点（standard）整体耗时显著下降；
  - p95 工具耗时下降或可解释（比如导出属于可选慢步骤）。

---

## 7. 问题 5：生图工具无法使用

### 7.1 根因分层

- **TikZ 路线**：依赖外部可执行文件 `xelatex` + `dvisvgm`（Windows 常缺）。
- **Seedream 路线**：依赖 `ARK_API_KEY` + `SEEDREAM_MODEL`，并受网络/配额影响。

### 7.2 修复策略：可降级的“生图能力矩阵”

- **优先级 1：纯 Python / Matplotlib（不依赖外部可执行）**
  - `draw_diagram`（示意图/受力/电路/结构图）
  - `plot_function` / `plot_3d`（函数图像/曲面）
  - 适合绝大多数教学示意，稳定性最高。

- **优先级 2：TikZ（可选）**
  - 仅当检测到 `xelatex` 与 `dvisvgm` 可用时启用。
  - 否则返回明确错误并提示安装方式（TeX Live / MiKTeX + dvisvgm）。

- **优先级 3：Seedream（可选）**
  - 仅当 `ARK_API_KEY` 与 model 配置齐全时启用。
  - 对 HTTP 非 200 返回错误码与截断后的 msg；不阻断主流程。

### 7.3 产品体验要求

- 生图失败不能让整次资料生成失败（除非用户显式 strict 且要求必须出图）。
- 最终 Markdown 中：
  - 有图则插图；无图则给出“为什么没有图”的简短说明（写入 warning 或注记段落）。

### 7.4 验收标准

- 未安装 LaTeX、未配置 ARK 也能完成资料生成（至少 Markdown）；
- 配置齐全时能稳定产出配图，且与知识点匹配。

---

## 8. Agent 自由度：自适应“搜索迭代步数”的具体落地设计

### 8.1 可控的自由度（避免无限循环）

- 上限：`AGENT_MAX_ITERATIONS`（硬上限）
- 软预算：每轮 tool 调用数、总时长、每 kp 最大检索轮数
- 终止条件：
  - review/critique 达标 → 提前停止
  - 连续两轮质量提升不足（delta 很小）→ 停止并给出建议

### 8.2 自适应策略（建议实现为显式 policy）

- **当 review 提示“资料来源不足”**：
  - 自动追加检索（仅对缺的知识点）
  - 自动提高 `sub_questions` / 更换 query_hint
  - 在预算内可切换到 `deepresearch`（若 EXA 可用）

- **当 review 提示“逻辑/严谨/结构问题”**：
  - 优先 revise/refine，而不是再检索

- **当生图失败**：
  - 优先降级到 matplotlib 方案，而不是无限重试 TikZ/Seedream

---

## 9. 验收标准（汇总）

- **继续/恢复**
  - running 状态刷新可恢复；completed 后可继续迭代；任务丢失提示明确。

- **LaTeX**
  - `.tex` 生成稳定；截断可自动续写/分块；无引擎可降级。

- **质量**
  - deep/research 下资料覆盖（条件/反例/应用）明显提升；review 通过率提升。

- **速度**
  - standard 下整体耗时下降（或在同等耗时下质量显著提升）。

- **生图**
  - 无依赖也不阻断；有依赖时成功率提升；错误信息可操作。

---

## 10. 回归测试清单

- **后端冒烟**
  - `python -m compileall . -q`
  - `python -m unittest discover -s backend/tests`

- **关键路径手测**
  - 生成过程中刷新页面：能自动重连或点击继续后接上输出。
  - 完成后点击“继续迭代优化”：能产生新的事件并更新下载链接。
  - LaTeX 转换：大文本也能完成（或给出 partial + warning）。
  - 生图：
    - 无 LaTeX/无 ARK：不会失败主流程；
    - 有配置：能生成至少 1 张图并落到 `/api/media/generated/`。

---

## 11. 分阶段实施顺序（建议）

1. **继续按钮（重连）可观测化 + 明确提示**（最快解决“按钮无反应”）
2. **新增 continue 续跑 API（继续迭代）**（解决用户真正想要的“继续”）
3. **LaTeX 分块 + 续写 + 降级策略完善**
4. **质量策略：自适应检索深度/迭代次数 + 定向重写**
5. **速度优化：并行/缓存/减少无效调用**
6. **生图能力矩阵 + 环境自检 + 降级链路**
