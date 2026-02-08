# 9. 产物 JSON 契约（字段定义与示例）

更新时间：2026-02-08

本章定义一组“抓取结果”的 JSON 数据结构，用于在不绑定具体数据库的前提下表达：试题、试卷、分类节点、静态资源与公式转换结果。

声明：
- 下述结构不是 zujuan.xkw.com 的官方返回结构。
- 下述结构用于描述“访客态抓取 + 结构化解析”的一种输出表达；字段可按使用方需求裁剪。
- 文档中用到的站点标识符（`bankId/questionId/paperId/categoryId` 等）含义见 `docs/01-identifiers-and-urls.md`。

时间字段约定：
- `*_at` 字段使用 ISO 8601 字符串（包含时区偏移），例如：`2026-02-08T14:05:00+08:00`。

命名约定：
- 本章使用 `snake_case`（例如 `question_id`），以区别于站点接口常见的 `camelCase`。

---

## 9.1 QuestionRecord（试题记录）

### 9.1.1 字段定义

| 字段 | 类型 | 必选 | 说明 | 常见来源 |
|---|---|---:|---|---|
| `bank_id` | int | 是 | 学科题库 ID。 | URL / 接口参数 |
| `question_id` | int | 是 | 试题 ID。 | `question/list` 片段或题目链接 |
| `course_id` | int | 否 | 课程 ID（若已知）。 | `base` 枚举、上下文配置 |
| `raw_html_fragment` | string | 是 | 原始题块 HTML（来自 `question/list` 的 `data.html` 中单题块片段）。 | `question/list` |
| `latex_html_fragment` | string | 否 | 将可转换公式替换为 LaTeX 后的题块 HTML。 | 公式链路（见 `docs/08-formula-mml-latex.md`） |
| `has_formula` | bool | 否 | 题块中是否出现公式图片路径（基于字符串/DOM 规则判定）。 | 题块解析 |
| `formula_hashes` | string[] | 否 | 题块中出现的 `{hash}` 列表（去重后）。`{hash}` 为 32 位十六进制字符串。 | 题块解析 |
| `meta` | object | 否 | 题块内可解析出的元信息集合（字段随页面变化）。 | 题块解析 |
| `links` | object | 否 | 与该题相关的 URL（详情页、来源试卷等）。 | 片段解析/上下文 |
| `tags` | object | 否 | 从题块链接中抽取的分类标签（知识点/方法等）。 | 题块解析 |
| `source` | object | 否 | 该记录的采集来源上下文（接口、分片参数、页码等）。 | 抓取侧生成 |
| `parser_version` | string | 否 | 解析规则版本标识（取值由实现方定义）。 | 解析侧生成 |
| `fetched_at` | string | 是 | 抓取时间。 | 抓取侧生成 |
| `parsed_at` | string | 否 | 解析时间。 | 解析侧生成 |

`meta`（示例字段，非封闭集合）：
- `question_index`：题块在当前分页返回中的序号（从 0 或 1 开始取决于实现方）。
- `ques_type`：题型对象，常形如 `{"id": 2702, "name": "填空题"}`。
- `ques_diff`：难度对象，常形如 `{"id": 3, "name": "适中"}`。
- `province` / `year` / `source_name`：题源与年份（是否可得取决于题块标签）。

`tags`（示例字段，非封闭集合）：
- `knowledge_zsd_ids`：知识点（`zsd`）ID 列表。
- `method_jtff_ids`：解题方法（`jtff`）ID 列表。
- `chapter_zj_ids`：章节（`zj`）ID 列表（若题块中存在该类链接）。

### 9.1.2 JSON 示例

```json
{
  "bank_id": 11,
  "course_id": 27,
  "question_id": 31205079,
  "raw_html_fragment": "<div class=\"tk-quest-item ...\">...</div>",
  "has_formula": true,
  "formula_hashes": [
    "d275fbb3ee5cd1177ca5a2ceecbbef0f",
    "204cb82cb2f3ec6865eae88e3de8b809"
  ],
  "latex_html_fragment": "<div ...>设函数 \\\\(f(x)=...\\\\) ...</div>",
  "meta": {
    "ques_type": {"id": 2702, "name": "填空题"},
    "ques_diff": {"id": 3, "name": "适中"}
  },
  "tags": {
    "knowledge_zsd_ids": [28102, 28118, 28077],
    "method_jtff_ids": [149446, 149438]
  },
  "links": {
    "detail_url": "https://zujuan.xkw.com/11q31205079.html"
  },
  "source": {
    "from_api": "/zujuan-api/question/list",
    "page_name": "zsd",
    "category_id": 27926,
    "cur_page": 1,
    "referer": "https://zujuan.xkw.com/gzsx/zsd27926/"
  },
  "parser_version": "2026-02-08.v1",
  "fetched_at": "2026-02-08T14:00:00+08:00",
  "parsed_at": "2026-02-08T14:05:00+08:00"
}
```

---

## 9.2 PaperRecord（试卷记录）

### 9.2.1 字段定义

| 字段 | 类型 | 必选 | 说明 | 常见来源 |
|---|---|---:|---|---|
| `bank_id` | int | 是 | 学科题库 ID。 | URL / 接口参数 |
| `paper_id` | int | 是 | 试卷 ID。 | `paper/list` 片段、sitemap |
| `url` | string | 否 | 试卷详情页 URL（`/{bankId}p{paperId}.html`）。 | 片段解析 |
| `title` | string | 否 | 试卷标题（页面文本）。 | `paper/list` 片段、试卷页 |
| `raw_html` | string | 否 | 试卷页 HTML（可为整页或局部片段）。 | `paper` 详情页 |
| `fetched_at` | string | 是 | 抓取时间。 | 抓取侧生成 |

