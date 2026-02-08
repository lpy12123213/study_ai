# 题目搜索筛选与组卷蓝图（Filters & Blueprints）

本项目的题目抓取基于组卷网的接口与站内 SSE 意图识别；为了避免“高中题混入初中题”等情况，已在爬虫与 MCP/后端链路中增加了更严格的学科约束与更丰富的筛选项。

## 1) 严学科约束（关键）

- **默认开启 `strict_subject`**：即使站内 SSE 偶发返回其它学科/学段的 `bank_id`，后续的 `question/list` 请求也会被强制校正到当前学科的 `bank_id`。
- 建议在高中英语等容易串库的场景，始终保持 `strict_subject=true`（MCP 的 `search_questions_by_keyword/search_questions_by_knowledge/compose_paper_blueprint` 已默认按此模式使用）。

## 2) 年级与教材版本（硬过滤）

### 年级（`learn_grade` / `learn_grade_id`）

- `learn_grade`：传中文名称（如 `高一/高二/七年级`），爬虫会在当前学科的元数据中解析成对应 ID。
- `learn_grade_id`：直接传 ID（优先级更高）。

### 教材版本（`textbook_version`）

- `textbook_version` 会被解析为对应的题库分类 `categoryId`，用于请求 `question/list`。
- 强烈建议先调用 **`get_available_filters`** 获取可用教材版本列表，避免手写 ID 或写错名称。

## 3) 选修过滤（三态）

新增 `elective_mode`：

- `include`：不做选修过滤（默认）
- `exclude`：排除选修/选必题
- `only`：仅保留选修/选必题

兼容旧参数：

- `exclude_elective=true` 且 `elective_mode` 为空时，等价于 `elective_mode=exclude`。

自定义关键词：

- `elective_keywords=["选修","选择性必修","选必"]`（不传则使用默认关键词）

## 4) 去重与质量阈值（推荐用于组卷）

### 题干去重（`dedup_by_stem`）

- `dedup_by_stem=true` 时，会对题干做规范化后指纹去重，减少同质题/重复题。

### 质量评分（`min_quality_score`）

- `quality_score` 是启发式评分（0-100），会根据题干长度、未知 token、图片占比等给出分数与 `quality_flags`。
- `min_quality_score` 用于过滤明显“题干过短/图片占比过高/疑似缺内容”的题。

## 5) 难度系数过滤的注意点（按你的需求：不强制剔除缺失项）

当使用 `difficulty_value_min/difficulty_value_max` 时：

- 如果某道题 **没有 `difficulty_value`**（难度系数缺失），**不会因为该条件被剔除**。
- 这样可以避免因为数据缺失导致“可用题量骤减”。

## 6) 获取可用筛选项（建议每次换学科先调用）

### MCP

- 工具：`get_available_filters`
- 返回：`grades / paper_types_by_grade / textbook_versions / question_types` 等

### HTTP（8000/8001）

- `POST /api/available-filters`（主后端 `8000` / OpenAI 适配器 `8001`）

请求示例：

```json
{
  "subject": "高中英语",
  "edu_level": "高中"
}
```

## 7) 组卷蓝图（compose_paper_blueprint）

用于“一次性按多个槽位检索并拼装题目列表”。

### blueprint 槽位格式

每项至少包含：

- `keyword`（或 `knowledge_point`）
- `count`

可选：`difficulty/question_type/source_contains/stem_contains/knowledge_contains/max_pages`

### MCP 示例

- 工具：`compose_paper_blueprint`
- HTTP：`POST /api/compose-blueprint`（主后端 `8000` / OpenAI 适配器 `8001`）

```json
{
  "subject": "高中英语",
  "edu_level": "高中",
  "learn_grade": "高一",
  "textbook_version": "人教版",
  "elective_mode": "exclude",
  "dedup_by_stem": true,
  "min_quality_score": 60,
  "blueprint": [
    {"keyword": "阅读理解", "count": 4, "difficulty": "中等"},
    {"keyword": "完形填空", "count": 2, "difficulty": "中等"},
    {"keyword": "语法填空", "count": 2, "difficulty": "中等"}
  ]
}
```

返回值包含：

- `question_ids`：最终选中的题目 ID 列表
- `sections`：每个槽位的命中/选中统计
- `questions_preview`：精简预览（含 `quality_score/flags`）

