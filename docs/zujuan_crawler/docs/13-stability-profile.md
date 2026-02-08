# 13. 响应类型稳定性（挑战页/登录页识别）

更新时间：2026-02-08

在访客态抓取中，“失败”常表现为：HTTP 状态码看似正常（例如 200），但响应体变为挑战页或登录页 HTML，从而无法得到预期的 JSON 或业务 HTML。

本章记录：
- 抽样观察到的“入口/端点”响应类型稳定性差异
- 挑战页与登录页的常见可观察特征（用于判别非目标响应）

范围边界：
- 本章仅提供“识别非目标响应”的判别特征。
- 不讨论也不提供任何绕过挑战/验证码/风控的实现。

相关文档：
- `docs/02-session-cookies-headers.md`
- `docs/troubleshooting.md`
- `docs/04-api-matrix.md`

---

## 13.1 抽样观察：API 相对稳定，HTML 页面波动更大

在 2026-02-08 的同一网络环境与同一台 Windows 机器上，抽样请求表现为：

### 13.1.1 相对更稳定的入口（访客态可获得结构化返回）

- `GET /zujuan-api/base`（返回前端变量文本，包含 `edu=[...]` 等）
- `POST /zujuan-api/paper/list`（返回 JSON，其中包含 HTML 片段）
- `POST /zujuan-api/question/list`（返回 JSON，其中包含 HTML 片段）
- `GET /zujuan-api/category/child_node`（返回 JSON 数组）
- CDN 预生成树：`GET {cdn_domain}/zujuan/tree/*.json`（返回 JSON；文件存在性与命名不保证）
- 静态资源域名 `staticzujuan.xkw.com` 下的图片与 `.mml`

### 13.1.2 更易出现挑战页的入口（与环境相关）

- `GET /sitemap.xml`
- 试卷列表 HTML 页（例如 `/shijuan/`）
- 试卷详情页（`/{bankId}p{paperId}.html`）
- 题目详情页（`/{bankId}q{questionId}.html`）
- `GET /robots.txt`（在部分环境也可能被挑战页替换）

说明：上述分类为“抽样观察结果”，不构成对未来稳定性的承诺。

---

## 13.2 非目标响应的判别特征

### 13.2.1 挑战页（JS Challenge）

可观察特征（命中任意一项即可将该响应判为挑战页）：
- `Content-Type: text/html`，且 HTML 顶部出现 `<body onload="check()">`
- HTML 中出现 `alicfw_gfver`
- HTML 中出现 `aliyun_waf_aa` / `aliyun_waf_bb`
- HTML 中出现 `acw_sc__v2`

判定：该响应不包含目标业务内容（JSON/题面 HTML）。本文档范围不包含挑战页绕过/对抗实现。

### 13.2.2 登录页 / 授权页

可观察特征：
- HTTP `302` 跳转到 `/login?ReturnUrl=...`
- 或 `Content-Type: text/html`，且 HTML 中包含登录相关资源或提示（例如 `login.css`）

判定：该内容通常表示目标数据需要登录或授权。本文档范围不包含绕过登录/授权的实现。

---

## 13.3 在不依赖 HTML 详情页的条件下形成“题面闭环”

在本文档范围内，以下链路可以在不依赖 `/{bankId}q{questionId}.html` 的前提下获得题面与公式资源：

1) 题块来源：`POST /zujuan-api/question/list`（获得题块 HTML）
2) 分类树来源（用于枚举节点/分片）：`GET /zujuan-api/category/child_node` 或 CDN tree（静态 JSON）
3) 公式资源：从题块 `<img>` 中提取 `{hash}`，再请求 `https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.mml` 获取 MathML，并可转换为 LaTeX（见 `docs/08-formula-mml-latex.md`）
