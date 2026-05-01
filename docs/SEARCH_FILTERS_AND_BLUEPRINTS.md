# 搜索筛选与蓝图组卷

题源搜索和蓝图组卷用于按学科、年级、教材、题型、难度等条件获取题目 ID。本文面向前端、MCP 和后端调用方，说明筛选字段如何使用。

为避免串学段、串学科，默认应保持严格学科约束。

## 推荐流程

1. 调用 `GET /api/subjects` 获取学科。
2. 调用 `GET /api/subjects/{subject_code}/filters` 或 `POST /api/available-filters` 获取可用筛选项。
3. 用真实返回的 ID 或名称构造搜索/蓝图请求。
4. 蓝图组卷时开启去重和质量阈值。

## 严格学科

`strict_subject=true` 表示后续题目列表请求会被校正到当前学科。高中英语、高中数学等容易串库的场景应保持开启。

不要自动放宽：

- 学科。
- 学段。
- 年级。
- 教材版本。

可以谨慎放宽：

- `max_pages`
- `min_quality_score`
- `dedup_by_stem`
- 非核心关键词。

## 可用筛选项

HTTP：

```http
POST /api/available-filters
```

请求：

```json
{
  "subject": "高中数学",
  "edu_level": "高中"
}
```

常见返回字段：

- `grades`
- `textbookVersions`
- `provinces`
- `paperTypes`
- `questionTypes`
- `knowledgeTree`

具体字段随题源可用数据而变化，前端和调用方应容忍缺失字段。

## 年级与教材

年级：

- `learn_grade`：中文名称，如 `高一`、`七年级`。
- `learn_grade_id`：题源返回的 ID，优先级更高。

教材：

- `textbook_version`：名称。
- `textbook_version_id`：如果接口返回 ID，应优先用 ID。

建议从可用筛选项接口读取，不要手写猜测。

## 选修过滤

`elective_mode`：

- `include`：包含选修，默认。
- `exclude`：排除选修/选择性必修。
- `only`：只保留选修/选择性必修。

兼容参数：

- `exclude_elective=true` 且 `elective_mode` 为空时，等价于 `exclude`。

可选：

- `elective_keywords`: 自定义关键词列表。

## 质量与去重

`dedup_by_stem=true` 会按规范化题干指纹去重。

`min_quality_score` 会过滤明显不可用的题，例如：

- 题干太短。
- 图片占比过高。
- 未知 token 或占位符过多。
- 内容解析不完整。

难度系数：

- `difficulty_value_min`
- `difficulty_value_max`
- `require_difficulty_value`

如果没有强制 `require_difficulty_value`，缺失难度系数的题不会因为区间条件直接被剔除。

## 蓝图组卷

HTTP：

```http
POST /api/compose-blueprint
```

请求示例：

```json
{
  "subject": "高中数学",
  "edu_level": "高中",
  "learn_grade": "高一",
  "textbook_version": "人教版",
  "strict_subject": true,
  "dedup_by_stem": true,
  "min_quality_score": 60,
  "max_pages": 2,
  "blueprint": [
    {
      "keyword": "函数性质",
      "question_type": "选择题",
      "difficulty": "中等",
      "count": 6
    },
    {
      "knowledge_point": "指数函数",
      "question_type": "填空题",
      "difficulty": "简单",
      "count": 4
    }
  ]
}
```

常见返回：

- `question_ids`：最终选中题目。
- `sections`：每个槽位的命中和选中统计。
- `questions_preview`：题目预览与质量信息。
- `warnings`：不足量、解析失败或降级信息。

## MCP 工具

MCP 中对应能力：

- `get_available_filters`
- `compose_paper_blueprint`
- `search_questions_by_keyword`
- `search_questions_by_knowledge`
- `filter_questions`

Cherry Studio 使用方式见 `CHERRY_STUDIO_MCP_GUIDE.md`。

## 调试建议

- 先用 `limit` 较小的搜索验证筛选项是否有效。
- 如果结果为空，先检查年级/教材 ID 是否来自当前学科。
- 如果结果混入其他学段，确认 `strict_subject` 没被关闭。
- 如果蓝图槽位不足，优先增大 `max_pages`，再降低质量阈值。

## 相关文档

- `QUESTION_SOURCE_API.md`：题源和题库边界。
- `CHERRY_STUDIO_MCP_GUIDE.md`：MCP 中使用筛选和蓝图。
- `API.md`：HTTP 接口路径。
