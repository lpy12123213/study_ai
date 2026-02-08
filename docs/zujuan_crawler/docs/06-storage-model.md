# 6. 数据实体与关系（概念模型）

更新时间：2026-02-08

本章不约束具体数据库选型与工程实现方式；其目的在于定义本文档集在描述“抓取结果”时使用的实体（Entity）、字段（Field）与标识（Identifier），以便不同章节（API、页面解析、静态资源）之间使用一致的术语。

## 6.1 实体：Paper（试卷）

### 6.1.1 主标识

- `bankId`（int）：学科题库 ID。
- `paperId`（int）：试卷 ID。

在站内 URL 与接口片段中，试卷通常以 `/{bankId}p{paperId}.html` 表示（见 `docs/01-identifiers-and-urls.md`）。

### 6.1.2 常见字段（来源取决于入口）

| 字段 | 类型 | 说明 | 主要来源 |
|---|---|---|---|
| `url` | string | 试卷详情页 URL。 | `paper/list` 片段、sitemap |
| `title` | string | 试卷标题（页面展示文本）。 | `paper/list` 片段、试卷页 HTML |
| `raw_html` | string | 原始 HTML（可为整页或局部片段）。 | `/{bankId}p{paperId}.html` |
| `fetched_at` | string（ISO8601） | 抓取时间戳。 | 抓取侧生成 |

说明：`paper/list` 返回的是 HTML 片段（`data.html`），标题等字段通常需从片段中解析（见 `docs/pages/list-html-fragments.md`）。

## 6.2 实体：Question（试题）

### 6.2.1 主标识

- `bankId`（int）：学科题库 ID。
- `questionId`（int）：试题 ID。

试题详情页 URL 形如 `/{bankId}q{questionId}.html`；列表接口片段中也常出现该链接或 `questionid="..."` 属性（见 `docs/api/question-list.md`）。

### 6.2.2 常见字段（来源取决于入口）

| 字段 | 类型 | 说明 | 主要来源 |
|---|---|---|---|
| `raw_html_fragment` | string | 列表接口返回的题块 HTML 片段（通常包含题干/选项/标签）。 | `question/list` 的 `data.html` |
| `latex_html_fragment` | string | 将题块中可转换的公式 `<img>` 替换为 LaTeX 后的题块片段。 | `docs/08-formula-mml-latex.md` 的转换链路 |
| `meta` | object | 题型/难度/年份/地区/题源等元信息（以片段包含为准）。 | 题块 HTML 片段解析 |
| `fetched_at` | string（ISO8601） | 抓取时间戳。 | 抓取侧生成 |

题块 HTML 的结构化解析规则见：`docs/10-question-fragment-to-json.md`。

## 6.3 关系：PaperQuestion（试卷-试题包含关系）

该关系用于表达：某份试卷包含哪些题目，以及它们在卷内的顺序信息（若可获得）。

| 字段 | 类型 | 说明 | 主要来源 |
|---|---|---|---|
| `bankId` | int | 学科题库 ID（与试卷一致）。 | 试卷 URL / 页面 |
| `paperId` | int | 试卷 ID。 | 试卷 URL / 页面 |
| `questionId` | int | 试题 ID。 | 试卷页 HTML、题目链接 |
| `order_no` | int / string | 题号/顺序（若页面或脚本变量可解析）。 | 试卷页 HTML、`paperJson` |

说明：同一 `questionId` 在不同 `paperId` 中重复出现属于可观察的常态现象（题目复用）。

## 6.4 实体：CategoryNode（分类树节点）

分类树节点用于表达章节/知识点/解题方法等层级结构。

### 6.4.1 主标识

- `bankId`（int）
- `type`（int）：`0` 章节 / `1` 知识点 / `2` 解题方法
- `categoryId`（int）：节点 ID

### 6.4.2 常见字段

| 字段 | 类型 | 说明 | 主要来源 |
|---|---|---|---|
| `parentId` | int / string | 父节点 ID。 | `child_node` 或 CDN tree |
| `title` / `name` | string | 节点名称。 | `child_node` 或 CDN tree |
| `href` | string | 节点对应的站内路由（相对路径）。 | CDN tree 常见 |
| `childNum` | int | 子节点数量（部分接口返回）。 | `child_node` 常见 |
| `children` | array | 子节点数组（嵌套结构）。 | CDN tree 常见；`child_node` 为扁平数组 |
| `raw_json` | object/string | 节点原始 JSON。 | 抓取侧保留 |

分类树相关接口见：
- `docs/api/category-child-node.md`
- `docs/03-entrypoints-cdn-tree.md`

## 6.5 关系：CategoryQuestion（分类节点-试题关联）

该关系用于表达：某个分类节点（章节/知识点/方法）下包含哪些试题。该关联通常通过“按节点调用 `question/list`”获得。

| 字段 | 类型 | 说明 | 主要来源 |
|---|---|---|---|
| `type` | int | 分类类型（同上）。 | 分片上下文 |
| `categoryId` | int | 节点 ID。 | 分片上下文 |
| `questionId` | int | 试题 ID。 | `question/list` 题块解析 |
| `fetched_at` | string（ISO8601） | 抓取时间戳。 | 抓取侧生成 |

说明：同一 `questionId` 关联到多个 `categoryId` 属于可观察的常态现象（多标签/多归类）。

## 6.6 实体：Asset（静态资源）

题块 HTML 与详情页 HTML 中常包含图片资源（配图、扫描图、公式图等）。静态资源的 URL 规则与提取范围见 `docs/07-static-assets.md`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `asset_url` | string | 资源原始 URL。 |
| `content_type` | string | 响应头 `Content-Type`。 |
| `bytes` | int | 响应体字节数。 |
| `etag` | string | 响应头 `ETag`（若存在）。 |
| `last_modified` | string | 响应头 `Last-Modified`（若存在）。 |
| `fetched_at` | string（ISO8601） | 抓取时间戳。 |

## 6.7 实体：Formula（公式资源与 LaTeX 映射）

当题面包含公式图片（`/quesimg/Upload/formula/{hash}.png`）时，站点通常提供同名 `.mml` 文件（Base64/MathML）。详见 `docs/08-formula-mml-latex.md`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `formula_hash` | string | 32 位十六进制 hash（小写），来自公式图片 URL。 |
| `png_url` | string | 公式图片 URL。 |
| `mml_url` | string | 公式 `.mml` URL。 |
| `mathml_xml` | string | Base64 解码后的 MathML（`<math>...</math>`）。 |
| `latex` | string | LaTeX 公式（示例使用 pandoc 转换得到）。 |

## 6.8 可观察的重复与复用

以下现象在抽样数据中普遍存在：
- 同一 `questionId` 可在多个试卷中出现（试题复用）。
- 同一 `questionId` 可关联到多个知识点/章节/方法节点（多归类）。
- 同一 `formula_hash` 可在大量试题中复用（公式复用）。

这些现象影响的是“关系表/关联表”的表达方式，不影响 `paperId/questionId/categoryId/formula_hash` 作为标识符本身的含义。
