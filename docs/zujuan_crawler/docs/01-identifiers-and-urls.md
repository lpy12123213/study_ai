# 1. 标识符（ID）与 URL 模式

zujuan.xkw.com 的页面与接口以一组稳定的标识符（ID）为核心。本文档集在后续章节中统一沿用这些名称，以降低参数歧义。

## 1.1 核心标识符

| 名称 | 类型 | 含义 | 常见出现位置 | 示例（仅示意） |
|---|---|---|---|---|
| `bankId` | int | 学科题库（题库分库）ID。前端脚本与接口参数中也可能出现 `quesBankId`。 | Cookie、`/zujuan-api/*` 参数、详情页 URL `/{bankId}p...` / `/{bankId}q...` | `11` |
| `courseId` | int | 课程 ID。 | 站内链接（例如 `.../course{courseId}/...`）、`question/list` 参数 | `27` |
| `courseIdPy` | string | 课程路由前缀（拼音缩写）。 | 分类页路由 `/{courseIdPy}/...` | `gzsx` |
| `paperId` | int | 试卷 ID。 | `paper/list` 片段、sitemap、试卷详情页 URL | `3044139` |
| `questionId` | int | 试题 ID。 | `question/list` 片段、试卷页 DOM 属性（例如 `questionid="..."`）、题目详情页 URL | `31298690` |
| `categoryId` | int | 分类节点 ID。可表示章节/知识点/解题方法等树节点。 | `category/child_node` 参数、`question/list` 参数、分类页路由（`zj{id}`/`zsd{id}`/`jtff{id}`） | `135303` |
| `type` | int | 分类树类型。 | `category/child_node` 参数 | `0/1/2` |

`type` 的已观察取值：
- `0`：章节（教材/章节树）
- `1`：知识点
- `2`：解题方法

## 1.2 常见过滤/枚举类标识符（用于列表接口）

下列字段更接近“过滤条件”而非“实体主键”，主要出现在 `POST /zujuan-api/question/list` 与 `POST /zujuan-api/paper/list` 的表单参数中：

| 名称 | 类型 | 含义（按接口语境） | 常见来源 |
|---|---|---|---|
| `quesType` / `quesTypes` | int / int[] | 题型过滤（单选或多选）。 | `GET /zujuan-api/base`（题型枚举）、页面按钮属性 |
| `quesDiff` / `quesDiffs` | int / int[] | 难度过滤（单选或多选）。 | 页面按钮属性、列表接口参数 |
| `quesAttributeId` | int | 题目属性过滤（例如“真题/模拟/常考”等，具体含义以页面展示为准）。 | 页面按钮属性、列表接口参数 |
| `paperTypeId` / `paperTypeIds` | int / int[] | 试卷类型过滤（常见于试卷列表/试题列表筛选）。 | 页面按钮属性、列表接口参数 |
| `provinceId` | int | 地区过滤；`-1` 常用于“全部”。 | 页面按钮属性、列表接口参数 |
| `learngrade` | int | 年级过滤（接口使用数值编码）。 | 页面按钮属性、列表接口参数 |
| `term` | int | 学期过滤（常见为 `1/2`）。 | 页面按钮属性、列表接口参数 |

上述枚举的“可用取值集合”以接口返回与页面渲染为准；文档在对应 API 章节给出样例与抽样验证结果。

## 1.3 URL 模式（站内路由）

### 1.3.1 详情页

- 试卷详情页（Paper）：`https://zujuan.xkw.com/{bankId}p{paperId}.html`
- 试题详情页（Question）：`https://zujuan.xkw.com/{bankId}q{questionId}.html`

### 1.3.2 分类页（用于定位 categoryId）

下列路由模式在站内较常见（以“分类类型前缀 + 数字 ID”的形式表达节点）：

- 章节：`https://zujuan.xkw.com/{courseIdPy}/zj{categoryId}/`
- 知识点：`https://zujuan.xkw.com/{courseIdPy}/zsd{categoryId}/`
- 解题方法：`https://zujuan.xkw.com/{courseIdPy}/jtff{categoryId}/` 或 `https://zujuan.xkw.com/course{courseId}/jtff{categoryId}`（两种形式均曾出现于页面链接）

注意：分类页路由本身并不等同于 API；在某些访问模式下，分类页可能返回挑战页（HTML）而非目标内容。

## 1.4 获取这些 ID 的信息源（不依赖猜测）

### 1.4.1 `bankId/courseId/courseIdPy`（课程枚举）

- `GET https://zujuan.xkw.com/zujuan-api/base`（详见 `docs/api/base.md`）

该接口返回前端脚本变量，其中包含课程与学段等枚举结构。

### 1.4.2 `paperId`（试卷列表）

- `POST https://zujuan.xkw.com/zujuan-api/paper/list`（详见 `docs/api/paper-list.md`）

该接口的 `data.html` 片段通常包含 `/{bankId}p{paperId}.html` 链接，可用于抽取 `paperId`。

### 1.4.3 `questionId`（试题列表）

- `POST https://zujuan.xkw.com/zujuan-api/question/list`（详见 `docs/api/question-list.md`）

该接口的 `data.html` 片段通常包含 `/{bankId}q{questionId}.html` 链接或 `questionid="..."` 等属性，可用于抽取 `questionId`。

### 1.4.4 `categoryId`（分类树）

- `GET https://zujuan.xkw.com/zujuan-api/category/child_node`（详见 `docs/api/category-child-node.md`）

该接口需要一个可用的 `categoryId` 作为查询起点。站内分类页路由（例如 `.../zj135303/`）可直接提供该数字部分。

## 1.5 域名与资源类型（主站 / 静态资源 / CDN）

### 1.5.1 主站（HTML 与 API）

- 主站域名：`https://zujuan.xkw.com`
- 结构化接口路径：`/zujuan-api/*`
- HTML 详情页：`/{bankId}p{paperId}.html`、`/{bankId}q{questionId}.html`

### 1.5.2 静态资源域名（题面配图与公式）

- 常见域名：`https://staticzujuan.xkw.com`
- 常见路径：`/quesimg/Upload/...`
  - 公式：`/quesimg/Upload/formula/{hash}.png` 与同名 `{hash}.mml`

详见：`docs/07-static-assets.md`、`docs/08-formula-mml-latex.md`。

### 1.5.3 CDN 域名（预生成分类树等）

- `cdn_domain` 可从 `GET /zujuan-api/base` 的返回内容中提取（详见 `docs/api/base.md`）。
- 在实测中，`cdn_domain` 常见为 `https://static.zxxk.com`。

CDN 预生成分类树文件命名见：`docs/03-entrypoints-cdn-tree.md`。
