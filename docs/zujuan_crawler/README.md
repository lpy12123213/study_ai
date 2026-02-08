# zujuan.xkw.com 访客态抓取文档（不登录；允许访客 Cookie）

更新时间：2026-02-08（以当日抓包与请求测试为依据；站点可能随时调整参数、返回结构与风控策略）

本仓库包含一组拆分的 Markdown 文档，用于描述在“访客态”（不登录账号、不使用登录态 Cookie）的前提下，对 zujuan.xkw.com 的公开内容进行数据获取与结构化解析时，可用的入口、API、页面结构与静态资源规则。

术语约定：
- 访客 Cookie：指你在浏览器正常访问站点时自动获得的非登录 Cookie。本文仅讨论此类 Cookie 的携带与复用，不讨论获取/伪造/绕过。
- 挑战页：指网关/风控返回的 HTML 页面（例如包含 `check()`、`aliyun_waf_*` 等特征）。该响应不等同于目标页面或目标 JSON。

文档入口：
- 文档总索引：`docs/README.md`
- 可用端点矩阵：`docs/04-api-matrix.md`
- API 参考（逐接口参数与返回示例）：`docs/api/`
- 页面结构解析（用于从 HTML 提取 ID/片段）：`docs/pages/`
- 示例请求（curl / Python）：`docs/examples/`
- CDN 预生成分类树（静态 JSON）：`docs/03-entrypoints-cdn-tree.md`
- 静态资源与公式：`docs/07-static-assets.md`、`docs/08-formula-mml-latex.md`
- `question/list` 参数抽样验证：`docs/16-question-list-param-validation.md`

适用范围与合规边界（必须阅读）：
- 仅抓取你有权使用的公开内容；遵守站点服务条款、版权声明、robots 规则与适用法律法规
- 不尝试绕过登录/会员/付费/验证码/JS 挑战等访问控制；本文不提供绕过方案
- Cookie 仅使用你本人访问站点时获得的访客 Cookie；不使用他人 Cookie；不使用登录态 Cookie
- 访问频率与并发需控制在不会对站点造成显著负载的范围内（阈值由站点策略决定，本文不提供数值基准）

编码说明：
- 文档为 UTF-8。PowerShell 读取请显式指定：`Get-Content README.md -Encoding UTF8`
