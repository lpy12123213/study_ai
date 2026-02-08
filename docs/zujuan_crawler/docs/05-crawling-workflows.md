# 5. 数据获取链路（访客态）

本章以“调用链”的形式描述入口、API 与页面解析之间的对应关系。目的在于明确：每条链路的输入、请求序列、可获得的输出，以及常见的非目标响应类型。

## 5.1 链路 A：试卷列表 → 试卷详情页 → 题目 ID 列表

### 输入

- `bankId`（学科题库 ID）
- 试卷列表入口（sitemap 或 `paper/list`）

### 请求与解析步骤

1) 获取试卷入口集合（二选一）：
- sitemap：`GET /sitemap.xml` → `GET /sitemap/p{n}.xml`（见 `docs/03-entrypoints-sitemap.md`）
- 列表接口：`POST /zujuan-api/paper/list`（见 `docs/api/paper-list.md`）

2) 请求试卷详情页：`GET /{bankId}p{paperId}.html`（见 `docs/pages/paper-detail.md`）。

3) 从试卷详情页 HTML 中抽取试题引用：
- DOM 属性 `questionid="..."`（常见于题块容器）
- 或题目链接 `/{bankId}q{questionId}.html`

### 输出（可得到的字段）

- `paperId`
- `questionId[]`（按出现顺序）
- （可选）试卷页中出现的题型/题号等元信息（以页面 `paperJson` 或 DOM 为准）

### 非目标响应（需要识别）

- 试卷详情页可能返回挑战页（`text/html`，但不包含目标业务内容）。特征见 `docs/02-session-cookies-headers.md` 与 `docs/troubleshooting.md`。

## 5.2 链路 B：分类树 → `question/list`（按分类节点分页）

### 输入

- `bankId`
- 分类类型 `type`：`0`（章节）/ `1`（知识点）/ `2`（解题方法）
- 一个可用的树根 `categoryId`

### 请求与解析步骤

1) 获取分类树结构（二选一）：
- 递归接口：`GET /zujuan-api/category/child_node?bankId=...&type=...&categoryId=...`（见 `docs/api/category-child-node.md`）
- CDN 预生成树：`GET {cdn_domain}/zujuan/tree/*.json`（见 `docs/03-entrypoints-cdn-tree.md`）

2) 选择一个节点集合作为分片单位（例如叶子节点集合或任意层级节点集合）。节点 ID 作为 `question/list` 的 `categoryId`。

3) 对每个分片分页调用：`POST /zujuan-api/question/list`（见 `docs/api/question-list.md`）。

4) 从 `question/list` 的 `data.html` 片段中抽取 `questionId` 与题块 HTML（见 `docs/pages/list-html-fragments.md` 与 `docs/10-question-fragment-to-json.md`）。

### 输出（可得到的字段）

- `categoryId → questionId[]` 的映射关系
- 每题的题块 HTML 片段与可解析出的元信息（题型、难度、题源/地区等，取决于片段内容）

## 5.3 链路 C：含公式题的 LaTeX 获取（公式图 → `.mml` → LaTeX）

### 输入

- `question/list` 返回的题块 HTML（`data.html` 中的题面片段）

### 请求与解析步骤

1) 在题块 HTML 中定位公式图片：
- 公式图常见路径形如 `https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.png`
- `{hash}` 通常为 32 位十六进制字符串（小写）

2) 对每个 `{hash}` 请求同名 `.mml`：
- `GET https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.mml`
- `.mml` 响应体为 Base64 字符串；解码后得到 MathML（`<math>...</math>`）

3) 将 MathML 转换为 LaTeX：
- 本仓库示例使用 pandoc 进行转换（输入 MathML/HTML，输出内联公式 `\\( ... \\)`）

4) 将题块 HTML 中对应的公式 `<img>` 节点替换为 LaTeX 文本（形成 LaTeX 化题面）。

### 输出（可得到的字段）

- `formula_hash → mathml → latex` 的映射（以 `{hash}` 为主键）
- `raw_html_fragment`：原始题块 HTML（保留 `<img>`）
- `latex_html_fragment`：将可转换公式替换为 LaTeX 后的题块 HTML

详细原理、返回特征与示例见：
- `docs/08-formula-mml-latex.md`
- `docs/examples/formula-mml-latex.md`
