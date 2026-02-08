# 0. 概览：访客态（不登录）可获取的数据与边界

本文档集的前提为“访客态”：不登录账号；请求中允许携带浏览器正常访问 zujuan.xkw.com 时自动获得的访客 Cookie（不包含获取/伪造/绕过逻辑）。

补充说明：
- `robots.txt` 与站点策略可能随时变化；即使某一时点允许抓取，也仍需遵守站点条款、版权边界与适用法律法规。

## 0.1 能拿到什么（通常）

- 试卷列表、试题列表（通过公开列表接口，返回 HTML 片段）
- 题面（题干/选项/题型标签/难度等以页面实际渲染为准）：很多情况下 `question/list` 返回片段里就包含完整题干与选项，**不一定需要抓 `/{bankId}q{questionId}.html`**
- 含公式题（可选增强）：题干里的公式常见为“公式图片”（`.../Upload/formula/{hash}.png`），通常可通过同名 `{hash}.mml` 拿到 MathML 并转换成 LaTeX（见 `docs/08-formula-mml-latex.md`）
- 试卷详情页中的题目列表、题面：在部分环境与访问模式下，`/{bankId}p{paperId}.html` 可能返回挑战页（见 `docs/troubleshooting.md`）；此时无法直接获得目标 HTML
- 章节/知识点等分类树（通过公开分类接口，可用于“分片抓取”）
- 基础枚举数据（学段/学科/题型/地区）

## 0.2 拿不到什么（通常）

- 答案/解析等内容多为登录/权限后可见；无登录时经常返回“请登录”或权限不足提示
- 某些批量/下载/收藏/同步相关接口会直接返回 `401/403` 或跳转到登录页
- 若触发站点风控（JS 挑战/验证码），纯 HTTP 抓取可能拿不到目标页面

核心结论：
- 无登录爬虫应该以“**题面 + 元数据 + 引用关系**（paper ↔ question）”为主，把“答案解析”当作不可用数据源（除非站点本就公开展示）。

## 0.3 数据获取闭环：入口组合（三种常见路径）

### 路径 A：以试卷（paper）为入口

目标：批量获得 `paperId`，并从试卷页或试卷片段中解析出 `questionId` 列表，以建立 `paper ↔ question` 关联。

1. 获取 paper URL 列表：
   - `sitemap.xml`（见 `docs/03-entrypoints-sitemap.md`；注意 sitemap 可能触发 JS 挑战）
   - 或 `/zujuan-api/paper/list`（见 `docs/api/paper-list.md`）
2. 抓取 `/{bankId}p{paperId}.html`：
   - 解析出 `questionid="..."` 或 `/{bankId}q{questionId}.html`
3.（可选）抓取 `/{bankId}q{questionId}.html`：
   - 提取题面结构与更多元信息（答案/解析不保证可见）

输入：`paper/list` 或 sitemap 的 URL/ID 列表。  
输出：`paperId`、`questionId`、以及试卷-试题关联关系。

### 路径 B：以试题列表接口为入口（按条件筛选）

目标：通过 `POST /zujuan-api/question/list` 直接分页获取试题列表，接口返回试题 HTML 片段与总量 `total`，并可叠加筛选条件。

输入：`question/list` 的筛选参数（例如 `pageName`、`bankId/courseId`、`categoryId`、地区/年级/题型/难度等）。  
输出：试题列表（HTML 片段）与可解析出的 `questionId` 集合。

### 路径 C：先获取分类树，再按节点分片调用 question/list

目标：将“章节/知识点/解题方法”等超大集合拆分为多个 `categoryId` 节点；对每个节点分别分页调用 `question/list`。

1. 通过 `GET /zujuan-api/category/child_node` 获取分类树（见 `docs/api/category-child-node.md`）。
2. 以树节点的 `categoryId` 作为 `question/list` 的 `categoryId`，分页获取试题列表（见 `docs/api/question-list.md`）。

输入：分类树根节点与递归结果。  
输出：按分类节点切分的试题列表与 `questionId`。

### 补充：CDN 预生成分类树（静态 JSON）

在部分学科库（`bankId`）下，站点的 `cdn_domain`（可从 `GET /zujuan-api/base` 提取）存在预生成分类树 JSON，可一次请求获得整棵树：

- 知识点树：`{cdn_domain}/zujuan/tree/lk_{bankId}.json`
- 解题方法树：`{cdn_domain}/zujuan/tree/j_{bankId}.json`（并非所有 `bankId` 都存在）
- 章节树：`{cdn_domain}/zujuan/tree/ct_{bankId}_{textbookVersionId}.json`

详见：`docs/03-entrypoints-cdn-tree.md`
