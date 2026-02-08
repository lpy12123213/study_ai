# 文档索引（无登录；允许访客 Cookie）

更新时间：2026-02-08

本文档集以“访客态”为前提：不登录账号；请求中允许携带浏览器正常访问站点时获得的访客 Cookie（不包含获取/伪造/绕过逻辑）。

## 1) 总览与可用性

- `docs/00-overview.md`：范围、术语、能获取/通常不可获取的数据类型
- `docs/04-api-matrix.md`：端点可用性矩阵（访客可用 vs 需要授权/不可用）
- `docs/13-stability-profile.md`：响应类型波动与挑战页特征（识别用）

## 2) 入口（Entry Points）

- `docs/03-entrypoints-sitemap.md`：sitemap 入口（XML）
- `docs/03-entrypoints-cdn-tree.md`：CDN 预生成分类树（静态 JSON）

## 3) API 参考（逐接口）

- `docs/api/README.md`：API 索引
- `docs/api/base.md`：`GET /zujuan-api/base`
- `docs/api/paper-list.md`：`POST /zujuan-api/paper/list`
- `docs/api/question-list.md`：`POST /zujuan-api/question/list`
- `docs/api/category-child-node.md`：`GET /zujuan-api/category/child_node`
- `docs/api/search-sse.md`：`GET /zujuan-api/search?query=`（SSE）

## 4) 页面结构解析（HTML）

- `docs/pages/README.md`：页面解析索引
- `docs/pages/paper-detail.md`：`/{bankId}p{paperId}.html`（试卷页）
- `docs/pages/question-detail.md`：`/{bankId}q{questionId}.html`（题目页）
- `docs/pages/list-html-fragments.md`：列表接口返回的 HTML 片段结构（题块/卷块）

## 5) 静态资源与公式

- `docs/07-static-assets.md`：题面图片/公式图片 URL 规则与下载要点
- `docs/08-formula-mml-latex.md`：公式图片 `.png` → `.mml`（Base64/MathML）→ LaTeX

## 6) 解析与产物格式

- `docs/01-identifiers-and-urls.md`：bankId/courseId/categoryId 等 ID 与 URL 模式
- `docs/10-question-fragment-to-json.md`：将 `question/list` 题块 HTML 解析为结构化字段
- `docs/09-output-contract.md`：产物 JSON 契约（字段定义与示例）
- `docs/12-category-alignment.md`：章节/知识点/解题方法的分类口径对齐

## 7) 验证、回归与示例

- `docs/14-smoke-tests.md`：自检脚本说明
- `docs/examples/README.md`：示例索引（curl / Python）
- `docs/16-question-list-param-validation.md`：`question/list` 参数抽样验证结果
- `docs/troubleshooting.md`：常见异常响应类型与定位要点

## 8) 未覆盖/待验证项

- `docs/15-next-exploration.md`：待验证问题清单与推进记录

## 最小闭环（四个文件）

以下四份文档覆盖“批量获取 paperId → 解析 questionId → 批量获取题块 → 按分类树切分”的最小数据闭环：
- `docs/api/paper-list.md`
- `docs/pages/paper-detail.md`
- `docs/api/question-list.md`
- `docs/api/category-child-node.md`