## 8) Zhipu（智谱）API 如何配置（用于 MCP 的联网搜索 web_search）

智谱 API 只用于 MCP 工具 `web_search`（通过 BigModel MCP Broker 代理）。

在 `.env` 中配置：

```bash
ZHIPU_API_KEY=你的_key
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPU_MODEL=glm-4.5
ZHIPU_TIMEOUT=60
```

- 只配置 `ZHIPU_API_KEY` 也可以，其它参数有默认值。
- 未配置时，调用 `web_search` 会返回清晰的错误提示。

## 9) 后续任务（Roadmap / BC）

你在实际组卷中遇到的核心问题是：**高中题搜索会混入初中题**。目前已通过 `strict_subject` 做了强约束；下面是进一步可演进的 BC 方向（优先级从高到低）。

### B) 更完整、更好用的筛选（Filters）

1) 省份（地区）筛选：`province` / `province_id`
- 目标：支持按“北京/北京市/全国”等中文名称筛选，同时兼容直接传 `province_id`。
- 数据来源：组卷网前端脚本 `/zujuan-api/base-province` 的 `province_list`。
- 预期改动点：
  - `get_available_filters` 返回 `provinces`（`[{id,name}]`）。
  - `search_questions_by_keyword/search_questions_by_knowledge/compose_paper_blueprint` 新增可选 `province` 字段（字符串），内部解析成 `province_id`。
- 兼容策略：同时传 `province_id` 与 `province` 时，以 `province_id` 为准（避免歧义）。

2) “可用筛选项”输出更贴近真实使用
- 把所有“必须先查元数据才敢填”的字段都集中到 `get_available_filters`：年级、试卷类型、教材版本、题型、（以及后续的省份）。
- 进一步增强可选：把每个选项的 `id` 一并返回，尽量减少“写错名字/别名”导致的空结果。

3) 允许直接使用 ID 形参（减少字符串不一致）
- 例如 `question_type_id`、`paper_type_id` 这类字段：当你从 `get_available_filters` 拿到 ID 后，可以直接传 ID，避免“名称不完全一致”造成误筛。

4) 知识点辅助（轻量）
- 不引入新接口时，先做一个“建议知识点”工具：对若干页搜索结果中的 `knowledge_points` 做聚合统计，输出 Top N 供 blueprint 选择。
- 优点：不依赖站点知识树结构；缺点：受样本分布影响，需要多翻页/多关键词覆盖。

### C) 更聪明的蓝图组卷（Blueprint）

1) 蓝图槽位支持“知识点优先”检索
- 当前 blueprint 槽位允许 `keyword` 或 `knowledge_point`。
- 后续增强：当槽位传 `knowledge_point` 且未传 `keyword` 时，自动走 `search_questions_by_knowledge`，让“按知识点组卷”更稳。

2) 并发检索（加速）
- 多槽位组卷目前可逐槽搜索；后续可引入带上限的并发（如 `Semaphore(2~4)`），显著降低组卷耗时。
- 注意：并发只影响速度，不改变严格约束（`strict_subject`、`learn_grade`、`textbook_version` 等不放宽）。

3) “自动放宽”策略（只放宽非核心约束）
- 当某槽位返回不足（例如需要 10 题只拿到 3 题）时，可以按顺序自动尝试：
  - 增大 `max_pages`（有上限）
  - 适度降低 `min_quality_score`（有下限）
  - 必要时关闭该槽位 `dedup_by_stem`
- 明确原则：**绝不自动放宽学科/学段/年级/教材**（避免再次引入初中题混入）。
- 结果透明：在 `sections[]` 中记录 `relax_trace`，便于复盘“为什么这次组卷放宽了哪些参数”。

4) 全局配额/分布控制（可选）
- 在 blueprint 层面加入“题型配额、难度分布、来源分布”的全局约束与统计输出，避免某一类题过多。

### 验证建议（等上述增强落地后）
- 仍以“高中英语”为例：设置 `learn_grade="高一"` + `textbook_version="人教版"` + `strict_subject=true`，再叠加 `province="北京"`，检查返回题干中是否仍出现 “七年级/八年级/中考/九年级” 等明显初中标记。