### 9.2.2 JSON 示例

```json
{
  "bank_id": 11,
  "paper_id": 3034944,
  "url": "https://zujuan.xkw.com/11p3034944.html",
  "title": "（示例）2023-2024 学年 ...",
  "fetched_at": "2026-02-08T14:00:00+08:00"
}
```

---

## 9.3 PaperQuestionRecord（试卷-试题关系）

用于表达：试卷包含哪些试题，以及（若可解析）在卷内的顺序。

| 字段 | 类型 | 必选 | 说明 |
|---|---|---:|---|
| `bank_id` | int | 是 | 学科题库 ID。 |
| `paper_id` | int | 是 | 试卷 ID。 |
| `question_id` | int | 是 | 试题 ID。 |
| `order_no` | int/string | 否 | 题号或顺序（以解析得到的数据类型为准）。 |
| `fetched_at` | string | 否 | 关系抽取时间。 |

JSON 示例：

```json
{
  "bank_id": 11,
  "paper_id": 3034944,
  "question_id": 31205079,
  "order_no": 1,
  "fetched_at": "2026-02-08T14:02:00+08:00"
}
```

---

## 9.4 CategoryNodeRecord（分类树节点记录）

用于表达：章节/知识点/解题方法等树结构节点。

| 字段 | 类型 | 必选 | 说明 | 常见来源 |
|---|---|---:|---|---|
| `bank_id` | int | 是 | 学科题库 ID。 | 上下文 |
| `type` | int | 是 | `0` 章节 / `1` 知识点 / `2` 解题方法。 | `child_node` 参数 |
| `category_id` | int | 是 | 节点 ID。 | `child_node` 或 CDN tree |
| `parent_id` | int/string | 否 | 父节点 ID。 | `child_node` 或 CDN tree |
| `title` | string | 否 | 节点名称。 | `child_node` 或 CDN tree |
| `href` | string | 否 | 站内相对路由（若可得）。 | CDN tree |
| `child_num` | int | 否 | 子节点数量（若可得）。 | `child_node` |
| `raw_json` | object/string | 否 | 节点原始数据。 | 抓取侧保留 |
| `fetched_at` | string | 否 | 抓取时间。 | 抓取侧生成 |

---

## 9.5 CategoryQuestionRecord（分类节点-试题关系）

用于表达：某分类节点下包含哪些试题（通过按节点调用 `question/list` 获得）。

| 字段 | 类型 | 必选 | 说明 |
|---|---|---:|---|
| `type` | int | 是 | 分类类型（章节/知识点/方法）。 |
| `category_id` | int | 是 | 节点 ID。 |
| `question_id` | int | 是 | 试题 ID。 |
| `fetched_at` | string | 否 | 抓取时间。 |

---

## 9.6 FormulaRecord（公式记录：hash → MathML → LaTeX）

该记录用于表达：一个公式 hash 对应的 `.mml`、MathML 与 LaTeX。

| 字段 | 类型 | 必选 | 说明 |
|---|---|---:|---|
| `formula_hash` | string | 是 | 32 位十六进制 hash（来自公式图片 URL）。 |
| `png_url` | string | 否 | 公式图片 URL（常为 `.png`）。 |
| `mml_url` | string | 否 | 公式 `.mml` URL。 |
| `mathml_xml` | string | 否 | Base64 解码后的 MathML（`<math>...</math>`）。 |
| `latex` | string | 否 | LaTeX 公式文本（转换得到）。 |
| `etag` | string | 否 | 响应头 `ETag`（若存在）。 |
| `last_modified` | string | 否 | 响应头 `Last-Modified`（若存在）。 |
| `updated_at` | string | 否 | 更新时间戳。 |

JSON 示例：

```json
{
  "formula_hash": "d275fbb3ee5cd1177ca5a2ceecbbef0f",
  "png_url": "https://staticzujuan.xkw.com/quesimg/Upload/formula/d275fbb3ee5cd1177ca5a2ceecbbef0f.png",
  "mml_url": "https://staticzujuan.xkw.com/quesimg/Upload/formula/d275fbb3ee5cd1177ca5a2ceecbbef0f.mml",
  "mathml_xml": "<math>...</math>",
  "latex": "\\\\(f(x)=x^3+x+1\\\\)",
  "etag": "FC5988201DDFADD7BC46A8EC1DC20301",
  "last_modified": "Mon, 29 Nov 2021 15:16:05 GMT",
  "updated_at": "2026-02-08T14:05:00+08:00"
}
```

---

## 9.7 AssetRecord（静态资源记录）

该记录用于表达：题面图片等静态资源的 URL 与抓取结果元信息。

| 字段 | 类型 | 必选 | 说明 |
|---|---|---:|---|
| `asset_url` | string | 是 | 资源原始 URL。 |
| `content_type` | string | 否 | 响应头 `Content-Type`（若可得）。 |
| `bytes` | int | 否 | 响应体字节数（若可得）。 |
| `etag` | string | 否 | 响应头 `ETag`（若存在）。 |
| `last_modified` | string | 否 | 响应头 `Last-Modified`（若存在）。 |
| `fetched_at` | string | 否 | 抓取时间。 |
| `referenced_by` | object | 否 | 反向引用（例如 `question_id` 列表或计数），结构由实现方定义。 |
