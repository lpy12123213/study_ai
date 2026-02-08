# 14. 自检（Smoke Test）：关键入口可用性与返回特征

更新时间：2026-02-08

本文档集依赖的入口包括：`/zujuan-api/*` 列表接口、分类树接口、以及静态资源域名（公式 `.mml`）。当站点改动参数、返回结构或风控策略时，常见现象是：
- 期望 JSON 的端点返回 `text/html`（挑战页/登录页）
- 期望业务 HTML 的页面返回挑战页
- 端点开始返回 `401/403` 或重定向到 `/login`

本章定义一组“最小可判定”的检查项，用于验证关键入口在某一时点是否仍返回目标类型数据。

---

## 14.1 检查项定义（访客态）

### 14.1.1 `GET /zujuan-api/base`

判定条件（目标响应）：
- HTTP 状态码为 `200`
- 响应体包含 `var edu=`（前端变量文本）

### 14.1.2 `POST /zujuan-api/paper/list`

判定条件（目标响应）：
- HTTP 状态码为 `200`
- `Content-Type` 为 JSON（或响应体可解析为 JSON）
- JSON 中存在 `data.html`
- `data.html` 中可抽取试卷链接 `/{bankId}p{paperId}.html`（见 `docs/pages/list-html-fragments.md`）

### 14.1.3 `POST /zujuan-api/question/list`

判定条件（目标响应）：
- HTTP 状态码为 `200`
- `Content-Type` 为 JSON（或响应体可解析为 JSON）
- JSON 中存在 `data.html`
- `data.html` 中可抽取 `questionid="..."` 或题目链接 `/{bankId}q{questionId}.html`

### 14.1.4 `GET /zujuan-api/category/child_node`

判定条件（目标响应）：
- HTTP 状态码为 `200`
- 响应体可解析为 JSON 数组

### 14.1.5 公式链路（静态资源 `.mml`）

适用前提：已从 `question/list` 的 `data.html` 中抽取到至少一个公式 `{hash}`（见 `docs/08-formula-mml-latex.md`）。

判定条件（目标响应）：
- `GET https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.mml` 返回 `200`
- 响应体可 Base64 解码
- 解码后文本包含 `<math`（MathML）

### 14.1.6 CDN 分类树（静态 JSON）

适用前提：已获得 `cdn_domain` 且对应文件存在（见 `docs/03-entrypoints-cdn-tree.md`）。

判定条件（目标响应）：
- `GET {cdn_domain}/zujuan/tree/lk_{bankId}.json` 返回 `200`
- 响应体可解析为 JSON
- 根对象存在 `children` 字段（数组）

---

## 14.2 通用非目标响应判别

对任意请求，若满足以下任一条件，可判为“非目标响应”：

1) `Content-Type` 不符合预期：
- 期望 JSON 但返回 `text/html`

2) 响应体包含挑战页特征（见 `docs/02-session-cookies-headers.md`）：
- `<body onload="check()">`
- `alicfw_gfver`
- `aliyun_waf_aa` / `aliyun_waf_bb`

3) 响应体包含登录页特征：
- 302 到 `/login?ReturnUrl=...`
- HTML 包含 `login.css` 等登录资源

---

## 14.3 仓库内脚本

仓库提供自检脚本：`docs/examples/smoke-test.py`。脚本输出每个检查项的状态、状态码、`Content-Type` 与响应体前缀特征（用于定位是否发生响应类型替换）。
